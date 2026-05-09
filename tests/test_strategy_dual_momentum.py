"""
test_strategy_dual_momentum.py
-------------------------------
Unit tests for src/strategy_dual_momentum.py (DualMomentumStrategy).
"""

import numpy as np
import pandas as pd
import pytest

from src.strategy_dual_momentum import DualMomentumStrategy, DualMomentumConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_prices(n_days: int = 500, n_stocks: int = 8, seed: int = 99):
    """Generic synthetic price data."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2016-01-01", periods=n_days, freq="B")
    tickers = [f"STK{i}" for i in range(n_stocks)]
    log_returns = rng.normal(0.0005, 0.012, size=(n_days, n_stocks))
    prices_arr = 100 * np.exp(np.cumsum(log_returns, axis=0))
    return pd.DataFrame(prices_arr, index=dates, columns=tickers)


def trending_up_prices(n_days: int = 500, n_stocks: int = 8):
    """Strong uptrending prices — all should pass trend + abs_mom filters."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2016-01-01", periods=n_days, freq="B")
    tickers = [f"STK{i}" for i in range(n_stocks)]
    prices_arr = np.zeros((n_days, n_stocks))
    for i in range(n_stocks):
        log_ret = rng.normal(0.0025, 0.008, n_days)   # strong positive drift
        prices_arr[:, i] = (80 + i * 5) * np.exp(np.cumsum(log_ret))
    return pd.DataFrame(prices_arr, index=dates, columns=tickers)


def trending_down_prices(n_days: int = 500, n_stocks: int = 8):
    """Strong downtrending prices — absolute momentum filter should block all."""
    dates = pd.date_range("2016-01-01", periods=n_days, freq="B")
    tickers = [f"STK{i}" for i in range(n_stocks)]
    prices_arr = np.zeros((n_days, n_stocks))
    for i in range(n_stocks):
        start = 200 - i * 5
        # Consistent decline over full history
        prices_arr[:, i] = np.maximum(start - np.arange(n_days) * 0.4, 1.0)
    return pd.DataFrame(prices_arr, index=dates, columns=tickers)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_strategy():
    return DualMomentumStrategy()


@pytest.fixture
def fast_strategy():
    """Reduced windows for tests to run quickly."""
    cfg = DualMomentumConfig(
        trend_sma_window=50,
        fast_sma_window=20,
        abs_mom_lookback=63,
        high_52w_window=63,
        rel_mom_lookback=42,
        rsi_window=7,
        vol_window=10,
        atr_window=7,
        top_n=5,
        min_positions=2,
        trailing_stop_enabled=False,
    )
    return DualMomentumStrategy(cfg)


# ---------------------------------------------------------------------------
# Output shape and type tests
# ---------------------------------------------------------------------------

class TestOutputShape:
    def test_output_shape_matches_input(self, fast_strategy):
        prices = make_prices(n_days=200, n_stocks=6)
        weights = fast_strategy.generate_weights(prices)
        assert weights.shape == prices.shape

    def test_output_is_dataframe(self, fast_strategy):
        prices = make_prices(n_days=200, n_stocks=6)
        weights = fast_strategy.generate_weights(prices)
        assert isinstance(weights, pd.DataFrame)

    def test_columns_match(self, fast_strategy):
        prices = make_prices(n_days=200, n_stocks=6)
        weights = fast_strategy.generate_weights(prices)
        assert list(weights.columns) == list(prices.columns)

    def test_index_matches(self, fast_strategy):
        prices = make_prices(n_days=200, n_stocks=6)
        weights = fast_strategy.generate_weights(prices)
        assert weights.index.equals(prices.index)


# ---------------------------------------------------------------------------
# Constraint tests
# ---------------------------------------------------------------------------

class TestConstraints:
    def test_weights_non_negative(self, fast_strategy):
        prices = make_prices(n_days=200, n_stocks=6)
        weights = fast_strategy.generate_weights(prices)
        assert (weights.values >= -1e-9).all()

    def test_row_sum_leq_one(self, fast_strategy):
        prices = make_prices(n_days=200, n_stocks=6)
        weights = fast_strategy.generate_weights(prices)
        row_sums = weights.sum(axis=1)
        assert (row_sums <= 1.0 + 1e-9).all(), "Row sum exceeds 1.0"

    def test_no_weight_exceeds_max_weight(self):
        cfg = DualMomentumConfig(
            trend_sma_window=50, abs_mom_lookback=63, high_52w_window=63,
            rel_mom_lookback=42, rsi_window=7, vol_window=10, atr_window=7,
            top_n=5, min_positions=2, max_weight=0.10,
            trailing_stop_enabled=False,
        )
        strat = DualMomentumStrategy(cfg)
        prices = trending_up_prices(n_days=200, n_stocks=8)
        weights = strat.generate_weights(prices)
        assert (weights.values <= 0.10 + 1e-9).all()

    def test_all_zeros_before_warmup(self, fast_strategy):
        """Before min_history bars, all weights should be zero."""
        cfg = fast_strategy.config
        min_hist = max(cfg.trend_sma_window, cfg.abs_mom_lookback, cfg.high_52w_window)
        prices = make_prices(n_days=300, n_stocks=6)
        weights = fast_strategy.generate_weights(prices)
        assert (weights.iloc[:min_hist].values == 0.0).all()


