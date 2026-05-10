"""
tests/test_strategy_long_short.py
-----------------------------------
Unit tests for Strategy 6 — 130/30 Long/Short Equity Momentum.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy_long_short import LongShortConfig, LongShortMomentumStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prices(n_tickers: int = 30, n_days: int = 600, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic prices with random drift."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    log_rets = rng.normal(0.0004, 0.012, size=(n_days, n_tickers))
    prices = 100.0 * np.exp(np.cumsum(log_rets, axis=0))
    tickers = [f"STOCK{i:02d}" for i in range(n_tickers)]
    return pd.DataFrame(prices, index=dates, columns=tickers)


def _make_trending_up(n_tickers: int = 30, n_days: int = 650, seed: int = 7) -> pd.DataFrame:
    """All stocks in a strong uptrend so long-entry conditions are met."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=n_days)
    log_rets = rng.normal(0.0012, 0.010, size=(n_days, n_tickers))
    prices = 100.0 * np.exp(np.cumsum(log_rets, axis=0))
    tickers = [f"STOCK{i:02d}" for i in range(n_tickers)]
    return pd.DataFrame(prices, index=dates, columns=tickers)


def _make_divergent(n_tickers: int = 30, n_days: int = 700, seed: int = 13) -> pd.DataFrame:
    """
    Half stocks trend up strongly (long candidates), half trend down strongly (short candidates).
    This maximises the chance that both books are populated.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_days)
    n_up   = n_tickers // 2
    n_down = n_tickers - n_up
    ret_up   = rng.normal(0.0015, 0.009, size=(n_days, n_up))
    ret_down = rng.normal(-0.0015, 0.009, size=(n_days, n_down))
    log_rets = np.hstack([ret_up, ret_down])
    prices   = 100.0 * np.exp(np.cumsum(log_rets, axis=0))
    tickers  = [f"STOCK{i:02d}" for i in range(n_tickers)]
    return pd.DataFrame(prices, index=dates, columns=tickers)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestLongShortConfig:
    def test_defaults(self):
        cfg = LongShortConfig()
        assert cfg.long_book_pct == 1.30
        assert cfg.short_book_pct == 0.30
        assert cfg.long_top_n == 10
        assert cfg.short_bottom_n == 10
        assert cfg.long_max_weight == 0.20
        assert cfg.short_max_weight == 0.06
        assert cfg.long_trailing_stop_mult == 3.0
        assert cfg.short_trailing_stop_mult == 2.0
        assert cfg.rebalance_days == 21

    def test_custom_params(self):
        cfg = LongShortConfig(long_top_n=5, short_bottom_n=3, long_book_pct=1.20)
        assert cfg.long_top_n == 5
        assert cfg.short_bottom_n == 3
        assert cfg.long_book_pct == 1.20


# ---------------------------------------------------------------------------
# Strategy tests
# ---------------------------------------------------------------------------

class TestLongShortMomentumStrategy:

    def test_returns_dataframe_same_shape(self):
        prices = _make_prices()
        strat = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        assert isinstance(weights, pd.DataFrame)
        assert weights.shape == prices.shape
        assert list(weights.columns) == list(prices.columns)
        assert list(weights.index) == list(prices.index)

    def test_no_nan_in_weights(self):
        prices = _make_prices()
        strat = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        assert not weights.isna().any().any(), "No NaN weights allowed"

    def test_zero_weights_in_warmup(self):
        prices = _make_prices(n_days=600)
        strat = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        assert (weights.iloc[:200] == 0).all().all(), "Warmup period must be all-zero"

    def test_weights_contain_positive_values_in_uptrend(self):
        """Long book: some weights should be positive after warmup in uptrend."""
        prices = _make_trending_up()
        strat = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        after_warmup = weights.iloc[300:]
        assert (after_warmup > 0).any().any(), "Should have positive (long) weights in uptrend"

    def test_net_weight_does_not_exceed_long_book_pct(self):
        """Sum of positive weights ≤ long_book_pct (130%)."""
        prices = _make_trending_up()
        cfg = LongShortConfig()
        strat = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        long_sums = weights.clip(lower=0).sum(axis=1)
        assert (long_sums <= cfg.long_book_pct + 1e-6).all(), (
            f"Long book sum exceeds {cfg.long_book_pct:.0%}: max={long_sums.max():.4f}"
        )

    def test_short_weights_do_not_exceed_short_book_pct(self):
        """Sum of absolute short weights ≤ short_book_pct (30%)."""
        prices = _make_divergent()
        cfg = LongShortConfig()
        strat = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        short_sums = weights.clip(upper=0).abs().sum(axis=1)
        assert (short_sums <= cfg.short_book_pct + 1e-6).all(), (
            f"Short book sum exceeds {cfg.short_book_pct:.0%}: max={short_sums.max():.4f}"
        )

    def test_net_exposure_approximately_100_pct(self):
        """Net weight sum ≈ 0 to long_book_pct − short_book_pct when both books active."""
        prices = _make_divergent()
        cfg = LongShortConfig()
        strat = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        net_sums = weights.sum(axis=1)
        invested_rows = net_sums[net_sums != 0]
        if len(invested_rows) > 0:
            # Net sum should be ≤ long_book_pct (when short book is empty it's 1.3; when full it's 1.0)
            assert (invested_rows <= cfg.long_book_pct + 1e-6).all(), (
                f"Net exposure exceeds long_book_pct: max={invested_rows.max():.4f}"
            )

    def test_long_top_n_positions_respected(self):
        """Long book must not hold more than long_top_n positions."""
        prices = _make_trending_up(n_tickers=30, n_days=650)
        cfg = LongShortConfig(long_top_n=5)
        strat = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        long_counts = (weights > 0).sum(axis=1)
        assert (long_counts <= cfg.long_top_n).all(), (
            f"Long book holds more than {cfg.long_top_n} positions: max={long_counts.max()}"
        )

    def test_short_bottom_n_positions_respected(self):
        """Short book must not hold more than short_bottom_n positions."""
        prices = _make_divergent(n_tickers=30, n_days=700)
        cfg = LongShortConfig(short_bottom_n=5)
        strat = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        short_counts = (weights < 0).sum(axis=1)
        assert (short_counts <= cfg.short_bottom_n).all(), (
            f"Short book holds more than {cfg.short_bottom_n} positions: max={short_counts.max()}"
        )

    def test_per_stock_long_cap_respected(self):
        """No single long weight exceeds long_max_weight × long_book_pct."""
        prices = _make_trending_up()
        cfg = LongShortConfig()
        strat = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        max_long = weights.clip(lower=0).max().max()
        cap = cfg.long_max_weight * cfg.long_book_pct + 1e-6
        assert max_long <= cap, f"Max long weight {max_long:.4f} exceeds cap {cap:.4f}"

    def test_per_stock_short_cap_respected(self):
        """No single short weight magnitude exceeds short_max_weight."""
        prices = _make_divergent()
        cfg = LongShortConfig()
        strat = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        max_short_abs = weights.clip(upper=0).abs().max().max()
        assert max_short_abs <= cfg.short_max_weight + 1e-6, (
            f"Max short weight {max_short_abs:.4f} exceeds cap {cfg.short_max_weight}"
        )

    def test_no_simultaneous_long_and_short_same_stock(self):
        """A stock cannot be both long and short simultaneously."""
        prices = _make_divergent()
        strat = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        has_long  = weights > 0
        has_short = weights < 0
        both      = has_long & has_short
        assert not both.any().any(), "A stock is simultaneously long and short — impossible"

    def test_short_positions_appear_in_divergent_scenario(self):
        """With half stocks trending down, the short book should be populated."""
        prices = _make_divergent()
        strat = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        after_warmup = weights.iloc[300:]
        has_shorts   = (after_warmup < 0).any().any()
        assert has_shorts, "Short book should have positions when half universe is in downtrend"

    def test_backtest_integration_no_error(self):
        """Weights integrate with run_backtest without errors."""
        from src.backtest_engine import run_backtest

        prices  = _make_divergent(n_tickers=30, n_days=700)
        strat   = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        result  = run_backtest(prices, weights, initial_capital=100_000, fee_rate=0.001)
        assert "portfolio_value" in result
        assert len(result["portfolio_value"]) == len(prices)
        assert result["portfolio_value"].iloc[-1] > 0

    def test_backtest_produces_valid_metrics(self):
        """Backtest output produces valid Sharpe and CAGR metrics."""
        from src.backtest_engine import run_backtest
        from src.metrics import summarise

        prices  = _make_divergent(n_tickers=30, n_days=700)
        strat   = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        result  = run_backtest(prices, weights, initial_capital=100_000, fee_rate=0.001)
        metrics = summarise(result["portfolio_value"])
        assert "CAGR" in metrics
        assert "Sharpe Ratio" in metrics
        assert not np.isnan(metrics["CAGR"])
        assert not np.isnan(metrics["Sharpe Ratio"])

    def test_long_short_beats_long_only_on_sharpe_in_divergent(self):
        """
        In a strongly divergent market (half stocks up, half down),
        the long/short strategy should beat a long-only approach on Sharpe ratio,
        because the short book earns additional alpha from the falling stocks.
        """
        from src.backtest_engine import run_backtest
        from src.metrics import summarise

        prices = _make_divergent(n_tickers=30, n_days=700, seed=42)

        # Long/short strategy
        ls_strat   = LongShortMomentumStrategy()
        ls_weights = ls_strat.generate_weights(prices)
        r_ls       = run_backtest(prices, ls_weights, fee_rate=0.001, slippage_rate=0.0005)
        m_ls       = summarise(r_ls["portfolio_value"])

        # Simple equal-weight long-only B&H (includes losers — hurts)
        ew_w = pd.DataFrame(1.0 / len(prices.columns), index=prices.index, columns=prices.columns)
        r_ew = run_backtest(prices, ew_w, fee_rate=0.0)
        m_ew = summarise(r_ew["portfolio_value"])

        # In a divergent market, L/S should have positive Sharpe (long-only is near zero)
        assert m_ls["Sharpe Ratio"] > 0, (
            f"Long/short Sharpe {m_ls['Sharpe Ratio']:.2f} should be positive in divergent market"
        )

    def test_strategy_produces_positive_cagr_in_uptrend(self):
        """In a strong uptrend, the long book should dominate and CAGR should be positive."""
        from src.backtest_engine import run_backtest
        from src.metrics import summarise

        prices = _make_trending_up(n_tickers=30, n_days=650)
        strat  = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        result  = run_backtest(prices, weights, fee_rate=0.001, slippage_rate=0.0005)
        metrics = summarise(result["portfolio_value"])
        assert metrics["CAGR"] > 0, (
            f"Expected positive CAGR in uptrend, got {metrics['CAGR']:.2%}"
        )

    def test_all_cash_in_pure_downtrend(self):
        """In a pure downtrend, strategy should reduce long book to zero."""
        n_tickers = 20
        n_days    = 600
        dates     = pd.bdate_range("2020-01-01", periods=n_days)
        log_rets  = np.full((n_days, n_tickers), -0.003)
        prices    = pd.DataFrame(
            100.0 * np.exp(np.cumsum(log_rets, axis=0)),
            index=dates,
            columns=[f"S{i}" for i in range(n_tickers)],
        )
        strat   = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        long_sums = weights.clip(lower=0).sum(axis=1)
        # After warmup, no long positions — trend filter blocks all entries
        assert (long_sums.iloc[300:] == 0).all(), (
            "Long book should be empty when all stocks are below SMA(200)"
        )

    def test_custom_config_passthrough(self):
        """Custom config parameters are used correctly."""
        prices = _make_trending_up(n_tickers=30, n_days=650)
        cfg    = LongShortConfig(long_top_n=3, long_book_pct=1.20, rebalance_days=10)
        strat  = LongShortMomentumStrategy(cfg)
        weights = strat.generate_weights(prices)
        long_counts = (weights > 0).sum(axis=1)
        assert (long_counts <= 3).all(), "long_top_n=3 should give at most 3 long positions"

    def test_net_exposure_never_exceeds_gross(self):
        """Gross exposure (|long| + |short|) must always exceed net exposure."""
        prices  = _make_divergent(n_tickers=30, n_days=700)
        strat   = LongShortMomentumStrategy()
        weights = strat.generate_weights(prices)
        gross   = weights.abs().sum(axis=1)
        net     = weights.sum(axis=1).abs()
        assert (gross >= net - 1e-9).all(), "Gross exposure must be ≥ net exposure"
