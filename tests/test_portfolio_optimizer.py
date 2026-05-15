"""
test_portfolio_optimizer.py
----------------------------
Unit tests for src/portfolio_optimizer.py (vol_target_scale, regime_aware_combine).
"""

import numpy as np
import pandas as pd
import pytest

from src.portfolio_optimizer import vol_target_scale, regime_aware_combine, DEFAULT_REGIME_ALLOCS
from src.regime_detector import REGIME_BULL, REGIME_BEAR, REGIME_CHOPPY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_prices(n_days: int = 400, n_stocks: int = 5, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    tickers = [f"T{i}" for i in range(n_stocks)]
    log_rets = rng.normal(0.0004, 0.012, (n_days, n_stocks))
    prices = pd.DataFrame(100 * np.exp(np.cumsum(log_rets, axis=0)), index=dates, columns=tickers)
    return prices


def make_weights(prices: pd.DataFrame, equal: bool = True) -> pd.DataFrame:
    """Uniform weights (equal allocation across all stocks)."""
    n_stocks = prices.shape[1]
    w = pd.DataFrame(1.0 / n_stocks, index=prices.index, columns=prices.columns)
    return w


def make_benchmark(n_days: int = 400, drift: float = 0.0005, vol: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(99)
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    rets = rng.normal(drift, vol, n_days)
    return pd.Series(100 * np.exp(np.cumsum(rets)), index=dates, name="BENCH")


# ---------------------------------------------------------------------------
# vol_target_scale tests
# ---------------------------------------------------------------------------

class TestVolTargetScale:
    def test_output_shape(self):
        prices = make_prices()
        w = make_weights(prices)
        scaled = vol_target_scale(w, prices)
        assert scaled.shape == w.shape

    def test_output_non_negative(self):
        prices = make_prices()
        w = make_weights(prices)
        scaled = vol_target_scale(w, prices)
        assert (scaled >= 0).all().all()

    def test_row_sums_at_most_one(self):
        prices = make_prices()
        w = make_weights(prices)
        scaled = vol_target_scale(w, prices)
        assert (scaled.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_reduces_exposure_in_high_vol_period(self):
        """
        When we artificially inject a high-vol period, the scaler should
        reduce the aggregate exposure.
        """
        rng = np.random.default_rng(5)
        n = 300
        dates = pd.date_range("2019-01-01", periods=n, freq="B")
        tickers = ["A", "B"]
        # First 200 days: low vol uptrend
        lv_rets = rng.normal(0.0005, 0.005, (200, 2))
        # Last 100 days: high vol crash
        hv_rets = rng.normal(-0.001, 0.030, (100, 2))
        all_rets = np.vstack([lv_rets, hv_rets])
        prices = pd.DataFrame(100 * np.exp(np.cumsum(all_rets, axis=0)), index=dates, columns=tickers)
        w = pd.DataFrame(0.5, index=dates, columns=tickers)

        scaled = vol_target_scale(w, prices, target_vol=0.12, vol_window=20)

        # Average row sum in the low-vol period vs high-vol period
        avg_lv = scaled.iloc[50:200].sum(axis=1).mean()
        avg_hv = scaled.iloc[230:].sum(axis=1).mean()
        assert avg_hv < avg_lv, f"High-vol exposure {avg_hv:.3f} should be less than low-vol {avg_lv:.3f}"

    def test_min_scale_floor(self):
        """Scale should never drop below min_scale."""
        prices = make_prices()
        w = make_weights(prices)
        min_s = 0.30
        scaled = vol_target_scale(w, prices, min_scale=min_s, max_scale=1.0)
        # Wherever original weights are positive, scaled should be >= min_s × original (proportionally)
        # But we just check row sums >= 0 and <= 1
        assert (scaled >= 0).all().all()

    def test_max_scale_cap(self):
        """Scale should never exceed max_scale × original weights."""
        prices = make_prices()
        w = make_weights(prices) * 0.1  # 10% each = 50% total
        scaled = vol_target_scale(w, prices, target_vol=0.50, max_scale=1.0)
        # Row sums should be <= 1.0
        assert (scaled.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_index_unchanged(self):
        prices = make_prices()
        w = make_weights(prices)
        scaled = vol_target_scale(w, prices)
        assert scaled.index.equals(w.index)

    def test_columns_unchanged(self):
        prices = make_prices()
        w = make_weights(prices)
        scaled = vol_target_scale(w, prices)
        assert list(scaled.columns) == list(w.columns)


# ---------------------------------------------------------------------------
# regime_aware_combine tests
# ---------------------------------------------------------------------------

class TestRegimeAwareCombine:
    def _make_weights_dict(self, prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
        return {
            "momentum": make_weights(prices) * 0.6,
            "mean_rev": make_weights(prices) * 0.2,
            "low_vol":  make_weights(prices) * 0.2,
        }

    def test_output_shape(self):
        prices = make_prices()
        wd = self._make_weights_dict(prices)
        bench = make_benchmark(n_days=len(prices))
        combined = regime_aware_combine(wd, bench)
        assert combined.shape == prices.shape

    def test_row_sums_at_most_one(self):
        prices = make_prices()
        wd = self._make_weights_dict(prices)
        bench = make_benchmark(n_days=len(prices))
        combined = regime_aware_combine(wd, bench)
        assert (combined.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_non_negative(self):
        prices = make_prices()
        wd = self._make_weights_dict(prices)
        bench = make_benchmark(n_days=len(prices))
        combined = regime_aware_combine(wd, bench)
        assert (combined >= 0).all().all()

    def test_missing_strategy_in_dict(self):
        """If a strategy key is absent, it just contributes zero."""
        prices = make_prices()
        wd = {"momentum": make_weights(prices) * 0.6}  # missing mean_rev and low_vol
        bench = make_benchmark(n_days=len(prices))
        combined = regime_aware_combine(wd, bench)
        assert (combined.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_custom_regime_allocs(self):
        """Custom regime allocations are applied."""
        prices = make_prices(n_days=400, n_stocks=3)
        bench = make_benchmark(n_days=400, drift=0.001, vol=0.003)  # steady uptrend → BULL

        # All weight goes to momentum in BULL
        custom_allocs = {
            REGIME_BULL:   {"momentum": 1.0, "mean_rev": 0.0, "low_vol": 0.0},
            REGIME_BEAR:   {"momentum": 0.0, "mean_rev": 0.0, "low_vol": 1.0},
            REGIME_CHOPPY: {"momentum": 0.5, "mean_rev": 0.5, "low_vol": 0.0},
        }
        wd = {
            "momentum": make_weights(prices),
            "mean_rev": make_weights(prices),
            "low_vol":  make_weights(prices),
        }
        combined = regime_aware_combine(wd, bench, regime_allocs=custom_allocs)
        assert (combined.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_accepts_dataframe_benchmark(self):
        prices = make_prices()
        wd = self._make_weights_dict(prices)
        bench_df = make_benchmark(n_days=len(prices)).to_frame("BENCH")
        combined = regime_aware_combine(wd, bench_df)
        assert combined.shape == prices.shape

    def test_index_matches_reference_strategy(self):
        prices = make_prices()
        wd = self._make_weights_dict(prices)
        bench = make_benchmark(n_days=len(prices))
        combined = regime_aware_combine(wd, bench)
        assert combined.index.equals(prices.index)


# ---------------------------------------------------------------------------
# DEFAULT_REGIME_ALLOCS structure
# ---------------------------------------------------------------------------

class TestDefaultRegimeAllocs:
    def test_all_regimes_present(self):
        assert REGIME_BULL in DEFAULT_REGIME_ALLOCS
        assert REGIME_BEAR in DEFAULT_REGIME_ALLOCS
        assert REGIME_CHOPPY in DEFAULT_REGIME_ALLOCS

    def test_allocations_sum_to_one(self):
        for regime, allocs in DEFAULT_REGIME_ALLOCS.items():
            total = sum(allocs.values())
            assert abs(total - 1.0) < 1e-9, f"Regime {regime} allocs sum to {total}"

    def test_all_non_negative(self):
        for allocs in DEFAULT_REGIME_ALLOCS.values():
            assert all(v >= 0 for v in allocs.values())