# ---------------------------------------------------------------------------
# Signal filter tests
# ---------------------------------------------------------------------------

class TestSignalFilters:
    def test_zero_weights_in_downtrend(self):
        """Downtrending prices should produce zero weights — absolute and trend filters."""
        cfg = DualMomentumConfig(
            trend_sma_window=20, fast_sma_window=10,
            abs_mom_lookback=63, high_52w_window=63,
            rel_mom_lookback=30, rsi_window=7, vol_window=10, atr_window=7,
            top_n=5, min_positions=1, trailing_stop_enabled=False,
        )
        strat = DualMomentumStrategy(cfg)
        prices = trending_down_prices(n_days=300, n_stocks=8)
        weights = strat.generate_weights(prices)
        # After warmup, downtrending stocks should have near-zero weights
        post_warmup = weights.iloc[70:].sum(axis=1)
        assert post_warmup.mean() < 0.05, "Downtrending stocks should not be held"

    def test_positive_weights_in_uptrend(self):
        """Strong uptrending prices with positive absolute momentum should get positive weights."""
        cfg = DualMomentumConfig(
            trend_sma_window=30, fast_sma_window=10,
            abs_mom_lookback=63, high_52w_window=63,
            rel_mom_lookback=42, rsi_window=7, vol_window=10, atr_window=7,
            top_n=6, min_positions=2, trailing_stop_enabled=False,
        )
        strat = DualMomentumStrategy(cfg)
        prices = trending_up_prices(n_days=200, n_stocks=8)
        weights = strat.generate_weights(prices)
        # In the last quarter, should have active positions
        last_quarter = weights.iloc[-50:].sum(axis=1)
        assert last_quarter.mean() > 0.0, "Should hold positions in strong uptrend"


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_config(self):
        cfg = DualMomentumConfig()
        assert cfg.trend_sma_window == 200
        assert cfg.abs_mom_lookback == 252
        assert cfg.high_52w_min_ratio == 0.70
        assert cfg.top_n == 20
        assert cfg.min_positions == 5
        assert cfg.max_weight == 0.12

    def test_custom_config_accepted(self):
        cfg = DualMomentumConfig(top_n=10, max_weight=0.15, abs_mom_threshold=0.05)
        strat = DualMomentumStrategy(cfg)
        assert strat.config.top_n == 10
        assert strat.config.max_weight == 0.15
        assert strat.config.abs_mom_threshold == 0.05

    def test_default_config_used_when_none(self):
        strat = DualMomentumStrategy()
        assert strat.config is not None
        assert strat.config.top_n == 20


# ---------------------------------------------------------------------------
# Select-and-size helper tests
# ---------------------------------------------------------------------------

class TestSelectAndSize:
    def _make_row(self, n: int = 8, seed: int = 3):
        rng = np.random.default_rng(seed)
        tickers = [f"S{i}" for i in range(n)]
        prices = pd.Series(rng.uniform(50, 200, n), index=tickers)
        ma200 = prices * 0.90     # all above SMA(200)
        ma50 = prices * 0.92      # all above SMA(50)
        abs_mom = pd.Series(rng.uniform(0.02, 0.20, n), index=tickers)  # all positive
        rel_mom_z = pd.Series(rng.normal(0, 1, n), index=tickers)
        high52w = pd.Series(rng.uniform(0.75, 1.0, n), index=tickers)   # near highs
        rsi_ = pd.Series(rng.uniform(40, 70, n), index=tickers)
        vol = pd.Series(rng.uniform(0.01, 0.03, n), index=tickers)
        current = pd.Series(0.0, index=tickers)
        return tickers, prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, current

    def test_selects_top_n(self):
        cfg = DualMomentumConfig(top_n=3, min_positions=1)
        tickers, prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur = self._make_row(8)
        w = DualMomentumStrategy._select_and_size(
            prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur, cfg
        )
        assert (w > 0).sum() <= 3

    def test_returns_zero_when_abs_mom_all_negative(self):
        cfg = DualMomentumConfig(top_n=3, min_positions=1, abs_mom_threshold=0.0)
        tickers, prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur = self._make_row(8)
        abs_mom_neg = pd.Series(-0.10, index=abs_mom.index)  # all negative
        w = DualMomentumStrategy._select_and_size(
            prices, ma200, ma50, abs_mom_neg, rel_mom_z, high52w, rsi_, vol, cur, cfg
        )
        assert (w == 0).all(), "Negative absolute momentum should produce zero weights"

    def test_returns_zero_when_below_52w_threshold(self):
        cfg = DualMomentumConfig(top_n=3, min_positions=1, high_52w_min_ratio=0.95)
        tickers, prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur = self._make_row(8)
        high52w_low = pd.Series(0.50, index=high52w.index)   # all far below 52w high
        w = DualMomentumStrategy._select_and_size(
            prices, ma200, ma50, abs_mom, rel_mom_z, high52w_low, rsi_, vol, cur, cfg
        )
        assert (w == 0).all(), "Below 52w threshold should produce zero weights"

    def test_weights_sum_leq_one(self):
        cfg = DualMomentumConfig(top_n=5, min_positions=1)
        tickers, prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur = self._make_row(8)
        w = DualMomentumStrategy._select_and_size(
            prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur, cfg
        )
        assert w.sum() <= 1.0 + 1e-9

    def test_no_individual_weight_exceeds_max(self):
        cfg = DualMomentumConfig(top_n=5, min_positions=1, max_weight=0.10)
        tickers, prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur = self._make_row(8)
        w = DualMomentumStrategy._select_and_size(
            prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur, cfg
        )
        assert (w <= 0.10 + 1e-9).all()

    def test_min_positions_enforced(self):
        cfg = DualMomentumConfig(top_n=8, min_positions=10)
        tickers, prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur = self._make_row(8)
        # Only 8 stocks but min_positions=10 → should return zeros
        w = DualMomentumStrategy._select_and_size(
            prices, ma200, ma50, abs_mom, rel_mom_z, high52w, rsi_, vol, cur, cfg
        )
        assert (w == 0).all(), "Should return zeros when fewer stocks than min_positions"


