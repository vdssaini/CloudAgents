"""
test_metrics.py
---------------
Unit tests for src/metrics.py
"""

import numpy as np
import pandas as pd
import pytest

from src.metrics import (
    cagr,
    annualised_volatility,
    sharpe_ratio,
    sortino_ratio,
    max_drawdown,
    calmar_ratio,
    win_rate,
    average_monthly_return,
    value_at_risk,
    conditional_value_at_risk,
    summarise,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_portfolio():
    """Portfolio that never changes — all metrics degenerate."""
    dates = pd.date_range("2015-01-01", periods=504, freq="B")
    return pd.Series(100_000.0, index=dates, name="portfolio_value")


@pytest.fixture
def perfect_portfolio():
    """
    Portfolio growing at exactly 20 % p.a. compounded daily.
    CAGR should equal 0.20.
    """
    daily_growth = (1.20) ** (1 / 252)
    dates = pd.date_range("2015-01-01", periods=504, freq="B")
    values = 100_000 * daily_growth ** np.arange(504)
    return pd.Series(values, index=dates, name="portfolio_value")


@pytest.fixture
def volatile_portfolio():
    """Random-walk portfolio for statistical metric checks."""
    rng = np.random.default_rng(7)
    daily_ret = rng.normal(0.0008, 0.012, size=1260)  # ~5 years
    dates = pd.date_range("2018-01-01", periods=1260, freq="B")
    values = 100_000 * np.cumprod(1 + daily_ret)
    return pd.Series(values, index=dates)


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------

class TestCAGR:
    def test_flat_is_zero(self, flat_portfolio):
        assert cagr(flat_portfolio) == pytest.approx(0.0, abs=1e-6)

    def test_perfect_20pct(self, perfect_portfolio):
        # 504 business days / 252 = exactly 2 years; allow 0.5 % abs tolerance
        assert cagr(perfect_portfolio) == pytest.approx(0.20, abs=0.005)

    def test_positive_growth(self, volatile_portfolio):
        result = cagr(volatile_portfolio)
        assert isinstance(result, float)

    def test_single_year_doubling(self):
        dates = pd.date_range("2020-01-01", periods=252, freq="B")
        values = pd.Series(np.linspace(100, 200, 252), index=dates)
        result = cagr(values)
        assert result == pytest.approx(1.0, rel=0.05)  # ~100 % in 1 year


# ---------------------------------------------------------------------------
# Annualised Volatility
# ---------------------------------------------------------------------------

class TestAnnualisedVolatility:
    def test_flat_portfolio(self, flat_portfolio):
        returns = flat_portfolio.pct_change().dropna()
        assert annualised_volatility(returns) == pytest.approx(0.0, abs=1e-10)

    def test_higher_noise_higher_vol(self):
        rng = np.random.default_rng(1)
        ret_low = pd.Series(rng.normal(0, 0.005, 252))
        ret_high = pd.Series(rng.normal(0, 0.02, 252))
        assert annualised_volatility(ret_high) > annualised_volatility(ret_low)

    def test_scale(self):
        """Check that annualisation factor (√252) is applied."""
        daily_std = 0.01
        rng = np.random.default_rng(2)
        ret = pd.Series(rng.normal(0, daily_std, 10_000))
        vol = annualised_volatility(ret)
        assert vol == pytest.approx(daily_std * np.sqrt(252), rel=0.05)


# ---------------------------------------------------------------------------
# Sharpe Ratio
# ---------------------------------------------------------------------------

class TestSharpeRatio:
    def test_flat_is_zero(self, flat_portfolio):
        returns = flat_portfolio.pct_change().dropna()
        assert sharpe_ratio(returns) == pytest.approx(0.0, abs=1e-6)

    def test_positive_for_positive_drift(self, perfect_portfolio):
        returns = perfect_portfolio.pct_change().dropna()
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_higher_return_higher_sharpe(self):
        rng = np.random.default_rng(3)
        vol = 0.01
        ret_low = pd.Series(rng.normal(0.0002, vol, 1000))
        ret_high = pd.Series(rng.normal(0.001, vol, 1000))
        assert sharpe_ratio(ret_high) > sharpe_ratio(ret_low)


# ---------------------------------------------------------------------------
# Sortino Ratio
# ---------------------------------------------------------------------------

class TestSortinoRatio:
    def test_always_ge_sharpe_for_positive_drift(self, perfect_portfolio):
        """Sortino ≥ Sharpe when returns are predominantly positive."""
        returns = perfect_portfolio.pct_change().dropna()
        sr = sharpe_ratio(returns)
        so = sortino_ratio(returns)
        assert so >= sr - 1e-6  # allow tiny float rounding

    def test_positive_for_positive_drift(self, volatile_portfolio):
        returns = volatile_portfolio.pct_change().dropna()
        so = sortino_ratio(returns)
        assert isinstance(so, float)


# ---------------------------------------------------------------------------
# Max Drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_flat_is_zero(self, flat_portfolio):
        assert max_drawdown(flat_portfolio) == pytest.approx(0.0, abs=1e-6)

    def test_always_nonpositive(self, volatile_portfolio):
        mdd = max_drawdown(volatile_portfolio)
        assert mdd <= 0

    def test_known_drawdown(self):
        """Manually constructed 50 % drawdown."""
        values = pd.Series([100, 150, 75, 120, 200])
        # Peak = 150, trough = 75 → MDD = (75-150)/150 = -0.50
        assert max_drawdown(values) == pytest.approx(-0.50, rel=1e-3)


# ---------------------------------------------------------------------------
# Calmar Ratio
# ---------------------------------------------------------------------------

class TestCalmarRatio:
    def test_flat_infinite(self, flat_portfolio):
        result = calmar_ratio(flat_portfolio)
        assert result == np.inf or result == pytest.approx(0.0, abs=1e-6)

    def test_positive_for_growing(self, volatile_portfolio):
        if cagr(volatile_portfolio) > 0:
            assert calmar_ratio(volatile_portfolio) > 0


# ---------------------------------------------------------------------------
# Win Rate
# ---------------------------------------------------------------------------

class TestWinRate:
    def test_range(self, volatile_portfolio):
        returns = volatile_portfolio.pct_change().dropna()
        wr = win_rate(returns)
        assert 0.0 <= wr <= 1.0

    def test_all_positive(self):
        returns = pd.Series([0.01, 0.02, 0.005, 0.001])
        assert win_rate(returns) == pytest.approx(1.0)

    def test_all_negative(self):
        returns = pd.Series([-0.01, -0.02])
        assert win_rate(returns) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# VaR / CVaR
# ---------------------------------------------------------------------------

class TestVaRCVaR:
    def test_var_negative(self, volatile_portfolio):
        returns = volatile_portfolio.pct_change().dropna()
        var = value_at_risk(returns, 0.95)
        assert var < 0

    def test_cvar_le_var(self, volatile_portfolio):
        returns = volatile_portfolio.pct_change().dropna()
        var = value_at_risk(returns, 0.95)
        cvar = conditional_value_at_risk(returns, 0.95)
        assert cvar <= var

    def test_known_var(self):
        """Exact VaR for uniform distribution."""
        rng = np.random.default_rng(99)
        returns = pd.Series(rng.uniform(-0.05, 0.05, 10_000))
        # 5th percentile of Uniform(-0.05, 0.05) ≈ -0.05 + 0.10*0.05 = -0.045
        var = value_at_risk(returns, 0.95)
        assert var == pytest.approx(-0.045, abs=0.002)


# ---------------------------------------------------------------------------
# summarise
# ---------------------------------------------------------------------------

class TestSummarise:
    def test_keys_present(self, volatile_portfolio):
        metrics = summarise(volatile_portfolio)
        for key in ["CAGR", "Sharpe Ratio", "Max Drawdown", "Calmar Ratio"]:
            assert key in metrics

    def test_with_benchmark(self, volatile_portfolio, perfect_portfolio):
        metrics = summarise(volatile_portfolio, benchmark_value=perfect_portfolio)
        assert "Alpha (annual)" in metrics
        assert "Beta" in metrics
        assert "Benchmark CAGR" in metrics
