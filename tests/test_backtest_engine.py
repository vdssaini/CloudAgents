"""
test_backtest_engine.py
-----------------------
Unit tests for src/backtest_engine.py
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest_engine import run_backtest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_prices():
    """3 stocks × 300 trading days with deterministic prices."""
    rng = np.random.default_rng(0)
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    data = {}
    for ticker in ["A", "B", "C"]:
        log_ret = rng.normal(0.0004, 0.012, 300)
        data[ticker] = 100 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def equal_weights(simple_prices):
    """1/3 equal weights every day."""
    return pd.DataFrame(
        1 / 3,
        index=simple_prices.index,
        columns=simple_prices.columns,
    )


@pytest.fixture
def zero_weights(simple_prices):
    """All cash — portfolio should stay at initial_capital (minus 0 fees)."""
    return pd.DataFrame(
        0.0,
        index=simple_prices.index,
        columns=simple_prices.columns,
    )


# ---------------------------------------------------------------------------
# Sanity / contract tests
# ---------------------------------------------------------------------------

class TestRunBacktest:
    def test_returns_required_keys(self, simple_prices, equal_weights):
        results = run_backtest(simple_prices, equal_weights, initial_capital=10_000)
        for key in [
            "portfolio_value", "returns", "log_returns",
            "turnover", "total_fees", "total_slippage", "holdings",
        ]:
            assert key in results

    def test_portfolio_value_length(self, simple_prices, equal_weights):
        results = run_backtest(simple_prices, equal_weights, initial_capital=10_000)
        assert len(results["portfolio_value"]) == len(simple_prices)

    def test_zero_weights_near_constant(self, simple_prices, zero_weights):
        """All cash → no market exposure → portfolio stays at initial_capital."""
        results = run_backtest(
            simple_prices, zero_weights, initial_capital=50_000,
            fee_rate=0.0, slippage_rate=0.0,
        )
        pv = results["portfolio_value"]
        # First rebalance trades into cash from cash — no costs
        assert pv.iloc[0] == pytest.approx(50_000, rel=1e-4)
        assert pv.std() == pytest.approx(0.0, abs=1.0)

    def test_no_negative_portfolio_value(self, simple_prices, equal_weights):
        results = run_backtest(
            simple_prices, equal_weights, initial_capital=10_000,
            fee_rate=0.005,  # very high fee to stress-test
        )
        assert (results["portfolio_value"] >= 0).all()

    def test_fees_reduce_portfolio(self, simple_prices, equal_weights):
        no_fee = run_backtest(
            simple_prices, equal_weights, initial_capital=10_000,
            fee_rate=0.0, slippage_rate=0.0,
        )
        with_fee = run_backtest(
            simple_prices, equal_weights, initial_capital=10_000,
            fee_rate=0.002, slippage_rate=0.001,
        )
        assert with_fee["portfolio_value"].iloc[-1] <= no_fee["portfolio_value"].iloc[-1]

    def test_total_fees_positive_when_trading(self, simple_prices, equal_weights):
        results = run_backtest(
            simple_prices, equal_weights, initial_capital=10_000,
            fee_rate=0.001,
        )
        assert results["total_fees"] > 0

    def test_total_fees_zero_for_zero_weights(self, simple_prices, zero_weights):
        results = run_backtest(
            simple_prices, zero_weights, initial_capital=10_000,
            fee_rate=0.001,
        )
        assert results["total_fees"] == pytest.approx(0.0, abs=1e-6)

    def test_holdings_shape(self, simple_prices, equal_weights):
        results = run_backtest(simple_prices, equal_weights, initial_capital=10_000)
        assert results["holdings"].shape == simple_prices.shape

    def test_returns_aligned_with_portfolio_value(self, simple_prices, equal_weights):
        results = run_backtest(simple_prices, equal_weights, initial_capital=10_000)
        assert results["returns"].index.equals(simple_prices.index)

    def test_buy_and_hold_single_stock(self):
        """Buy-and-hold a stock that doubles → portfolio should ~double (minus fees)."""
        dates = pd.date_range("2020-01-01", periods=252, freq="B")
        prices = pd.DataFrame(
            {"X": np.linspace(100, 200, 252)}, index=dates
        )
        weights = pd.DataFrame(1.0, index=dates, columns=["X"])
        results = run_backtest(
            prices, weights, initial_capital=10_000,
            fee_rate=0.001, slippage_rate=0.0005,
        )
        final = results["portfolio_value"].iloc[-1]
        # Should be close to 20 000 minus small fees
        assert final > 18_000  # generous bound accounting for costs
        assert final <= 20_100  # sanity upper bound

    def test_high_turnover_incurs_more_fees(self, simple_prices):
        """Strategy that churns positions every day should pay more fees."""
        # Strategy A: buy-and-hold
        w_hold = pd.DataFrame(1 / 3, index=simple_prices.index, columns=simple_prices.columns)

        # Strategy B: alternate between all-in A and all-in B every day
        w_churn = pd.DataFrame(0.0, index=simple_prices.index, columns=simple_prices.columns)
        for i, date in enumerate(simple_prices.index):
            if i % 2 == 0:
                w_churn.at[date, "A"] = 1.0
            else:
                w_churn.at[date, "B"] = 1.0

        r_hold = run_backtest(simple_prices, w_hold, fee_rate=0.001, slippage_rate=0.0)
        r_churn = run_backtest(simple_prices, w_churn, fee_rate=0.001, slippage_rate=0.0)
        assert r_churn["total_fees"] > r_hold["total_fees"]
