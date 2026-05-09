"""
run_comparison.py
-----------------
Run a comprehensive side-by-side backtest of all portfolios over a 20-year
period on a 100-stock universe and print/save detailed results.

Portfolios compared
-------------------
1. Strategy 1 — Adaptive Momentum + Trend Filter  (Jegadeesh & Titman 1993)
2. Strategy 2 — RSI(2) + Bollinger Band Mean Reversion  (Connors & Alvarez 2009)
3. Strategy 3 — Low Volatility Factor  (Baker, Bradley & Wurgler 2011)
4. Strategy 4 — Dual Momentum + 52-Week High  (Antonacci 2014 + George & Hwang 2004)
5. Master     — Regime-Aware blend (vol-targeted): BULL→momentum, BEAR→low-vol, CHOPPY→mean-rev
6. Benchmark  — Buy-and-hold SPY (frictionless)
7. Avg Stock  — Equal-weight buy-and-hold of all 100 stocks in the universe

Goal of Strategy 4: Beat buy-and-hold of individual stocks by capturing upside
while avoiding major bear-market drawdowns via absolute (time-series) momentum.

Usage
-----
    python run_comparison.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                             [--capital N] [--no-plot]
"""

import argparse
import logging
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from src.simulate_data import simulate_prices, simulate_benchmark, SIMULATED_TICKERS
from src.strategy import MomentumTrendStrategy, StrategyConfig
from src.strategy_mean_reversion import MeanReversionStrategy, MeanReversionConfig, combine_strategies
from src.strategy_low_vol import LowVolStrategy, LowVolConfig
from src.strategy_dual_momentum import DualMomentumStrategy, DualMomentumConfig
from src.regime_detector import RegimeDetector
from src.portfolio_optimizer import vol_target_scale, regime_aware_combine
from src.backtest_engine import run_backtest
from src.metrics import summarise, print_summary, cagr, max_drawdown, sharpe_ratio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _annual_returns_table(
    portfolio_values: dict[str, pd.Series],
) -> pd.DataFrame:
    """Build a year-by-year return table for every portfolio."""
    rows = []
    all_years = sorted({y for pv in portfolio_values.values() for y in pv.index.year.unique()})

    for year in all_years:
        row = {"Year": year}
        for label, pv in portfolio_values.items():
            yr = pv[pv.index.year == year]
            if len(yr) < 2:
                row[label] = np.nan
                continue
            row[label] = yr.iloc[-1] / yr.iloc[0] - 1
        rows.append(row)

    df = pd.DataFrame(rows).set_index("Year")
    return df


def _print_annual_table(df: pd.DataFrame) -> None:
    header = f"  {'Year':>4}  " + "".join(f"{col:>24}" for col in df.columns)
    print("\n" + "=" * len(header))
    print("  Year-by-Year Annual Returns")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for year, row in df.iterrows():
        line = f"  {year:>4}  "
        for col in df.columns:
            v = row[col]
            s = f"{v:>+.1%}" if not np.isnan(v) else "     N/A"
            line += f"{s:>24}"
        print(line)
    print("=" * len(header) + "\n")


