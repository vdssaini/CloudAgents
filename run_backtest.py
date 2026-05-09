"""
run_backtest.py
---------------
Entry point for the Adaptive Momentum + Trend-Filter strategy backtest.

Usage
-----
    python run_backtest.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                          [--capital N] [--top-n N] [--fee F]
                          [--simulated] [--no-plot]

Examples
--------
    # Live data from Yahoo Finance (requires internet)
    python run_backtest.py --start 2013-01-01 --capital 100000

    # Synthetic data (no internet required)
    python run_backtest.py --simulated --start 2013-01-01

Results are saved to the ``results/`` directory:
* ``results/portfolio_value.csv``
* ``results/performance_chart.png``
* ``results/metrics.txt``
"""

import argparse
import logging
import os
import sys

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for servers / CI
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from src.strategy import MomentumTrendStrategy, StrategyConfig
from src.backtest_engine import run_backtest
from src.metrics import summarise, print_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_real_data(tickers: list[str], start: str, end: str | None):
    """Attempt to download live data; return None on failure."""
    try:
        from src.data_fetcher import fetch_prices
        prices = fetch_prices(tickers, start=start, end=end)
        if prices.empty:
            return None, None
        from src.data_fetcher import fetch_prices as _fp
        benchmark = _fp(["SPY"], start=start, end=end)
        if benchmark.empty:
            return None, None
        return prices, benchmark
    except Exception as exc:
        logger.warning("Live data download failed (%s). Falling back to simulated data.", exc)
        return None, None


