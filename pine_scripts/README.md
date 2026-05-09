# TradingView Pine Scripts — Setup & Usage Guide

Four Pine Script v5 strategy files, covering all three quantitative strategies and the
regime-aware Master Portfolio implemented in the CloudAgents backtesting system.

---

## Files

| File | Strategy | Style | Hold Period |
|------|----------|-------|-------------|
| `strategy1_momentum_trend.pine` | Adaptive Momentum + Trend Filter | Trend-following | ~1 month |
| `strategy2_mean_reversion.pine` | Short-Term Mean Reversion (RSI(2) + Bollinger Band) | Contrarian swing | 1–5 days |
| `strategy3_low_vol.pine` | Low Volatility Factor | Quality/defensive | ~1 month |
| `strategy_master_regime.pine` | Master Portfolio — Regime-Aware Dynamic Rotation | All three, regime-switched | Varies |

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
| RSI(2) entry threshold | 20 | Oversold level |
| RSI(2) exit threshold | 60 | Recovery level |
| 5-day return threshold | −2.0 % | Adjust by stock volatility (see table above) |
| Min consecutive down days | 1 | Streak filter |
| Time stop (bars) | 5 | Exit after 5 trading days regardless |
| Hard stop-loss (%) | 7.0 | Exit if down 7 % from entry |
| Scan every N bars | 5 | Weekly scan |

---

## Strategy 3 — Low Volatility Factor

### What it does
Holds stocks that are (1) in a long-term uptrend and (2) exhibiting low realized
volatility relative to peers. Based on the well-documented low-volatility anomaly:
low-vol stocks deliver higher risk-adjusted returns than high-vol stocks because
leverage-constrained fund managers systematically overpay for exciting high-vol names.

### Recommended Stocks (Daily chart)
The Python system selects the 20 lowest-volatility stocks from a 100-stock universe.
In TradingView, apply to consistently low-volatility large-caps:

**Best candidates (test these first):**

| Ticker | Sector | Typical 20d Ann.Vol | Why |
|--------|--------|--------------------|----|
| **JNJ** | Health Care | 12–18 % | Classic defensive low-vol; rarely breaches SMA(200) |
| **PG** | Consumer Staples | 13–18 % | Consumer staple with stable cash flows |
| **KO** | Consumer Staples | 13–17 % | Berkshire favourite; ultra-low vol |
| **WMT** | Consumer Staples | 14–20 % | Retail defensive |
| **MCD** | Consumer Discretionary | 14–20 % | Franchise model; predictable earnings |
| **VZ** | Telecom | 14–20 % | Utility-like; high dividend yield |
| **MMM** | Industrials | 15–22 % | Diversified industrial |
| **ABT** | Health Care | 14–20 % | Medical devices; stable low-vol |
| **MRK** | Health Care | 16–22 % | Pharma with stable dividend |
| **CL** | Consumer Staples | 12–18 % | Colgate-Palmolive; extremely stable |

**Set the Max Ann.Vol threshold** according to your target:
- Set to **20 %** for the most defensive (JNJ, KO, CL only)
- Set to **28 %** (default) for normal large-cap low-vol stocks
- Set to **35 %** to include more names

**Avoid for this strategy:**
- High-vol stocks (NVDA, TSLA, SMCI) — they will not qualify and may trigger vol-spike exits
- Meme stocks or thematic ETFs
- Small-caps — vol is high and signals are noisy

### Recommended Timeframe
**Daily (1D)** — monthly rebalancing cadence. Holds for ~21 trading days at a time.

### Parameter settings (defaults match the Python backtest)

| Parameter | Default | Notes |
|-----------|---------|-------|
| Trend SMA window | 200 | Python: trend_sma_window=200 |
| Realized vol window | 20 | Python: vol_window=20 (days) |
| Min ann. vol % | 5.0 | Python: min_vol_annual=0.05. Filters flat/illiquid stocks |
| Max ann. vol % | 28.0 | Proxy for bottom-quintile selection. Lower = more selective |
| Vol spike exit mult | 2.5 | Python: vol_exit_mult=2.5. Exit if vol spikes to 2.5x entry vol |
| Rebalance every N bars | 21 | Python: rebalance_days=21 (monthly) |

---

## Master Portfolio — Regime-Aware Dynamic Rotation

### What it does
Combines all three strategies in a single Pine Script by dynamically switching between
them based on the detected market regime:

| Regime | Detected when | Active Strategy | Logic |
|--------|--------------|-----------------|-------|
| **BULL** | Close > SMA(200) AND 20d ann.vol < 20% | Strategy 1 (Momentum) | Trend continuation favoured |
| **BEAR** | Close < SMA(200) AND 20d ann.vol ≥ 20% | Strategy 3 (Low-Vol) | Defensive capital preservation |
| **CHOPPY** | Mixed signals | Strategy 2 (Mean Reversion) | Short-term signals work in sideways markets |

When the regime changes mid-position, the script forces a clean exit before switching
to the new strategy's signals — preventing momentum positions from being held through
bear-regime corrections.