def _plot_comparison(
    portfolio_values: dict[str, pd.Series],
    annual_table: pd.DataFrame,
    save_path: str,
) -> None:
    colors = {
        "Strategy 1\n(Momentum)":         "#2196F3",
        "Strategy 2\n(Mean Reversion)":   "#4CAF50",
        "Strategy 3\n(Low Vol)":          "#FF5722",
        "Strategy 4\n(Dual Momentum)":    "#00BCD4",
        "Master\n(Regime+VolTarget)":     "#9C27B0",
        "Benchmark\n(SPY)":               "#FF9800",
        "Avg Stock\n(Equal-weight B&H)":  "#9E9E9E",
    }
    linestyles = {
        "Strategy 1\n(Momentum)":         "-",
        "Strategy 2\n(Mean Reversion)":   "-",
        "Strategy 3\n(Low Vol)":          "-",
        "Strategy 4\n(Dual Momentum)":    "-",
        "Master\n(Regime+VolTarget)":     "-",
        "Benchmark\n(SPY)":               "--",
        "Avg Stock\n(Equal-weight B&H)":  ":",
    }

    fig = plt.figure(figsize=(22, 20))
    gs = fig.add_gridspec(3, 2, hspace=0.42, wspace=0.28)

    ax_cum = fig.add_subplot(gs[0, :])
    ax_dd = fig.add_subplot(gs[1, 0])
    ax_annual = fig.add_subplot(gs[1, 1])
    ax_roll = fig.add_subplot(gs[2, :])

    fig.suptitle(
        "Strategy Comparison — 20-Year Backtest (Goal: Beat Individual Stock Buy-and-Hold)\n"
        "100-Stock Universe | Regime-Switching Simulation | Fees & Slippage Included",
        fontsize=13, fontweight="bold",
    )

    # ---- 1. Cumulative performance (log scale) ----
    for label, pv in portfolio_values.items():
        pv_norm = pv / pv.iloc[0] * 100
        lw = 2.5 if "Dual Momentum" in label or "Master" in label else (
            1.5 if "Benchmark" not in label and "Equal" not in label else 1.2
        )
        ax_cum.plot(
            pv_norm.index, pv_norm,
            label=label.replace("\n", " "),
            color=colors.get(label, "#888888"),
            linestyle=linestyles.get(label, "-"),
            linewidth=lw,
        )
    ax_cum.set_yscale("log")
    ax_cum.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    ax_cum.set_ylabel("Normalised Value (log, base=100)")
    ax_cum.legend(loc="upper left", ncol=4, fontsize=8)
    ax_cum.grid(True, alpha=0.3)
    ax_cum.set_title("Cumulative Performance (log scale) — Strategy 4 goal: beat avg stock B&H")

    # ---- 2. Drawdown ----
    for label, pv in portfolio_values.items():
        peak = pv.cummax()
        dd = (pv - peak) / peak * 100
        ax_dd.plot(dd.index, dd, label=label.replace("\n", " "),
                   color=colors.get(label, "#888888"),
                   linestyle=linestyles.get(label, "-"), linewidth=1.2)
    ax_dd.axhline(0, color="black", linewidth=0.6)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax_dd.legend(fontsize=7, loc="lower left")
    ax_dd.grid(True, alpha=0.3)
    ax_dd.set_title("Drawdown")

    # ---- 3. Annual returns grouped bar chart ----
    years = annual_table.index.astype(str)
    col_labels = list(annual_table.columns)
    n_groups = len(years)
    n_bars = len(col_labels)
    bar_width = max(0.10, 0.80 / n_bars)  # 0.80 = total group width; 0.10 = min readable bar
    x = np.arange(n_groups)

    bar_colors = [colors.get(c, "#888888") for c in col_labels]
    for bi, col in enumerate(col_labels):
        vals = annual_table[col].values * 100
        offset = (bi - (n_bars - 1) / 2) * bar_width
        ax_annual.bar(x + offset, vals, bar_width, label=col.replace("\n", " "),
                      color=bar_colors[bi], alpha=0.8)

    ax_annual.axhline(0, color="black", linewidth=0.8)
    ax_annual.set_xticks(x)
    ax_annual.set_xticklabels(years, rotation=45, ha="right", fontsize=7)
    ax_annual.set_ylabel("Annual Return (%)")
    ax_annual.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax_annual.legend(fontsize=6, loc="upper left")
    ax_annual.grid(True, alpha=0.3, axis="y")
    ax_annual.set_title("Year-by-Year Returns")

    # ---- 4. Rolling 252-day Sharpe ----
    for label, pv in portfolio_values.items():
        ret = pv.pct_change().dropna()
        roll_sharpe = ret.rolling(252).mean() / ret.rolling(252).std() * np.sqrt(252)
        ax_roll.plot(roll_sharpe.index, roll_sharpe,
                     label=label.replace("\n", " "),
                     color=colors.get(label, "#888888"),
                     linestyle=linestyles.get(label, "-"), linewidth=1.2)
    ax_roll.axhline(0, color="black", linewidth=0.6)
    ax_roll.axhline(1, color="gray", linewidth=0.6, linestyle=":")
    ax_roll.set_ylabel("Rolling Sharpe (252-day)")
    ax_roll.legend(fontsize=7, loc="upper right", ncol=4)
    ax_roll.grid(True, alpha=0.3)
    ax_roll.set_title("Rolling 1-Year Sharpe Ratio")

    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Comparison chart saved → %s", save_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Side-by-side 20-year backtest: all strategies vs avg stock buy-and-hold."
    )
    p.add_argument("--start", default="2005-01-01",
                   help="Start date (YYYY-MM-DD). Default: 2005-01-01")
    p.add_argument("--end", default=None,
                   help="End date (YYYY-MM-DD). Default: today")
    p.add_argument("--capital", type=float, default=100_000,
                   help="Initial capital in USD. Default: 100000")
    p.add_argument("--no-plot", action="store_true",
                   help="Skip chart generation.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    start, end = args.start, args.end

    logger.info("=" * 70)
    logger.info("  Comprehensive Strategy Comparison Backtest")
    logger.info("  Universe: %d stocks   |   Period: %s → %s", len(SIMULATED_TICKERS), start, end or "today")
    logger.info("=" * 70)

    # 1. Generate price data (100 stocks, 20 years, regime-switching simulation)
    logger.info("Generating simulated price data (100 stocks, regime-switching model) …")
    prices = simulate_prices(tickers=SIMULATED_TICKERS, start=start, end=end)
    benchmark = simulate_benchmark(start=start, end=end)
    benchmark = benchmark.reindex(prices.index).ffill()
    logger.info("Data: %d dates × %d tickers", len(prices), prices.shape[1])

    # 2. Strategy 1: Momentum + Trend Filter
    logger.info("Running Strategy 1: Momentum + Trend Filter …")
    mom_cfg = StrategyConfig(top_n=20)
    mom_strat = MomentumTrendStrategy(mom_cfg)
    mom_w = mom_strat.generate_weights(prices)
    logger.info("  Avg positions held: %.1f", (mom_w > 0).sum(axis=1).mean())

    # 3. Strategy 2: Mean Reversion
    logger.info("Running Strategy 2: RSI(2) + Bollinger Band Mean Reversion …")
    mr_cfg = MeanReversionConfig(max_positions=10, rebalance_days=5)
    mr_strat = MeanReversionStrategy(mr_cfg)
    mr_w = mr_strat.generate_weights(prices)
    logger.info("  Avg positions held: %.1f", (mr_w > 0).sum(axis=1).mean())

    # 4. Strategy 3: Low Volatility Factor
    logger.info("Running Strategy 3: Low Volatility Factor …")
    lv_cfg = LowVolConfig(top_n=20)
    lv_strat = LowVolStrategy(lv_cfg)
    lv_w = lv_strat.generate_weights(prices)
    logger.info("  Avg positions held: %.1f", (lv_w > 0).sum(axis=1).mean())

    # 5. Strategy 4: Dual Momentum + 52-Week High (designed to beat individual B&H)
    logger.info("Running Strategy 4: Dual Momentum + 52-Week High …")
    logger.info("  Goal: Beat buy-and-hold of individual stocks by avoiding bear markets")
    dm_cfg = DualMomentumConfig(top_n=20)
    dm_strat = DualMomentumStrategy(dm_cfg)
    dm_w = dm_strat.generate_weights(prices)
    logger.info("  Avg positions held: %.1f", (dm_w > 0).sum(axis=1).mean())

    # 6. Master Portfolio: Regime-Aware + Volatility Targeting
    logger.info("Building Master Portfolio (regime-aware + vol-targeting) …")
    bench_series = benchmark.squeeze()
    detector = RegimeDetector()
    regimes = detector.detect(bench_series)
    regime_counts = detector.regime_counts(bench_series)
    logger.info("  Regime distribution — BULL: %d days | BEAR: %d days | CHOPPY: %d days",
                regime_counts["bull"], regime_counts["bear"], regime_counts["choppy"])

    weights_dict = {"momentum": mom_w, "mean_rev": mr_w, "low_vol": lv_w}
    master_raw = regime_aware_combine(weights_dict, bench_series)
    master_w = vol_target_scale(master_raw, prices, target_vol=0.12)
    logger.info("  Master portfolio avg gross exposure: %.1f%%", master_w.sum(axis=1).mean() * 100)

    # 7. Benchmarks: SPY buy-and-hold + avg stock equal-weight buy-and-hold
    bench_w = pd.DataFrame(1.0, index=benchmark.index, columns=benchmark.columns)
    # Equal-weight buy-and-hold of all 100 stocks — the "average individual stock" benchmark
    n_stocks = prices.shape[1]
    avg_stock_w = pd.DataFrame(
        1.0 / n_stocks, index=prices.index, columns=prices.columns
    )

    # 8. Run backtests
    logger.info("Running backtests with fees (0.10%% commission + 0.05%% slippage) …")
    fee, slip = 0.001, 0.0005

    r_mom = run_backtest(prices, mom_w, initial_capital=args.capital, fee_rate=fee, slippage_rate=slip)
    r_mr = run_backtest(prices, mr_w, initial_capital=args.capital, fee_rate=fee, slippage_rate=slip)
    r_lv = run_backtest(prices, lv_w, initial_capital=args.capital, fee_rate=fee, slippage_rate=slip)
    r_dm = run_backtest(prices, dm_w, initial_capital=args.capital, fee_rate=fee, slippage_rate=slip)
    r_master = run_backtest(prices, master_w, initial_capital=args.capital, fee_rate=fee, slippage_rate=slip)
    r_bm = run_backtest(benchmark, bench_w, initial_capital=args.capital, fee_rate=0.0)
    # Average stock B&H: buy-and-hold all stocks equally — no fees (pure B&H benchmark)
    r_avg = run_backtest(prices, avg_stock_w, initial_capital=args.capital, fee_rate=0.0)

    pv_mom = r_mom["portfolio_value"]
    pv_mr = r_mr["portfolio_value"]
    pv_lv = r_lv["portfolio_value"]
    pv_dm = r_dm["portfolio_value"]
    pv_master = r_master["portfolio_value"]
    pv_bm = r_bm["portfolio_value"].reindex(pv_mom.index).ffill()
    pv_avg = r_avg["portfolio_value"].reindex(pv_mom.index).ffill()

    # 9. Print individual strategy metrics
    m_mom = summarise(pv_mom, pv_bm)
    m_mr = summarise(pv_mr, pv_bm)
    m_lv = summarise(pv_lv, pv_bm)
    m_dm = summarise(pv_dm, pv_bm)
    m_master = summarise(pv_master, pv_bm)

    print("\n" + "=" * 60)
    print("  STRATEGY 1: Adaptive Momentum + Trend Filter")
    print("  (Jegadeesh & Titman 1993 + Faber 2007)")
    print("=" * 60)
    print_summary(m_mom)

    print("\n" + "=" * 60)
    print("  STRATEGY 2: Short-Term Mean Reversion")
    print("  (Connors & Alvarez 2009 + Blitz et al. 2011)")
    print("=" * 60)
    print_summary(m_mr)

    print("\n" + "=" * 60)
    print("  STRATEGY 3: Low-Volatility Factor")
    print("  (Baker, Bradley & Wurgler 2011; Frazzini & Pedersen 2014)")
    print("=" * 60)
    print_summary(m_lv)

    print("\n" + "=" * 60)
    print("  STRATEGY 4: Dual Momentum + 52-Week High")
    print("  GOAL: Beat buy-and-hold of individual stocks")
    print("  (Antonacci 2014 dual momentum + George & Hwang 2004 52w high)")
    print("=" * 60)
    print_summary(m_dm)

    print("\n" + "=" * 60)
    print("  MASTER PORTFOLIO: Regime-Aware + Volatility-Targeted")
    print("  (Dynamic allocation: BULL→momentum, BEAR→low-vol, CHOPPY→mean-rev)")
    print("  (Moreira & Muir 2017 vol-targeting | Ang & Timmermann 2012 regime)")
    print("=" * 60)
    print_summary(m_master)

    # 10. Year-by-year table
    pv_dict = {
        "Strategy 1\n(Momentum)":         pv_mom,
        "Strategy 2\n(Mean Reversion)":   pv_mr,
        "Strategy 3\n(Low Vol)":          pv_lv,
        "Strategy 4\n(Dual Momentum)":    pv_dm,
        "Master\n(Regime+VolTarget)":     pv_master,
        "Benchmark\n(SPY)":               pv_bm,
        "Avg Stock\n(Equal-weight B&H)":  pv_avg,
    }
    annual_tbl = _annual_returns_table(pv_dict)
    _print_annual_table(annual_tbl)

    # 11. Summary comparison table (vs avg stock B&H for Strategy 4)
    bm_avg_metrics = summarise(pv_avg)
    print("\n" + "=" * 90)
    print("  SUMMARY COMPARISON TABLE")
    print("  Note: Strategy 4 is benchmarked vs Avg Stock (equal-weight B&H) — the harder target")
    print("=" * 90)
    headers = ["Portfolio", "CAGR", "Sharpe", "Max DD", "Total Return", "Fees Paid"]
    print(f"  {headers[0]:<36} {headers[1]:>8} {headers[2]:>8} {headers[3]:>10} {headers[4]:>13} {headers[5]:>12}")
    print("-" * 90)
    rows = [
        ("Strategy 1 (Momentum)",              m_mom,    r_mom),
        ("Strategy 2 (Mean Reversion)",         m_mr,     r_mr),
        ("Strategy 3 (Low Volatility)",         m_lv,     r_lv),
        ("Strategy 4 (Dual Momentum)",          m_dm,     r_dm),
        ("Master (Regime + Vol-Targeting)",     m_master, r_master),
    ]
    for name, metrics, result in rows:
        total_cost = result["total_fees"] + result["total_slippage"]
        print(
            f"  {name:<36} {metrics['CAGR']:>+8.2%} {metrics['Sharpe Ratio']:>8.2f}"
            f" {metrics['Max Drawdown']:>10.2%} {metrics['Total Return']:>+13.2%}"
            f" ${total_cost:>10,.0f}"
        )
    bm_metrics = summarise(pv_bm)
    print(
        f"  {'Benchmark (SPY buy-and-hold)':<36} {bm_metrics['CAGR']:>+8.2%}"
        f" {'N/A':>8} {bm_metrics['Max Drawdown']:>10.2%}"
        f" {bm_metrics['Total Return']:>+13.2%} {'$0':>12}"
    )
    print(
        f"  {'Avg Stock (100-stock equal-wt B&H)':<36} {bm_avg_metrics['CAGR']:>+8.2%}"
        f" {'N/A':>8} {bm_avg_metrics['Max Drawdown']:>10.2%}"
        f" {bm_avg_metrics['Total Return']:>+13.2%} {'$0':>12}"
    )
    print("=" * 90 + "\n")

    # Strategy 4 vs avg stock comparison
    dm_cagr = m_dm["CAGR"]
    avg_cagr = bm_avg_metrics["CAGR"]
    dm_dd = m_dm["Max Drawdown"]
    avg_dd = bm_avg_metrics["Max Drawdown"]
    beat_str = "BEATS" if dm_cagr > avg_cagr else "TRAILS"
    print(f"  ▶ Strategy 4 {beat_str} avg stock B&H: {dm_cagr:+.1%} vs {avg_cagr:+.1%} CAGR")
    print(f"  ▶ Strategy 4 drawdown: {dm_dd:.1%} vs avg stock: {avg_dd:.1%} (smaller = better)")
    print()

    # 12. Save files
    annual_tbl.to_csv(os.path.join(RESULTS_DIR, "annual_returns_comparison.csv"))
    logger.info("Annual returns saved → %s", os.path.join(RESULTS_DIR, "annual_returns_comparison.csv"))

    with open(os.path.join(RESULTS_DIR, "comparison_metrics.txt"), "w") as f:
        for name, metrics in [
            ("Strategy 1 (Momentum)", m_mom),
            ("Strategy 2 (Mean Reversion)", m_mr),
            ("Strategy 3 (Low Volatility)", m_lv),
            ("Strategy 4 (Dual Momentum)", m_dm),
            ("Master (Regime + Vol-Targeting)", m_master),
            ("Benchmark (SPY)", summarise(pv_bm)),
            ("Avg Stock (Equal-weight B&H)", bm_avg_metrics),
        ]:
            f.write(f"\n=== {name} ===\n")
            for k, v in metrics.items():
                f.write(f"{k}: {v}\n")
    logger.info("Metrics saved → %s", os.path.join(RESULTS_DIR, "comparison_metrics.txt"))

    if not args.no_plot:
        _plot_comparison(
            portfolio_values=pv_dict,
            annual_table=annual_tbl,
            save_path=os.path.join(RESULTS_DIR, "comparison_chart.png"),
        )

    logger.info("Done.")


if __name__ == "__main__":
    main()
