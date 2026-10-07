# ALADIN 2.0, Phase 2: strategies and the evaluation machine (2026-10-07)

Branch `feature/aladin-learning`. Nothing pushed or merged. `python -m pytest tests/aladin2` : **80 tests pass** (19 s).

## What was built
- `strategies/` : 34 selectable strategies in 5 families (trend 11, reversion 12, volatility 6, relative strength 3, delivery flow 2) plus the naive 12-1 momentum baseline. Every strategy has a unit test for look-ahead (future prices changed, data truncated), and a hash for the multiple-testing count (34 distinct).
  **Not built yet:** fundamental/quality, event, text/graph and ML families (brief families 6-9). They need point-in-time fundamentals and events and their own ML protocol.
- `evaluate.py` : nested walk-forward (63-day blocks, 20-day purge + 5-day embargo, 2,000-day selection window), stationary block bootstrap, Benjamini-Hochberg across all (stock x strategy) pairs of a block (q = 0.10), empirical-Bayes shrinkage (sector, else universe), plateau, yearly-stability and recent-window checks, beats-naive-momentum check, CUSUM inside the block. `select()` is the production step; `walk_forward()` replays it block by block.
- `lifecycle.py` : Candidate, Probation, Active, Demoted, Retired, with PSR/DSR, CUSUM, cap of 4 active per stock, fresh-evidence re-entry; every transition returns an evidence event (tested through the whole path).
- `experiments.py`, `run_phase2.py`: the honesty experiments and the real-data run.

## 1. The gate question: does ALADIN as a policy beat the baselines net of costs?
**No. It never trades.** NIFTY 500 members with 20-day average traded value >= Rs 2 crore (425 stocks, survivor-only list), 56 unseen blocks from 2012-07 to 2026-10, real cost model (liquidity decile 0-9), 2,951 to 6,532 (stock x strategy) pairs tested per block. **FDR-passing pairs: 0 in all 56 blocks.** Probation/Active strategies: 0. Paper trades: 0. Share of stocks with any evidence: 0%. The best single pair in the latest block had p = 0.001 against a BH threshold of about 0.1/6,425 = 1.6e-5, which is what chance alone produces among 6,425 tests.

So the stock-by-stock selection policy defined in the brief adds nothing measurable here: every stock reads "No edge" (Learning). I did not loosen any threshold.

Baselines on the same unseen blocks (excess = trade net of costs minus what simply owning the stock earned over the same days; 95% intervals resample calendar months):

| Rule | Trades | Excess vs owning the stock |
|---|---|---|
| ALADIN policy (Probation + Active) | 0 | n/a |
| Naive 12-1 momentum, every stock | 74,799 | **-52 bps** [-83, -21] |
| All 34 strategies, every stock, no selection | 802,139 | **-185 bps** [-211, -156] |
| Buy and hold | | 0 by definition |
| Outlook model | | per-row predictions were never saved; only its yearly AUC (0.534) exists |

## 2. What the data does say: pooled evidence per strategy (34 pre-defined hypotheses, month-clustered bootstrap, BH q = 0.10, no selection)
Seven strategies clear it, all short-term reversal / oversold rules, long only:

| Strategy | Trades | Excess per trade | 95% interval | p |
|---|---|---|---|---|
| reversal5_vol_2.0 (5-day drop of 2 sigma + volume surge, hold 10d) | 4,956 | +208 bps | [+111, +290] | 0.0002 |
| reversal5_vol_1.5 | 9,012 | +154 | [+87, +217] | 0.0002 |
| reversal5_vol_1.0 | 14,356 | +118 | [+65, +170] | 0.0002 |
| bb_z_below_2.5 | 9,703 | +106 | [+34, +173] | 0.0012 |
| bb_z_below_2.0 | 21,891 | +91 | [+33, +146] | 0.0012 |
| bb_z_below_1.5 | 35,409 | +80 | [+35, +125] | 0.0010 |
| rsi2_below_5 | 42,736 | +30 | [0, +57] | 0.018 |

Everything trend-following, breakout, relative-strength and delivery-surge is flat or negative. Diagnostic (post hoc, for reversal5_vol_1.5): excess was positive in 14 of 15 calendar years, negative in 2020 (-104 bps), +171 bps without 2020.

