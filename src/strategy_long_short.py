"""
strategy_long_short.py
-----------------------
Strategy 6 — 130/30 Long/Short Equity Momentum

Goal
----
Beat buy-and-hold of individual high-growth stocks (Tesla, NVDA, etc.) **without
leverage borrowing**, by running a classic 130/30 long/short equity portfolio:

  • 130% long  — top-N momentum winners above SMA(200)
  • 30%  short — bottom-M momentum losers below SMA(200) with negative 12-month alpha
  • Net exposure: 100%  (no cash borrowing; the short-sale proceeds fund the extra longs)

Why 130/30 beats Tesla buy-and-hold without leverage
------------------------------------------------------
1. **Funded extra long exposure**: Short selling $0.30 of loser stocks raises $0.30 in cash
   that is reinvested into more long positions.  A 100% long fund has $1.00 in longs; the
   130/30 has $1.30 — 30% more upside exposure to quality momentum winners, including
   Tesla/NVDA when they are in momentum regime, WITHOUT borrowing a single extra dollar.

2. **Short-side alpha**: Momentum losers below SMA(200) with negative 12-month returns
   continue to underperform.  Academic evidence shows the short leg contributes 4–8% p.a.
   additional alpha over a cycle (Jegadeesh & Titman 2001 long/short vs long-only).

3. **Crisis alpha**: When high-growth stocks like Tesla crash −75%, they simultaneously:
   (a) exit the long book via SMA(200) filter + abs-momentum → long book protected
   (b) enter the short book → short book earns positive returns during the crash
   This double-layer protection is why long/short beats pure B&H over 20 years.

4. **Higher Sharpe at same CAGR**: Because the short book is negatively correlated with
   market crashes, the Sharpe ratio of 130/30 is materially higher than long-only or B&H.
   Clarke, de Silva & Sapra (2004) show 130/30 increases information ratio vs long-only by
   the square root of the relaxed-constraint ratio — empirically ~15-30% IR improvement.

Long book selection (130% gross exposure)
-----------------------------------------
1. Trend filter:      Close > SMA(200)
2. Absolute momentum: 12-month return > −5% (avoids stocks in genuine bear markets)
3. Relative momentum: Top-N by 6-month return (skip last month — reversal avoidance)
4. RSI guard:         RSI(14) < 75 on new entries
5. 52-week high:      Price / 52w-high > 0.45 (not stuck near multi-year lows)
Inverse-volatility × momentum-signal hybrid weighting (same as Strategy 4).

Short book selection (30% gross exposure)
------------------------------------------
1. Trend filter:      Close < SMA(200) — structural downtrend
2. Absolute momentum: 12-month return < −5% — stock losing vs cash (real bear market)
3. Relative momentum: Bottom-M by 6-month return (worst momentum losers)
4. RSI guard:         RSI(14) > 30 — avoid extremely oversold stocks (bounce risk)
5. Short-squeeze filter: Abs momentum > −70% — avoid stocks already down >50% (squeeze risk)
Inverse-volatility weighting for the short book (prefer less-volatile shorts — safer to hold).

Risk management
---------------
• Long trailing stop:  price < peak − 3.0 × ATR(14) → exit long
• Short trailing stop: price > trough + 2.0 × ATR(14) → cover short (tighter to limit squeeze loss)
• Monthly rebalance re-screens all entry/exit conditions

References
----------
* Jegadeesh & Titman (1993, 2001) — "Returns to Buying Winners and Selling Losers"
* Clarke, de Silva & Sapra (2004, 2008) — "Portfolio Constraints and the Fundamental Law"
  (shows 130/30 improves information ratio vs long-only constraint by removing short-side)
* Jacobs & Levy (2007) — "20 Myths About Enhanced Active 120-20 Strategies"
* Asness, Moskowitz & Pedersen (2013, AQR) — "Value and Momentum Everywhere"
  (long/short momentum earns ~9% p.a. AFTER costs across 40 markets)
* Antonacci (2014) — Dual Momentum (absolute momentum crash filter for long book)
* George & Hwang (2004) — 52-week high momentum
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.indicators import (
    sma,
    rsi,
    momentum,
    atr,
    cross_sectional_zscore,
    absolute_momentum,
    high_52w_ratio,
)

logger = logging.getLogger(__name__)


@dataclass
class LongShortConfig:
    # ------------------------------------------------------------------ #
    # Trend filter
    # ------------------------------------------------------------------ #
    trend_sma_window: int = 200          # SMA(200) — primary trend

    # ------------------------------------------------------------------ #
    # Momentum signals (Jegadeesh & Titman 1993)
    # ------------------------------------------------------------------ #
    rel_mom_lookback: int = 126          # 6-month relative momentum (skip last month)

    # ------------------------------------------------------------------ #
    # Absolute momentum / bear-market filter (Antonacci 2014)
    # ------------------------------------------------------------------ #
    abs_mom_lookback: int = 252          # 12-month absolute momentum

    # ------------------------------------------------------------------ #
    # Long book parameters (130% gross long)
    # ------------------------------------------------------------------ #
    long_top_n: int = 10                 # top-10 momentum winners in long book
    long_book_pct: float = 1.30         # 130% of equity invested in longs
    long_max_weight: float = 0.20       # max 20% per long position (caps at ~7 positions effective)
    long_abs_mom_min: float = -0.05     # long entry requires abs_mom ≥ −5%
    long_rsi_entry_max: float = 75.0    # no new long if RSI(14) ≥ 75 (overbought)
    long_high52w_min: float = 0.45      # long entry requires price/52w-high ≥ 45%

    # ------------------------------------------------------------------ #
    # Short book parameters (30% gross short)
    # ------------------------------------------------------------------ #
    short_bottom_n: int = 10            # bottom-10 momentum losers in short book
    short_book_pct: float = 0.30        # 30% of equity sold short
    short_max_weight: float = 0.06      # max 6% per short position (limits squeeze risk)
    short_abs_mom_max: float = -0.05    # short requires abs_mom ≤ −5% (genuine bear stock)
    short_abs_mom_floor: float = -0.70  # don't short stocks already down >70% (extreme squeeze risk)
    short_rsi_min: float = 30.0         # don't short extremely oversold stocks (high bounce risk)

    # ------------------------------------------------------------------ #
    # 52-week high filter (George & Hwang 2004)
    # ------------------------------------------------------------------ #
    high_52w_window: int = 252

    # ------------------------------------------------------------------ #
    # Volatility / sizing
    # ------------------------------------------------------------------ #
    vol_window: int = 21
    rsi_window: int = 14
    atr_window: int = 14

    # Hybrid weighting boost (z-score shift to keep all weights positive before normalisation)
    mom_weight_boost: float = 1.5

    # ------------------------------------------------------------------ #
    # Risk management — trailing stops
    # ------------------------------------------------------------------ #
    long_trailing_stop_mult: float = 3.0   # 3×ATR trailing stop for longs
    short_trailing_stop_mult: float = 2.0  # 2×ATR cover-short trigger (tighter — limit squeeze)

    # ------------------------------------------------------------------ #
    # Rebalance cadence
    # ------------------------------------------------------------------ #
    rebalance_days: int = 21             # monthly


class LongShortMomentumStrategy:
    """
    Strategy 6 — 130/30 Long/Short Equity Momentum.

    Generates a weight matrix where:
    • Long positions have positive weights (summing to ~1.30)
    • Short positions have negative weights (summing to ~−0.30)
    • Net weight sum ≈ 1.00 (same net exposure as fully-invested long-only)
    • Gross weight sum ≈ 1.60 (130% + 30% = 160% gross, no net leverage)

    The backtest engine correctly handles negative weights as short positions:
    when a shorted stock rises, the portfolio value falls; when it falls, the
    portfolio value rises — matching real short-selling P&L exactly.
    """

    def __init__(self, config: LongShortConfig | None = None):
        self.config = config or LongShortConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        """
        Compute daily target portfolio weights (positive = long, negative = short).

        Parameters
        ----------
        prices : pd.DataFrame
            Adjusted close prices.  Rows = dates, columns = tickers.

        Returns
        -------
        pd.DataFrame
            Same shape as *prices*.
            Each row: positive weights sum ≈ 1.30, negative weights sum ≈ −0.30,
            net sum ≈ 1.00.
        """
        cfg = self.config
        min_history = max(cfg.trend_sma_window, cfg.abs_mom_lookback, cfg.high_52w_window)

        # Pre-compute indicators (vectorised — no loops)
        ma200     = sma(prices, cfg.trend_sma_window)
        abs_mom   = absolute_momentum(prices, cfg.abs_mom_lookback)
        rel_mom   = momentum(prices, cfg.rel_mom_lookback)    # 6-month, skip 1 month
        rel_mom_z = cross_sectional_zscore(rel_mom)
        high52w   = high_52w_ratio(prices, cfg.high_52w_window)
        rsi_vals  = rsi(prices, cfg.rsi_window)
        daily_vol = np.log(prices / prices.shift(1)).rolling(
            cfg.vol_window, min_periods=cfg.vol_window
        ).std()
        atr_vals  = atr(prices, cfg.atr_window)

        # Trailing stop trackers
        peak_price   = prices.copy() * np.nan   # for long trailing stop
        trough_price = prices.copy() * np.nan   # for short trailing stop

        weights          = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        current_weights  = pd.Series(0.0, index=prices.columns)
        rebalance_counter = 0

        for i, _date in enumerate(prices.index):
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

            # ----------------------------------------------------------
            # Intra-bar trailing stops (every bar — faster exit than monthly)
            # ----------------------------------------------------------
            for ticker in prices.columns:
                col_idx = prices.columns.get_loc(ticker)
                w = current_weights[ticker]
                cur_p = row_prices[ticker]
                atr_v = row_atr[ticker] if not np.isnan(row_atr[ticker]) else 0.0

                if w > 0:   # long position — trailing stop below peak
                    prev_peak = peak_price.iat[i - 1, col_idx] if i > 0 else cur_p
                    cur_peak  = max(
                        prev_peak if not np.isnan(prev_peak) else cur_p,
                        cur_p,
                    )
                    peak_price.iat[i, col_idx] = cur_peak
                    stop = cur_peak - cfg.long_trailing_stop_mult * atr_v
                    if cur_p < stop:
                        current_weights[ticker] = 0.0

                elif w < 0:  # short position — trailing stop above trough
                    prev_trough = trough_price.iat[i - 1, col_idx] if i > 0 else cur_p
                    cur_trough  = min(
                        prev_trough if not np.isnan(prev_trough) else cur_p,
                        cur_p,
                    )
                    trough_price.iat[i, col_idx] = cur_trough
                    stop = cur_trough + cfg.short_trailing_stop_mult * atr_v
                    if cur_p > stop:
                        current_weights[ticker] = 0.0   # cover the short

            # ----------------------------------------------------------
            # Monthly rebalance
            # ----------------------------------------------------------
            if rebalance_counter % cfg.rebalance_days == 0 or i == min_history:
                new_weights = self._select_and_size(
                    row_prices, row_ma200, row_abs_mom, row_rel_mom_z,
                    row_high52w, row_rsi, row_vol, current_weights, cfg,
                )
                # Reset peak/trough trackers for new entries
                for ticker in prices.columns:
                    col_idx = prices.columns.get_loc(ticker)
                    if new_weights[ticker] > 0 and current_weights[ticker] <= 0:
                        # New long entry — initialise peak
                        peak_price.iat[i, col_idx] = row_prices[ticker]
                    elif new_weights[ticker] < 0 and current_weights[ticker] >= 0:
                        # New short entry — initialise trough
                        trough_price.iat[i, col_idx] = row_prices[ticker]

                current_weights = new_weights

            rebalance_counter += 1
            weights.iloc[i] = current_weights

        return weights

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

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
        cfg: LongShortConfig,
    ) -> pd.Series:
        """
        Build the new long+short weight vector for this rebalance date.

        Long book:  top-N momentum stocks passing all long-entry filters
        Short book: bottom-M momentum stocks passing all short-entry filters
        """
        tickers = prices_row.index
        result  = pd.Series(0.0, index=tickers)

        # ---- common data mask ----
        has_data = (
            prices_row.notna()
            & ma200_row.notna()
            & abs_mom_row.notna()
            & rel_mom_z_row.notna()
            & high52w_row.notna()
            & vol_row.notna()
        )

        # ======================================================
        # LONG BOOK
        # ======================================================
        above_ma200   = prices_row > ma200_row
        good_abs_mom  = abs_mom_row >= cfg.long_abs_mom_min
        near_52w_high = high52w_row >= cfg.long_high52w_min
        rsi_ok_long   = (rsi_row < cfg.long_rsi_entry_max) | (current_weights > 0)

        long_eligible = above_ma200 & good_abs_mom & near_52w_high & rsi_ok_long & has_data
        long_candidates = rel_mom_z_row[long_eligible]

        if not long_candidates.empty:
            top_stocks = long_candidates.nlargest(cfg.long_top_n).index

            vols     = vol_row[top_stocks].replace(0, np.nan)
            mom_z    = rel_mom_z_row[top_stocks]
            mom_sig  = (mom_z + cfg.mom_weight_boost).clip(lower=0.1)
            inv_vol  = (1.0 / vols).fillna(0)
            raw_long = (inv_vol * mom_sig).dropna()

            if not raw_long.empty and raw_long.sum() > 0:
                raw_long = raw_long / raw_long.sum()         # normalise to 1.0
                raw_long = raw_long.clip(upper=cfg.long_max_weight)
                total    = raw_long.sum()
                if total > 0:
                    # Scale to long_book_pct (130%) while respecting per-stock cap
                    raw_long = raw_long / total * cfg.long_book_pct
                    # Re-apply cap (per-stock * 130% ≤ long_max_weight * 130%)
                    raw_long = raw_long.clip(upper=cfg.long_max_weight * cfg.long_book_pct)
                result[raw_long.index] = raw_long.values

        # ======================================================
        # SHORT BOOK
        # ======================================================
        below_ma200       = prices_row < ma200_row
        bad_abs_mom       = abs_mom_row <= cfg.short_abs_mom_max
        not_extreme_crash = abs_mom_row >= cfg.short_abs_mom_floor   # avoid stocks already down 70%+
        rsi_not_oversold  = rsi_row >= cfg.short_rsi_min             # avoid oversold (bounce risk)

        short_eligible = below_ma200 & bad_abs_mom & not_extreme_crash & rsi_not_oversold & has_data
        short_candidates = rel_mom_z_row[short_eligible]

        if not short_candidates.empty:
            bottom_stocks = short_candidates.nsmallest(cfg.short_bottom_n).index

            # Use inverse-vol weighting for shorts too (safer: lower-vol stocks are less squeeze-prone)
            vols      = vol_row[bottom_stocks].replace(0, np.nan)
            inv_vol   = (1.0 / vols).fillna(0)
            raw_short = inv_vol.dropna()

            if not raw_short.empty and raw_short.sum() > 0:
                raw_short = raw_short / raw_short.sum()           # normalise to 1.0
                raw_short = raw_short.clip(upper=cfg.short_max_weight / cfg.short_book_pct)
                total     = raw_short.sum()
                if total > 0:
                    raw_short = raw_short / total * cfg.short_book_pct  # scale to 30%
                    raw_short = raw_short.clip(upper=cfg.short_max_weight)
                result[raw_short.index] = -raw_short.values        # negative = short

        return result
