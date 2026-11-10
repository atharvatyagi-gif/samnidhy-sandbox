# ALADIN, rebuilt: the single model (specification for approval)

Model **E: momentum with a daily risk check**, chosen by the owner on 2026-11-10 from the Phase 4 test. Version name: `aladin-e-1`.

## What it predicts
Not "will this stock go up tomorrow". It ranks stocks by how strongly they have risen over the last 6 months and expects the
leaders to keep beating the average stock over the next quarter, on average and with many exceptions. Every number shown with it
is a **measured frequency from the Phase 4 test**, not a promise.

## Inputs (all free, all already collected nightly)
- Daily prices and volumes from NSE's end-of-day files (Daily update job).
- The NIFTY 500 index close (for the daily risk check).
- Nothing else: no fundamentals, news or sentiment (Phases 2–4 found they did not help after costs).

## Which stocks are considered
On each rebalance day: main-board, non-ETF stocks with at least 250 days of prices and an average traded value of at least
₹5 Cr a day over 60 sessions; the 500 largest by traded value.

## The signal
1. **Score** each stock: its price change over the last 126 trading days (about 6 months).
2. **Rank** the 500; the best 5% (about 25 stocks) are **"In the portfolio"**. Every other stock shows **"No signal"** with its rank.
3. **Rebalance every 63 trading days** (about once a quarter): sell stocks that dropped out of the best 5%, buy the new ones. Stocks
   that stay are not traded (saves costs).
4. **Daily risk check:** every evening, if the NIFTY 500 closes below its 200-day average, the next morning the portfolio goes to
   **half** its normal size; when it closes back above, it returns to normal size the next morning.
5. All trades at the **next day's open**, after costs (costs.json: STT, stamp, exchange, SEBI, GST, DP charge, slippage).

## What each stock shows
Its rank ("better than 93% of the 500"), its state ("In the portfolio" / "No signal" / "Not ranked: too little history or
trading"), the measured chance that stocks in its rank group beat the market over the next 63 days **with a 95% range**, the
as-of date, and the model version. No price target is ever shown.

## Position size and loss limits
- **Invested share: 70% of capital** (30% kept in cash / a liquid fund), so the tested worst fall stays inside the owner's −25%
  limit. Halved to 35% when the daily risk check says so.
- Equal weight: about 2.8% of capital per stock at full size. A Kelly-style check is applied as a ceiling, never a target: the size
  is never above one quarter of the Kelly fraction implied by the measured edge, and never above 5% of capital per stock.
- **Maximum loss per trade:** bounded by the position size (at most 5% of capital even if a stock went to zero).
- **Maximum loss per day:** if the paper account falls more than 4% in one day, no new buys the next day.

## When it says "no signal" or stops
- **Degraded** (signals hidden, a banner shown): prices more than 2 sessions old, or the NIFTY 500 close missing.
- **Kill switch:** if the paper account falls more than **25%** from its peak (the owner's limit), all buying stops and the
  invested share drops to 35% until the owner reviews it.
- **Accuracy alarm:** if the live portfolio trails the NIFTY 500 by more than 15 points over any rolling 12 months, a warning is
  shown (momentum can lag for long stretches; this is a prompt to review, not an automatic stop).

## Retraining
There is nothing to "train": the rule has three fixed settings (6 months, best 5%, every 63 days), chosen in Phase 4. They are
re-checked once a year with the same walk-forward test; a change needs the owner's approval.

## What happens to today's ALADIN
After this is built and tested: ALADIN 1, the Outlook model, the ALADIN 2.0 engine, the weekly signal, the movers model and the old
paper bots are moved to `archive/` with a note each, and removed from the nightly jobs and the pages. The current paper bot
(v5.1) and its shadow keep running until this phase is approved, then are archived with their records saved. ALADIN 1's 20-day
ranking (the Phase 4 runner-up) keeps a small hidden paper track for comparison only, if the owner agrees.

## Honest limits (shown on the page)
Tested 2010–2026 on companies listed today (survivorship bias: about half the tested edge may be this). No result passed the
strict luck test. The last six months were flat. It has had losing years (2016, 2018, 2022, 2025) and deep falls. Educational
analysis on paper only; not investment advice.
