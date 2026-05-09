"""
strategy_low_vol.py
--------------------
Low-Volatility Factor Strategy
================================

Academic foundation
-------------------
* Baker, Bradley & Wurgler (2011) "Benchmarks as Limits to Arbitrage: Understanding
  the Low-Volatility Anomaly" — documents the low-vol anomaly across many markets
* Frazzini & Pedersen (2014) "Betting Against Beta" (AQR) — BAB factor; low-beta
  stocks earn higher risk-adjusted returns than high-beta stocks
* Ang, Hodrick, Xing & Zhang (2006) "The Cross-Section of Volatility and Expected
  Returns" — low idiosyncratic vol stocks outperform over the subsequent month
* Blitz & van Vliet (2007) "The Volatility Effect: Lower Risk Without Lower Return"

Key insight
-----------
Leverage-constrained investors (mutual funds benchmarked to an index) overweight
high-volatility stocks to maximise expected return within mandate constraints,
systematically overpricing them.  Low-vol stocks are underpriced as a result.
This creates a **persistent long-run alpha** for low-volatility strategies —
one of the best-documented market anomalies with decades of out-of-sample evidence.

Strategy overview
-----------------
ENTRY  — all must be true:
  1. Trend filter    : Price > SMA(200)       — avoid structural downtrends
  2. Minimum vol     : 20-day ann. vol > 5%   — filter illiquid / flat stocks
  3. Selection       : Rank by 20-day realized vol ascending; hold top-N lowest

EXIT   — first condition wins:
  1. Monthly rebalance: re-rank; replace stocks that left the top-N
  2. Trend exit       : sell if stock falls below SMA(200)
  3. Vol spike exit   : sell if 20-day vol > 2.5x the vol recorded at entry

Position sizing
---------------
* Inverse-variance weighting (1/σ²) — the minimum-variance portfolio weight
* Individual cap: 10% per stock
* Minimum simultaneous positions: 5

Rebalance cadence
-----------------
Monthly (21 trading days) — matches Baker et al. 2011 holding period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.indicators import sma

logger = logging.getLogger(__name__)


@dataclass
class LowVolConfig:
    # Trend filter
    trend_sma_window: int = 200

    # Volatility measurement
    vol_window: int = 20            # 20-day realized vol for ranking
    min_vol_annual: float = 0.05  # minimum 5% ann. vol (filter illiquid / flat stocks)

    # Selection
    top_n: int = 20                 # hold 20 lowest-vol stocks

    # Position sizing
    max_weight: float = 0.10        # max 10% per stock
    min_positions: int = 5

    # Rebalance cadence
    rebalance_days: int = 21        # monthly

    # Risk management
    vol_exit_mult: float = 2.5      # exit if current vol > entry vol × this


class LowVolStrategy:
    """
    Monthly-rebalancing low-volatility factor strategy.

    Selects the lowest-realized-volatility stocks from the universe that are
    in structural uptrends (above SMA-200), sizes them by inverse variance
    (minimum-variance portfolio weights), and rebalances monthly.
    """

    def __init__(self, config: LowVolConfig | None = None):
        self.config = config or LowVolConfig()

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
            Same shape as *prices*.  Each row sums to <= 1.0 (remainder is cash).
        """
        cfg = self.config
        tickers = list(prices.columns)

        # Pre-compute indicators (vectorised)
        ma200 = sma(prices, cfg.trend_sma_window)
        log_rets = np.log(prices / prices.shift(1))
        daily_vol = log_rets.rolling(cfg.vol_window, min_periods=cfg.vol_window).std()
        annual_vol = daily_vol * np.sqrt(252)

        weights = pd.DataFrame(0.0, index=prices.index, columns=tickers)
        current_weights = pd.Series(0.0, index=tickers)
        entry_vol: dict[str, float] = {}

        rebalance_counter = 0

        for i, date in enumerate(prices.index):
            if i < cfg.trend_sma_window:
                continue

            row_prices = prices.iloc[i]
            row_ma200 = ma200.iloc[i]
            row_vol = annual_vol.iloc[i]

            # ---- Vol-spike exits (checked every bar) ----
            for ticker in list(entry_vol.keys()):
                if current_weights[ticker] == 0:
                    entry_vol.pop(ticker, None)
                    continue
                ev = entry_vol[ticker]
                cv = row_vol[ticker]
                if not np.isnan(cv) and not np.isnan(ev) and cv > ev * cfg.vol_exit_mult:
                    logger.debug("Vol spike exit %s on %s (entry=%.2f curr=%.2f)", ticker, date, ev, cv)
                    current_weights[ticker] = 0.0
                    entry_vol.pop(ticker, None)

            # ---- Monthly rebalance ----
            if rebalance_counter % cfg.rebalance_days == 0 or i == cfg.trend_sma_window:
                new_weights, new_entries = self._select_and_size(row_prices, row_ma200, row_vol, cfg)

                # Record entry vol for new positions
                for ticker in new_entries:
                    if not np.isnan(row_vol[ticker]):
                        entry_vol[ticker] = row_vol[ticker]

                # Clear entry tracking for positions that exited
                for ticker in tickers:
                    if new_weights[ticker] == 0 and ticker in entry_vol:
                        entry_vol.pop(ticker, None)

                current_weights = new_weights

            rebalance_counter += 1
            weights.iloc[i] = current_weights

        return weights

    @staticmethod
    def _select_and_size(
        prices_row: pd.Series,
        ma200_row: pd.Series,
        vol_row: pd.Series,
        cfg: LowVolConfig,
    ) -> tuple[pd.Series, list[str]]:
        """
        Pick lowest-vol stocks and compute inverse-variance weights.

        Returns
        -------
        tuple[pd.Series, list[str]]
            (weights, new_entry_tickers)
        """
        tickers = prices_row.index

        # 1. Trend filter
        above_ma = prices_row > ma200_row

        # 2. Minimum vol filter (exclude illiquid / flat stocks)
        above_min_vol = vol_row >= cfg.min_vol_annual

        # 3. Valid data
        has_data = prices_row.notna() & ma200_row.notna() & vol_row.notna()

        eligible = above_ma & above_min_vol & has_data
        eligible_vols = vol_row[eligible]

        if eligible_vols.empty:
            return pd.Series(0.0, index=tickers), []

        # 4. Rank by vol ascending (lowest vol first), keep top_n
        top_stocks = eligible_vols.nsmallest(cfg.top_n).index.tolist()

        # 5. Inverse-variance weighting (1/σ²) — minimum-variance portfolio
        vols_top = vol_row[top_stocks].replace(0, np.nan)
        inv_var = (1.0 / (vols_top ** 2)).dropna()

        if inv_var.empty:
            return pd.Series(0.0, index=tickers), []

        raw_weights = inv_var / inv_var.sum()
        raw_weights = raw_weights.clip(upper=cfg.max_weight)
        total = raw_weights.sum()
        if total > 0:
            raw_weights = raw_weights / total * min(total, 1.0)

        # 6. Minimum positions check
        if len(raw_weights) < cfg.min_positions:
            return pd.Series(0.0, index=tickers), []

        result = pd.Series(0.0, index=tickers)
        result[raw_weights.index] = raw_weights.values
        return result, top_stocks
