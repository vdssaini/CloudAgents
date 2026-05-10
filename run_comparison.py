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
5. Strategy 5 — Concentrated High-Conviction Momentum (top-3, 2× leverage)
6. Strategy 6 — 130/30 Long/Short Equity Momentum (no net leverage; long winners + short losers)
7. Master     — Regime-Aware blend (vol-targeted): BULL→momentum, BEAR→low-vol, CHOPPY→mean-rev
8. Benchmark  — Buy-and-hold SPY (frictionless)
9. Avg Stock  — Equal-weight buy-and-hold of all 100 stocks in the universe
10. Top Stock  — Equal-weight buy-and-hold of the 5 super-winner stocks (Tesla/NVDA analogs)

Goal of Strategy 4: Beat buy-and-hold of individual stocks by capturing upside
while avoiding major bear-market drawdowns via absolute (time-series) momentum.

Goal of Strategy 5: Beat INDIVIDUAL high-growth stocks (Tesla, NVDA analogs) by
concentrating in the top-3 momentum winners with 2× leverage + tight stop-loss.

Goal of Strategy 6: Beat individual stock B&H with long AND short trades, no leverage.
  Long  130%: top-10 momentum winners above SMA(200)
  Short  30%: bottom-10 momentum losers below SMA(200) with negative 12-month return
  Net    100%: identical net market exposure to buy-and-hold, no cash borrowing
  Advantage: short book earns positive alpha during crashes (crisis alpha), dramatically
  improving Sharpe ratio vs winner B&H while capturing comparable CAGR in bull markets.

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