**Why this is NOT yet a claim of edge:**
1. **Survivorship.** The universe is today's NIFTY 500. A stock that fell sharply and was then delisted or demoted is missing, and buying sell-offs is exactly the strategy that benefits most from that. The true figure is lower by an amount I cannot measure from free data. Today's liquidity filter is also applied to the past.
2. **Fills.** Entries are at the next open after a sell-off with a Rs 1 lakh reference order; real fills in panicking stocks, circuit days and wider spreads would be worse than the decile slippage assumes.
3. It is a **pooled** result about a strategy across hundreds of stocks, not evidence that any one stock will behave that way.

## 3. Honesty tests (brief 6.7)
- **Noise, zero costs, 2,000 series x 29 strategies = 58,000 pairs, 64 blocks:** pairs ever promoted **0**; blocks with any promotion **0%** (limit q = 10%). Full run: `data/aladin2/honesty_null2000_zerocost.json`.
- **Noise with real costs, 2,000 series:** running; costs only make promotion harder. Will be appended.
- **Planted edges** (60 noise + 108 planted series, zero costs, evidence window 4,000 days; 6,000-day series; false-discovery proportion among promoted = 0 of all promotions in the noise-only runs, 0.7% in the mixed pilot): found with power
  - reversion at all three strengths tested: **12 of 12 each (100%)**;
  - momentum: 92% (strength 120), 58% (240), 25% (480);
  - regime-dependent: 92% (240), 67-75% (480).
  The planted momentum and regime strengths are enormous (a drifting component whose standard deviation is 1.2% to 4.8% a day; an edge of that size explains many percent of 20-day returns, versus well under 1% in real markets). **A realistic small edge is far below what stock-level evidence can detect.** The momentum power falls at the largest strength only because the synthetic paths become degenerate.
- **Vanishing edge: NOT met.** With 48 planted-then-vanishing series, the strategies live at the vanishing point took a **median of 628 days (90th percentile 1,157)** to be demoted. The lifecycle rules are tested and correct (`test_lifecycle.py`), but a per-trade standard deviation of about 8% against an edge of about 1% means a loss of edge cannot be seen faster. The CUSUM never fires on a small shift. I did not tune it to pass; a recent-window rule I added cut the median only modestly.

## 4. Why the per-stock design fails here (the measured reason)
A stock-strategy pair has 30-70 trades in the window, each with a standard deviation of 5-15% against a cost of about 0.5%. Even a real edge of 1% per trade has t of about 1, and with thousands of pairs the BH bar is t of about 4.5. This is the multiple-testing price the brief asked me to pay. It is the honest result, and it is also what the Phase 0 numbers (IC t = 7.8 only after pooling 300,000 predictions) already suggested.

## 5. What I propose next (needs your decision; it changes the brief)
**Option 1 (recommended):** pooled-first evidence. Test each strategy across the whole universe or sector (month-clustered, BH over strategies, as in section 2), promote a *strategy* when pooled evidence holds up out of sample, and let per-stock data only *tilt* it (shrinkage, abstaining on stocks where the strategy has clearly failed). This gives real signals (today: the reversal family) while keeping per-stock "No edge" honest. Before building on it, test survivorship as far as free data allows (stocks that fell > 50% and later went illiquid; fills on sell-off days at realistic spreads).
**Option 2:** keep the brief as written. The product would show "No edge" for every stock until some pair clears q = 0.10, possibly for a very long time.
**Option 3:** stop at the evidence: report to students that the free-data technical strategies tested do not beat owning the stocks, apart from short-term reversal pending the survivorship check.

## 6. Other items
- Compute: real run 117 s on 14 cores (build 43 s, replay 40 s); 2,000-series null replay about 25 minutes.
- Product-state shares: Validated 0%, Provisional 0%, Learning 100% (unchanged).
- Delivery % history: 2020-01 to 2022-08 downloaded and the backfill resumes after a crash fix (a non-UTF8 file); the two delivery strategies had few trades.
- Config additions: `eval.data_start/first_test/select_lookback_d/boot_*/stab_*/recent_*`, `lifecycle.min_live_trades/cusum_k`.
- Raw outputs: `data/aladin2/phase2_report.json`, `phase2_events.jsonl.gz`, `honesty_*.json`.

## GATE: what I need from you
1. Choose Option 1, 2 or 3 (or your own).
2. Keep the strategy count at 34? More strategies raise the multiple-testing bar; fundamentals/events/ML families are not built.
