"""
strategy.py
-----------
Adaptive Momentum + Trend-Filter Strategy
==========================================

Core idea
---------
Each month we select up to *top_n* stocks from the universe that satisfy
**all** three conditions:

1. **Trend filter** — the stock's adjusted close is above its 200-day SMA.
   This keeps us out of stocks in structural down-trends and significantly
   reduces drawdowns during bear markets.

2. **Momentum** — 6-month total return (skipping last month to avoid
   short-term reversal), standardised cross-sectionally.  We hold only the
   top *top_n* ranked stocks.

3. **RSI guard** — RSI(14) < 75 on entry to avoid chasing grossly overbought
   situations.  Already-held positions are not forced out by RSI alone.

Position sizing
---------------
We use **inverse-volatility weighting**: each position's weight is
proportional to 1 / σ_i, normalised so weights sum to 1 and capped at
*max_weight*.  This gives larger allocations to lower-volatility (steadier)
stocks and naturally de-risks the portfolio.

Cash allocation
---------------
If fewer than *min_positions* stocks pass the filters, the remainder of
capital stays in cash (earning zero in this model — conservative).

Re-balance frequency
--------------------
Monthly (every *rebalance_days* trading days, default = 21).

References
----------
* Jegadeesh & Titman (1993) — original momentum paper
* Antonacci (2014) — "Dual Momentum Investing"
* Faber (2007) — "A Quantitative Approach to Tactical Asset Allocation"
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.indicators import sma, rsi, momentum, atr, cross_sectional_zscore

logger = logging.getLogger(__name__)


@dataclass
class StrategyConfig:
    # Trend filter
    trend_sma_window: int = 200          # price must be above this SMA

    # Momentum
    momentum_lookback: int = 126         # ~6 months of trading days
    top_n: int = 20                      # max stocks held at once

    # RSI guard on new entries
    rsi_window: int = 14
    rsi_entry_max: float = 75.0          # don't buy if RSI > this

    # Volatility-adjusted sizing
    vol_window: int = 21                 # rolling vol for position sizing
    max_weight: float = 0.10            # no single stock > 10 % of portfolio
    min_positions: int = 5              # must have at least this many signals

    # Rebalance cadence
    rebalance_days: int = 21             # ~monthly

    # Risk management
    trailing_stop_enabled: bool = True    # set False to disable trailing stops (e.g., in tests)
    trailing_stop_atr_mult: float = 3.0  # exit if price drops > N × ATR from peak
    atr_window: int = 14


class MomentumTrendStrategy:
    """Generate daily target-weight DataFrames from price history."""

    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        """
        Compute daily target portfolio weights.

        Parameters
        ----------
        prices : pd.DataFrame
            Adjusted close prices.  Rows = dates, columns = tickers.

        Returns
        -------
        pd.DataFrame
            Same shape as *prices*.  Each row sums to ≤ 1.0
            (remainder is cash).  Values are rebalanced monthly and
            held constant in between.
        """
        cfg = self.config
        n_dates, n_stocks = prices.shape

        # --- Pre-compute indicators ---
        ma200 = sma(prices, cfg.trend_sma_window)
        mom_score = momentum(prices, cfg.momentum_lookback)
        mom_zscore = cross_sectional_zscore(mom_score)
        rsi_vals = rsi(prices, cfg.rsi_window)
        daily_vol = np.log(prices / prices.shift(1)).rolling(
            cfg.vol_window, min_periods=cfg.vol_window
        ).std()
        atr_vals = atr(prices, cfg.atr_window)

        # Trailing-stop: track per-stock peak price since entry
        peak_price = prices.copy() * np.nan

        weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        current_weights = pd.Series(0.0, index=prices.columns)

        rebalance_counter = 0

        for i, date in enumerate(prices.index):
            # Need enough history for all indicators
            if i < cfg.trend_sma_window:
                continue

            row_prices = prices.iloc[i]
            row_ma200 = ma200.iloc[i]
            row_mom = mom_zscore.iloc[i]
            row_rsi = rsi_vals.iloc[i]
            row_vol = daily_vol.iloc[i]
            row_atr = atr_vals.iloc[i]

            # ---- Update trailing stops ----
            # Any stock in-position: update peak; check if stop hit
            if cfg.trailing_stop_enabled:
                for ticker in prices.columns:
                    if current_weights[ticker] > 0:
                        prev_peak = peak_price.iat[i - 1, prices.columns.get_loc(ticker)] \
                            if i > 0 else row_prices[ticker]
                        current_peak = max(
                            prev_peak if not np.isnan(prev_peak) else row_prices[ticker],
                            row_prices[ticker],
                        )
                        peak_price.iat[i, prices.columns.get_loc(ticker)] = current_peak

                        stop_level = current_peak - cfg.trailing_stop_atr_mult * (
                            row_atr[ticker] if not np.isnan(row_atr[ticker]) else 0
                        )
                        if row_prices[ticker] < stop_level:
                            current_weights[ticker] = 0.0

            # ---- Monthly rebalance ----
            if rebalance_counter % cfg.rebalance_days == 0 or i == cfg.trend_sma_window:
                new_weights = self._select_and_size(
                    row_prices, row_ma200, row_mom, row_rsi, row_vol,
                    current_weights, cfg,
                )
                # Reset peaks for newly entered positions
                for ticker in prices.columns:
                    if new_weights[ticker] > 0 and current_weights[ticker] == 0:
                        peak_price.iat[i, prices.columns.get_loc(ticker)] = (
                            row_prices[ticker]
                        )
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
        mom_row: pd.Series,
        rsi_row: pd.Series,
        vol_row: pd.Series,
        current_weights: pd.Series,
        cfg: StrategyConfig,
    ) -> pd.Series:
        """
        Pick stocks and compute inverse-vol weights.
        """
        tickers = prices_row.index

        # 1. Trend filter
        above_ma = prices_row > ma200_row

        # 2. RSI guard — allow already-held stocks to stay even if RSI > max
        rsi_ok = (rsi_row < cfg.rsi_entry_max) | (current_weights > 0)

        # 3. Valid data
        has_data = prices_row.notna() & ma200_row.notna() & mom_row.notna()

        eligible = above_ma & rsi_ok & has_data

        candidate_mom = mom_row[eligible]
        if candidate_mom.empty:
            return pd.Series(0.0, index=tickers)

        # 4. Rank by momentum, keep top_n
        top_stocks = candidate_mom.nlargest(cfg.top_n).index

        # 5. Inverse-volatility weighting
        vols = vol_row[top_stocks].replace(0, np.nan)
        inv_vol = (1 / vols).dropna()
        if inv_vol.empty:
            return pd.Series(0.0, index=tickers)

        raw_weights = inv_vol / inv_vol.sum()

        # 6. Cap individual weights
        raw_weights = raw_weights.clip(upper=cfg.max_weight)
        total = raw_weights.sum()
        if total > 0:
            raw_weights = raw_weights / total * min(total, 1.0)

        # 7. Enforce minimum number of positions
        if len(raw_weights) < cfg.min_positions:
            return pd.Series(0.0, index=tickers)

        result = pd.Series(0.0, index=tickers)
        result[raw_weights.index] = raw_weights.values
        return result
