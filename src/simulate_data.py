"""
simulate_data.py
----------------
Generate realistic synthetic stock price data for strategy testing and
demonstration when live market data is unavailable.

The simulation uses a **two-factor market + regime model** calibrated to
historical S&P 500 statistics:

    r_i(t) = α_i + β_i · r_m(t) + ε_i(t)

where
    r_m(t)  ~ regime-switching N(μ, σ)   market daily log-return
    ε_i(t)  ~ N(0, σ_ε)                  stock-specific (idiosyncratic) return
    β_i     ~ U(0.6, 1.4)                 market sensitivity

Regime switching gives realistic bull / crash / recovery cycles over multi-year
periods, matching empirical properties of the S&P 500 (2005–2025 calibration).

References
----------
* Campbell, Lo & MacKinlay (1997), "The Econometrics of Financial Markets"
* Fama & French (1993), "Common risk factors in the returns on stocks and bonds"
* Hamilton (1989) — Markov Regime Switching model for returns
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---- Calibrated parameters (matching 2005-2025 US large-cap universe) ----

# Regime 0: Normal / Bull market
REGIME_BULL_DRIFT = 0.00060    # ≈ 15 % p.a.
REGIME_BULL_VOL   = 0.0085     # ≈ 13 % ann. vol

# Regime 1: Bear / Crisis market  (2008-type, COVID)
REGIME_BEAR_DRIFT = -0.00150   # ≈ -30 % p.a.
REGIME_BEAR_VOL   = 0.0220     # ≈ 35 % ann. vol

# Regime 2: Sideways / Volatile (2015-style, high vol, no trend)
REGIME_CHOP_DRIFT = 0.00010    # ≈ 2.5 % p.a.
REGIME_CHOP_VOL   = 0.0130     # ≈ 21 % ann. vol

# Regime transition probabilities (Markov chain)
# From Bull → [Bull, Bear, Chop]
REGIME_TRANSITION = np.array([
    [0.990, 0.005, 0.005],   # Bull is sticky; small crash probability
    [0.050, 0.930, 0.020],   # Bear lasts ~20 days on avg then recovers
    [0.020, 0.010, 0.970],   # Chop is moderately sticky
])

STOCK_ALPHA_MEAN   = 0.00020    # cross-sectional average α ≈ 5 % p.a. extra
STOCK_ALPHA_STD    = 0.00060    # dispersion → some losers, some 40 % p.a. winners
STOCK_IDIO_VOL     = 0.0090     # idiosyncratic daily vol (higher for realism)
STOCK_BETA_LOW     = 0.60
STOCK_BETA_HIGH    = 1.40

# 100-ticker extended universe (large-cap US + mid-cap mix for richer cross-section)
SIMULATED_TICKERS = [
    # Technology (20)
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "TXN", "AMAT", "KLAC", "LRCX",
    "ORCL", "CRM",  "ADBE",  "INTC", "QCOM", "AMD",  "MU",  "SNPS", "CDNS", "ANSS",
    # Consumer Discretionary (15)
    "AMZN", "TSLA", "HD",    "MCD",  "NKE",  "SBUX", "LOW",  "TJX",  "ROST", "BKNG",
    "YUM",  "DHI",  "LEN",   "PHM",  "NVR",
    # Financials (15)
    "JPM",  "BAC",  "WFC",   "GS",   "MS",   "BLK",  "AXP",  "USB",  "PNC",  "TFC",
    "CME",  "ICE",  "SCHW",  "MET",  "PRU",
    # Health Care (15)
    "JNJ",  "UNH",  "ABBV",  "PFE",  "TMO",  "ABT",  "MDT",  "DHR",  "BMY",  "AMGN",
    "GILD", "CVS",  "CI",    "HUM",  "ISRG",
    # Industrials (15)
    "CAT",  "HON",  "UNP",   "RTX",  "LMT",  "DE",   "EMR",  "ITW",  "ETN",  "FDX",
    "NSC",  "CSX",  "GE",    "MMM",  "ROK",
    # Consumer Staples / Energy / Utilities / Materials (20)
    "PG",   "KO",   "PEP",   "WMT",  "COST", "XOM",  "CVX",  "COP",  "NEE",  "DUK",
    "MO",   "PM",   "EL",    "CL",   "KMB",  "ECL",  "SHW",  "NUE",  "FCX",  "LIN",
]


def _generate_regime_sequence(n_days: int, seed_rng: np.random.Generator) -> np.ndarray:
    """Generate a sequence of regime states via a Markov chain."""
    states = np.zeros(n_days, dtype=int)
    states[0] = 0  # start in Bull
    for t in range(1, n_days):
        probs = REGIME_TRANSITION[states[t - 1]]
        states[t] = seed_rng.choice(3, p=probs)
    return states


def simulate_prices(
    tickers: list[str] = SIMULATED_TICKERS,
    start: str = "2005-01-01",
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
        Start date in "YYYY-MM-DD" format.  Default covers 20 years.
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

    # ---- Regime sequence ----
    regimes = _generate_regime_sequence(n_days, rng)

    drift_vec = np.where(
        regimes == 0, REGIME_BULL_DRIFT,
        np.where(regimes == 1, REGIME_BEAR_DRIFT, REGIME_CHOP_DRIFT),
    )
    vol_vec = np.where(
        regimes == 0, REGIME_BULL_VOL,
        np.where(regimes == 1, REGIME_BEAR_VOL, REGIME_CHOP_VOL),
    )

    # ---- Market factor returns ----
    market_ret = rng.normal(drift_vec, vol_vec)

    # ---- Per-stock parameters (fixed across time) ----
    alphas = rng.normal(STOCK_ALPHA_MEAN, STOCK_ALPHA_STD, size=n_tickers)
    betas  = rng.uniform(STOCK_BETA_LOW, STOCK_BETA_HIGH, size=n_tickers)

    # ---- Idiosyncratic returns with mild negative AR(1) autocorrelation ----
    # ρ ≈ -0.15 reflects bid-ask bounce / microstructure mean reversion documented
    # in Jegadeesh (1990) and Lo & MacKinlay (1990).  This makes the synthetic data
    # realistic for both momentum (medium-term) and mean-reversion (short-term)
    # strategies.
    AR1_RHO    = -0.15   # short-term reversal coefficient
    AR1_SCALE  = np.sqrt(1 - AR1_RHO ** 2)   # normalise to preserve total variance
    innovations = rng.normal(0.0, STOCK_IDIO_VOL * AR1_SCALE, size=(n_days, n_tickers))
    idio = np.zeros_like(innovations)
    for t in range(n_days):
        if t == 0:
            idio[t] = innovations[t]
        else:
            idio[t] = AR1_RHO * idio[t - 1] + innovations[t]

    # ---- Combine: r_i = α_i + β_i·r_m + ε_i ----
    log_returns = (
        alphas[np.newaxis, :]
        + betas[np.newaxis, :] * market_ret[:, np.newaxis]
        + idio
    )

    # ---- Convert to price levels (start at 100) ----
    prices = 100.0 * np.exp(np.cumsum(log_returns, axis=0))

    return pd.DataFrame(prices, index=dates, columns=tickers)


def simulate_benchmark(
    start: str = "2005-01-01",
    end: str | None = None,
    seed: int = 2024,
) -> pd.DataFrame:
    """
    Simulate a market-cap-weighted benchmark (like SPY) using the same
    regime model as simulate_prices.

    Returns
    -------
    pd.DataFrame with a single column "SPY".
    """
    rng = np.random.default_rng(seed + 999)
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    dates = pd.bdate_range(start=start, end=end)
    n_days = len(dates)

    regimes = _generate_regime_sequence(n_days, rng)
    drift_vec = np.where(
        regimes == 0, REGIME_BULL_DRIFT,
        np.where(regimes == 1, REGIME_BEAR_DRIFT, REGIME_CHOP_DRIFT),
    )
    vol_vec = np.where(
        regimes == 0, REGIME_BULL_VOL,
        np.where(regimes == 1, REGIME_BEAR_VOL, REGIME_CHOP_VOL),
    )
    log_ret = rng.normal(drift_vec, vol_vec)
    prices = 100.0 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame({"SPY": prices}, index=dates)