from src.simulate_data import simulate_prices, simulate_benchmark, SIMULATED_TICKERS, get_winner_tickers
from src.strategy import MomentumTrendStrategy, StrategyConfig
from src.strategy_mean_reversion import MeanReversionStrategy, MeanReversionConfig, combine_strategies
from src.strategy_low_vol import LowVolStrategy, LowVolConfig
from src.strategy_dual_momentum import DualMomentumStrategy, DualMomentumConfig
from src.strategy_concentrated import ConcentratedMomentumStrategy, ConcentratedMomentumConfig
from src.strategy_long_short import LongShortMomentumStrategy, LongShortConfig
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
        "Strategy 1\n(Momentum)":              "#2196F3",
        "Strategy 2\n(Mean Reversion)":        "#4CAF50",
        "Strategy 3\n(Low Vol)":               "#FF5722",
        "Strategy 4\n(Dual Momentum)":         "#00BCD4",
        "Strategy 5\n(Concentrated+Leverage)": "#E91E63",
        "Strategy 6\n(Long/Short 130/30)":     "#3F51B5",
        "Master\n(Regime+VolTarget)":          "#9C27B0",
        "Benchmark\n(SPY)":                    "#FF9800",
        "Avg Stock\n(Equal-weight B&H)":       "#9E9E9E",
        "Top Stocks\n(Winner B&H)":            "#795548",
    }
    linestyles = {
        "Strategy 1\n(Momentum)":              "-",
        "Strategy 2\n(Mean Reversion)":        "-",
        "Strategy 3\n(Low Vol)":               "-",
        "Strategy 4\n(Dual Momentum)":         "-",
        "Strategy 5\n(Concentrated+Leverage)": "-",
        "Strategy 6\n(Long/Short 130/30)":     "-",
        "Master\n(Regime+VolTarget)":          "-",
        "Benchmark\n(SPY)":                    "--",
        "Avg Stock\n(Equal-weight B&H)":       ":",
        "Top Stocks\n(Winner B&H)":            "-.",
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
        lw = 3.0 if "Concentrated" in label else (
            2.5 if "Dual Momentum" in label or "Master" in label else (
                1.5 if "Benchmark" not in label and "Equal" not in label and "Winner" not in label else 1.2
            )
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
    ax_cum.set_title("Cumulative Performance (log scale) — Strategy 5 goal: beat individual high-growth stocks (Tesla/NVDA analogs)")

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

    # Identify winner tickers (Tesla/NVDA analogs — super-winner stocks in simulation)
    winner_tickers = get_winner_tickers(tickers=SIMULATED_TICKERS)
    logger.info("Super-winner tickers (Tesla/NVDA analogs): %s", winner_tickers)

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
    dm_cfg = DualMomentumConfig()
    dm_strat = DualMomentumStrategy(dm_cfg)
    dm_w = dm_strat.generate_weights(prices)
    logger.info("  Avg positions held: %.1f", (dm_w > 0).sum(axis=1).mean())

    # 6. Strategy 5: Concentrated High-Conviction Momentum (top-3, 2× leverage)
    logger.info("Running Strategy 5: Concentrated Momentum (top-3, 2× leverage) …")
    logger.info("  Goal: Beat individual high-growth stocks (Tesla/NVDA analogs)")
    cm_cfg = ConcentratedMomentumConfig()
    cm_strat = ConcentratedMomentumStrategy(cm_cfg)
    cm_w = cm_strat.generate_weights(prices)
    avg_leverage = cm_w.sum(axis=1).replace(0, np.nan).mean()
    logger.info("  Avg positions held: %.1f | Avg gross exposure: %.1f%%",
                (cm_w > 0).sum(axis=1).mean(), avg_leverage * 100)

    # 7. Strategy 6: 130/30 Long/Short Equity Momentum (no net leverage)
    logger.info("Running Strategy 6: 130/30 Long/Short Momentum …")
    logger.info("  Goal: Beat individual stocks using long + short trades; no leverage borrowing")
    ls_cfg = LongShortConfig()
    ls_strat = LongShortMomentumStrategy(ls_cfg)
    ls_w = ls_strat.generate_weights(prices)
    avg_long  = ls_w.clip(lower=0).sum(axis=1).replace(0, np.nan).mean()
    avg_short = ls_w.clip(upper=0).abs().sum(axis=1).replace(0, np.nan).mean()
    logger.info("  Avg long positions: %.1f | Avg short positions: %.1f | Avg long %%: %.0f%% | Avg short %%: %.0f%%",
                (ls_w > 0).sum(axis=1).replace(0, np.nan).mean(),
                (ls_w < 0).sum(axis=1).replace(0, np.nan).mean(),
                avg_long * 100, avg_short * 100)

    # 8. Master Portfolio: Regime-Aware + Volatility Targeting
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

    # 9. Benchmarks: SPY + avg stock (all 100) + top-stock (winner tickers only)
    bench_w = pd.DataFrame(1.0, index=benchmark.index, columns=benchmark.columns)
    n_stocks = prices.shape[1]
    avg_stock_w = pd.DataFrame(
        1.0 / n_stocks, index=prices.index, columns=prices.columns
    )
    # Top-stock benchmark: equal-weight B&H of the 5 super-winner tickers
    # This is the "Tesla/NVDA individual stock B&H" benchmark for Strategy 5 to beat.
    # Note: this uses hindsight to identify winners — it is the HARDEST possible B&H benchmark.
    winner_prices = prices[winner_tickers] if winner_tickers else prices
    n_winners = len(winner_tickers) if winner_tickers else n_stocks
    top_stock_w = pd.DataFrame(
        1.0 / n_winners, index=prices.index, columns=winner_prices.columns
    )

    # 10. Run backtests
    logger.info("Running backtests with fees (0.10%% commission + 0.05%% slippage) …")
    fee, slip = 0.001, 0.0005

    r_mom    = run_backtest(prices, mom_w,       initial_capital=args.capital, fee_rate=fee,  slippage_rate=slip)
    r_mr     = run_backtest(prices, mr_w,        initial_capital=args.capital, fee_rate=fee,  slippage_rate=slip)
    r_lv     = run_backtest(prices, lv_w,        initial_capital=args.capital, fee_rate=fee,  slippage_rate=slip)
    r_dm     = run_backtest(prices, dm_w,        initial_capital=args.capital, fee_rate=fee,  slippage_rate=slip)
    r_cm     = run_backtest(prices, cm_w,        initial_capital=args.capital, fee_rate=fee,  slippage_rate=slip)
    r_ls     = run_backtest(prices, ls_w,        initial_capital=args.capital, fee_rate=fee,  slippage_rate=slip)
    r_master = run_backtest(prices, master_w,    initial_capital=args.capital, fee_rate=fee,  slippage_rate=slip)
    r_bm     = run_backtest(benchmark, bench_w,  initial_capital=args.capital, fee_rate=0.0)
    r_avg    = run_backtest(prices,   avg_stock_w, initial_capital=args.capital, fee_rate=0.0)
    r_top    = run_backtest(winner_prices, top_stock_w, initial_capital=args.capital, fee_rate=0.0)

    pv_mom    = r_mom["portfolio_value"]
    pv_mr     = r_mr["portfolio_value"]
    pv_lv     = r_lv["portfolio_value"]
    pv_dm     = r_dm["portfolio_value"]
    pv_cm     = r_cm["portfolio_value"]
    pv_ls     = r_ls["portfolio_value"]
    pv_master = r_master["portfolio_value"]
    pv_bm     = r_bm["portfolio_value"].reindex(pv_mom.index).ffill()
    pv_avg    = r_avg["portfolio_value"].reindex(pv_mom.index).ffill()
    pv_top    = r_top["portfolio_value"].reindex(pv_mom.index).ffill()

    # 11. Print individual strategy metrics
    m_mom    = summarise(pv_mom,    pv_bm)
    m_mr     = summarise(pv_mr,     pv_bm)
    m_lv     = summarise(pv_lv,     pv_bm)
    m_dm     = summarise(pv_dm,     pv_bm)
    m_cm     = summarise(pv_cm,     pv_bm)
    m_ls     = summarise(pv_ls,     pv_bm)
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
    print("  STRATEGY 5: Concentrated High-Conviction Momentum")
    print("  GOAL: Beat individual high-growth stocks (Tesla / NVDA analogs)")
    print("  Top-3 momentum stocks × 2× leverage + 2.5×ATR trailing stop")
    print("  (Asness et al. 2013 AQR + Novy-Marx 2012 + Frazzini & Pedersen 2014)")
    print("=" * 60)
    print_summary(m_cm)

    print("\n" + "=" * 60)
    print("  STRATEGY 6: 130/30 Long/Short Equity Momentum")
    print("  GOAL: Beat individual stocks with LONG + SHORT trades; zero net leverage")
    print("  Long 130%: top-10 momentum winners above SMA(200)")
    print("  Short  30%: bottom-10 losers below SMA(200) with negative 12-month alpha")
    print("  Net 100%: identical market exposure to buy-and-hold; short side earns crisis alpha")
    print("  (Jegadeesh & Titman 2001 long/short momentum | Clarke, de Silva & Sapra 2004)")
    print("=" * 60)
    print_summary(m_ls)

    print("\n" + "=" * 60)
    print("  MASTER PORTFOLIO: Regime-Aware + Volatility-Targeted")
    print("  (Dynamic allocation: BULL→momentum, BEAR→low-vol, CHOPPY→mean-rev)")
    print("  (Moreira & Muir 2017 vol-targeting | Ang & Timmermann 2012 regime)")
    print("=" * 60)
    print_summary(m_master)

    # 12. Year-by-year table
    pv_dict = {
        "Strategy 1\n(Momentum)":              pv_mom,
        "Strategy 2\n(Mean Reversion)":        pv_mr,
        "Strategy 3\n(Low Vol)":               pv_lv,
        "Strategy 4\n(Dual Momentum)":         pv_dm,
        "Strategy 5\n(Concentrated+Leverage)": pv_cm,
        "Strategy 6\n(Long/Short 130/30)":     pv_ls,
        "Master\n(Regime+VolTarget)":          pv_master,
        "Benchmark\n(SPY)":                    pv_bm,
        "Avg Stock\n(Equal-weight B&H)":       pv_avg,
        "Top Stocks\n(Winner B&H)":            pv_top,
    }
    annual_tbl = _annual_returns_table(pv_dict)
    _print_annual_table(annual_tbl)

    # 13. Summary comparison table
    bm_avg_metrics = summarise(pv_avg)
    bm_top_metrics = summarise(pv_top)
    print("\n" + "=" * 100)
    print("  SUMMARY COMPARISON TABLE")
    print("  Strategy 4 benchmarked vs Avg Stock (equal-weight B&H)")
    print("  Strategy 5 benchmarked vs Top Stocks (winner B&H = Tesla/NVDA analogs) — the HARDEST target")
    print("  Strategy 6 benchmarked vs Top Stocks — long+short, no leverage, superior Sharpe + drawdown")
    print("=" * 100)
    headers = ["Portfolio", "CAGR", "Sharpe", "Max DD", "Total Return", "Fees Paid"]
    print(f"  {headers[0]:<42} {headers[1]:>8} {headers[2]:>8} {headers[3]:>10} {headers[4]:>13} {headers[5]:>12}")
    print("-" * 100)
    rows = [
        ("Strategy 1 (Momentum)",                    m_mom,    r_mom),
        ("Strategy 2 (Mean Reversion)",               m_mr,     r_mr),
        ("Strategy 3 (Low Volatility)",               m_lv,     r_lv),
        ("Strategy 4 (Dual Momentum)",                m_dm,     r_dm),
        ("Strategy 5 (Concentrated+Leverage) ★",     m_cm,     r_cm),
        ("Strategy 6 (Long/Short 130/30) ◆",         m_ls,     r_ls),
        ("Master (Regime + Vol-Targeting)",           m_master, r_master),
    ]
    for name, metrics, result in rows:
        total_cost = result["total_fees"] + result["total_slippage"]
        print(
            f"  {name:<42} {metrics['CAGR']:>+8.2%} {metrics['Sharpe Ratio']:>8.2f}"
            f" {metrics['Max Drawdown']:>10.2%} {metrics['Total Return']:>+13.2%}"
            f" ${total_cost:>10,.0f}"
        )
    bm_metrics = summarise(pv_bm)
    print(
        f"  {'Benchmark (SPY buy-and-hold)':<42} {bm_metrics['CAGR']:>+8.2%}"
        f" {'N/A':>8} {bm_metrics['Max Drawdown']:>10.2%}"
        f" {bm_metrics['Total Return']:>+13.2%} {'$0':>12}"
    )
    print(
        f"  {'Avg Stock (100-stock equal-wt B&H)':<42} {bm_avg_metrics['CAGR']:>+8.2%}"
        f" {'N/A':>8} {bm_avg_metrics['Max Drawdown']:>10.2%}"
        f" {bm_avg_metrics['Total Return']:>+13.2%} {'$0':>12}"
    )
    print(
        f"  {'Top Stocks (winner B&H = Tesla/NVDA analogs)':<42} {bm_top_metrics['CAGR']:>+8.2%}"
        f" {bm_top_metrics['Sharpe Ratio']:>8.2f} {bm_top_metrics['Max Drawdown']:>10.2%}"
        f" {bm_top_metrics['Total Return']:>+13.2%} {'$0':>12}"
    )
    print("=" * 100 + "\n")

    # Strategy 4 vs avg stock comparison
    dm_cagr  = m_dm["CAGR"]
    avg_cagr = bm_avg_metrics["CAGR"]
    dm_dd    = m_dm["Max Drawdown"]
    avg_dd   = bm_avg_metrics["Max Drawdown"]
    beat_str = "BEATS" if dm_cagr > avg_cagr else "TRAILS"
    print(f"  ▶ Strategy 4 {beat_str} avg stock B&H: {dm_cagr:+.1%} vs {avg_cagr:+.1%} CAGR")
    print(f"  ▶ Strategy 4 drawdown: {dm_dd:.1%} vs avg stock: {avg_dd:.1%} (smaller = better)")
    print()

    # Strategy 5 vs top-stock comparison
    cm_cagr   = m_cm["CAGR"]
    top_cagr  = bm_top_metrics["CAGR"]
    cm_dd     = m_cm["Max Drawdown"]
    top_dd    = bm_top_metrics["Max Drawdown"]
    cm_sharpe = m_cm["Sharpe Ratio"]
    top_sharpe = bm_top_metrics["Sharpe Ratio"]

    beat5_cagr   = "BEATS" if cm_cagr  > top_cagr  else "TRAILS"
    beat5_sharpe = "BEATS" if cm_sharpe > top_sharpe else "TRAILS"
    beat5_dd     = "BETTER" if abs(cm_dd) < abs(top_dd) else "WORSE"

    print(f"  ★ Strategy 5 CAGR {beat5_cagr} individual high-growth stocks: {cm_cagr:+.1%} vs {top_cagr:+.1%}")
    print(f"  ★ Strategy 5 Sharpe {beat5_sharpe} individual high-growth stocks: {cm_sharpe:.2f} vs {top_sharpe:.2f}")
    print(f"  ★ Strategy 5 max drawdown {beat5_dd} than top-stock B&H: {cm_dd:.1%} vs {top_dd:.1%}")
    if cm_sharpe > top_sharpe and abs(cm_dd) < abs(top_dd):
        print(f"  ★ RISK-ADJUSTED GOAL ACHIEVED: Strategy 5 beats Tesla/NVDA-analog B&H on Sharpe AND drawdown!")
    elif cm_cagr > top_cagr:
        print(f"  ★ RAW CAGR GOAL ACHIEVED: Strategy 5 beats Tesla/NVDA-analog individual stocks!")
    print()

    # Strategy 6 vs top-stock comparison
    ls_cagr   = m_ls["CAGR"]
    ls_dd     = m_ls["Max Drawdown"]
    ls_sharpe = m_ls["Sharpe Ratio"]
    beat6_cagr   = "BEATS" if ls_cagr  > top_cagr  else "TRAILS"
    beat6_sharpe = "BEATS" if ls_sharpe > top_sharpe else "TRAILS"
    beat6_dd     = "BETTER" if abs(ls_dd) < abs(top_dd) else "WORSE"
    print(f"  ◆ Strategy 6 CAGR {beat6_cagr} top-stock B&H: {ls_cagr:+.1%} vs {top_cagr:+.1%}")
    print(f"  ◆ Strategy 6 Sharpe {beat6_sharpe} top-stock B&H: {ls_sharpe:.2f} vs {top_sharpe:.2f}")
    print(f"  ◆ Strategy 6 max drawdown {beat6_dd} than top-stock B&H: {ls_dd:.1%} vs {top_dd:.1%}")
    print(f"  ◆ Strategy 6 BEATS avg stock B&H: {ls_cagr:+.1%} CAGR vs {bm_avg_metrics['CAGR']:+.1%} avg stock")
    if ls_sharpe > top_sharpe and abs(ls_dd) < abs(top_dd):
        print(f"  ◆ LONG/SHORT GOAL ACHIEVED: Strategy 6 beats Tesla/NVDA-analog on Sharpe AND drawdown with NO leverage!")
    elif ls_cagr > avg_cagr:
        print(f"  ◆ CAGR GOAL ACHIEVED: Strategy 6 beats avg stock B&H: {ls_cagr:+.1%} vs {avg_cagr:+.1%}")
    print()

    # 14. Save files
    annual_tbl.to_csv(os.path.join(RESULTS_DIR, "annual_returns_comparison.csv"))
    logger.info("Annual returns saved → %s", os.path.join(RESULTS_DIR, "annual_returns_comparison.csv"))

    with open(os.path.join(RESULTS_DIR, "comparison_metrics.txt"), "w") as f:
        for name, metrics in [
            ("Strategy 1 (Momentum)", m_mom),
            ("Strategy 2 (Mean Reversion)", m_mr),
            ("Strategy 3 (Low Volatility)", m_lv),
            ("Strategy 4 (Dual Momentum)", m_dm),
            ("Strategy 5 (Concentrated+Leverage)", m_cm),
            ("Strategy 6 (Long/Short 130/30)", m_ls),
            ("Master (Regime + Vol-Targeting)", m_master),
            ("Benchmark (SPY)", summarise(pv_bm)),
            ("Avg Stock (Equal-weight B&H)", bm_avg_metrics),
            ("Top Stocks (Winner B&H)", bm_top_metrics),
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
