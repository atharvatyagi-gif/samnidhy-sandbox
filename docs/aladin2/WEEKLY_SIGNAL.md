# ALADIN 2.0 weekly BUY / SELL signal (branch `feature/aladin-weekly`, 2026-10-08)

Written for: the project owner deciding whether to publish weekly BUY and SELL calls.

## What you asked for, and what the data allows
You asked for a BUY and SELL signal with a weekly time limit, using everything ALADIN has. I first measured what a week can honestly deliver, then built the signal around the result.

**The study** (`scripts/aladin2/weekly_study.py`, `data/aladin2/weekly_study.json`): 310,816 stock-weeks (655 Fridays, 1,500 liquid stocks, 2013 to 2026), signal at the Friday close, entry at the next open, exit at the open five trading days later, the full cost model, measured against the equal-weight market of the same week, 95% intervals from resampling calendar months. Scores tried: ALADIN 1's 5-day probability, 5-day reversal, 3-month momentum, a blend, and a walk-forward learned stack.

| Group (by ALADIN 1's 5-day score) | Before costs vs market | After costs vs market | Closed higher | Years |
|---|---|---|---|---|
| **Worst 5% (SELL)** | **-72 bps a week** [-87, -56] | n/a (cash cannot be shorted) | **42%** | below the market in **14 of 14** |
| Worst 10% | -50 bps [-62, -38] | | 43% | 14 of 14 |
| Best 10% | +30 bps | **-7 bps** [-18, +5] | 53% | 7 of 14 positive |
| Best 5% / 2% | +38 / +52 bps | +2 / +15 bps (not significant) | 54 / 56% | 9 of 14 |
| **Best 1% (BUY)** | **+64 bps** [+43, +84] | **+27 bps** [+6, +47] | 55% | 9 of 14 positive |
Average round trip cost 37 bps (SELL side stocks are less liquid: 44 bps). The market itself rose 33 bps a week on average.
Everything else failed after costs: reversal -35 bps, momentum -24 bps, and a blend or stack of all three did no better than ALADIN 1's score alone (stack best 10%: -4.5 bps). A market-stress filter was useless (the regime model says "stress" in 0.7% of weeks). Fundamental, sentiment and supply-chain views have **no weekly history**, so they could not be tested; they are shown as context.

## The signal (rules fixed from that study, in `scripts/aladin2/weekly.py` and `data/config/aladin2.json`)
- **BUY** = best 1% of the ~1,300 liquid stocks by ALADIN 1's 5-day score (about 13 names). Entry zone around the close, exit at the open of the 5th trading day after entry, or earlier if the price closes below a 2-ATR exit level. Sized for your capital (1% risk, 10% position cap, Kelly cap, 5% of volume).
- **SELL** = worst 5% (about 66 names). Cash shares cannot be shorted, so it means **exit if you hold it, do not add it**; the page marks the stocks that have futures, where a short is possible.
- **HOLD** = everything else.
- Every signal is **Provisional**: 13 years of out-of-sample history behind it, no live weekly record yet. It becomes Validated only after 60 live days and a positive live result.
- Signals made on days other than Friday use the same score but were not separately tested (labelled on the page).

## The honest reading
1. **The SELL side is the strong one.** The worst-ranked stocks fell behind the market every single year for 14 years. Survivorship (delisted losers are missing) makes this *understated*.
2. **The BUY side is weak.** Only the best 1% pays after costs, the interval is +6 to +47, positive in 9 of 14 years, and four thresholds were looked at before choosing 1%, so it is the weaker claim. Survivorship flatters it. The best 10% does not pay. Size small or skip.
3. A signal is a ranking of probabilities, not a prediction of any one stock. Roughly 45% of BUY signals closed lower in the past.
4. The first book (as of 7 Oct) was written after the 8 Oct entry open, so it does **not** count as live. The live record starts with the next nightly run; the Weekly signals page recomputes it from the ledger, only for books published before their entry open.

## What changed in the product (this branch only, not merged)
- New **Weekly signals** page (first tab of ALADIN 2.0): BUY and SELL lists, entry zone, exit level, cost, futures flag, the measured record, the live record, and what was tested and did not help.
- **Brief** for each stock: BUY / SELL / HOLD verdict, a Weekly signal block (what to do, the record, the evidence checklist: ALADIN 1 technical and combined probabilities, Outlook, sentiment, supply-chain impact, forecast range, strategy states), the plan and size calculator for BUY.
- Nightly job gets a `weekly` step (writes ledger lines `wk` and `wkout`, `weekly.json`, scores finished weeks); the workflow runs it.
- **`signal_labels` is set to `directional` on this branch** (BUY / SELL / HOLD). Everything is still looked up through the labels dictionary and a neutral build is tested to contain none of those words. Switching back is one line.

## Decisions I need from you before this goes to `main`
1. **Legal.** Publishing BUY and SELL calls on a public site can amount to investment advice or research-analyst activity that needs SEBI registration in India. You told me you are checking. I have **not merged** this branch to `main` and have not pushed it. Say "merge" only once you are comfortable (or keep `neutral` wording, which is a one-line change and still shows the same ranking as BULLISH / BEARISH SIGNAL).
2. Do you want the BUY list at all, given its weaker evidence? A reasonable option is to publish SELL (exit / avoid) lists and show BUY as "watch" until the live record exists.
