"""
test_strategy_low_vol.py
------------------------
Unit tests for src/strategy_low_vol.py (LowVolStrategy).
"""

import numpy as np
import pandas as pd
import pytest

from src.strategy_low_vol import LowVolStrategy, LowVolConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_prices(n_days: int = 350, n_stocks: int = 10, seed: int = 0) -> pd.DataFrame:
    """Synthetic uptrending price data (so trend filter passes)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    tickers = [f"S{i}" for i in range(n_stocks)]
    log_rets = rng.normal(0.0005, 0.012, size=(n_days, n_stocks))
    prices = 100 * np.exp(np.cumsum(log_rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=tickers)


def downtrending_prices(n_days: int = 350, n_stocks: int = 6) -> pd.DataFrame:
    """All stocks in a steady downtrend — trend filter should block all entries."""
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    tickers = [f"D{i}" for i in range(n_stocks)]
    arr = np.zeros((n_days, n_stocks))
    for i in range(n_stocks):
        arr[:, i] = np.maximum(200 - np.arange(n_days) * 0.5, 1.0)
    return pd.DataFrame(arr, index=dates, columns=tickers)


# ---------------------------------------------------------------------------
# Basic weight properties
# ---------------------------------------------------------------------------

class TestLowVolBasicProperties:
    """Weight output should have correct shape, non-negative values, row sums <= 1."""

    def test_output_shape(self):
        prices = make_prices()
        w = LowVolStrategy().generate_weights(prices)
        assert w.shape == prices.shape

    def test_weights_non_negative(self):
        prices = make_prices()
        w = LowVolStrategy().generate_weights(prices)
        assert (w >= 0).all().all()

    def test_row_sums_at_most_one(self):
        prices = make_prices()
        w = LowVolStrategy().generate_weights(prices)
        assert (w.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_columns_match_prices(self):
        prices = make_prices()
        w = LowVolStrategy().generate_weights(prices)
        assert list(w.columns) == list(prices.columns)

    def test_index_matches_prices(self):
        prices = make_prices()
        w = LowVolStrategy().generate_weights(prices)
        assert w.index.equals(prices.index)


# ---------------------------------------------------------------------------
# Trend filter
# ---------------------------------------------------------------------------

class TestLowVolTrendFilter:
    """Strategy must hold zero weight in stocks below SMA(200)."""

    def test_no_positions_in_downtrend(self):
        prices = downtrending_prices()
        w = LowVolStrategy().generate_weights(prices)
        assert w.sum().sum() == 0.0, "Should hold no positions in downtrending universe"

    def test_positions_in_uptrend(self):
        prices = make_prices(n_days=350, n_stocks=15)
        w = LowVolStrategy().generate_weights(prices)
        # After warmup, should have at least some positions
        assert w.tail(100).sum(axis=1).mean() > 0.1


# ---------------------------------------------------------------------------
# Stock selection: lowest-vol stocks should be selected
# ---------------------------------------------------------------------------

class TestLowVolSelection:
    """Low-vol stocks should be preferred over high-vol stocks."""

    def test_selects_lower_vol_stocks(self):
        """
        Build a universe with two groups:
          - Stocks 0..4: very low vol (σ = 0.005 daily)
          - Stocks 5..9: very high vol (σ = 0.030 daily)
        Strategy should predominantly hold the low-vol group.
        """
        rng = np.random.default_rng(42)
        n_days = 350
        dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
        tickers = [f"LV{i}" for i in range(5)] + [f"HV{i}" for i in range(5)]

        # Low-vol: gentle uptrend + tiny noise
        lv_rets = rng.normal(0.0004, 0.005, size=(n_days, 5))
        # High-vol: same drift + large noise
        hv_rets = rng.normal(0.0004, 0.030, size=(n_days, 5))

        all_rets = np.hstack([lv_rets, hv_rets])
        prices = pd.DataFrame(
            100 * np.exp(np.cumsum(all_rets, axis=0)),
            index=dates, columns=tickers,
        )

        cfg = LowVolConfig(top_n=5, min_positions=3)
        w = LowVolStrategy(cfg).generate_weights(prices)

        # In the last 50 bars, low-vol stocks should hold most of the weight
        late_weights = w.tail(50)
        lv_weight = late_weights[[c for c in tickers if c.startswith("LV")]].sum(axis=1).mean()
        hv_weight = late_weights[[c for c in tickers if c.startswith("HV")]].sum(axis=1).mean()
        assert lv_weight > hv_weight, f"Low-vol weight {lv_weight:.3f} should > high-vol {hv_weight:.3f}"


# ---------------------------------------------------------------------------
# Position size cap
# ---------------------------------------------------------------------------

class TestLowVolPositionCap:
    """No single stock should exceed max_weight."""

    def test_max_weight_respected(self):
        cap = 0.08
        cfg = LowVolConfig(max_weight=cap)
        prices = make_prices(n_days=350, n_stocks=20)
        w = LowVolStrategy(cfg).generate_weights(prices)
        assert (w <= cap + 1e-9).all().all(), f"Some weight exceeds cap {cap}"

    def test_default_cap_ten_pct(self):
        prices = make_prices(n_days=350, n_stocks=25)
        w = LowVolStrategy().generate_weights(prices)
        assert (w <= 0.10 + 1e-9).all().all()


# ---------------------------------------------------------------------------
# Minimum positions
# ---------------------------------------------------------------------------

class TestLowVolMinPositions:
    """When fewer than min_positions qualify, strategy should go to cash."""

    def test_cash_when_too_few_qualify(self):
        """Only 2 stocks in the universe → below min_positions=5 → all cash."""
        prices = make_prices(n_days=350, n_stocks=2)
        cfg = LowVolConfig(min_positions=5)
        w = LowVolStrategy(cfg).generate_weights(prices)
        assert w.sum().sum() == 0.0, "Should be all-cash with only 2 stocks"


# ---------------------------------------------------------------------------
# Monthly rebalance cadence
# ---------------------------------------------------------------------------

class TestLowVolRebalanceCadence:
    """Weights should be constant between rebalance dates."""

    def test_weights_constant_between_rebalances(self):
        prices = make_prices(n_days=350, n_stocks=12)
        cfg = LowVolConfig(rebalance_days=21)
        w = LowVolStrategy(cfg).generate_weights(prices)

        # Find the first day with a non-zero position
        first_active = (w.sum(axis=1) > 0).idxmax()
        idx = w.index.get_loc(first_active)

        # The next 5 bars should have identical weights (no rebalance within month)
        if idx + 6 < len(w):
            w0 = w.iloc[idx]
            for j in range(1, 6):
                pd.testing.assert_series_equal(w.iloc[idx + j], w0, check_names=False)


# ---------------------------------------------------------------------------
# Config dataclass defaults
# ---------------------------------------------------------------------------

class TestLowVolConfig:
    def test_defaults(self):
        cfg = LowVolConfig()
        assert cfg.trend_sma_window == 200
        assert cfg.vol_window == 20
        assert cfg.top_n == 20
        assert cfg.max_weight == 0.10
        assert cfg.min_positions == 5
        assert cfg.rebalance_days == 21

    def test_custom_config(self):
        cfg = LowVolConfig(top_n=10, max_weight=0.05)
        assert cfg.top_n == 10
        assert cfg.max_weight == 0.05
