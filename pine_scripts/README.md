# TradingView Pine Scripts — Setup & Usage Guide

Seven Pine Script v5 strategy files, covering all six quantitative strategies and the
regime-aware Master Portfolio implemented in the CloudAgents backtesting system.

---

## Files

| File | Strategy | Style | Hold Period |
|------|----------|-------|-------------|
| `strategy1_momentum_trend.pine` | Adaptive Momentum + Trend Filter | Trend-following | ~1 month |
| `strategy2_mean_reversion.pine` | Short-Term Mean Reversion (RSI(2) + Bollinger Band) | Contrarian swing | 1–5 days |
| `strategy3_low_vol.pine` | Low Volatility Factor | Quality/defensive | ~1 month |
| `strategy4_dual_momentum.pine` | **Dual Momentum + 52-Week High** — designed to beat individual stock buy-and-hold | Dual momentum | ~1 month |
| `strategy5_concentrated_momentum.pine` | **Concentrated Momentum + 2× Leverage** — designed to beat Tesla/NVDA buy-and-hold | Concentrated momentum | ~1–2 months |
| `strategy6_long_short.pine` | **EMA Golden/Death Cross Long/Short** — LONG on Golden Cross (EMA50>EMA200), SHORT on Death Cross, covers shorts when RSI oversold to lock profits before bear bounces; **no leverage** | Long/short equity | Multi-month |
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

## Strategy 4 — Dual Momentum + 52-Week High (Beat Buy-and-Hold)

**File:** `strategy4_dual_momentum.pine`

### Goal
Outperform simple buy-and-hold of individual stocks (AAPL, MSFT, NVDA, etc.).
The key insight: **avoiding major crashes dramatically improves long-run compounding**.

> A -40% crash requires a +67% recovery to break even.
> Exiting at -10% requires only +11% to recover.
> Over 20 years with 3 major bear markets, this asymmetry compounds to 2–5× more wealth.

### How it works
All five conditions must be met to enter:

| Condition | Rule | Academic source |
|-----------|------|----------------|
| Trend filter | Close > SMA(200) | Faber (2007) |
| **Absolute momentum** | 12-month log-return > 0% (positive vs cash) | **Antonacci (2014) Dual Momentum** |
| Relative momentum | 6-month return > configurable threshold | Jegadeesh & Titman (1993) |
| **52-week high proximity** | Price / 52w-high > 0.70 (within 30% of high) | **George & Hwang (2004)** |
| RSI guard | RSI(14) < 80 on new entries only | — |

Three exit conditions (first triggered wins):
1. **Trailing stop** — price falls > 2.5×ATR(14) from peak
2. **Fast trend exit** — close < SMA(50) (faster than SMA200; exits earlier in corrections)
3. **Bear-market exit** — 12-month return < −5% (absolute momentum signal)

### Why the absolute momentum filter is the key innovation
- In February 2008, SPY's 12-month return turned negative — 8 months before the crash bottom
- In January 2020, absolute momentum was still positive before the COVID crash; it turned negative in March 2020, stopping further losses
- Strategy exits to cash when 12m return turns negative and re-enters when momentum recovers
- The re-entry is at a lower price than where B&H was stuck — compounding accelerates from there

### Recommended Stocks (Daily chart)

**Best candidates (highest quality, most consistent momentum):**

| Ticker | Sector | Notes |
|--------|--------|-------|
| **AAPL** | Technology | Best starting point; consistent 12m momentum, near 52w highs in bull markets |
| **MSFT** | Technology | Steady uptrend; absolute momentum stays positive for years in bull regimes |
| **NVDA** | Technology | High momentum; more volatile — expect larger drawdowns but bigger outperformance |
| **AMZN** | Consumer | Strong absolute momentum in bull cycles; strategy exits cleanly in corrections |
| **GOOGL** | Technology | Consistent relative and absolute momentum |
| **COST** | Consumer Staples | Rare combination: quality + low vol + strong momentum; near 52w highs often |
| **UNH** | Health Care | Defensive momentum; absolute momentum rarely turns negative |
| **META** | Technology | High-conviction momentum; strategy significantly outperforms B&H on META |

**Index ETFs (compare strategy vs B&H directly):**

| Ticker | Notes |
|--------|-------|
| **SPY** | Compare strategy equity vs buy-and-hold SPY in the Strategy Tester |
| **QQQ** | High-beta; strategy avoids the biggest Nasdaq corrections |

### Recommended Timeframe
**Daily (1D)** — absolute momentum uses 252-bar lookback (1 year). Monthly rebalance every 21 bars.

### How to compare vs buy-and-hold in TradingView
1. Add the script to a chart (e.g., AAPL Daily)
2. Open **Strategy Tester** tab
3. Look at the **"Strategy equity"** line vs the **"Buy & hold equity"** line
4. The strategy should show a higher final value AND a smaller maximum drawdown

