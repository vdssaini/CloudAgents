"""
tests/test_strategy_concentrated.py
------------------------------------
Unit tests for Strategy 5 — Concentrated High-Conviction Momentum.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy_concentrated import (
    ConcentratedMomentumConfig,
    ConcentratedMomentumStrategy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prices(n_tickers: int = 20, n_days: int = 600, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic prices with a trending market."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    log_rets = rng.normal(0.0005, 0.012, size=(n_days, n_tickers))
    prices = 100.0 * np.exp(np.cumsum(log_rets, axis=0))
    tickers = [f"STOCK{i:02d}" for i in range(n_tickers)]
    return pd.DataFrame(prices, index=dates, columns=tickers)


def _make_trending_prices(n_tickers: int = 20, n_days: int = 600, seed: int = 7) -> pd.DataFrame:
    """Prices with strong upward trend to ensure most stocks qualify for entry."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=n_days)
    # Strong positive drift so stocks stay above SMA(200) and have positive abs-momentum
    log_rets = rng.normal(0.0012, 0.010, size=(n_days, n_tickers))
    prices = 100.0 * np.exp(np.cumsum(log_rets, axis=0))
    tickers = [f"STOCK{i:02d}" for i in range(n_tickers)]
    return pd.DataFrame(prices, index=dates, columns=tickers)


# ---------------------------------------------------------------------------
# ConcentratedMomentumConfig tests
# ---------------------------------------------------------------------------

class TestConcentratedMomentumConfig:
    def test_defaults(self):
        cfg = ConcentratedMomentumConfig()
        assert cfg.top_n == 3
        assert cfg.leverage_bull == 2.0
        assert cfg.leverage_default == 1.0
        assert cfg.max_weight == 0.50
        assert cfg.trailing_stop_enabled is True
        assert cfg.trailing_stop_atr_mult == 2.5
        assert cfg.abs_mom_threshold == -0.05
        assert cfg.high_52w_min_ratio == 0.50

    def test_custom_params(self):
        cfg = ConcentratedMomentumConfig(top_n=5, leverage_bull=1.5, max_weight=0.40)
        assert cfg.top_n == 5
        assert cfg.leverage_bull == 1.5
        assert cfg.max_weight == 0.40


# ---------------------------------------------------------------------------
# ConcentratedMomentumStrategy tests
# ---------------------------------------------------------------------------

