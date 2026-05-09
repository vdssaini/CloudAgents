"""
indicators.py
-------------
Vectorised technical indicators used by the strategy.
All functions operate on pandas DataFrames/Series and return the same type.
"""

import numpy as np
import pandas as pd


def sma(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Simple Moving Average."""
    return prices.rolling(window, min_periods=window).mean()


def ema(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Exponential Moving Average (span = window)."""
    return prices.ewm(span=window, min_periods=window, adjust=False).mean()


def rsi(prices: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """
    Relative Strength Index (Wilder / EMA smoothing).
    Returns values in [0, 100].
    """
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(prices: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """
    Average True Range — requires a DataFrame with columns
    ['High', 'Low', 'Close'] *or* a plain close-price DataFrame
    (in which case we proxy ATR with rolling std of returns × price).
    """
    if isinstance(prices, pd.DataFrame) and {"High", "Low", "Close"}.issubset(
        prices.columns
    ):
        prev_close = prices["Close"].shift(1)
        tr = pd.concat(
            [
                prices["High"] - prices["Low"],
                (prices["High"] - prev_close).abs(),
                (prices["Low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    # Fallback: volatility proxy for plain close DataFrames
    log_ret = np.log(prices / prices.shift(1))
    vol = log_ret.rolling(window, min_periods=window).std()
    return vol * prices  # price × daily vol ≈ ATR


def momentum(prices: pd.DataFrame, lookback: int = 126) -> pd.DataFrame:
    """
    Price momentum: total log-return over *lookback* trading days,
    skipping the most recent month (21 days) to avoid short-term reversal.

    Computed as log(P[t-21] / P[t-lookback-21]), which is the log-return
    from (lookback+21) days ago to 21 days ago.
    """
    return np.log(prices.shift(21) / prices.shift(lookback + 21))


def cross_sectional_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """Standardise each row so scores are comparable across stocks."""
    mean = df.mean(axis=1)
    std = df.std(axis=1).replace(0, np.nan)
    return df.sub(mean, axis=0).div(std, axis=0)
