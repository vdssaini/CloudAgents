"""
simulate_data.py
----------------
Generate realistic synthetic stock price data for strategy testing and
demonstration when live market data is unavailable.

The simulation uses a **one-factor market model** calibrated to historical
S&P 500 statistics:

    r_i(t) = α_i + β_i · r_m(t) + ε_i(t)

where
    r_m(t)  ~ N(μ_m, σ_m)        market daily log-return
    ε_i(t)  ~ N(α_i, σ_ε)        stock-specific (idiosyncratic) return
    β_i     ~ U(0.6, 1.4)         market sensitivity

This produces realistic cross-sectional correlations (~0.4–0.6) and a
distribution of stock CAGRs spanning roughly -5 % to +40 % p.a.,
with clear momentum cross-sectional dispersion.

References
----------
* Campbell, Lo & MacKinlay (1997), "The Econometrics of Financial Markets"
* Fama & French (1993), "Common risk factors in the returns on stocks and bonds"
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---- Calibrated parameters (matching 2010-2023 US large-cap universe) ----

MARKET_DAILY_DRIFT = 0.00040    # ≈ 10 % p.a.  (log-return)
MARKET_DAILY_VOL   = 0.0100     # ≈ 16 % ann. vol

STOCK_ALPHA_MEAN   = 0.00020    # cross-sectional average α ≈ 5 % p.a. extra
STOCK_ALPHA_STD    = 0.00060    # dispersion of α → some losers, some +40 % stocks
STOCK_IDIO_VOL     = 0.0085     # idiosyncratic daily vol
STOCK_BETA_LOW     = 0.60
STOCK_BETA_HIGH    = 1.40

# Tickers matching the DEFAULT_UNIVERSE in data_fetcher.py
SIMULATED_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "TXN", "AMAT", "KLAC", "LRCX",
    "AMZN", "TSLA", "HD",    "MCD",  "NKE",  "SBUX", "LOW",  "TJX",  "ROST", "BKNG",
    "JPM",  "BAC",  "WFC",   "GS",   "MS",   "BLK",  "AXP",  "USB",  "PNC",  "TFC",
    "JNJ",  "UNH",  "ABBV",  "PFE",  "TMO",  "ABT",  "MDT",  "DHR",  "BMY",  "AMGN",
    "CAT",  "HON",  "UNP",   "RTX",  "LMT",  "DE",   "EMR",  "ITW",  "ETN",  "FDX",
    "PG",   "KO",   "PEP",   "WMT",  "COST", "XOM",  "CVX",  "COP",  "NEE",  "DUK",
]


def simulate_prices(
    tickers: list[str] = SIMULATED_TICKERS,
    start: str = "2013-01-01",
    end: str | None = None,
    seed: int = 2024,
) -> pd.DataFrame:
    """
    Generate synthetic adjusted-close prices for a cross-section of stocks.

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols (used as column names only).
    start : str
        Start date in "YYYY-MM-DD" format.
    end : str or None
        End date (inclusive).  Defaults to today.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        Rows = business dates, columns = tickers.
        Prices start at 100.0 for every ticker.
    """
    rng = np.random.default_rng(seed)
    n_tickers = len(tickers)

    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    dates = pd.bdate_range(start=start, end=end)
    n_days = len(dates)

    # ---- Market factor ----
    market_ret = rng.normal(MARKET_DAILY_DRIFT, MARKET_DAILY_VOL, size=n_days)

    # ---- Per-stock parameters (fixed across time) ----
    alphas = rng.normal(STOCK_ALPHA_MEAN, STOCK_ALPHA_STD, size=n_tickers)
    betas  = rng.uniform(STOCK_BETA_LOW, STOCK_BETA_HIGH, size=n_tickers)

    # ---- Idiosyncratic returns ----
    idio = rng.normal(0.0, STOCK_IDIO_VOL, size=(n_days, n_tickers))

    # ---- Combine: r_i = α_i + β_i·r_m + ε_i ----
    log_returns = alphas[np.newaxis, :] + betas[np.newaxis, :] * market_ret[:, np.newaxis] + idio

    # ---- Convert to price levels (start at 100) ----
    prices = 100.0 * np.exp(np.cumsum(log_returns, axis=0))

    df = pd.DataFrame(prices, index=dates, columns=tickers)
    return df


def simulate_benchmark(start: str = "2013-01-01", end: str | None = None, seed: int = 2024) -> pd.DataFrame:
    """
    Simulate a market-cap-weighted benchmark (like SPY).

    Returns
    -------
    pd.DataFrame with a single column "SPY".
    """
    rng = np.random.default_rng(seed + 999)
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")
    dates = pd.bdate_range(start=start, end=end)
    n_days = len(dates)
    log_ret = rng.normal(MARKET_DAILY_DRIFT, MARKET_DAILY_VOL, size=n_days)
    prices = 100.0 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame({"SPY": prices}, index=dates)