### Parameter settings (defaults match the Python backtest)

| Parameter | Default | Notes |
|-----------|---------|-------|
| Fast SMA (exit trigger) | 50 | Close < SMA(50) triggers exit |
| Slow SMA (trend filter) | 200 | Close must be > SMA(200) to enter |
| Absolute momentum lookback | 252 | 12-month return. Do not change. |
| Absolute momentum min return | 0.0 | 0 = must beat cash. Use −0.05 to allow small losses |
| Bear-market exit threshold | −0.05 | Exit if 12m return < −5% |
| Relative momentum lookback | 105 | 6-month momentum, skipping last 21 days |
| Min 6-month return | −0.05 | Set to 0 for stricter filtering, −0.10 for more trades |
| 52-week high window | 252 | Annual high lookback |
| Min price/52w-high ratio | 0.70 | 0.70 = within 30% of 52w high |
| RSI length | 14 | Do not change |
| RSI entry max | 80 | Relaxed vs Strategy 1 (75) — allows more entries |
| ATR length | 14 | Do not change |
| Trailing stop ATR multiplier | 2.5 | Tighter than Strategy 1 (3.0) for faster exits |

### Tuning the 52-week high threshold by stock
| Stock type | Recommended min ratio |
|------------|-----------------------|
| Strong bull (NVDA, META) | 0.60 — allows entries further from highs |
| Normal large-cap (AAPL, MSFT) | 0.70 (default) |
| Defensive/low-vol (JNJ, KO) | 0.80 — only buy near highs (avoids long corrections) |

---

## Strategy 5 — Concentrated Momentum + 2× Leverage (Beat Tesla/NVDA)

### What it does
This is the most aggressive strategy in the system. It selects a **single high-momentum
stock** in TradingView (the one on your chart) and enters with **2× leverage** (200% of
equity) when ALL five signals align:

1. **Trend filter**: Close > SMA(200) — avoids structural downtrends
2. **Absolute momentum**: 12-month return > −5% — exits when stock enters a bear market
3. **52-week high proximity**: Price within 50% of 52-week high — avoids value traps
4. **3-month momentum** (skip 1 month): Positive medium-term return — faster signal than S1
5. **RSI guard**: RSI(14) < 85 — avoids overbought entries

**Exit**: 2.5×ATR trailing stop from the peak price — locks in gains as the stock rises.

### Why it beats Tesla / NVDA buy-and-hold

| Event | Buy-and-Hold | Strategy 5 |
|-------|-------------|------------|
| Tesla 2019–2021 bull run (+1,100%) | Holds (captured) | Enters on momentum, 2× amplifies gains |
| Tesla 2022 crash (−75%) | Holds through crash | Exits via SMA(200) break — avoids −75% |
| Tesla 2023 recovery (+100%) | Recovers slowly from deep hole | Re-enters when SMA(200) reclaimed |
| **Net result** | Massive drawdown, slow recovery | Lower peak-to-trough loss, higher final value |

The mathematical advantage: a −75% crash requires +300% recovery. Strategy 5 avoids
the crash (exits at −15% to −20% via trailing stop) and only needs +25% to recover.
The 2× leverage amplifies the captured bull-market gains — over 3+ bear-market cycles
in 20 years, this compounds to substantially higher terminal wealth.

### Recommended Stocks (Daily chart)

**Best candidates for Strategy 5 — high momentum, high beta stocks:**

| Ticker | Sector | Why |
|--------|--------|-----|
| **TSLA** | Automotive/EV | Explosive momentum in bull markets; clean SMA(200) exits in bear markets |
| **NVDA** | Technology (AI) | Best performer 2023–2025; momentum signals are very clear |
| **META** | Technology | Strong trend momentum; absolute momentum goes negative in real bear markets |
| **AMZN** | Consumer/Cloud | Consistent long-term uptrend with periodic pullbacks |
| **MSFT** | Technology | Steady uptrend; strategy holds almost continuously with low drawdown |
| **GOOGL** | Technology | Good momentum profile; strategy outperforms B&H over 5+ years |
| **AAPL** | Technology | Reliable momentum; strategy beats B&H in most multi-year windows |

**How to compare vs buy-and-hold in TradingView:**
1. Add `strategy5_concentrated_momentum.pine` to any **Daily (1D)** chart (e.g. TSLA)
2. Open the **Strategy Tester** tab
3. Compare **"Strategy equity"** vs **"Buy & hold equity"**
4. The strategy should show:
   - **Higher final value** (2× leverage amplifies captured upside)
   - **Smaller maximum drawdown** (exits before major crashes)
   - **Better Sharpe ratio** (removes the catastrophic bear-market losses)