# ---------------------------------------------------------------------------
# Absolute momentum indicator integration
# ---------------------------------------------------------------------------

class TestAbsoluteMomentumIndicator:
    def test_positive_after_strong_uptrend(self):
        from src.indicators import absolute_momentum
        n = 300
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        # Strong uptrend: 30% ann CAGR
        log_ret = np.ones(n) * (np.log(1.30) / 252)
        prices_arr = 100 * np.exp(np.cumsum(log_ret))
        prices = pd.DataFrame({"STK": prices_arr}, index=dates)
        abs_mom = absolute_momentum(prices, lookback=252)
        # After 252 days, absolute momentum should be strongly positive
        assert abs_mom.iloc[-1].iloc[0] > 0.20

    def test_negative_after_bear_market(self):
        from src.indicators import absolute_momentum
        n = 300
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        # Bear market: -30% ann return
        log_ret = np.ones(n) * (np.log(0.70) / 252)
        prices_arr = 100 * np.exp(np.cumsum(log_ret))
        prices = pd.DataFrame({"STK": prices_arr}, index=dates)
        abs_mom = absolute_momentum(prices, lookback=252)
        assert abs_mom.iloc[-1].iloc[0] < -0.20

    def test_returns_nan_before_lookback(self):
        from src.indicators import absolute_momentum
        prices = pd.DataFrame({"S": [100.0] * 300}, index=pd.date_range("2020-01-01", periods=300, freq="B"))
        abs_mom = absolute_momentum(prices, lookback=252)
        assert abs_mom.iloc[:252].isna().all().all()


# ---------------------------------------------------------------------------
# 52-week high ratio indicator tests
# ---------------------------------------------------------------------------

class TestHigh52wRatio:
    def test_ratio_equals_one_at_all_time_high(self):
        from src.indicators import high_52w_ratio
        n = 300
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        # Monotonically increasing — always at all-time high
        prices_arr = np.arange(100, 100 + n, dtype=float)
        prices = pd.DataFrame({"STK": prices_arr}, index=dates)
        ratio = high_52w_ratio(prices, window=252)
        # After warmup, ratio should be 1.0
        last_vals = ratio.iloc[-50:].values.flatten()
        assert np.allclose(last_vals, 1.0, atol=1e-9)

    def test_ratio_below_one_after_decline(self):
        from src.indicators import high_52w_ratio
        n = 300
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        prices_arr = np.ones(n) * 100.0
        prices_arr[250:] = 70.0   # 30% drop in last 50 bars
        prices = pd.DataFrame({"STK": prices_arr}, index=dates)
        ratio = high_52w_ratio(prices, window=252)
        assert ratio.iloc[-1].iloc[0] < 1.0

    def test_ratio_clipped_at_one(self):
        from src.indicators import high_52w_ratio
        prices = pd.DataFrame(
            {"S": np.arange(50, 350, dtype=float)},
            index=pd.date_range("2020-01-01", periods=300, freq="B"),
        )
        ratio = high_52w_ratio(prices, window=252)
        assert (ratio.fillna(0).values <= 1.0 + 1e-9).all()

    def test_returns_nan_before_min_periods(self):
        from src.indicators import high_52w_ratio
        prices = pd.DataFrame(
            {"S": [100.0] * 200},
            index=pd.date_range("2020-01-01", periods=200, freq="B"),
        )
        ratio = high_52w_ratio(prices, window=252)
        # First 63 bars (min_periods=63) should be NaN
        assert ratio.iloc[:62].isna().all().all()
