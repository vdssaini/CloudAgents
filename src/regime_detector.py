"""
regime_detector.py
------------------
Market Regime Classifier
=========================

Classifies each trading day into one of three market regimes using a
benchmark price series (e.g., SPY):

  BULL   — Sustained uptrend + calm volatility    → favour momentum
  BEAR   — Downtrend + elevated volatility          → favour low-vol / defensive
  CHOPPY — Mixed or transitional                    → favour mean reversion

Academic foundation
-------------------
* Hamilton (1989) "A New Approach to the Economic Analysis of Nonstationary
  Time Series and the Business Cycle" — Markov regime switching
* Faber (2007) "A Quantitative Approach to Tactical Asset Allocation" — SMA
  as a trend filter for tactical allocation
* Ang & Timmermann (2012) "Regime Changes and Financial Markets" — regime-aware
  strategies outperform static allocations over full market cycles

Regime definitions
------------------
  BULL   : benchmark > SMA(200) AND 20-day ann. vol < high_vol_ann_threshold
  BEAR   : benchmark < SMA(200) AND 20-day ann. vol >= high_vol_ann_threshold
  CHOPPY : all other cases (trend up but high vol; trend down but calm)

The volatility threshold is expressed in absolute annualised terms (default
0.20 = 20%), analogous to VIX > 20 signalling an elevated-fear environment.
This fixed threshold is more robust than a relative short/long-vol ratio
because it does not require a long history of "calm" vol to compare against.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REGIME_BULL = "bull"
REGIME_BEAR = "bear"
REGIME_CHOPPY = "choppy"


class RegimeDetector:
    """
    Detect market regime from a benchmark price series.

    Uses two orthogonal signals:
      1. Trend  : Is the benchmark above its 200-day SMA?
      2. Vol    : Is the 20-day annualised realised vol above a fixed threshold?

    The combination gives four quadrants collapsed to three regimes:
      (above SMA, low vol)  → BULL
      (below SMA, high vol) → BEAR
      (mixed)               → CHOPPY
    """

    def __init__(
        self,
        sma_window: int = 200,
        vol_window: int = 20,
        high_vol_ann_threshold: float = 0.20,
    ):
        """
        Parameters
        ----------
        sma_window : int
            Window for the long-run trend SMA.
        vol_window : int
            Rolling window (trading days) for realised vol estimation.
        high_vol_ann_threshold : float
            Annualised daily vol above which the market is considered
            "high volatility".  Default 0.20 = 20% p.a. (VIX ≈ 20).
        """
        self.sma_window = sma_window
        self.vol_window = vol_window
        self.high_vol_ann_threshold = high_vol_ann_threshold

    def detect(self, benchmark_prices: pd.Series | pd.DataFrame) -> pd.Series:
        """
        Detect regime for each date in the benchmark price series.

        Parameters
        ----------
        benchmark_prices : pd.Series or single-column pd.DataFrame
            Daily closing prices of a benchmark index (e.g., SPY).

        Returns
        -------
        pd.Series
            Same index as *benchmark_prices*, values in
            {REGIME_BULL, REGIME_BEAR, REGIME_CHOPPY}.
            Dates before the warm-up period are labelled CHOPPY.
        """
        prices = benchmark_prices.squeeze()
        if not isinstance(prices, pd.Series):
            raise ValueError("benchmark_prices must be a Series or single-column DataFrame")

        # 1. Trend signal: price vs SMA(200)
        sma200 = prices.rolling(self.sma_window, min_periods=self.sma_window).mean()
        above_sma = prices > sma200

        # 2. Volatility signal: 20-day realised vol (annualised) vs fixed threshold
        log_ret = np.log(prices / prices.shift(1))
        ann_vol = log_ret.rolling(self.vol_window, min_periods=self.vol_window).std() * np.sqrt(252)
        high_vol = ann_vol >= self.high_vol_ann_threshold

        # 3. Classify into three regimes
        regime = pd.Series(REGIME_CHOPPY, index=prices.index, dtype=object)
        regime.loc[above_sma & ~high_vol] = REGIME_BULL
        regime.loc[~above_sma & high_vol] = REGIME_BEAR
        # Warm-up NaN rows and mixed-signal rows remain CHOPPY

        return regime

    def regime_counts(self, benchmark_prices: pd.Series | pd.DataFrame) -> dict[str, int]:
        """Return a count of days in each regime (useful for diagnostics)."""
        r = self.detect(benchmark_prices)
        return {
            REGIME_BULL: (r == REGIME_BULL).sum(),
            REGIME_BEAR: (r == REGIME_BEAR).sum(),
            REGIME_CHOPPY: (r == REGIME_CHOPPY).sum(),
        }
