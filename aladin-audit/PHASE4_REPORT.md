# ALADIN audit, Phase 4: head-to-head test of the options

Written 2026-11-10. Code: `aladin-audit/scripts/phase4_engine.py` (one simulator for all), `phase4_run.py` (the comparison).
Results: `aladin-audit/phase4/results.json`, `sizing_and_holdout.json`. Every setting tried: `aladin-audit/TRIALS.md` (409 trials).

## 4.1 Setup (the same for every option)

| Item | Choice |
|---|---|
| Universe | On each rebalance date: main-board, non-ETF stocks with ≥ 250 days of prices, **60-day average traded value ≥ ₹5 Cr**, the 500 largest by that value (point in time) |
| Period | Prices 2008-01-01 to 2026-11-06. Tests from 2010 (ALADIN 1's machine-learning record only exists 2015 to Sept 2026). Limited by free data: Yahoo/NSE daily candles from the repository's caches |
| **Survivorship** | Free history exists only for companies listed today. Collapsed and delisted companies are missing, which **inflates every absolute number**, more for small and mid caps. Not removable with free data |
| Trades | Signal at a close, trade at the next open plus slippage; long-only delivery; equal weight; ₹1,00,000 compounding; whole shares (a stock costing more than one position is skipped) |
| Costs | `aladin-audit/costs.json` (your brief's rates): STT 0.1% each side, stamp 0.015% on buys, exchange, SEBI, 18% GST, **DP ₹15.93 per stock sold**, slippage 0.05–0.20% per side by liquidity |
| Walk-forward | Each year's setting is the one with the best Sharpe on all earlier years only; the years are stitched together. Switching between settings is not charged extra |
| Purged cross-validation | 5 time blocks; a setting is chosen on the other blocks, leaving out 21 trading days on each side of the test block (purge and embargo), then judged on the block |
| Trials and luck | 409 settings tried. The **deflated Sharpe ratio** (DSR) is the chance the result is real rather than the luckiest of 409 tries: above 0.95 is the usual bar |
| Hold-out | 2026-05-08 to 2026-11-06, never used to choose anything; run once at the end |
| Filter levels (your goal) | tight = best 2% of the universe (≈ 10 stocks), medium = best 5% (≈ 25), loose = best 10% (≈ 50) |
| Not testable with free data | **B (earnings drift)** and the **quality half of A**: past results dates and past fundamentals are not stored. **F (pairs)**: needs the history of which stocks had futures and their futures prices. Longer intraday history: free 5-minute data covers about 60 days; NSE-licensed vendors sell more, and I am not sure of current prices |

## 4.2 and 4.3 Results (walk-forward, unseen years, after costs)

| Option | Filter | Per year | Worst fall | Sharpe | DSR | Years beating random | Up / down / sideways markets (per year) | Before / after 2020 |
|---|---|---|---|---|---|---|---|---|
| **E. Momentum + daily risk check** | medium 5% | **30.0%** | −36.0% | 1.16 | 0.83 | 12/14 | +81% / −38% / +20% | 27.0% / 33.5% |
| A. Momentum | loose 10% | 28.6% | −39.5% | 1.12 | 0.79 | 14/14 | +82% / −50% / +26% | 24.8% / 32.9% |
| A. Momentum | medium 5% | 27.8% | −57.2% | 1.02 | 0.68 | 10/14 | | |
| C. ALADIN 1's machine learning, 20-day | medium 5% | 22.5% | −31.3% | 1.16 | 0.79 | 9/10 | +51% / −18% / +13% | 21.4% / 23.0% |
| C. same | loose 10% | 18.6% | −31.2% | 1.04 | 0.68 | 9/10 | | |
| D. Regime blend | tight 2% | 21.3% | −30.8% | 1.25 | 0.90 | 10/14 | +55% / −32% / +16% | 25.4% / 17.0% |
| G. Low volatility | medium 5% | 12.3% | **−23.8%** | 1.02 | 0.68 | 7/14 | +32% / −23% / +9% | 13.6% / 11.0% |
| G. Short-term reversal | any | −5% to −13% | −76% to −89% | < 0 | 0.00 | 0–1/14 | | |
| **Current ALADIN (weekly BUY rule)** | top 1% | **7.1%** | −47.2% | 0.40 | 0.07 | 4/10 | +35% / −31% / −3% | 16.9% / **2.8%** |
| Baseline: NIFTY 500 index (price only) | – | 11.0% | −38.3% | 0.73 | | | | |
| Baseline: equal weight, whole universe | – | 11.0% | −41.7% | 0.65 | | | | |
| Baseline: random picks, same rules | 2% / 5% / 10% | 7.5% / 4.7% / −0.7% | −64% | | | | | |

What this means: momentum (A, E) and ALADIN's own 20-day ranking (C) clearly beat the index in these tests; the current live rule
did not. The random baseline is weak because it replaces every stock every month, so DP charges and costs sink it, especially with
50 positions on ₹1 lakh; NIFTY 500 is the fairer yardstick. **No DSR reaches 0.95**: with 409 tries, luck cannot be ruled out.

Trade-level detail (selection period): Momentum loose 10%: 1,399 trades, 49.5% won, average win +38.8%, average loss −16.1%, costs
about 6% of gross profit. ALADIN machine learning 20-day: 3,273 trades, 54.3% won, average win +10.6%, average loss −7.4%, costs
about 22% of gross profit.

## Your risk limit (worst fall −25%)

Of 409 settings, only one stayed inside −25% fully invested (low volatility, 12.2% a year). A long-only stock strategy that is
always fully invested will fall more than −25% in a crash like 2020 (NIFTY 500 itself fell −38%). The honest way to meet the limit
is **position sizing**: keep part of the money in a liquid fund (6% a year assumed; I am not sure of future liquid-fund rates).

| Option (walk-forward series) | Invested | Per year | Worst fall | Sharpe |
|---|---|---|---|---|
| **E. Momentum + daily risk check, medium 5%** | **70%** | **23.2%** | **−24.9%** | 1.27 |
| E. same | 60% | 20.9% | −21.6% | 1.32 |
| A. Momentum, loose 10% | 60% | 20.0% | −23.0% | 1.28 |
| C. ALADIN machine learning 20-day, medium 5% | 70% | 17.8% | −22.7% | 1.30 |

## Hold-out (2026-05-08 to 2026-11-06, run once, fully invested)

| Option | Return | Worst dip | Trades |
|---|---|---|---|
| E. Momentum + daily risk check, medium 5% | +0.9% | −22.9% | 73 |
| A. Momentum, loose 10% | −0.4% | −19.1% | 29 |
| E. same, loose 10% | −0.9% | −18.8% | 123 |
| NIFTY 500 | +1.0% | −10.0% | – |
| C. ALADIN machine learning | not possible: its record ends in September 2026 | | |
| D, G | not computed (not finalists) | | |

What this means: over the last six months momentum did **not** beat the index and dipped about twice as deep. Six months is too
short to judge, but it is a fair warning that momentum has flat and painful stretches (also 2016, 2018, 2022, 2025).

## 4.4 Robustness

| Check | Momentum, loose 10% (6-month return, every 63 days) | ALADIN machine learning 20-day, loose 10% |
|---|---|---|
| As chosen | 25.1% a year, worst −39.5% (full period from 2010) | 17.7%, worst −31.2% (from 2015) |
| Rebalance 20% more often | 18.6%, worst −53.1% | 16.0%, −34.2% |
| Rebalance 20% less often | 20.3%, worst −43.9% | 19.0%, −34.3% |
| Pick 20% fewer stocks | 27.1%, −39.8% | 19.1%, −31.3% |
| Pick 20% more stocks | 23.6%, −43.2% | 18.0%, −32.5% |
| Remove the 5 best trades | net per trade 11.1% → 8.3% | 2.4% → 2.2% |
| **Largest 100 stocks only** | **13.5%**, −48.7% | **9.1%**, −32.1% |
| Largest 250 | 25.2%, −39.8% | 14.1%, −30.6% |
| Purged cross-validation | same family chosen in all 5 blocks; Sharpe 0.22–1.84 | same setting all 5 blocks; Sharpe 0.73–1.61 |

What this means: both survive dropping the best trades and changing the number of stocks. Momentum is sensitive to how often it
rebalances. **Most of the gain comes from mid and small caps**: limited to the 100 largest stocks it falls to about the index's
level, which is also where survivorship bias inflates numbers most. For E, the purged cross-validation chose the same setting
(6-month momentum, every 63 days, half invested when NIFTY 500 is below its 200-day average) in all five blocks, with a positive
Sharpe in every one.

**Reality check against survivorship-free data.** IIMA's survivorship-adjusted long-only winners beat the market by about
**9 points a year** in 2016–2025, before costs. Our momentum beats NIFTY 500 by about 17 points, so roughly half of our edge may be
survivorship. A realistic expectation is well below the table.

## 4.5 Comparison and recommendation

Ranked by return per unit of risk on unseen data, steadiness across years as the tie-breaker:

1. **E. Momentum with a daily risk check, medium filter (about 25 stocks)** — highest Sharpe among the strong options, chosen the
   same way in every cross-validation block, simple to explain and to run (a quarterly rebalance plus a daily index check), and it
   fits your −25% limit at about 70% invested.
2. **Runner-up: C. ALADIN 1's own machine-learning ranking at a 20-day hold, medium filter** — steadier (worst calendar year
   −1.5%, shallowest falls), but only tested from 2015, no hold-out, much heavier to run every night, and harder to explain.
3. D (regime blend) has the best DSR (0.90) but weaker after 2020; G low volatility is the only one inside −25% fully invested but
   barely beats the index.

**Recommendation: build E as the single model**, sized at about 70% invested (30% in a liquid fund), with these honest limits:
roughly half of the tested edge may be survivorship; no result passes the strict luck test; the last six months were flat; and it
will have losing years. I recommend Phase 5 also keeps a small, separate paper track of the runner-up C for comparison, without
showing it as a signal.

The decision is yours: **E (recommended), C, or another option**, and the invested share (70% recommended for your −25% limit).
