"""
test_indicators.py
------------------
Unit tests for src/indicators.py
"""

import numpy as np
import pandas as pd
import pytest

from src.indicators import sma, ema, rsi, momentum, atr, cross_sectional_zscore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_prices():
    """Constant price series — all indicators should be well-defined."""
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    data = {t: [100.0] * 300 for t in ["AAPL", "MSFT", "GOOG"]}
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def trending_prices():
    """Linearly increasing price series."""
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    data = {}
    for i, t in enumerate(["AAPL", "MSFT", "GOOG"]):
        start = 100 + i * 10
        data[t] = [start + j * 0.5 for j in range(300)]
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def random_prices():
    """Seeded random-walk prices for statistical checks."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2015-01-01", periods=500, freq="B")
    log_ret = rng.normal(0.0003, 0.015, size=(500, 4))
    prices_arr = 100 * np.exp(np.cumsum(log_ret, axis=0))
    return pd.DataFrame(
        prices_arr, index=dates, columns=["A", "B", "C", "D"]
    )


# ---------------------------------------------------------------------------
# SMA tests
# ---------------------------------------------------------------------------

class TestSMA:
    def test_shape_preserved(self, flat_prices):
        result = sma(flat_prices, 50)
        assert result.shape == flat_prices.shape

    def test_constant_prices(self, flat_prices):
        result = sma(flat_prices, 50)
        valid = result.dropna()
        assert np.allclose(valid.values, 100.0)

    def test_warmup_nan(self, flat_prices):
        result = sma(flat_prices, 50)
        assert result.iloc[:49].isna().all().all()
        assert not result.iloc[49:].isna().any().any()

    def test_linearly_increasing(self, trending_prices):
        result = sma(trending_prices, 20)
        # SMA of a linear series = value at mid-point of window
        valid = result.dropna()
        prices_valid = trending_prices.iloc[len(trending_prices) - len(valid):]
        # SMA should be ≤ current price (price is increasing)
        assert (prices_valid.values >= valid.values).all()


# ---------------------------------------------------------------------------
# EMA tests
# ---------------------------------------------------------------------------

class TestEMA:
    def test_shape(self, flat_prices):
        result = ema(flat_prices, 20)
        assert result.shape == flat_prices.shape

    def test_constant_prices(self, flat_prices):
        result = ema(flat_prices, 20).dropna()
        assert np.allclose(result.values, 100.0, atol=1e-6)

    def test_ema_faster_than_sma(self, trending_prices):
        """EMA reacts faster to new prices than SMA of same window."""
        s = sma(trending_prices, 50).dropna()
        e = ema(trending_prices, 50).dropna()
        common = s.index.intersection(e.index)
        # For an upward trend, EMA > SMA (EMA gives more weight to recent prices)
        assert (e.loc[common].values >= s.loc[common].values).all()


# ---------------------------------------------------------------------------
# RSI tests
# ---------------------------------------------------------------------------

class TestRSI:
    def test_range(self, random_prices):
        result = rsi(random_prices, 14).dropna()
        assert (result >= 0).all().all()
        assert (result <= 100).all().all()

    def test_constant_prices(self, flat_prices):
        result = rsi(flat_prices, 14).dropna()
        # No gains, no losses → RSI is NaN or 50 (undefined; different implementations vary)
        # We just check it doesn't crash and is in valid range where defined
        valid = result.dropna()
        if not valid.empty:
            assert (valid >= 0).all().all() and (valid <= 100).all().all()

    def test_warmup(self, random_prices):
        result = rsi(random_prices, 14)
        assert result.iloc[:13].isna().all().all()


# ---------------------------------------------------------------------------
# Momentum tests
# ---------------------------------------------------------------------------

class TestMomentum:
    def test_shape(self, random_prices):
        result = momentum(random_prices, 63)
        assert result.shape == random_prices.shape

    def test_positive_for_rising_price(self):
        """A consistently rising stock should have positive momentum."""
        dates = pd.date_range("2015-01-01", periods=300, freq="B")
        prices = pd.DataFrame(
            {"A": np.linspace(100, 200, 300)}, index=dates
        )
        result = momentum(prices, 63).dropna()
        assert (result["A"] > 0).all()

    def test_negative_for_falling_price(self):
        """A consistently falling stock should have negative momentum."""
        dates = pd.date_range("2015-01-01", periods=300, freq="B")
        prices = pd.DataFrame(
            {"A": np.linspace(200, 100, 300)}, index=dates
        )
        result = momentum(prices, 63).dropna()
        assert (result["A"] < 0).all()


# ---------------------------------------------------------------------------
# ATR tests
# ---------------------------------------------------------------------------

class TestATR:
    def test_positive(self, random_prices):
        result = atr(random_prices, 14).dropna()
        assert (result > 0).all().all()

    def test_higher_vol_higher_atr(self):
        """Higher-volatility stock should have larger ATR."""
        rng = np.random.default_rng(0)
        dates = pd.date_range("2020-01-01", periods=200, freq="B")
        low_vol = pd.DataFrame(
            {"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.005, 200)))},
            index=dates,
        )
        high_vol = pd.DataFrame(
            {"B": 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 200)))},
            index=dates,
        )
        atr_low = atr(low_vol, 14).dropna().mean().iloc[0]
        atr_high = atr(high_vol, 14).dropna().mean().iloc[0]
        assert atr_high > atr_low


# ---------------------------------------------------------------------------
# Cross-sectional z-score tests
# ---------------------------------------------------------------------------

class TestCrossSectionalZScore:
    def test_mean_zero(self, random_prices):
        result = cross_sectional_zscore(random_prices).dropna()
        row_means = result.mean(axis=1)
        assert np.allclose(row_means, 0, atol=1e-10)

    def test_std_one(self, random_prices):
        result = cross_sectional_zscore(random_prices).dropna()
        row_stds = result.std(axis=1)
        assert np.allclose(row_stds, 1, atol=1e-10)