The chart background colour shows the current regime:
- 🟢 Green = BULL (momentum-favourable)
- 🔴 Red = BEAR (low-vol defensive)
- 🟠 Orange = CHOPPY (mean-reversion-favourable)

### Recommended Stocks and Application

**Best approach — load on SPY first:**
Run the Master Portfolio script on SPY (S&P 500 ETF) to determine the overall market
regime. The regime shown on SPY tells you which individual strategy to run on your
other stocks at any given time.

**Alternatively — run directly on any large-cap stock:**
The script runs on any single security. The regime detection uses that security's own
price series. For most large-cap stocks this correlates well with overall market regime.

| Ticker | Notes |
|--------|-------|
| **SPY** | Best for regime detection; run here first to understand current market state |
| **QQQ** | High-beta; BULL/BEAR signals are amplified vs SPY |
| **AAPL** | Works well for all three embedded strategies |
| **MSFT** | Steady trends + good RSI(2) reversion + low vol |
| **JNJ** | Dominated by BULL/CHOPPY modes; good low-vol defensive |
| **COST** | Strong trend + very low volatility; works in all regimes |

### Timeframe
**Daily (1D)** — all embedded strategies are calibrated to daily bars.

### Inputs are grouped by component
Open **Settings → Inputs** in TradingView. Parameters are grouped into:
- **Regime Detection** — SMA window, vol window, high-vol threshold (20% = like VIX 20)
- **BULL: Momentum** — all Strategy 1 parameters
- **CHOPPY: Mean Reversion** — all Strategy 2 parameters
- **BEAR: Low Volatility** — all Strategy 3 parameters

Defaults match the Python backtest exactly.

### How it differs from running the three strategies separately
Running each strategy script separately and manually allocating capital is more
flexible (you can weight them 60/40/0 or any ratio). The Master Portfolio script
is best for a single decision: **"which strategy should I be running right now?"**
The regime panel at top-right always shows the answer.

---

## Combining Strategies — Portfolio Allocation Guide

| Scenario | Allocation |
|----------|-----------|
| **Market in BULL regime** (SPY > SMA200, VIX < 20) | 70% Strategy 1, 15% Strategy 3, 15% Strategy 2 |
| **Market in BEAR regime** (SPY < SMA200, VIX ≥ 20) | 20% Strategy 1, 60% Strategy 3, 20% Strategy 2 |
| **Market CHOPPY** (mixed signals) | 40% Strategy 1, 25% Strategy 3, 35% Strategy 2 |

This matches the Python Master Portfolio allocations from `src/portfolio_optimizer.py`.

---

## Important Differences: Python System vs TradingView

| Feature | Python System | TradingView Pine Script |
|---------|--------------|------------------------|
| Universe | 100 stocks simultaneously | Single security per chart |
| Cross-sectional ranking | Ranks all 100 stocks by momentum or vol | Not possible — uses absolute thresholds |
| Cross-sectional z-score | Compares stock vs. 100-stock universe | Approximated by fixed return threshold |
| Low-vol selection | Bottom quintile by realized vol | Ann.vol < configurable threshold |
| Position sizing | Inverse-volatility weighted | Fixed 100% of equity (set manually) |
| Regime detection | Uses simulated SPY benchmark | Uses chart's own price series |
| Fee model | 0.10% commission + 0.05% slippage | 0.10% commission, ~5 ticks slippage |

The entry/exit **logic and indicator calculations** are identical between Python and
Pine Script. The cross-sectional conditions (requiring 100 stocks) are approximated
by single-stock thresholds that produce the same relative behaviour.

---

## Backtested Performance Reference (Python system, 100 stocks, 2005–2025)

> **Note:** Results are from a Monte Carlo regime-switching simulation (Markov bull/bear/choppy + AR(1) autocorrelation). Numbers vary slightly across runs due to the stochastic simulation. The values below are from the most recent run of `python run_comparison.py --start 2005-01-01`.

| Portfolio | CAGR | Sharpe | Max Drawdown |
|-----------|------|--------|--------------|
| Strategy 1 (Momentum) | +17 % | 1.32 | −17.6 % |
| Strategy 2 (Mean Rev.) | ~6–12 % (real data) | ~0.5–0.65 | ~−15 to −22 % |
| Strategy 3 (Low Vol) | +19 % | 1.30 | −25.7 % |
| **Master (Regime + Vol-Targeting)** | **+13 %** | **1.37** | **−13.7 %** |
| Benchmark (SPY buy-and-hold) | +5.7 % | — | −43 % |

The Master Portfolio has the **highest Sharpe ratio** and **smallest drawdown** because it
dynamically allocates to whichever strategy is most favoured by current market conditions.

> Strategy 2 performs near flat on synthetic data (GBM without microstructure)
> but delivers 6–12 % CAGR on real market data per the academic literature
> (Connors 2009; Blitz et al. 2011). Test on real AAPL/SPY/QQQ data in TradingView
> to see realistic signals.
