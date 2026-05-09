"""
test_regime_detector.py
-----------------------
Unit tests for src/regime_detector.py (RegimeDetector).
"""

import numpy as np
import pandas as pd
import pytest

from src.regime_detector import RegimeDetector, REGIME_BULL, REGIME_BEAR, REGIME_CHOPPY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_benchmark(n_days: int = 500, drift: float = 0.0005, vol: float = 0.01, seed: int = 0) -> pd.Series:
    """Create a synthetic benchmark price series."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2017-01-01", periods=n_days, freq="B")
    rets = rng.normal(drift, vol, n_days)
    prices = 100 * np.exp(np.cumsum(rets))
    return pd.Series(prices, index=dates, name="BENCH")


def make_single_col_df(n_days: int = 500) -> pd.DataFrame:
    """Wrap as single-column DataFrame."""
    s = make_benchmark(n_days)
    return s.to_frame(name="BENCH")


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestRegimeDetectorOutput:
    def test_returns_series(self):
        bench = make_benchmark()
        r = RegimeDetector().detect(bench)
        assert isinstance(r, pd.Series)

    def test_index_matches_input(self):
        bench = make_benchmark()
        r = RegimeDetector().detect(bench)
        assert r.index.equals(bench.index)

    def test_only_valid_labels(self):
        bench = make_benchmark()
        r = RegimeDetector().detect(bench)
        valid = {REGIME_BULL, REGIME_BEAR, REGIME_CHOPPY}
        assert set(r.unique()).issubset(valid)

    def test_accepts_dataframe(self):
        df = make_single_col_df()
        r = RegimeDetector().detect(df)
        assert isinstance(r, pd.Series)

    def test_rejects_multi_col_df(self):
        df = pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [1.0, 2.0, 3.0]})
        with pytest.raises((ValueError, Exception)):
            RegimeDetector().detect(df)


# ---------------------------------------------------------------------------
# Regime classification correctness
# ---------------------------------------------------------------------------

class TestRegimeClassification:
    def test_strong_bull_regime(self):
        """
        Steadily rising prices with low volatility should produce BULL labels
        after the SMA warm-up period.
        """
        n = 600
        dates = pd.date_range("2016-01-01", periods=n, freq="B")
        # Very gentle drift + tiny noise → above SMA(200) + low short/long vol ratio
        rng = np.random.default_rng(7)
        rets = rng.normal(0.001, 0.003, n)  # very low vol
        prices = pd.Series(100 * np.exp(np.cumsum(rets)), index=dates)

        r = RegimeDetector().detect(prices)
        # After warmup (200 bars), majority should be BULL
        late = r.iloc[250:]
        bull_frac = (late == REGIME_BULL).mean()
        assert bull_frac > 0.5, f"Expected >50% BULL in uptrending low-vol market, got {bull_frac:.2%}"

    def test_bear_regime_detected(self):
        """
        When prices are below SMA(200) AND 20-day annualised vol exceeds
        the fixed threshold (0.20 = 20% p.a.), the regime should be BEAR.

        Crash period: vol = 0.040 daily ≈ 63.5% annualised → well above 20%.
        """
        n = 600
        dates = pd.date_range("2016-01-01", periods=n, freq="B")
        rng = np.random.default_rng(13)
        # First 300 days: calm uptrend (vol well below 20% ann.)
        calm_rets = rng.normal(0.0005, 0.007, 300)
        # Last 300 days: crash + very high vol (vol ≈ 63% ann. >> 20% threshold)
        crash_rets = rng.normal(-0.003, 0.040, 300)
        rets = np.concatenate([calm_rets, crash_rets])
        prices = pd.Series(100 * np.exp(np.cumsum(rets)), index=dates)

        r = RegimeDetector(high_vol_ann_threshold=0.20).detect(prices)
        # Deep in crash (last 100 bars): expect significant BEAR labelling
        final = r.iloc[500:]
        bear_frac = (final == REGIME_BEAR).mean()
        assert bear_frac > 0.3, f"Expected >30% BEAR in high-vol crash, got {bear_frac:.2%}"

    def test_warmup_period_defaults_to_choppy(self):
        """
        Bars before the SMA warm-up (first sma_window - 1 bars) should be
        CHOPPY because SMA is not yet computable.

        rolling(200, min_periods=200) first produces a value at index 199;
        so indices 0..198 are NaN → must be CHOPPY.
        """
        bench = make_benchmark(n_days=600)
        r = RegimeDetector(sma_window=200).detect(bench)
        # Indices 0..198 (first 199 bars): SMA is NaN → must be CHOPPY
        pre_warmup = r.iloc[:199]
        assert (pre_warmup == REGIME_CHOPPY).all(), "Pre-warmup bars should all be CHOPPY"


# ---------------------------------------------------------------------------
# regime_counts helper
# ---------------------------------------------------------------------------

class TestRegimeCounts:
    def test_counts_sum_to_total_days(self):
        bench = make_benchmark(n_days=500)
        det = RegimeDetector()
        counts = det.regime_counts(bench)
        total = counts[REGIME_BULL] + counts[REGIME_BEAR] + counts[REGIME_CHOPPY]
        assert total == len(bench)

    def test_counts_non_negative(self):
        bench = make_benchmark()
        counts = RegimeDetector().regime_counts(bench)
        assert all(v >= 0 for v in counts.values())


# ---------------------------------------------------------------------------
# Config parameters
# ---------------------------------------------------------------------------

class TestRegimeDetectorConfig:
    def test_custom_thresholds(self):
        det = RegimeDetector(sma_window=50, high_vol_ann_threshold=0.15)
        bench = make_benchmark(n_days=400)
        r = det.detect(bench)
        # Just verify it runs and returns valid labels
        valid = {REGIME_BULL, REGIME_BEAR, REGIME_CHOPPY}
        assert set(r.unique()).issubset(valid)

    def test_defaults(self):
        det = RegimeDetector()
        assert det.sma_window == 200
        assert det.vol_window == 20
        assert det.high_vol_ann_threshold == 0.20