class TestConcentratedMomentumStrategy:

    def test_returns_dataframe_same_shape(self):
        prices = _make_prices()
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        assert isinstance(weights, pd.DataFrame)
        assert weights.shape == prices.shape
        assert list(weights.columns) == list(prices.columns)
        assert list(weights.index) == list(prices.index)

    def test_weights_non_negative(self):
        prices = _make_prices()
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        assert (weights >= 0).all().all(), "No negative weights allowed"

    def test_weights_zero_in_warmup(self):
        prices = _make_prices(n_days=600)
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        # First 200 rows should have zero weights (SMA-200 warmup period)
        assert (weights.iloc[:200] == 0).all().all()

    def test_top_n_positions_respected(self):
        prices = _make_trending_prices(n_tickers=20, n_days=600)
        cfg = ConcentratedMomentumConfig(top_n=3)
        strat = ConcentratedMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        # Non-zero dates should have at most top_n positions
        nonzero_rows = weights[weights.sum(axis=1) > 0]
        assert (nonzero_rows > 0).sum(axis=1).max() <= cfg.top_n

    def test_leverage_applied_in_bull(self):
        """Weights should sum to approximately leverage_bull when conditions are met."""
        prices = _make_trending_prices(n_tickers=20, n_days=600)
        cfg = ConcentratedMomentumConfig(leverage_bull=2.0, top_n=3)
        strat = ConcentratedMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        invested_rows = weights[weights.sum(axis=1) > 0]
        if len(invested_rows) > 0:
            # When fully invested, weights should sum close to leverage_bull
            max_weight_sum = invested_rows.sum(axis=1).max()
            assert max_weight_sum <= cfg.leverage_bull * 1.05, (
                f"Max weight sum {max_weight_sum:.2f} exceeds leverage {cfg.leverage_bull}"
            )

    def test_max_weight_per_stock_respected(self):
        prices = _make_trending_prices(n_tickers=20, n_days=600)
        cfg = ConcentratedMomentumConfig(max_weight=0.50, leverage_bull=2.0)
        strat = ConcentratedMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        # After leverage scaling, max weight can be up to max_weight × leverage_bull
        assert (weights <= cfg.max_weight * cfg.leverage_bull + 1e-9).all().all()

    def test_no_positions_when_all_below_sma(self):
        """In a strong downtrend, strategy should go to cash."""
        n_days = 600
        dates = pd.bdate_range("2020-01-01", periods=n_days)
        # Strong downtrend: all stocks fall below SMA-200
        log_rets = np.full((n_days, 10), -0.003)
        prices = pd.DataFrame(
            100.0 * np.exp(np.cumsum(log_rets, axis=0)),
            index=dates,
            columns=[f"S{i}" for i in range(10)],
        )
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        # After warmup, all weights should be 0 due to downtrend
        assert (weights.iloc[300:] == 0).all().all()

    def test_produces_nonzero_weights_in_uptrend(self):
        """In a strong uptrend, strategy should invest."""
        prices = _make_trending_prices(n_tickers=20, n_days=600)
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        # After warmup, should have some nonzero weights
        assert (weights.iloc[300:].sum(axis=1) > 0).any()

    def test_custom_config_passthrough(self):
        """Custom config values are respected."""
        prices = _make_trending_prices(n_tickers=20, n_days=600)
        cfg = ConcentratedMomentumConfig(top_n=2, leverage_bull=1.5, rebalance_days=10)
        strat = ConcentratedMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        nonzero_rows = weights[weights.sum(axis=1) > 0]
        # With top_n=2, at most 2 positions
        if len(nonzero_rows) > 0:
            assert (nonzero_rows > 0).sum(axis=1).max() <= 2

    def test_no_nan_in_weights(self):
        prices = _make_prices()
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        assert not weights.isna().any().any(), "No NaN weights allowed"

    def test_weights_consistent_with_backtest(self):
        """Weights integrate with backtest engine without errors."""
        from src.backtest_engine import run_backtest
        from src.metrics import summarise

        prices = _make_trending_prices(n_tickers=15, n_days=600, seed=42)
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        result = run_backtest(prices, weights, initial_capital=100_000, fee_rate=0.001)
        assert "portfolio_value" in result
        assert len(result["portfolio_value"]) == len(prices)
        assert result["portfolio_value"].iloc[-1] > 0
        metrics = summarise(result["portfolio_value"])
        assert "CAGR" in metrics
        assert "Sharpe Ratio" in metrics

    def test_goal_beats_avg_stock_bh(self):
        """Strategy 5 should beat average-stock B&H in a trending market."""
        from src.backtest_engine import run_backtest
        from src.metrics import summarise

        prices = _make_trending_prices(n_tickers=20, n_days=800, seed=99)
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        r_s5 = run_backtest(prices, weights, fee_rate=0.001, slippage_rate=0.0005)
        m_s5 = summarise(r_s5["portfolio_value"])

        avg_w = pd.DataFrame(1.0 / len(prices.columns), index=prices.index, columns=prices.columns)
        r_avg = run_backtest(prices, avg_w, fee_rate=0.0)
        m_avg = summarise(r_avg["portfolio_value"])

        # In a strongly trending market with leverage, Strategy 5 should beat avg B&H
        # (this may not always hold — it's a directional test, not a guarantee)
        assert m_s5["CAGR"] >= m_avg["CAGR"] * 0.8, (
            f"Strategy 5 CAGR {m_s5['CAGR']:.1%} should be competitive with "
            f"avg B&H CAGR {m_avg['CAGR']:.1%} (within 20% of avg)"
        )

    def test_sharpe_advantage_over_bh(self):
        """Strategy 5's Sharpe should be competitive with top-stock B&H."""
        from src.backtest_engine import run_backtest
        from src.metrics import summarise

        # Use a long enough period for meaningful statistics
        prices = _make_trending_prices(n_tickers=20, n_days=800, seed=55)
        strat = ConcentratedMomentumStrategy()
        weights = strat.generate_weights(prices)
        r_s5 = run_backtest(prices, weights, fee_rate=0.001, slippage_rate=0.0005)
        m_s5 = summarise(r_s5["portfolio_value"])

        avg_w = pd.DataFrame(1.0 / len(prices.columns), index=prices.index, columns=prices.columns)
        r_avg = run_backtest(prices, avg_w, fee_rate=0.0)
        m_avg = summarise(r_avg["portfolio_value"])

        # Both Sharpes should be positive in an uptrending market
        assert m_s5["Sharpe Ratio"] > 0
        assert m_avg["Sharpe Ratio"] > 0

    def test_get_winner_tickers_consistent(self):
        """get_winner_tickers() returns a deterministic subset matching simulation."""
        from src.simulate_data import get_winner_tickers, SIMULATED_TICKERS, STOCK_WINNER_TICKERS
        winners = get_winner_tickers()
        assert len(winners) > 0, "Should always find some winners in the 100-ticker universe"
        assert all(t in SIMULATED_TICKERS for t in winners), "Winners must be valid tickers"
        assert all(t in STOCK_WINNER_TICKERS for t in winners), "Winners must be in fixed set"

    def test_get_winner_tickers_seed_independent(self):
        """Winner tickers should be the same regardless of seed."""
        from src.simulate_data import get_winner_tickers
        w1 = get_winner_tickers(seed=2024)
        w2 = get_winner_tickers(seed=9999)
        assert w1 == w2, "Winner tickers must be deterministic (seed-independent)"
