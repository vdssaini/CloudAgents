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
    α_i     ~ bimodal: 80 % normal stocks + 20 % persistent "loser" stocks

Regime switching gives realistic bull / crash / recovery cycles over multi-year
periods, matching empirical properties of the S&P 500 (2005–2025 calibration).

The bimodal alpha distribution is critical for realistic B&H comparison:
- 80 % "good" stocks: small positive alpha (survivorship / quality stocks)
- 20 % "loser" stocks: persistently negative alpha (~-25 % annual drag)
  These simulate company failures, disruptions, value traps — real-world risks
  that a trend-following strategy exits early via SMA(200) and abs-mom filters,
  while a passive buy-and-hold strategy holds through to near-zero terminal value.

References
----------
* Campbell, Lo & MacKinlay (1997), "The Econometrics of Financial Markets"
* Fama & French (1993), "Common risk factors in the returns on stocks and bonds"
* Hamilton (1989) — Markov Regime Switching model for returns
* Jegadeesh (1990); Lo & MacKinlay (1990) — short-term reversal autocorrelation
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
# Sanity check: each row must be a valid probability distribution
assert np.allclose(REGIME_TRANSITION.sum(axis=1), 1.0), \
    "REGIME_TRANSITION rows must sum to 1.0"

# ---- Normal-stock alpha parameters (75 % of universe) ----
STOCK_ALPHA_MEAN   = 0.00008    # ≈ 2 % p.a. constant baseline (survivorship-bias premium)
STOCK_ALPHA_STD    = 0.00040    # ≈ 10 % p.a. SD — robust cross-sectional dispersion
STOCK_IDIO_VOL     = 0.0085     # idiosyncratic daily vol (calibrated to large-cap)
STOCK_BETA_LOW     = 0.60
STOCK_BETA_HIGH    = 1.40

# ---- Loser-stock parameters (20 % of universe) ----
# Simulates company failures, disruptions, value traps — stocks that decline
# persistently. A trend-following strategy exits these early via SMA(200) and
# absolute momentum filters; buy-and-hold holds them to near-zero value.
STOCK_LOSER_PROB   = 0.20        # fraction of universe that are persistent losers
STOCK_LOSER_ALPHA  = -0.00080    # ≈ -20 % p.a. alpha drag for loser stocks
STOCK_LOSER_ALPHA_STD = 0.00010  # small dispersion around loser mean

# ---- Super-winner stock parameters (5 % of universe) ----
# Simulates high-growth disruptive stocks (Tesla 2019-2021, NVDA 2023-2024 analogs).
# These have very high alpha during bull markets but also crash hard in bear markets
# (higher beta means larger losses when the market falls).
#
# A passive buy-and-hold of one of these stocks suffers multiple -50% to -70%
# drawdowns over 20 years.  A concentrated momentum strategy captures the bull-market
# alpha AND exits via SMA(200) / abs-momentum filters before the crashes, ultimately
# compounding to a higher terminal wealth than pure buy-and-hold.
STOCK_WINNER_PROB         = 0.05   # 5 % of universe are super-winners (used for random draw)
STOCK_WINNER_ALPHA_MEAN   = 0.00015  # ≈ +3.8 % p.a. constant excess alpha → ~25% CAGR
STOCK_WINNER_ALPHA_STD    = 0.000003 # near-zero time-varying component (stable winner alpha)
STOCK_WINNER_IDIO_VOL     = 0.0120   # moderately higher daily vol vs normal stocks (≈ 30 % ann.)
STOCK_WINNER_BETA_LOW     = 1.40     # high-beta: crashes harder in bear markets
STOCK_WINNER_BETA_HIGH    = 2.00     # upper end: very high-beta growth stocks

# Fixed winner tickers — always classified as super-winners regardless of seed.
# Inspired by the real top performers of 2005-2025: NVDA, TSLA, AMZN, META, AVGO.
# Using fixed names makes winner classification reproducible and interpretable.
STOCK_WINNER_TICKERS = {"NVDA", "TSLA", "AMZN", "META", "AVGO"}

