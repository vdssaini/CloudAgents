"""
data_fetcher.py
---------------
Downloads and caches historical adjusted-close price data from Yahoo Finance.
All prices are split- and dividend-adjusted so that momentum and return
calculations remain economically meaningful.
"""

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# A curated universe of 60 large-cap US stocks spread across sectors.
# These all have sufficient history (15+ years) for a robust backtest.
DEFAULT_UNIVERSE = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "TXN", "AMAT", "KLAC", "LRCX",
    # Consumer Discretionary
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "ROST", "BKNG",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "AXP", "USB", "PNC", "TFC",
    # Health Care
    "JNJ", "UNH", "ABBV", "PFE", "TMO", "ABT", "MDT", "DHR", "BMY", "AMGN",
    # Industrials
    "CAT", "HON", "UNP", "RTX", "LMT", "DE", "EMR", "ITW", "ETN", "FDX",
    # Consumer Staples / Energy / Utilities
    "PG", "KO", "PEP", "WMT", "COST", "XOM", "CVX", "COP", "NEE", "DUK",
]


def fetch_prices(
    tickers: list[str] = DEFAULT_UNIVERSE,
    start: str = "2010-01-01",
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Download adjusted close prices for *tickers* between *start* and *end*.

    Returns
    -------
    pd.DataFrame
        Rows = trading dates, columns = ticker symbols.
        Columns with > 5 % missing data are dropped.
    """
    logger.info("Downloading price data for %d tickers …", len(tickers))
    raw = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
    )

    # yfinance returns multi-level columns when len(tickers) > 1
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        # Single ticker — wrap in a DataFrame
        prices = raw[["Close"]].copy()
        prices.columns = [tickers[0]]

    # Drop tickers with excessive missing data
    threshold = 0.05 * len(prices)
    prices = prices.dropna(axis=1, thresh=int(len(prices) - threshold))

    # Forward-fill occasional missing trading days (e.g. halted sessions)
    prices = prices.ffill().dropna()

    logger.info(
        "Price data ready: %d dates × %d tickers", len(prices), prices.shape[1]
    )
    return prices