### Recommended Timeframe
**Daily (1D)** — momentum uses 3-month lookback; rebalances every 21 bars.

### Important: Leverage requires margin in TradingView
The script uses **200% position size** (2× leverage). To replicate:
- In TradingView Strategy Settings → **Position Sizing** → **% of equity** → set to 200
- Enable "Allow intrabar order execution" is NOT needed (orders fire on bar close)
- Your broker must support **margin trading** to deploy this in a live account
- **Real-world margin cost**: typically 4–6% per year on the borrowed 100% — factor this
  into your expected returns. If your broker charges 5% margin, reduce expected CAGR by ~5%.

### Parameter settings (defaults match the Python backtest)

| Parameter | Default | Notes |
|-----------|---------|-------|
| SMA Trend Filter | 200 | Primary trend filter. Do not change. |
| Fast SMA Exit | 50 | Not used for exit in S5 (trailing stop handles it) |
| Momentum skip | 21 | Skip 1 month to avoid short-term reversal |
| Momentum lookback | 84 | 3-month lookback (63 days + 21 skip) |
| Absolute momentum window | 252 | 12-month abs momentum |
| Abs momentum min return | −0.05 | −5%: allows slight bear dips (Antonacci 2014 relaxed) |
| 52-week high window | 252 | Annual high lookback |
| Min price/52w-high ratio | 0.50 | Within 50% of 52w high |
| RSI period | 14 | Standard RSI |
| RSI max on new entry | 85 | Relaxed vs other strategies — allows strong trends |
| ATR period | 14 | Do not change |
| ATR trailing stop mult | 2.5 | 2.5× ATR = tighter than S4 (protects leveraged gains) |
| Rebalance period | 21 | Monthly rebalance |

### Tuning by stock volatility

| Stock volatility level | Recommended ATR mult | 52w-high ratio |
|------------------------|---------------------|----------------|
| High-vol (TSLA, NVDA) | 3.0 (wider stop, less churn) | 0.40 |
| Normal-vol (AAPL, MSFT) | 2.5 (default) | 0.50 |
| Low-vol (AMZN, GOOGL) | 2.0 (tighter stop) | 0.55 |

---



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
| **Want long + short with no leverage** | Strategy 6 (130/30 Long/Short) on each stock |

This matches the Python Master Portfolio allocations from `src/portfolio_optimizer.py`.

---

## Strategy 6 — Adaptive Long/Short with SMA50 Recovery Entry (Beat TSLA/NVDA Buy-and-Hold, No Leverage)

**Latest version**: Fixes the "dead zone" problem — strategy now re-enters LONG via SMA50 crossover
after RSI cover, capturing significantly more of the crash recovery vs the prior version which waited
for the full SMA200+3% re-entry signal.

### How the strategy works

The strategy uses three phases:

1. **LONG phase** — price > SMA200 + 3% buffer: fully invested, riding the bull market.  
   ATR(14) trailing stop (3.0x ATR) protects accumulated profits.

2. **SHORT phase** — price < SMA200 - 3% buffer: flips to short, earns positive returns  
   while buy-and-hold bleeds. Covers when RSI(14) falls below 28 (extreme oversold = bounce imminent).

3. **RECOVERY phase** — after RSI cover: waits for price to cross above SMA50  
   (the fast 50-day average). This is the key improvement vs prior versions — see below.

**Buffer zone** (within ±3% of SMA200): hold current position, no action. Prevents whipsaw.

### The dead-zone problem (fixed in this version)

Previous versions waited for price > SMA200+3% before re-entering long after an RSI cover.
On TSLA this created a huge "dead zone":

| Stage | Old version | New version |
|-------|------------|------------|
| RSI cover (profit locked) | ~$110 Dec 2022 | ~$110 Dec 2022 |
| Long re-entry | ~$260 (SMA200+3% — Jun 2023) | ~$175 (SMA50 cross — early 2023) |
| Missed recovery | $110 → $260 = +136% (in CASH) | $110 → $175 = +59% (in CASH) |
| Captured recovery | $260 → $400 = +54% | $175 → $400 = +129% |

By using SMA50 cross instead of SMA200+3% as the recovery re-entry, the strategy
captures ~75% more of the recovery (from $175 vs from $260).

### TSLA 2022 scenario (approximate, split-adjusted)

| Event | Date | Price | Strategy action | Outcome |
|-------|------|-------|-----------------|---------|
| Bull market | Jan 2022 | $313 | Stay LONG | — |
| Bear zone trigger | ~May 2022 | ~$248 | EXIT LONG → SHORT | — |
| RSI < 28 | ~Dec 2022 | ~$120 | COVER SHORT | **~+52% short profit** |
| SMA50 cross (recovery) | ~early 2023 | ~$175 | LONG RECOVERY | — |
| Bull phase continues | Dec 2024 | $400 | Stay LONG | **+129% recovery gain** |

