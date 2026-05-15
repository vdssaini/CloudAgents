"""
metrics.py
----------
Portfolio performance metrics used to evaluate the backtest.

All functions accept a pd.Series of daily portfolio values or daily returns.
"""

import numpy as np
import pandas as pd
from scipy import stats


def cagr(portfolio_value: pd.Series) -> float:
    """
    Compound Annual Growth Rate.

    Parameters
    ----------
    portfolio_value : pd.Series
        Time series of daily portfolio values.

    Returns
    -------
    float
        CAGR as a decimal (e.g. 0.20 = 20 % p.a.).
    """
    total_return = portfolio_value.iloc[-1] / portfolio_value.iloc[0]
    n_years = len(portfolio_value) / 252
    if n_years <= 0:
        return 0.0
    return total_return ** (1 / n_years) - 1


def annualised_volatility(returns: pd.Series) -> float:
    """Annualised standard deviation of daily returns."""
    return returns.std() * np.sqrt(252)


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Annualised Sharpe ratio.

    Parameters
    ----------
    returns : pd.Series
        Daily returns.
    risk_free_rate : float
        Annual risk-free rate (default 0.0 — conservative).
    """
    rf_daily = (1 + risk_free_rate) ** (1 / 252) - 1
    excess = returns - rf_daily
    if excess.std() == 0:
        return 0.0
    return (excess.mean() / excess.std()) * np.sqrt(252)


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Annualised Sortino ratio (downside deviation denominator).

    Uses daily returns below the risk-free rate as the downside.
    """
    rf_daily = (1 + risk_free_rate) ** (1 / 252) - 1
    excess = returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return np.inf
    downside_vol = np.sqrt((downside ** 2).mean()) * np.sqrt(252)
    return (excess.mean() * 252) / downside_vol


def max_drawdown(portfolio_value: pd.Series) -> float:
    """
    Maximum peak-to-trough drawdown as a negative fraction.

    Returns
    -------
    float
        E.g. -0.30 means a 30 % drawdown.
    """
    rolling_peak = portfolio_value.cummax()
    drawdown = (portfolio_value - rolling_peak) / rolling_peak
    return drawdown.min()


def calmar_ratio(portfolio_value: pd.Series) -> float:
    """
    Calmar ratio = CAGR / abs(max drawdown).
    Values > 1.0 indicate strong risk-adjusted performance.
    """
    mdd = max_drawdown(portfolio_value)
    if mdd == 0:
        return np.inf
    return cagr(portfolio_value) / abs(mdd)


def win_rate(returns: pd.Series) -> float:
    """Fraction of trading days with positive return."""
    return (returns > 0).mean()


def average_monthly_return(returns: pd.Series) -> float:
    """
    Arithmetic average of month-end returns.
    """
    monthly = (1 + returns).resample("ME").prod() - 1
    return monthly.mean()


def value_at_risk(returns: pd.Series, confidence: float = 0.95) -> float:
    """
    Historical VaR at *confidence* level (e.g. 0.95 → 95 % VaR).

    Returns
    -------
    float
        Negative value representing the worst expected daily loss.
    """
    return np.percentile(returns, (1 - confidence) * 100)


def conditional_value_at_risk(returns: pd.Series, confidence: float = 0.95) -> float:
    """Expected shortfall (CVaR / ES) — average loss beyond VaR."""
    var = value_at_risk(returns, confidence)
    tail = returns[returns <= var]
    return tail.mean() if len(tail) > 0 else var


def summarise(
    portfolio_value: pd.Series,
    benchmark_value: pd.Series | None = None,
    risk_free_rate: float = 0.0,
) -> dict:
    """
    Compute a full set of performance metrics and return as a dictionary.

    Parameters
    ----------
    portfolio_value : pd.Series
        Daily strategy portfolio values.
    benchmark_value : pd.Series, optional
        Daily benchmark portfolio values for comparison.
    risk_free_rate : float
        Annual risk-free rate used for Sharpe / Sortino.

    Returns
    -------
    dict
    """
    returns = portfolio_value.pct_change().dropna()

    result = {
        "CAGR": cagr(portfolio_value),
        "Annual Volatility": annualised_volatility(returns),
        "Sharpe Ratio": sharpe_ratio(returns, risk_free_rate),
        "Sortino Ratio": sortino_ratio(returns, risk_free_rate),
        "Max Drawdown": max_drawdown(portfolio_value),
        "Calmar Ratio": calmar_ratio(portfolio_value),
        "Win Rate": win_rate(returns),
        "Avg Monthly Return": average_monthly_return(returns),
        "VaR (95%)": value_at_risk(returns, 0.95),
        "CVaR (95%)": conditional_value_at_risk(returns, 0.95),
        "Total Return": portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1,
    }

    if benchmark_value is not None:
        bench_ret = benchmark_value.pct_change().dropna()
        bench_ret, returns_aligned = bench_ret.align(returns, join="inner")

        # Alpha / Beta via OLS
        slope, intercept, *_ = stats.linregress(bench_ret, returns_aligned)
        rf_daily = (1 + risk_free_rate) ** (1 / 252) - 1
        alpha_annual = (intercept - rf_daily * (1 - slope)) * 252
        result["Beta"] = slope
        result["Alpha (annual)"] = alpha_annual
        result["Benchmark CAGR"] = cagr(benchmark_value)
        result["Benchmark Max DD"] = max_drawdown(benchmark_value)

    return result


def print_summary(metrics: dict) -> None:
    """Pretty-print the metrics dictionary."""
    print("\n" + "=" * 52)
    print("  Portfolio Performance Summary")
    print("=" * 52)
    fmts = {
        "CAGR": "{:.2%}",
        "Annual Volatility": "{:.2%}",
        "Sharpe Ratio": "{:.2f}",
        "Sortino Ratio": "{:.2f}",
        "Max Drawdown": "{:.2%}",
        "Calmar Ratio": "{:.2f}",
        "Win Rate": "{:.2%}",
        "Avg Monthly Return": "{:.2%}",
        "VaR (95%)": "{:.2%}",
        "CVaR (95%)": "{:.2%}",
        "Total Return": "{:.2%}",
        "Beta": "{:.2f}",
        "Alpha (annual)": "{:.2%}",
        "Benchmark CAGR": "{:.2%}",
        "Benchmark Max DD": "{:.2%}",
    }
    for k, v in metrics.items():
        fmt = fmts.get(k, "{}")
        try:
            print(f"  {k:<26} {fmt.format(v)}")
        except (ValueError, TypeError):
            print(f"  {k:<26} {v}")
    print("=" * 52 + "\n")
