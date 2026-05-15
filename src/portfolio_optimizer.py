"""
portfolio_optimizer.py
-----------------------
Portfolio Optimization Utilities for Multi-Strategy Combination
================================================================

Implements two key techniques used by top quantitative asset managers:

1. **Volatility Targeting** (Moreira & Muir 2017)
   Scale position sizes inversely to recent realized portfolio volatility
   to maintain a constant risk budget.  Reduces drawdowns in high-vol regimes
   without sacrificing long-run return (Sharpe improvement ~0.3 empirically).

2. **Regime-Aware Dynamic Allocation** (Ang & Timmermann 2012)
   Shift capital between momentum, mean reversion, and low-vol strategies
   depending on the detected market regime (BULL / BEAR / CHOPPY).

   BULL   : Overweight momentum (trend continuation)
   BEAR   : Overweight low-vol (defensive quality)
   CHOPPY : Balanced, slight tilt to mean reversion (short-term signals work)

Academic foundation
-------------------
* Moreira & Muir (2017) "Volatility-Managed Portfolios" — vol targeting
  improves Sharpe across momentum, value, carry, and profitability factors
* Maillard, Roncalli & Teiletche (2010) — Equal Risk Contribution (ERC)
* Bridgewater / Dalio (2011) — Risk Parity "All Weather" portfolio
* Ang & Timmermann (2012) "Regime Changes and Financial Markets"
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.regime_detector import RegimeDetector, REGIME_BULL, REGIME_BEAR, REGIME_CHOPPY

# Default regime allocations (fractions across strategies)
# Fractions should sum to 1.0 within each regime
DEFAULT_REGIME_ALLOCS: dict[str, dict[str, float]] = {
    REGIME_BULL:   {"momentum": 0.70, "mean_rev": 0.15, "low_vol": 0.15},
    REGIME_BEAR:   {"momentum": 0.20, "mean_rev": 0.20, "low_vol": 0.60},
    REGIME_CHOPPY: {"momentum": 0.40, "mean_rev": 0.35, "low_vol": 0.25},
}


def vol_target_scale(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    target_vol: float = 0.12,
    vol_window: int = 20,
    min_scale: float = 0.25,
    max_scale: float = 1.0,
) -> pd.DataFrame:
    """
    Scale position weights to maintain approximately *target_vol* annualised
    portfolio volatility (Moreira & Muir 2017 "Volatility-Managed Portfolios").

    The scaler at time t is:

        scale_t = target_vol / realized_vol_{t-1}

    where realized_vol is the rolling *vol_window*-day standard deviation of
    the (unscaled) portfolio daily returns, annualised by sqrt(252).

    The scale is capped between *min_scale* and *max_scale* (long-only:
    max_scale ≤ 1.0 prevents leverage, min_scale avoids near-zero exposure).

    Parameters
    ----------
    weights : pd.DataFrame
        Target weights from a strategy (rows = dates, cols = tickers).
    prices : pd.DataFrame
        Aligned daily prices used to compute portfolio returns.
    target_vol : float
        Annualised target volatility (e.g., 0.12 = 12%).
    vol_window : int
        Rolling window (trading days) for realized vol estimation.
    min_scale : float
        Minimum scale factor (floor, avoids going to zero exposure).
    max_scale : float
        Maximum scale factor (cap, avoid leverage; set 1.0 for long-only).

    Returns
    -------
    pd.DataFrame
        Scaled weights.  Row sums are <= 1.0.
    """
    stock_rets = prices.pct_change()
    aligned_w, aligned_r = weights.align(stock_rets, join="inner")

    # Daily portfolio return using previous day's weights (no look-ahead)
    port_ret = (aligned_w.shift(1) * aligned_r).sum(axis=1)

    # Realized vol at t (returns from t-vol_window to t), annualised
    realized_vol = port_ret.rolling(vol_window, min_periods=vol_window).std() * np.sqrt(252)

    # Scale at t = target_vol / vol_{t-1}: use yesterday's vol to set today's exposure
    scale = (target_vol / realized_vol.shift(1)).clip(lower=min_scale, upper=max_scale)
    scale = scale.fillna(1.0)

    # Apply scale and enforce long-only row sum <= 1
    scaled = weights.mul(scale, axis=0).clip(lower=0.0)
    row_sums = scaled.sum(axis=1)
    too_large = row_sums > 1.0
    scaled.loc[too_large] = scaled.loc[too_large].div(row_sums[too_large], axis=0)

    return scaled


def regime_aware_combine(
    weights_dict: dict[str, pd.DataFrame],
    benchmark_prices: pd.Series | pd.DataFrame,
    regime_allocs: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """
    Combine multiple strategy weight DataFrames using regime-aware allocation.

    The allocation between strategies shifts dynamically based on the current
    market regime detected from the benchmark price series:

      BULL   → overweight momentum (trend continues)
      BEAR   → overweight low-vol (capital preservation)
      CHOPPY → balanced, tilt to mean reversion (short-term signals)

    Parameters
    ----------
    weights_dict : dict[str, pd.DataFrame]
        Strategy name → weight DataFrame.
        Recognised keys: 'momentum', 'mean_rev', 'low_vol'.
    benchmark_prices : pd.Series or single-column pd.DataFrame
        Benchmark price series used for regime detection (e.g., SPY).
    regime_allocs : dict, optional
        Custom regime → strategy allocation mapping.
        If None, uses DEFAULT_REGIME_ALLOCS.

    Returns
    -------
    pd.DataFrame
        Combined weights (rows sum to <= 1.0).
    """
    if regime_allocs is None:
        regime_allocs = DEFAULT_REGIME_ALLOCS

    detector = RegimeDetector()
    regime_series = detector.detect(benchmark_prices)

    # Use first strategy's index / columns as the reference frame
    ref = next(iter(weights_dict.values()))
    combined = pd.DataFrame(0.0, index=ref.index, columns=ref.columns)
    regime_aligned = regime_series.reindex(combined.index, method="ffill").fillna(REGIME_CHOPPY)

    for regime, allocs in regime_allocs.items():
        mask = regime_aligned == regime
        if not mask.any():
            continue
        for strat_name, frac in allocs.items():
            if frac == 0 or strat_name not in weights_dict:
                continue
            strat_w = weights_dict[strat_name].reindex(combined.index, method="ffill").fillna(0.0)
            combined.loc[mask] = combined.loc[mask].add(strat_w.loc[mask] * frac, fill_value=0.0)

    # Normalise: clip individual values to [0,1] and ensure row sums <= 1
    combined = combined.clip(lower=0.0)
    row_sums = combined.sum(axis=1)
    too_large = row_sums > 1.0
    combined.loc[too_large] = combined.loc[too_large].div(row_sums[too_large], axis=0)

    return combined.fillna(0.0)