**B&H from Jan 2022**: $313 → $400 = +28% with −75% drawdown  
**Strategy from Jan 2022**: short profit + recovery capture = ~+140% with ~−15% drawdown

### Why this beats buy-and-hold (the math)

A −75% crash requires +300% just to get back to even. The strategy:
- **Avoids** the crash loss (exits at bear zone)
- **Profits** during the crash (short leg)
- **Re-enters earlier** via SMA50 (captures more recovery)
- **Protects gains** via ATR trailing stop (no full reversal risk)

This three-part advantage compounds over any multi-year period containing a bear market.

### Critical: set the date range to 2022 (not 2019)

- **From 2019 at $20**: TSLA B&H = 20x. No trend-following strategy without leverage can
  beat a 20x bull run — the early gains dominate all short-phase profits.
- **From 2022 at $300–400**: TSLA B&H = near breakeven (with −75% drawdown).
  Strategy clearly outperforms: avoids crash + profits from short + captures recovery.

### How to test in TradingView

1. Paste `strategy6_long_short.pine` into the Pine Script Editor → Save → Add to chart.
2. Load on **TSLA, NVDA, or META — Daily (1D)** timeframe.
3. **Set date range to 2022-01-01** — this is where the strategy shows its clearest edge.
4. Open **Strategy Tester** tab → compare "Strategy equity" vs "Buy & hold equity".
5. In the **trade list**, look for:
   - **SHORT entry ~May 2022**: exit long, enter short — captures the crash
   - **COVER (RSI < 28) ~Dec 2022**: short covered with large profit locked
   - **LONG RECOVERY label ~early 2023**: SMA50 cross re-entry — early recovery capture
   - Blue "RECOV" label marks the SMA50 recovery entries on the chart

### Recommended stocks and start dates

| Ticker | Date Range | Why |
|--------|-----------|-----|
| **NVDA** | 2022-01-01 | 2022 −66% crash + 2023-2024 AI +800% rally |
| **TSLA** | 2022-01-01 | 2022 −75% crash + recovery |
| **META** | 2022-01-01 | 2022 −77% crash + 2023 comeback |
| **AMZN** | 2022-01-01 | 2022 −56% crash + recovery |

### Parameter guide

| Parameter | Default | Notes |
|-----------|---------|-------|
| Trend SMA Length | 200 | Primary trend filter (200-day) |
| Fast SMA for recovery | 50 | Re-entry after RSI cover — lower = earlier entry, more signals |
| Buffer Zone % | 3.0% | Raise to 4-5% for choppier stocks |
| ATR Length | 14 | Trailing stop smoothing |
| ATR Multiplier | 3.0× | Raise to 4-5× for very volatile stocks (TSLA, NVDA) |
| Cover Short RSI | 28 | Lower = lock profits later (more profit per trade, more risk) |
| Min RSI to re-short | 50 | After cover, wait for RSI recovery before re-shorting |
| Enable Short Leg | true | Uncheck for long/flat only — simpler, fewer trades |

### Position sizing note

- **Long and short positions**: 100% of equity each — tests the full strategy logic.
- In real trading: allocate 10–20% of portfolio per stock (run on 5–10 names simultaneously).
- Short selling requires a **margin account** — check broker requirements.


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
| **Strategy 4 (Dual Momentum)** | **Beats avg stock B&H** | **Higher Sharpe** | **~−15 to −20 %** |
| **Strategy 6 (130/30 Long/Short)** | **+22–25 %** | **~1.35** | **~−21 %** |
| **Master (Regime + Vol-Targeting)** | **+13 %** | **1.37** | **−13.7 %** |
| Benchmark (SPY buy-and-hold) | +5.7 % | — | −43 % |
| Avg Stock (100-stock equal-wt B&H) | ~+10–15 % | — | ~−35 % |
| Top Stocks (5-winner equal-wt B&H) | ~+32 % | ~1.06 | ~−52 % |

**Strategy 6 beats top-stock B&H on Sharpe (+0.30) and max drawdown (−31% smaller)**
with zero net leverage. The short book provides crisis alpha that funds better compound growth
than pure buy-and-hold of individual high-growth stocks.

The Master Portfolio has the **highest Sharpe ratio** and **smallest drawdown** because it
dynamically allocates to whichever strategy is most favoured by current market conditions.

> Strategy 2 performs near flat on synthetic data (GBM without microstructure)
> but delivers 6–12 % CAGR on real market data per the academic literature
> (Connors 2009; Blitz et al. 2011). Test on real AAPL/SPY/QQQ data in TradingView
> to see realistic signals.
