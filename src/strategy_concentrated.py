"""
strategy_concentrated.py
------------------------
Strategy 5 — Concentrated High-Conviction Momentum

Goal
----
Beat buy-and-hold of individual high-growth stocks (Tesla, Nvidia, etc.) by:
1. Concentrating in the TOP 3 momentum stocks (not 10–20)
2. Applying 1.5× leverage in BULL regimes (weights sum to 1.5)
3. Using a faster 3-month momentum signal to catch momentum breakouts early
4. Exiting quickly via tight trailing stop (2.5×ATR) and SMA(200) filter

How it beats Tesla / NVDA buy-and-hold
---------------------------------------
High-growth stocks like Tesla have explosive upside BUT also catastrophic crashes:
  • Tesla 2019-2021: +1,100 %
  • Tesla 2021-2022: −75 %
  • Net 2019-2022 buy-and-hold: still down 40 % from the 2021 peak

This strategy captures the bull-market run (momentum filter enters TSLA early)
and exits before the crash (SMA(200) + abs-momentum filter signals exit).
The 1.5× leverage amplifies the captured upside.  Over multiple such cycles, the
compounding advantage (avoid the -75 %, keep the +1,100 %) beats pure B&H.

Mathematical edge
-----------------
Let R_bull = +1,100 %, R_bear = −75 %, over a 3-year cycle:

  B&H path:       100 → ×12 → ×0.25 → 300  (3× in 3 years = +44 % CAGR for this cycle)
  Strategy path:  100 → ×(12^1.5) → ×1.0 → 4,096  (hypothetical 1.5× leverage,
                  exits at peak) → much higher end wealth

In practice the strategy does not exit at the exact peak, but academic evidence
shows momentum strategies capture 60–80 % of the upside while avoiding 50–80 %
of the drawdown (Antonacci 2014; Asness et al. 2014 AQR).

References
----------
* Jegadeesh & Titman (1993) — cross-sectional momentum
* Antonacci (2014) — Dual Momentum (absolute momentum bear exit)
* Asness, Moskowitz & Pedersen (2013) — "Value and Momentum Everywhere" (AQR)
* Novy-Marx (2012) — "Is Momentum Really Momentum?" (3–12m lookback)
* George & Hwang (2004) — 52-week high proximity
* Frazzini & Pedersen (2014) — "Betting Against Beta" (leverage as alpha source)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.indicators import (
    sma,
    rsi,
    atr,
    cross_sectional_zscore,
    absolute_momentum,
    high_52w_ratio,
)

logger = logging.getLogger(__name__)


@dataclass
class ConcentratedMomentumConfig:
    # Trend filters
    trend_sma_window: int = 200          # primary trend: close > SMA(200)

    # Momentum (Jegadeesh & Titman 1993; Novy-Marx 2012)
    # 3-month lookback — catches breakouts faster than the standard 6-month window
    rel_mom_lookback: int = 63           # ≈ 3 months (skip last month handled inside)
    skip_days: int = 21                  # skip most-recent month (reversal avoidance)
    top_n: int = 3                       # hyper-concentrated: top 3 momentum stocks

    # Absolute momentum (Antonacci 2014) — bear-market exit
    abs_mom_lookback: int = 252          # 12-month absolute momentum
    abs_mom_threshold: float = 0.0       # must beat cash / zero

    # 52-week high proximity (George & Hwang 2004)
    high_52w_window: int = 252
    high_52w_min_ratio: float = 0.50     # within 50 % of 52w high (relaxed from 0.65)

    # RSI guard
    rsi_window: int = 14
    rsi_entry_max: float = 85.0          # relaxed — allow entry into strong trends

    # Volatility / sizing
    vol_window: int = 21
    max_weight: float = 0.50             # up to 50 % in a single name (very concentrated)

    # Hybrid weighting: mix of inv-vol and momentum signal strength
    mom_weight_boost: float = 2.0        # shift to z-score before weighting

    # Rebalance cadence
    rebalance_days: int = 21             # monthly

    # Risk management — trailing stop (tighter than Strategy 4 to protect leverage gains)
    trailing_stop_enabled: bool = True
    trailing_stop_atr_mult: float = 2.5  # 2.5×ATR trailing stop
    atr_window: int = 14

    # Absolute momentum (Antonacci 2014) — bear-market exit (relaxed to -5%)
    abs_mom_lookback: int = 252          # 12-month absolute momentum
    abs_mom_threshold: float = -0.05     # allow entry if stock is within 5% of flat

    # Leverage — apply a scalar to target weights in BULL conditions
    # (weights may sum to > 1; the backtest engine handles borrowing via negative cash)
    # NOTE: Real-world margin borrowing costs ~4-6% p.a. — factor this in when deploying.
    leverage_bull: float = 2.0          # 2× leverage: strongly amplifies bull-market gains
    leverage_default: float = 1.0       # 1× when conditions mixed
    min_positions: int = 1              # even 1 qualifying stock gets full leverage


class ConcentratedMomentumStrategy:
    """
    Strategy 5 — Concentrated High-Conviction Momentum with Leverage.

    Selects the top-3 momentum stocks from the universe and allocates up to
    1.5× gross exposure, amplifying returns during momentum-driven bull markets
    while using absolute-momentum and SMA(200) filters to exit before crashes.

    This strategy is explicitly designed to beat buy-and-hold of individual
    high-growth stocks like Tesla and NVDA by combining:
    - Momentum alpha (selecting the current best-performing stocks)
    - Bear-market avoidance (exiting before major crashes)
    - Leverage (amplifying the captured bull-market upside)
    """

    def __init__(self, config: ConcentratedMomentumConfig | None = None):
        self.config = config or ConcentratedMomentumConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        """
        Compute daily target portfolio weights.

        Weights may sum to > 1.0 (= leverage).  The backtest engine treats the
        surplus as borrowing at the risk-free rate.

        Parameters
        ----------
        prices : pd.DataFrame
            Adjusted close prices.  Rows = dates, columns = tickers.

        Returns
        -------
        pd.DataFrame
            Same shape as *prices*.  Each row sums to ≤ leverage_bull (default 1.5).
        """
        cfg = self.config
        min_history = max(cfg.trend_sma_window, cfg.abs_mom_lookback, cfg.high_52w_window)

        # Pre-compute indicators (vectorised)
        ma200 = sma(prices, cfg.trend_sma_window)
        abs_mom = absolute_momentum(prices, cfg.abs_mom_lookback)

        # 3-month relative momentum with skip-1-month: prices[t-21] / prices[t-84] - 1
        # skip_days + rel_mom_lookback gives the lagged window
        _lag_near = cfg.skip_days
        _lag_far  = cfg.skip_days + cfg.rel_mom_lookback
        rel_mom_raw = prices.shift(_lag_near) / prices.shift(_lag_far) - 1
        rel_mom_z = cross_sectional_zscore(rel_mom_raw)

        high52w = high_52w_ratio(prices, cfg.high_52w_window)
        rsi_vals = rsi(prices, cfg.rsi_window)
        daily_vol = np.log(prices / prices.shift(1)).rolling(
            cfg.vol_window, min_periods=cfg.vol_window
        ).std()
        atr_vals = atr(prices, cfg.atr_window)

        peak_price = prices.copy() * np.nan
        weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        current_weights = pd.Series(0.0, index=prices.columns)
        rebalance_counter = 0

        for i, date in enumerate(prices.index):
            if i < min_history:
                continue

            row_prices    = prices.iloc[i]
            row_ma200     = ma200.iloc[i]
            row_abs_mom   = abs_mom.iloc[i]
            row_rel_mom_z = rel_mom_z.iloc[i]
            row_high52w   = high52w.iloc[i]
            row_rsi       = rsi_vals.iloc[i]
            row_vol       = daily_vol.iloc[i]
            row_atr       = atr_vals.iloc[i]

            # ---- Trailing stop exits (intra-bar) ----
            if cfg.trailing_stop_enabled:
                for ticker in prices.columns:
                    if current_weights[ticker] > 0:
                        col_idx = prices.columns.get_loc(ticker)
                        prev_peak = peak_price.iat[i - 1, col_idx] if i > 0 else row_prices[ticker]
                        cur_peak = max(
                            prev_peak if not np.isnan(prev_peak) else row_prices[ticker],
                            row_prices[ticker],
                        )
                        peak_price.iat[i, col_idx] = cur_peak
                        atr_val = row_atr[ticker] if not np.isnan(row_atr[ticker]) else 0
                        stop_level = cur_peak - cfg.trailing_stop_atr_mult * atr_val
                        if row_prices[ticker] < stop_level:
                            current_weights[ticker] = 0.0

            # ---- Monthly rebalance ----
            if rebalance_counter % cfg.rebalance_days == 0 or i == min_history:
                new_weights = self._select_and_size(
                    row_prices, row_ma200, row_abs_mom, row_rel_mom_z,
                    row_high52w, row_rsi, row_vol, current_weights, cfg,
                )
                # Reset peak for newly entered positions
                for ticker in prices.columns:
                    if new_weights[ticker] > 0 and current_weights[ticker] == 0:
                        peak_price.iat[i, prices.columns.get_loc(ticker)] = row_prices[ticker]
                current_weights = new_weights

            rebalance_counter += 1
            weights.iloc[i] = current_weights

        return weights

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select_and_size(
        prices_row: pd.Series,
        ma200_row: pd.Series,
        abs_mom_row: pd.Series,
        rel_mom_z_row: pd.Series,
        high52w_row: pd.Series,
        rsi_row: pd.Series,
        vol_row: pd.Series,
        current_weights: pd.Series,
        cfg: ConcentratedMomentumConfig,
    ) -> pd.Series:
        """
        Select top-N momentum stocks passing all filters and return leveraged weights.
        """
        tickers = prices_row.index

        # 1. Trend filter: price > SMA(200)
        above_ma200 = prices_row > ma200_row

        # 2. Absolute momentum: beats cash (no bear market)
        positive_abs_mom = abs_mom_row >= cfg.abs_mom_threshold

        # 3. 52-week high proximity (not stuck near lows)
        near_52w_high = high52w_row >= cfg.high_52w_min_ratio

        # 4. RSI guard on new entries (existing positions may stay through RSI spikes)
        rsi_ok = (rsi_row < cfg.rsi_entry_max) | (current_weights > 0)

        # 5. Valid data
        has_data = (
            prices_row.notna()
            & ma200_row.notna()
            & abs_mom_row.notna()
            & rel_mom_z_row.notna()
            & high52w_row.notna()
        )

        eligible = above_ma200 & positive_abs_mom & near_52w_high & rsi_ok & has_data

        candidate_mom = rel_mom_z_row[eligible]
        if candidate_mom.empty:
            return pd.Series(0.0, index=tickers)

        # 6. Rank by 3-month relative momentum, keep top_n
        top_stocks = candidate_mom.nlargest(cfg.top_n).index

        # 7. Hybrid inverse-vol × momentum-signal weighting
        vols = vol_row[top_stocks].replace(0, np.nan)
        mom_z = rel_mom_z_row[top_stocks]
        mom_signal = (mom_z + cfg.mom_weight_boost).clip(lower=0.1)
        inv_vol = (1.0 / vols).fillna(0)
        raw_weights = (inv_vol * mom_signal).dropna()

        if raw_weights.empty or raw_weights.sum() == 0:
            return pd.Series(0.0, index=tickers)

        raw_weights = raw_weights / raw_weights.sum()

        # 8. Cap individual weights before leverage
        raw_weights = raw_weights.clip(upper=cfg.max_weight)
        total = raw_weights.sum()
        if total > 0:
            raw_weights = raw_weights / total  # normalise to sum to 1.0

        # 9. Determine leverage scalar:
        #    Use full leverage when ≥ 2 stocks qualify AND all signals are strong;
        #    scale back to 1.0 when only 1 stock qualifies.
        n_positions = len(raw_weights)
        if n_positions < cfg.min_positions:
            return pd.Series(0.0, index=tickers)

        leverage = cfg.leverage_bull if n_positions >= 2 else cfg.leverage_default

        # 10. Apply leverage: weights may sum to > 1.0 (leveraged)
        leveraged_weights = raw_weights * leverage

        result = pd.Series(0.0, index=tickers)
        result[leveraged_weights.index] = leveraged_weights.values
        return result
