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


# ---------------------------------------------------------------------------
# Additional indicators for Mean-Reversion Strategy
# ---------------------------------------------------------------------------

def rsi_fast(prices: pd.DataFrame, window: int = 2) -> pd.DataFrame:
    """
    Fast RSI using *simple* (not EMA) moving averages over *window* periods.

    Connors & Alvarez (2009) use RSI(2) with a simple rolling average rather
    than Wilder's EMA to make the indicator more reactive to very recent price
    changes.  This is the standard practitioner implementation of RSI(2).

    When average loss is zero (pure uptrend), RSI returns 100.
    """
    delta    = prices.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window, min_periods=window).mean()
    avg_loss = loss.rolling(window, min_periods=window).mean()

    # When avg_loss = 0 but avg_gain > 0 → RSI = 100 (pure uptrend)
    # When both = 0 → NaN (no data / flat period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))

    # Fill RSI = 100 where gains exist but losses are zero
    pure_up = (avg_loss == 0) & (avg_gain > 0)
    result  = result.where(~pure_up, 100.0)
    return result


def bollinger_pct_b(
    prices: pd.DataFrame, window: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """
    Bollinger Band %B indicator.

    %B = (Price − Lower Band) / (Upper Band − Lower Band)

    * %B = 0  → price is at the lower band (2σ below the mean)
    * %B = 1  → price is at the upper band (2σ above the mean)
    * %B < 0.2 → oversold signal used by the mean-reversion strategy

    References
    ----------
    * Bollinger, J. (2002), "Bollinger on Bollinger Bands"
    """
    mid = prices.rolling(window, min_periods=window).mean()
    std = prices.rolling(window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    band_width = (upper - lower).replace(0, np.nan)
    return (prices - lower) / band_width


def consecutive_down_days(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Count of consecutive calendar days with a declining close.

    Returns an integer DataFrame with the same shape as *prices*.
    A value of 3 means the stock closed lower three days in a row.
    The count resets to 0 on any up day.

    This is vectorised: no Python loops over rows.
    """
    is_down = (prices.diff() < 0).astype(int)
    # Cumulative sum that resets to 0 on an up day
    # Standard trick: group by cumsum of non-down days
    result = pd.DataFrame(0, index=prices.index, columns=prices.columns)
    for col in prices.columns:
        col_down = is_down[col]
        streak_id = (~col_down.astype(bool)).cumsum()
        result[col] = col_down.groupby(streak_id).cumsum()
    return result


def nday_return_zscore(
    prices: pd.DataFrame, lookback: int = 5
) -> pd.DataFrame:
    """
    Cross-sectional z-score of the n-day price return.

    Used by the mean-reversion strategy to identify stocks that have
    underperformed their peers over the very short term.

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices.
    lookback : int
        Number of trading days for the return window.

    Returns
    -------
    pd.DataFrame
        Cross-sectionally standardised n-day returns (z-scores).
    """
    nday_ret = np.log(prices / prices.shift(lookback))
    return cross_sectional_zscore(nday_ret)


# ---------------------------------------------------------------------------
# Additional indicators for Dual Momentum + Quality Strategy (Strategy 4)
# ---------------------------------------------------------------------------

def absolute_momentum(prices: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    """
    Absolute (time-series) momentum over *lookback* trading days.

    Returns the log-return of each stock over the lookback period.
    Positive values indicate the stock beat cash (zero-return proxy).

    Antonacci (2014) "Dual Momentum Investing" uses 12-month (252 trading day)
    absolute momentum as a filter: only hold a stock if its absolute momentum
    is positive, otherwise hold cash.  This is the mechanism that avoids bear
    markets — both the 2008 crash and COVID crash had deeply negative 12-month
    absolute momentum for most stocks before the worst losses occurred.

    Academic basis: Antonacci, G. (2014) "Dual Momentum Investing"

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices.
    lookback : int
        Look-back window in trading days. Default: 252 (~12 months).

    Returns
    -------
    pd.DataFrame
        Log-return over the lookback period (same shape as *prices*).
    """
    return np.log(prices / prices.shift(lookback))


def high_52w_ratio(prices: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """
    Ratio of current price to the rolling *window*-day high.

    George & Hwang (2004) "The 52-Week High and Momentum Investing" show that
    stocks trading near their 52-week high outperform significantly over the
    next 6–12 months.  The anchoring explanation: investors are reluctant to
    push the stock past a psychological resistance level near the 52-week high,
    creating a short-term underreaction that subsequently corrects.

    * Ratio = 1.0 → price is exactly at the 52-week high
    * Ratio = 0.75 → price is 25% below the 52-week high (less bullish)

    Academic basis: George, T. & Hwang, C.Y. (2004) "The 52-Week High and
    Momentum Investing", Journal of Finance.

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices.
    window : int
        Rolling window in trading days. Default: 252 (~52 weeks).

    Returns
    -------
    pd.DataFrame
        Price / rolling_high ratio in [0, 1].
    """
    # Require at least 1 quarter (63 trading days) of data before producing a
    # signal — this prevents noisy ratios based on only a few bars while still
    # allowing earlier signals than waiting for the full 252-day window.
    _MIN_PERIODS = max(63, window // 4)
    rolling_high = prices.rolling(window, min_periods=_MIN_PERIODS).max()
    return (prices / rolling_high).clip(upper=1.0)
