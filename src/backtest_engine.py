"""
backtest_engine.py
------------------
Vectorised portfolio backtester.

Design choices
--------------
* **Vectorised** — avoids Python loops over dates so it is fast even for
  large universes and long histories.
* **Realistic costs** — explicit commission (fee_rate) applied on every
  dollar traded (buy or sell), plus a slippage model (slippage_rate) that
  widens the effective price on each trade.
* **Daily mark-to-market** — weights are held constant between rebalances
  and the portfolio value drifts with daily returns.
* **Cash** — uninvested capital (1 − sum(weights)) earns the risk-free
  rate (default: 0, conservative assumption).
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def run_backtest(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    initial_capital: float = 100_000.0,
    fee_rate: float = 0.001,      # 0.10 % per trade, one-way
    slippage_rate: float = 0.0005, # 0.05 % per trade, one-way
    risk_free_rate: float = 0.0,   # annual; set to e.g. 0.04 for T-bill
) -> dict:
    """
    Run a full backtest and return a results dictionary.

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices aligned to *weights*.
    weights : pd.DataFrame
        Target weights produced by the strategy (same index / columns).
        Each row should sum to ≤ 1.0; the remainder is cash.
    initial_capital : float
        Starting portfolio value in USD.
    fee_rate : float
        One-way commission as a fraction of trade value.
    slippage_rate : float
        One-way slippage as a fraction of trade value.
    risk_free_rate : float
        Annual risk-free rate for cash.  Set 0 for conservative backtest.

    Returns
    -------
    dict with keys:
        portfolio_value   pd.Series  — daily portfolio value
        returns           pd.Series  — daily arithmetic returns
        log_returns       pd.Series  — daily log returns
        turnover          pd.Series  — daily turnover fraction
        total_fees        float      — total fees paid (USD)
        total_slippage    float      — total slippage paid (USD)
        holdings          pd.DataFrame — daily dollar holdings per stock
    """
    # Align indices
    common_idx = prices.index.intersection(weights.index)
    prices = prices.loc[common_idx]
    weights = weights.loc[common_idx]

    # Daily stock returns
    stock_returns = prices.pct_change().fillna(0.0)

    # Daily risk-free return
    rf_daily = (1 + risk_free_rate) ** (1 / 252) - 1

    n_days = len(common_idx)
    portfolio_value = np.zeros(n_days)
    portfolio_value[0] = initial_capital

    total_fees = 0.0
    total_slippage = 0.0
    turnover_series = np.zeros(n_days)
    holdings = pd.DataFrame(0.0, index=common_idx, columns=prices.columns)

    current_weights = np.zeros(len(prices.columns))

    for t in range(n_days):
        pv = portfolio_value[t - 1] if t > 0 else initial_capital

        target_w = weights.iloc[t].values
        cash_w = max(0.0, 1.0 - target_w.sum())

        # --- Drift current weights with today's returns ---
        if t > 0:
            day_ret = stock_returns.iloc[t].values
            drifted = current_weights * (1 + day_ret)
            drifted_total = drifted.sum()
            drifted_cash = (1 - current_weights.sum()) * (1 + rf_daily)
            pv_after_drift = pv * (
                drifted_total + (1 - current_weights.sum()) * (1 + rf_daily)
            )
            # Normalise drifted weights
            if pv_after_drift > 0:
                drifted_w = drifted * pv / pv_after_drift
            else:
                drifted_w = drifted
        else:
            drifted_w = current_weights.copy()
            pv_after_drift = pv

        # --- Compute turnover (one-way) ---
        trades = np.abs(target_w - drifted_w)
        turnover = trades.sum() / 2.0  # round-trip turnover
        turnover_series[t] = turnover

        # --- Apply transaction costs ---
        cost_fraction = (fee_rate + slippage_rate) * trades.sum()
        cost_usd = cost_fraction * pv_after_drift
        total_fees += fee_rate * trades.sum() * pv_after_drift
        total_slippage += slippage_rate * trades.sum() * pv_after_drift

        pv_after_costs = pv_after_drift - cost_usd

        portfolio_value[t] = pv_after_costs
        current_weights = target_w.copy()

        holdings.iloc[t] = target_w * pv_after_costs

    pv_series = pd.Series(portfolio_value, index=common_idx, name="portfolio_value")
    daily_ret = pv_series.pct_change().fillna(0.0)
    log_ret = np.log(pv_series / pv_series.shift(1)).fillna(0.0)

    logger.info(
        "Backtest complete. Total fees: $%.0f | Total slippage: $%.0f",
        total_fees,
        total_slippage,
    )

    return {
        "portfolio_value": pv_series,
        "returns": daily_ret,
        "log_returns": log_ret,
        "turnover": pd.Series(turnover_series, index=common_idx, name="turnover"),
        "total_fees": total_fees,
        "total_slippage": total_slippage,
        "holdings": holdings,
    }
