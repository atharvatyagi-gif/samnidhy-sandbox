# ALADIN audit, phase 7: rules for the 4-week paper test (written 2026-11-13, before the first weekly report)

The paper account (Rs 1,00,000, model E exactly as live) placed its first orders after the 9 Nov close and bought at the
11 Nov open (10 Nov was an exchange holiday). A plain report is written every Friday evening after the daily run:
**13 Nov, 20 Nov, 27 Nov and 4 Dec 2026**. The last one gives the verdict: Continue, Fix or Stop, by the rules below.

Honest note: while checking the account's records were healthy (no missed day, no run before the close) I saw its value on
13 Nov (Rs 1,01,121). No rule below was moved because of it; none sits near that number.

## What 4 weeks can and cannot show

In the back-test (2010-2026, after costs, `aladin-audit/phase7/backtest_ranges.json`), model E lost money in 37 of every 100
four-week spans while still earning about 24% a year overall. So 4 weeks cannot prove E has an edge, and **beating or trailing
the NIFTY 500 over 4 weeks is reported but is not a rule**. The test checks two things only: (1) the machine works exactly as
written, (2) results stay inside what the back-test says is normal.

Back-test ranges (model E as live, 19-session spans):

| | worst 1 in 100 | worst 1 in 20 | typical | best 1 in 20 |
|---|---|---|---|---|
| 1 week (5 sessions) | -7.6% | -4.3% | +0.6% | +5.1% |
| 4 weeks (19 sessions) | -13.7% | -7.2% | +1.7% | +11.6% |

These flatter E (free data covers companies listed today only), so a live result a little worse is not by itself alarming.

## STOP if any one happens

- **S1 risk limit:** the kill switch fires, or the account falls more than 25% from its peak (the owner's limit).
- **S2 outside the back-test:** the account's return since the start is below -13.7% (worse than the back-test's worst 1 in
  100 four-week spans).
- **S3 money bookkeeping wrong and not fixable:** cash plus holdings at the close does not equal the reported value, a fill is
  not at that day's opening price, or the public signals do not match the account's holdings.

## FIX if any one happens (and no STOP)

- **F1 a missed or early run:** a trading day missing from the account's daily record, or a run that used prices before the
  15:30 close.
- **F2 weak but inside the range:** return since the start below -7.2% (worse than the back-test's worst 1 in 20). Find out
  why (the market, one stock, or the model) before going on.
- **F3 orders not filled:** more than 2 orders in the 4 weeks marked "not filled".
- **F4 a bookkeeping slip that was fixed:** any S3 problem found and corrected within the 4 weeks.

A Fix means: correct it, re-run the checks, and run 2 more weeks before the verdict is repeated.

## CONTINUE

None of the above. Continue means: keep the paper account running, keep publishing the signals, and keep the weekly report.
It does not mean the model is proven; that needs at least a year of live record.

## Not allowed

Changing these rules after a weekly report, adding a stop-loss without a new pre-written test, or changing model E's settings
during the 4 weeks.