def _load_simulated_data(start: str, end: str | None):
    """Generate synthetic price data."""
    from src.simulate_data import simulate_prices, simulate_benchmark, SIMULATED_TICKERS
    logger.info("Using SIMULATED price data (no live market data).")
    prices = simulate_prices(tickers=SIMULATED_TICKERS, start=start, end=end)
    benchmark = simulate_benchmark(start=start, end=end)
    return prices, benchmark


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def _plot_results(
    portfolio_value: pd.Series,
    benchmark_value: pd.Series,
    drawdown: pd.Series,
    monthly_returns: pd.Series,
    save_path: str,
    data_label: str = "",
) -> None:
    fig, axes = plt.subplots(
        3, 1, figsize=(14, 12),
        gridspec_kw={"height_ratios": [3, 1.5, 1.5]},
    )
    title = "Adaptive Momentum + Trend-Filter Strategy — Backtest Results"
    if data_label:
        title += f"\n{data_label}  |  fees + slippage included"
    else:
        title += "\nfees + slippage included"
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)

    # ---- 1. Portfolio vs benchmark (log scale) ----
    ax0 = axes[0]
    pv_norm = portfolio_value / portfolio_value.iloc[0] * 100
    bm_norm = benchmark_value / benchmark_value.iloc[0] * 100
    ax0.plot(pv_norm.index, pv_norm, label="Strategy", color="#2196F3", linewidth=1.8)
    ax0.plot(bm_norm.index, bm_norm, label="Benchmark (SPY / simulated)",
             color="#FF9800", linewidth=1.4, linestyle="--", alpha=0.8)
    ax0.set_yscale("log")
    ax0.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    ax0.set_ylabel("Normalised Value (log scale, base=100)")
    ax0.legend(loc="upper left")
    ax0.grid(True, alpha=0.3)
    ax0.set_title("Cumulative Performance")

    # ---- 2. Drawdown ----
    ax1 = axes[1]
    ax1.fill_between(drawdown.index, drawdown * 100, 0,
                     color="#F44336", alpha=0.6, label="Drawdown (%)")
    ax1.set_ylabel("Drawdown (%)")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax1.legend(loc="lower left")
    ax1.grid(True, alpha=0.3)
    ax1.set_title("Portfolio Drawdown")

    # ---- 3. Monthly return bar chart ----
    ax2 = axes[2]
    colors = ["#4CAF50" if r >= 0 else "#F44336" for r in monthly_returns]
    ax2.bar(monthly_returns.index, monthly_returns * 100, color=colors,
            width=20, label="Monthly Return")
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_ylabel("Monthly Return (%)")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.3)
    ax2.set_title("Monthly Returns")

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Chart saved → %s", save_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the Adaptive Momentum + Trend-Filter strategy backtest."
    )
    p.add_argument("--start", default="2013-01-01",
                   help="Backtest start date (YYYY-MM-DD). Default: 2013-01-01")
    p.add_argument("--end", default=None,
                   help="Backtest end date (YYYY-MM-DD). Default: today")
    p.add_argument("--capital", type=float, default=100_000,
                   help="Initial capital in USD. Default: 100000")
    p.add_argument("--top-n", type=int, default=20,
                   help="Max number of stocks held at once. Default: 20")
    p.add_argument("--fee", type=float, default=0.001,
                   help="One-way commission (fraction). Default: 0.001 = 0.1%%")
    p.add_argument("--slippage", type=float, default=0.0005,
                   help="One-way slippage (fraction). Default: 0.0005 = 0.05%%")
    p.add_argument("--simulated", action="store_true",
                   help="Use simulated price data (no internet required).")
    p.add_argument("--no-plot", action="store_true",
                   help="Skip chart generation.")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 60)
    logger.info("  Adaptive Momentum + Trend-Filter Strategy Backtest")
    logger.info("=" * 60)
    logger.info("Period   : %s → %s", args.start, args.end or "today")
    logger.info("Capital  : $%s", f"{args.capital:,.0f}")
    logger.info("Top-N    : %d stocks", args.top_n)
    logger.info("Fee      : %.3f%%  (one-way)", args.fee * 100)
    logger.info("Slippage : %.3f%%  (one-way)", args.slippage * 100)

    # 1. Load price data
    data_label = ""
    if args.simulated:
        prices, benchmark_prices = _load_simulated_data(args.start, args.end)
        data_label = "Simulated data"
    else:
        from src.data_fetcher import DEFAULT_UNIVERSE
        prices, benchmark_prices = _load_real_data(DEFAULT_UNIVERSE, args.start, args.end)
        if prices is None:
            logger.warning("Switching to simulated data due to download failure.")
            prices, benchmark_prices = _load_simulated_data(args.start, args.end)
            data_label = "Simulated data (live download failed)"
        else:
            data_label = "Live data (Yahoo Finance)"

    if prices is None or prices.empty:
        logger.error("No price data available. Exiting.")
        sys.exit(1)

    benchmark_prices = benchmark_prices.reindex(prices.index).ffill()

    logger.info(
        "Data loaded: %d dates × %d tickers (%s)",
        len(prices), prices.shape[1], data_label,
    )

    # 2. Generate strategy weights
    logger.info("Generating strategy signals …")
    cfg = StrategyConfig(top_n=args.top_n)
    strategy = MomentumTrendStrategy(cfg)
    weights = strategy.generate_weights(prices)

    avg_positions = (weights > 0).sum(axis=1).mean()
    logger.info("Average number of positions held: %.1f", avg_positions)

    # 3. Run backtest
    logger.info("Running backtest …")
    results = run_backtest(
        prices=prices,
        weights=weights,
        initial_capital=args.capital,
        fee_rate=args.fee,
        slippage_rate=args.slippage,
    )

    portfolio_value = results["portfolio_value"]
    daily_returns = results["returns"]

    # Benchmark: buy-and-hold
    bench_weights = pd.DataFrame(
        1.0,
        index=benchmark_prices.index,
        columns=benchmark_prices.columns,
    )
    bench_results = run_backtest(
        prices=benchmark_prices,
        weights=bench_weights,
        initial_capital=args.capital,
        fee_rate=0.0,
    )
    benchmark_value = bench_results["portfolio_value"]

    # 4. Metrics
    metrics = summarise(portfolio_value, benchmark_value)

    logger.info("Total fees paid   : $%s", f"{results['total_fees']:,.0f}")
    logger.info("Total slippage    : $%s", f"{results['total_slippage']:,.0f}")
    logger.info("Data source       : %s", data_label)
    print_summary(metrics)

    # 5. Save results
    pv_path = os.path.join(RESULTS_DIR, "portfolio_value.csv")
    pd.DataFrame({
        "portfolio_value": portfolio_value,
        "benchmark_value": benchmark_value.reindex(portfolio_value.index).ffill(),
        "daily_return": daily_returns,
    }).to_csv(pv_path)
    logger.info("Portfolio values saved → %s", pv_path)

    metrics_path = os.path.join(RESULTS_DIR, "metrics.txt")
    with open(metrics_path, "w") as f:
        f.write(f"Data source: {data_label}\n")
        f.write(f"Period: {args.start} to {args.end or 'today'}\n\n")
        for k, v in metrics.items():
            f.write(f"{k}: {v}\n")
    logger.info("Metrics saved → %s", metrics_path)

    if not args.no_plot:
        rolling_peak = portfolio_value.cummax()
        drawdown = (portfolio_value - rolling_peak) / rolling_peak
        monthly_returns = (1 + daily_returns).resample("ME").prod() - 1

        _plot_results(
            portfolio_value=portfolio_value,
            benchmark_value=benchmark_value.reindex(portfolio_value.index).ffill(),
            drawdown=drawdown,
            monthly_returns=monthly_returns,
            save_path=os.path.join(RESULTS_DIR, "performance_chart.png"),
            data_label=data_label,
        )

    logger.info("Done.")


if __name__ == "__main__":
    main()
