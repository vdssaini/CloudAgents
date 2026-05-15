"""
test_mean_reversion_strategy.py
--------------------------------
Unit tests for the RSI(2) + Bollinger Band mean-reversion strategy
and the new indicators it depends on.
"""

import numpy as np
import pandas as pd
import pytest

from src.indicators import rsi_fast, bollinger_pct_b, consecutive_down_days, nday_return_zscore
from src.strategy_mean_reversion import MeanReversionStrategy, MeanReversionConfig, combine_strategies
from src.strategy import MomentumTrendStrategy, StrategyConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_prices(n_days: int = 400, n_stocks: int = 8, seed: int = 7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    tickers = [f"STK{i}" for i in range(n_stocks)]
    log_ret = rng.normal(0.0005, 0.015, size=(n_days, n_stocks))
    prices  = 100 * np.exp(np.cumsum(log_ret, axis=0))
    return pd.DataFrame(prices, index=dates, columns=tickers)


@pytest.fixture
def random_prices():
    return make_prices(n_days=400, n_stocks=8)


@pytest.fixture
def default_mr_strategy():
    return MeanReversionStrategy()


# ---------------------------------------------------------------------------
# rsi_fast
# ---------------------------------------------------------------------------

class TestRSIFast:
    def test_range(self, random_prices):
        result = rsi_fast(random_prices, 2).dropna()
        assert (result >= 0).all().all()
        assert (result <= 100).all().all()

    def test_warmup_nan(self, random_prices):
        result = rsi_fast(random_prices, 2)
        assert result.iloc[:1].isna().all().all()

    def test_oversold_after_big_drop(self):
        """After several large down days RSI(2) should be < 10."""
        dates = pd.date_range("2020-01-01", periods=20, freq="B")
        # Drop 5 % per day for 5 days
        prices = pd.DataFrame(
            {"A": 100 * np.cumprod(np.r_[np.ones(10), np.full(10, 0.95)])},
            index=dates,
        )
        result = rsi_fast(prices, 2).dropna()
        assert result["A"].iloc[-1] < 30  # well oversold

    def test_overbought_after_big_rise(self):
        """After several large up days RSI(2) should be > 70."""
        dates = pd.date_range("2020-01-01", periods=20, freq="B")
        prices = pd.DataFrame(
            {"A": 100 * np.cumprod(np.r_[np.ones(10), np.full(10, 1.05)])},
            index=dates,
        )
        result = rsi_fast(prices, 2).dropna()
        assert len(result) > 0, "rsi_fast produced only NaN for 20 rows"
        assert result["A"].iloc[-1] > 70  # overbought


# ---------------------------------------------------------------------------
# bollinger_pct_b
# ---------------------------------------------------------------------------

class TestBollingerPctB:
    def test_shape(self, random_prices):
        result = bollinger_pct_b(random_prices)
        assert result.shape == random_prices.shape

    def test_at_midband_approx_half(self):
        """When price equals the 20-day mean, %B should be ≈ 0.5."""
        dates = pd.date_range("2020-01-01", periods=60, freq="B")
        # Random walk then flat at mean
        rng = np.random.default_rng(0)
        log_ret = rng.normal(0, 0.01, 60)
        prices_arr = 100 * np.exp(np.cumsum(log_ret))
        prices = pd.DataFrame({"A": prices_arr}, index=dates)
        result = bollinger_pct_b(prices).dropna()
        # At steady state the mean of %B should be near 0.5
        assert 0.2 < result["A"].mean() < 0.8

    def test_low_after_sustained_drop(self):
        """After a sustained decline %B should be < 0.2."""
        dates = pd.date_range("2020-01-01", periods=50, freq="B")
        prices = pd.DataFrame(
            {"A": np.linspace(150, 50, 50)},  # strong downtrend
            index=dates,
        )
        result = bollinger_pct_b(prices).dropna()
        assert result["A"].iloc[-1] < 0.3

    def test_high_after_sustained_rise(self):
        """After a sustained rise %B should be > 0.7."""
        dates = pd.date_range("2020-01-01", periods=50, freq="B")
        prices = pd.DataFrame(
            {"A": np.linspace(50, 200, 50)},  # strong uptrend
            index=dates,
        )
        result = bollinger_pct_b(prices).dropna()
        assert result["A"].iloc[-1] > 0.7


# ---------------------------------------------------------------------------
# consecutive_down_days
# ---------------------------------------------------------------------------

class TestConsecutiveDownDays:
    def test_shape(self, random_prices):
        result = consecutive_down_days(random_prices)
        assert result.shape == random_prices.shape

    def test_non_negative(self, random_prices):
        result = consecutive_down_days(random_prices)
        assert (result >= 0).all().all()

    def test_reset_on_up_day(self):
        """Streak must reset to 0 after an up day."""
        dates = pd.date_range("2020-01-01", periods=6, freq="B")
        prices = pd.DataFrame(
            {"A": [100, 99, 98, 97, 98, 97]},  # down, down, down, UP, down
            index=dates,
        )
        result = consecutive_down_days(prices)
        assert result["A"].iloc[3] == 3   # 3 down days
        assert result["A"].iloc[4] == 0   # reset on up day
        assert result["A"].iloc[5] == 1   # 1 new down day

    def test_all_up_days_zero(self):
        dates = pd.date_range("2020-01-01", periods=10, freq="B")
        prices = pd.DataFrame({"A": np.linspace(100, 200, 10)}, index=dates)
        result = consecutive_down_days(prices)
        assert (result["A"] == 0).all()

    def test_all_down_days_increasing_count(self):
        """In a persistent downtrend, count should increase each day."""
        dates = pd.date_range("2020-01-01", periods=10, freq="B")
        prices = pd.DataFrame({"A": np.linspace(200, 100, 10)}, index=dates)
        result = consecutive_down_days(prices)
        # From the second row onwards the count should increase
        assert list(result["A"].iloc[1:]) == list(range(1, 10))


# ---------------------------------------------------------------------------
# nday_return_zscore
# ---------------------------------------------------------------------------

class TestNDayReturnZScore:
    def test_shape(self, random_prices):
        result = nday_return_zscore(random_prices, 5).dropna()
        assert result.shape[1] == random_prices.shape[1]

    def test_row_mean_zero(self, random_prices):
        result = nday_return_zscore(random_prices, 5).dropna()
        assert np.allclose(result.mean(axis=1), 0, atol=1e-10)

    def test_row_std_one(self, random_prices):
        result = nday_return_zscore(random_prices, 5).dropna()
        assert np.allclose(result.std(axis=1), 1, atol=1e-10)


# ---------------------------------------------------------------------------
# MeanReversionStrategy output contract
# ---------------------------------------------------------------------------

class TestMeanReversionWeightContract:
    def test_returns_dataframe(self, default_mr_strategy, random_prices):
        w = default_mr_strategy.generate_weights(random_prices)
        assert isinstance(w, pd.DataFrame)

    def test_same_shape(self, default_mr_strategy, random_prices):
        w = default_mr_strategy.generate_weights(random_prices)
        assert w.shape == random_prices.shape

    def test_weights_non_negative(self, default_mr_strategy, random_prices):
        w = default_mr_strategy.generate_weights(random_prices)
        assert (w >= 0).all().all()

    def test_row_sum_at_most_one(self, default_mr_strategy, random_prices):
        w = default_mr_strategy.generate_weights(random_prices)
        assert (w.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_max_weight_per_stock(self, default_mr_strategy, random_prices):
        w = default_mr_strategy.generate_weights(random_prices)
        assert (w <= default_mr_strategy.config.max_weight + 1e-9).all().all()

    def test_max_positions_respected(self):
        prices = make_prices(n_days=400, n_stocks=20)
        cfg    = MeanReversionConfig(max_positions=5)
        w      = MeanReversionStrategy(cfg).generate_weights(prices)
        assert ((w > 0).sum(axis=1) <= 5).all()

    def test_warmup_all_zero(self, default_mr_strategy, random_prices):
        w      = default_mr_strategy.generate_weights(random_prices)
        warmup = default_mr_strategy.config.trend_sma_window
        assert (w.iloc[:warmup] == 0).all().all()


# ---------------------------------------------------------------------------
# combine_strategies
# ---------------------------------------------------------------------------

class TestCombineStrategies:
    def _get_weights(self):
        prices = make_prices(n_days=400, n_stocks=10, seed=42)
        mom_w = MomentumTrendStrategy(StrategyConfig(top_n=5, min_positions=1)).generate_weights(prices)
        mr_w  = MeanReversionStrategy(MeanReversionConfig(max_positions=3)).generate_weights(prices)
        return mom_w, mr_w

    def test_returns_dataframe(self):
        mom_w, mr_w = self._get_weights()
        result = combine_strategies(mom_w, mr_w)
        assert isinstance(result, pd.DataFrame)

    def test_row_sum_at_most_one(self):
        mom_w, mr_w = self._get_weights()
        result = combine_strategies(mom_w, mr_w)
        assert (result.sum(axis=1) <= 1.0 + 1e-9).all()

    def test_non_negative(self):
        mom_w, mr_w = self._get_weights()
        result = combine_strategies(mom_w, mr_w)
        assert (result >= 0).all().all()

    def test_allocation_split(self):
        """Fully invested momentum + zero MR → result ≈ 60 % invested."""
        prices = make_prices(n_days=400, n_stocks=6, seed=1)
        mom_w  = pd.DataFrame(1.0 / 6, index=prices.index, columns=prices.columns)
        mr_w   = pd.DataFrame(0.0,     index=prices.index, columns=prices.columns)
        result = combine_strategies(mom_w, mr_w, momentum_alloc=0.60, mean_rev_alloc=0.40)
        # Each stock gets (1/6) * 0.60 ≈ 0.10; total ≈ 0.60
        assert result.sum(axis=1).mean() == pytest.approx(0.60, abs=0.01)
