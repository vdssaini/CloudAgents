"""
test_strategy.py
----------------
Unit tests for src/strategy.py  (MomentumTrendStrategy signal generation)
"""

import numpy as np
import pandas as pd
import pytest

from src.strategy import MomentumTrendStrategy, StrategyConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_prices(n_days: int = 400, n_stocks: int = 6, seed: int = 42):
    """Generate synthetic price data for testing strategy logic."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    tickers = [f"STK{i}" for i in range(n_stocks)]
    log_returns = rng.normal(0.0005, 0.015, size=(n_days, n_stocks))
    prices_arr = 100 * np.exp(np.cumsum(log_returns, axis=0))
    return pd.DataFrame(prices_arr, index=dates, columns=tickers)


def trending_up_prices(n_days: int = 400):
    """
    All stocks trending upward via a random walk with strong positive drift.
    We intentionally add daily noise so RSI stays below 100 (not all gains).
    """
    rng = np.random.default_rng(1)
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    tickers = [f"STK{i}" for i in range(8)]
    prices_arr = np.zeros((n_days, 8))
    for i, _ in enumerate(tickers):
        log_ret = rng.normal(0.002, 0.01, n_days)   # strong upward drift + noise
        prices_arr[:, i] = (80 + i * 5) * np.exp(np.cumsum(log_ret))
    return pd.DataFrame(prices_arr, index=dates, columns=tickers)


def trending_down_prices(n_days: int = 400):
    """All stocks in strong downtrends — trend filter should block them."""
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    tickers = [f"STK{i}" for i in range(6)]
    prices_arr = np.zeros((n_days, 6))
    for i in range(6):
        start = 200 - i * 5
        prices_arr[:, i] = np.maximum(start - np.arange(n_days) * 0.5, 1.0)
    return pd.DataFrame(prices_arr, index=dates, columns=tickers)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_strategy():
    return MomentumTrendStrategy()


@pytest.fixture
def random_prices():
    return make_prices()


# ---------------------------------------------------------------------------
# Weight output contract
# ---------------------------------------------------------------------------

class TestWeightOutput:
    def test_returns_dataframe(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        assert isinstance(weights, pd.DataFrame)

    def test_same_shape_as_prices(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        assert weights.shape == random_prices.shape

    def test_same_index_as_prices(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        assert weights.index.equals(random_prices.index)

    def test_same_columns_as_prices(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        assert list(weights.columns) == list(random_prices.columns)

    def test_weights_non_negative(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        assert (weights >= 0).all().all()

    def test_row_sum_at_most_one(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        row_sums = weights.sum(axis=1)
        assert (row_sums <= 1.0 + 1e-9).all()

    def test_max_weight_per_stock_respected(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        max_w = default_strategy.config.max_weight
        assert (weights <= max_w + 1e-9).all().all()

    def test_warmup_period_all_zero(self, default_strategy, random_prices):
        weights = default_strategy.generate_weights(random_prices)
        warmup = default_strategy.config.trend_sma_window
        assert (weights.iloc[:warmup] == 0).all().all()


# ---------------------------------------------------------------------------
# Trend-filter logic
# ---------------------------------------------------------------------------

class TestTrendFilter:
    def test_uptrend_produces_positions(self):
        """Strong upward trend → stocks pass the 200-day SMA filter."""
        prices = trending_up_prices(400)
        cfg = StrategyConfig(top_n=8, min_positions=1)
        strategy = MomentumTrendStrategy(cfg)
        weights = strategy.generate_weights(prices)
        # After warmup there should be at least some non-zero weights
        active = (weights.sum(axis=1) > 0)
        assert active.any(), "Expected at least some positions in an uptrend."

    def test_downtrend_few_positions(self):
        """Stocks below 200-day SMA are blocked by the trend filter."""
        prices = trending_down_prices(400)
        cfg = StrategyConfig(top_n=6, min_positions=1)
        strategy = MomentumTrendStrategy(cfg)
        weights = strategy.generate_weights(prices)
        # Most days after the warmup should have zero or very few positions
        post_warmup = weights.iloc[cfg.trend_sma_window:]
        avg_invested = post_warmup.sum(axis=1).mean()
        # In a persistent down-trend, most/all days should be in cash
        assert avg_invested < 0.5, (
            f"Expected low allocation in a downtrend, got {avg_invested:.2%}"
        )


# ---------------------------------------------------------------------------
# Config parameters honoured
# ---------------------------------------------------------------------------

class TestConfigHonoured:
    def test_top_n_respected(self):
        prices = make_prices(n_days=400, n_stocks=20)
        cfg = StrategyConfig(top_n=5, min_positions=1)
        weights = MomentumTrendStrategy(cfg).generate_weights(prices)
        max_positions = (weights > 0).sum(axis=1).max()
        assert max_positions <= 5

    def test_custom_rebalance_period(self):
        """Rebalance cadence only fires when the counter hits a multiple of rebalance_days.
        We verify the strategy re-evaluates positions no more often than that cadence
        by checking that consecutive weight-change events are spaced by at least
        (rebalance_days - 1) business days in the post-warmup period.
        """
        prices = make_prices(n_days=400, n_stocks=8)
        rebalance_days = 42
        cfg = StrategyConfig(rebalance_days=rebalance_days, min_positions=1, top_n=5,
                             trailing_stop_enabled=False)  # disable stops to isolate rebalance logic
        weights = MomentumTrendStrategy(cfg).generate_weights(prices)
        post_warmup = weights.iloc[cfg.trend_sma_window:]
        changed = (post_warmup.diff().abs().sum(axis=1) > 1e-9)
        if changed.sum() > 1:
            # Count business-day gaps between consecutive rebalances
            change_positions = np.where(changed.values)[0]
            gaps_in_bdays = np.diff(change_positions)
            # Every gap must be at least (rebalance_days - 1) business days
            assert gaps_in_bdays.min() >= rebalance_days - 1, (
                f"Shortest gap between rebalances: {gaps_in_bdays.min()} bdays "
                f"(expected ≥ {rebalance_days - 1})"
            )

    def test_min_positions_threshold(self):
        """If not enough stocks pass filters, strategy goes to cash."""
        # Very few stocks, very strict filter → should stay in cash
        prices = make_prices(n_days=400, n_stocks=3)
        cfg = StrategyConfig(top_n=10, min_positions=10, rsi_entry_max=5.0)
        weights = MomentumTrendStrategy(cfg).generate_weights(prices)
        # RSI entry max of 5 means almost nothing passes → go to cash
        post_warmup = weights.iloc[cfg.trend_sma_window:]
        assert (post_warmup.sum(axis=1) == 0).all()
