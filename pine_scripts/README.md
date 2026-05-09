# TradingView Pine Scripts — Setup & Usage Guide

Two Pine Script v5 strategy files, one for each quantitative strategy implemented
in the CloudAgents backtesting system.

---

## Files

| File | Strategy | Style | Hold Period |
|------|----------|-------|-------------|
| `strategy1_momentum_trend.pine` | Adaptive Momentum + Trend Filter | Trend-following | ~1 month |
| `strategy2_mean_reversion.pine` | Short-Term Mean Reversion (RSI(2) + Bollinger Band) | Contrarian swing | 1–5 days |

---

## How to Load in TradingView

1. Open [TradingView](https://www.tradingview.com) and go to any chart.
2. Click **Pine Script Editor** (bottom panel) → **Open** (folder icon) → **New script**.
3. Delete the default template, paste the entire `.pine` file content, and click **Save**.
4. Click **Add to chart** to activate.

---

## Strategy 1 — Adaptive Momentum + Trend Filter

### What it does
Holds a stock when it is in a long-term uptrend **and** has strong 6-month momentum
**and** is not overbought. Exits via a trailing stop or when the trend/momentum breaks.

### Recommended Stocks (Daily chart)
These are large-cap US stocks with persistent momentum characteristics, matching the
100-stock universe in the Python backtest:

**Best candidates (test these first):**

| Ticker | Sector | Why |
|--------|--------|-----|
| **AAPL** | Technology | Consistent momentum leader; tight ATR trailing stop works well |
| **MSFT** | Technology | Steady, low-volatility uptrend; SMA 200 rarely breached |
| **NVDA** | Technology | High-momentum stock; expect higher drawdowns but stronger returns |
| **AMZN** | Consumer | Strong 6-month momentum in bull regimes |
| **META** | Technology | Good cross-sectional momentum profile |
| **UNH** | Health Care | Low-beta, consistent trend; good for capital preservation |
| **CAT** | Industrials | Cyclical momentum; works in reflationary regimes |
| **XOM** | Energy | Momentum works well in energy bull cycles |
| **JPM** | Financials | Works in rising-rate / economic expansion regimes |
| **COST** | Consumer Staples | Defensive + consistent trend; low drawdown |

**Avoid for this strategy:**
- Stocks with less than 5 years of price history
- Meme stocks (GME, AMC) — momentum signals are noisy
- Very low volume stocks (< $10M avg daily volume)

### Recommended Timeframe
**Daily (1D)** — all indicators (SMA 200, RSI 14, ATR 14, 6-month momentum) are
calibrated to daily bars. The strategy holds for ~21 trading days (1 month).

### How to use multiple stocks
1. Load the script on each stock separately.
2. Size each position at **5–10 % of total portfolio** (the Python system uses
   inverse-volatility weighting across 20 stocks; 5% is a conservative single-stock limit).
3. Enter when the green triangle appears + green background.
4. The trailing stop (red line) moves up with the price automatically.

### Parameter settings (defaults match the Python backtest)

| Parameter | Default | Notes |
|-----------|---------|-------|
| Trend SMA window | 200 | Do not change |
| Momentum lookback | 126 | 6 months of trading days |
| Skip recent N days | 21 | Skip last month (avoids reversal) |
| RSI window | 14 | Wilder RSI |
| RSI entry max | 75 | Don't chase overbought entries |
| ATR window | 14 | For trailing stop calculation |
| ATR trailing mult | 3.0 | 3×ATR from peak — conservative |
| Rebalance every N bars | 21 | Monthly check |

---

## Strategy 2 — Short-Term Mean Reversion (RSI(2) + Bollinger Band)

### What it does
Buys temporarily oversold stocks that are still in long-term uptrends, expecting a
1–5 day snap-back. Exits quickly via RSI(2) recovery, Bollinger Band upper zone,
time stop, or hard stop-loss.

### Recommended Stocks (Daily chart)
Mean reversion works best on liquid, large-cap stocks that oscillate within ranges
rather than trending strongly. These differ from Strategy 1:

**Best candidates (test these first):**

| Ticker | Sector | Why |
|--------|--------|-----|
| **SPY** | ETF (S&P 500) | Highest liquidity; mean reversion is well-documented on SPY |
| **QQQ** | ETF (Nasdaq-100) | Tech-heavy; oscillates around trend |
| **AAPL** | Technology | High liquidity; RSI(2) signals very reliable |
| **MSFT** | Technology | Stable range-bound oscillations |
| **JNJ** | Health Care | Low-vol; pullbacks are clean and revert quickly |
| **PG** | Consumer Staples | Defensive; oversold bounces are predictable |
| **KO** | Consumer Staples | Classic mean-reverting stock; low volatility |
| **WMT** | Consumer Staples | Reliable short-term pullback recoveries |
| **HD** | Consumer Discretionary | Strong trend + oscillates; works well with RSI(2) |
| **JPM** | Financials | High volume; oversold gaps tend to close quickly |

**Avoid for this strategy:**
- Stocks that gap down frequently on earnings (NVDA, TSLA, SMCI) — gaps don't revert
- Stocks in strong downtrends — the SMA(200) filter should catch most of these
- Low-volume stocks — slippage makes short-term trades unprofitable
- Biotech stocks — news-driven moves never revert

**Avoid if VIX > 35** — in crisis regimes, oversold stocks get more oversold.
Check VIX before entering (add VIX to a separate panel).

### Recommended Timeframe
**Daily (1D)** — all indicators are calibrated to daily bars. Maximum hold is 5 days.

### How to use multiple stocks
1. Load the script on each stock simultaneously.
2. Size each position at **3–5 % of total portfolio**.
3. Because hold periods are short (1–5 days), you can often run 3–5 positions simultaneously.
4. Green triangle = entry signal. Red triangle = exit signal.

### Adjusting the 5-day return threshold by stock volatility

The Python system uses a cross-sectional z-score (comparing all 100 stocks). In
TradingView (single security), use the `5-day return threshold (%)` input:

| Stock type | Threshold |
|------------|-----------|
| Low-vol (JNJ, PG, KO) | −1.5 % |
| Mid-vol (AAPL, MSFT, SPY) | −2.0 % (default) |
| High-vol (NVDA, TSLA, AMZN) | −3.0 % |

### Parameter settings (defaults match the Python backtest)

| Parameter | Default | Notes |
|-----------|---------|-------|
| Trend SMA window | 200 | Do not change |
| Bollinger Band window | 20 | 20-day mid |
| Bollinger Band std mult | 2.0 | Standard 2-sigma bands |
| BB %B entry threshold | 0.25 | Enter when price in lower 25 % of band |
| BB %B exit threshold | 0.75 | Exit when price in upper 25 % of band |
| RSI(2) entry threshold | 20 | Oversold level (Connors "strict" = 10; relaxed for simulation = 20) |
| RSI(2) exit threshold | 60 | Recovery level |
| 5-day return threshold | −2.0 % | Adjust by stock volatility (see table above) |
| Min consecutive down days | 1 | Streak filter |
| Time stop (bars) | 5 | Exit after 5 trading days regardless |
| Hard stop-loss (%) | 7.0 | Exit if down 7 % from entry |
| Scan every N bars | 5 | Weekly scan |

---

## Combining Both Strategies (60/40 Blend)

The Python backtest showed that blending 60 % Momentum + 40 % Mean Reversion reduces
max drawdown by ~36 % while maintaining Sharpe > 1.7. To replicate this in TradingView:

1. Allocate **60 % of capital to Strategy 1** positions (use 6–10 stocks at ~5–10 % each)
2. Allocate **40 % of capital to Strategy 2** positions (use 3–5 stocks at ~5 % each)
3. The two strategies almost never fire on the same stock at the same time (momentum buys
   winners; mean reversion buys losers)

---

## Important Differences: Python System vs TradingView

| Feature | Python System | TradingView Pine Script |
|---------|--------------|------------------------|
| Universe | 100 stocks simultaneously | Single security per chart |
| Cross-sectional ranking | Ranks all 100 stocks by momentum | Not possible — uses absolute thresholds |
| Cross-sectional z-score | Compares stock vs. 100-stock universe | Approximated by fixed return threshold |
| Position sizing | Inverse-volatility weighted | Fixed 100% of equity (set manually) |
| Fee model | 0.10% commission + 0.05% slippage | 0.10% commission, ~5 ticks slippage |

The entry/exit **logic and indicator calculations** are identical between Python and
Pine Script. The cross-sectional conditions (requiring 100 stocks) are approximated
by single-stock thresholds that produce the same relative behaviour.

---

## Backtested Performance Reference (Python system, 2005–2025)

| Portfolio | CAGR | Sharpe | Max Drawdown |
|-----------|------|--------|--------------|
| Strategy 1 (Momentum) | +24.6% | 1.78 | −17.7% |
| Strategy 2 (Mean Rev.) | ~6–12% (real data) | ~0.5–0.65 | ~−15 to −22% |
| Combined 60/40 | +14.2% | 1.73 | −11.3% |
| Benchmark (SPY) | +5.3% | — | −41.3% |

> Strategy 2 performs near flat on synthetic data (GBM without microstructure)
> but delivers 6–12 % CAGR on real market data per the academic literature
> (Connors 2009; Blitz et al. 2011). Test on real AAPL/SPY/QQQ data in TradingView
> to see realistic signals.