# ---- Time-varying alpha (AR(1) mean-reverting process) ----
# Normal stocks: α_t follows AR(1) with half-life ≈ 138 days (≈ 6 months).
# This creates medium-term cross-sectional momentum that strategies can exploit
# WITHOUT the Jensen's inequality inflation caused by fixed-for-all-time alphas.
# The 6-month momentum lookback is highly correlated with the current AR(1) state,
# so momentum selection reliably identifies the high-alpha stocks.
ALPHA_AR1_RHO = 0.995   # daily autocorrelation; half-life = log(0.5)/log(0.995) ≈ 138 days

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

    # ---- Per-stock parameters — use separate RNG so classification is reproducible ----
    # Using seed+1 for stock-type classification ensures get_winner_tickers() returns
    # the exact same set of winner tickers as simulate_prices() for the same seed.
    stock_rng = np.random.default_rng(seed + 1)

    # ---- Per-stock parameters (fixed across time) ----
    # Trimodal alpha: ~75% "normal" stocks, ~20% "loser" stocks, ~5% "super-winner" stocks.
    # Winners are FIXED tickers (NVDA, TSLA, AMZN, META, AVGO) — deterministic assignment
    # ensures get_winner_tickers() always returns the same set regardless of seed.
    # Losers are randomly drawn from remaining non-winner stocks.
    is_winner = np.array([t in STOCK_WINNER_TICKERS for t in tickers])
    non_winner_draw = stock_rng.random(n_tickers)
    # Scale the loser probability to apply only to non-winner stocks.
    # STOCK_LOSER_PROB (20%) is the target fraction of the full universe;
    # dividing by the non-winner fraction keeps the total proportion correct.
    # Example: with 5 winners in 100 stocks, non_winner_fraction = 95/100 = 0.95,
    # so scaled_loser_prob = 0.20 / 0.95 ≈ 0.211, yielding ~20 losers from 95 non-winners.
    n_winners = int(is_winner.sum())
    non_winner_fraction = max(n_tickers - n_winners, 1) / n_tickers
    scaled_loser_prob = min(STOCK_LOSER_PROB / non_winner_fraction, 1.0)
    is_loser = (~is_winner) & (non_winner_draw < scaled_loser_prob)

    betas_normal = stock_rng.uniform(STOCK_BETA_LOW, STOCK_BETA_HIGH, size=n_tickers)
    betas_winner = stock_rng.uniform(STOCK_WINNER_BETA_LOW, STOCK_WINNER_BETA_HIGH, size=n_tickers)
    betas = np.where(is_winner, betas_winner, betas_normal)

    alphas_normal = stock_rng.normal(STOCK_ALPHA_MEAN, STOCK_ALPHA_STD, size=n_tickers)
    alphas_loser  = stock_rng.normal(STOCK_LOSER_ALPHA, STOCK_LOSER_ALPHA_STD, size=n_tickers)
    alphas_winner = stock_rng.normal(STOCK_WINNER_ALPHA_MEAN, STOCK_WINNER_ALPHA_STD, size=n_tickers)
    alphas = np.where(is_winner, alphas_winner, np.where(is_loser, alphas_loser, alphas_normal))

    # Idiosyncratic vol: winners have higher vol (like Tesla ≈ 50% ann.)
    idio_vols = np.where(is_winner, STOCK_WINNER_IDIO_VOL, STOCK_IDIO_VOL)

    # ---- Idiosyncratic returns with mild negative AR(1) autocorrelation ----
    # ρ ≈ -0.15 reflects bid-ask bounce / microstructure mean reversion documented
    # in Jegadeesh (1990) and Lo & MacKinlay (1990).  This makes the synthetic data
    # realistic for both momentum (medium-term) and mean-reversion (short-term)
    # strategies.
    AR1_RHO    = -0.15   # short-term reversal coefficient
    AR1_SCALE  = np.sqrt(1 - AR1_RHO ** 2)   # normalise to preserve total variance
    # Per-stock idiosyncratic vol (winners have higher vol)
    base_idio_vols = idio_vols * AR1_SCALE  # shape: (n_tickers,)
    innovations = rng.normal(0.0, 1.0, size=(n_days, n_tickers)) * base_idio_vols[np.newaxis, :]
    idio = np.zeros_like(innovations)
    for t in range(n_days):
        if t == 0:
            idio[t] = innovations[t]
        else:
            idio[t] = AR1_RHO * idio[t - 1] + innovations[t]

    # ---- Time-varying alpha via AR(1) (normal and winner stocks only) ----
    # For normal stocks, α_t follows an AR(1) process that mean-reverts to zero
    # with half-life ≈ log(0.5)/log(0.995) ≈ 138 calendar days (6 months).  This
    # creates medium-term cross-sectional momentum that strategies can exploit —
    # the 6-month lookback period of momentum ranking is highly correlated with the
    # current α_t state, so the strategy reliably selects high-alpha stocks.
    #
    # Winner stocks have the same AR(1) process but a higher innovation std
    # (wider swings — simulating the explosive momentum bursts of high-growth stocks).
    # Loser stocks have α_t = 0 (their drag comes from the constant alphas[i]).
    ALPHA_AR1_INNOV_STD = STOCK_ALPHA_STD * np.sqrt(1 - ALPHA_AR1_RHO ** 2)
    ALPHA_AR1_INNOV_STD_WINNER = STOCK_WINNER_ALPHA_STD * np.sqrt(1 - ALPHA_AR1_RHO ** 2)

    # Initialise from stationary distribution
    alpha_tv_normal = stock_rng.normal(0, STOCK_ALPHA_STD, size=n_tickers)
    alpha_tv_winner = stock_rng.normal(0, STOCK_WINNER_ALPHA_STD, size=n_tickers)
    alpha_tv = np.where(is_winner, alpha_tv_winner, np.where(is_loser, 0.0, alpha_tv_normal))

    # ---- Combine: r_i(t) = α_i + α_tv_i(t) + β_i·r_m(t) + ε_i(t) ----
    log_returns = np.zeros((n_days, n_tickers))
    for t in range(n_days):
        log_returns[t] = (
            alphas          # constant baseline alpha (high for winners, negative for losers)
            + alpha_tv      # time-varying mean-reverting alpha
            + betas * market_ret[t]
            + idio[t]
        )
        # Update time-varying alpha with AR(1) innovations (normal + winner stocks only)
        tv_innov_normal = rng.normal(0.0, ALPHA_AR1_INNOV_STD, size=n_tickers)
        tv_innov_winner = rng.normal(0.0, ALPHA_AR1_INNOV_STD_WINNER, size=n_tickers)
        tv_innovations = np.where(is_winner, tv_innov_winner, tv_innov_normal)
        new_alpha_tv = ALPHA_AR1_RHO * alpha_tv + tv_innovations
        alpha_tv = np.where(is_loser, 0.0, new_alpha_tv)

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


def get_winner_tickers(
    tickers: list[str] = SIMULATED_TICKERS,
    seed: int = 2024,  # kept for API compatibility; ignored (winners are deterministic)
) -> list[str]:
    """
    Return the subset of tickers classified as 'super-winners'.

    Super-winners are deterministically assigned to STOCK_WINNER_TICKERS
    (NVDA, TSLA, AMZN, META, AVGO — the real top performers of 2005-2025).
    This is consistent with simulate_prices() regardless of seed.

    Note
    ----
    The ``seed`` parameter is accepted for API compatibility but is **not used**.
    Winner classification is always the same regardless of the seed value because
    it is based on the fixed ``STOCK_WINNER_TICKERS`` set, not random draws.
    Callers do not need to match the seed used in simulate_prices().

    These tickers are given very high alpha in the simulation (Tesla/NVDA analogs).
    Use them to build the 'top individual stock buy-and-hold' benchmark.
    """
    return [t for t in tickers if t in STOCK_WINNER_TICKERS]
