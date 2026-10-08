# ALADIN: one front page (2026-10-09)

Written for: the project owner, to see what changed and what is still open.

## What the visitor sees
The **ALADIN** tab lists the week's signals with three things per stock: the signal (BUY / SELL / HOLD, words come from the labels dictionary), the target price and the stop loss. A search box finds any stock (symbol or name), signal or not. Clicking a stock opens a side sheet: Summary (levels, chances with 95% ranges, what to do, the same signal's history), How it was made (six steps, what pushed ALADIN 1's score, which inputs are in the rule), Range and chance (the forecast fan), Revenue dependencies (from NEXUS, with filing, page and quote, and a button to the full supply-chain view).

## What the two numbers are
- **Target price**: the upper edge (BUY) or lower edge (SELL) of the model's 5-day 50% price range. Chosen by the owner on 2026-10-09. "Not measured" when the stock has no forecast range.
- **Stop loss**: 2 x ATR under the price (BUY) or over it (SELL), the exit level the weekly plan already used.
- With a 50% range edge and a 2 x ATR stop, reward is usually below risk (about 0.6 for 1 in the first book). The page says so in plain words and shows the chance of winning next to it.

## ALADIN 1 versus ALADIN 2
They are not rivals. ALADIN 1 is the scoring engine (79 inputs, AUC 0.544, rank correlation 0.067 out of sample). ALADIN 2 is the decision layer on top of its 5-day score: rank rule, measured chances with intervals, costs, ranges, an append-only ledger. The weekly signal is computed from ALADIN 1's score. So the merged product is one page, ALADIN 1 inside, ALADIN 2 deciding.

## NEXUS
Shown per stock, not part of the rule. ALADIN 1 has an impact term but it cannot be validated yet (0 of 200 edge-days needed) and NEXUS has read 212 of 3,525 companies, 10 of 238 links carry a share. When the term passes its own test it is switched on by the existing weights logic.

## Forecast coverage 500 -> 1,500
`forecast.universe_top` (config) was fixed at 500. Re-running the out-of-sample coverage test on the point-in-time top 1,500 (`data/aladin2/phase3_top1500.json`): the 80% range held 79.1% to 79.7% at 1 to 5 days against 79.4% to 79.8% for the top 500; ECE 0.030 and 0.034 against 0.029 and 0.036. Calibration did not degrade, so every liquid stock in the weekly universe now gets a range, and therefore a target price. At 60 days ECE is worse (0.107 against 0.089); 60 days is range-only and not used here.

## UI patterns (designeer.xyz)
designeer.xyz is a directory of other people's component libraries (shadcn/ui, Radix, Tremor, HyperUI and others), not a library, and carries its own copyright line. No code was copied. These patterns were re-drawn in the desk's CSS with its own tokens: search field, toggle group, data table, badge, tabs, side sheet, stat card, marker bar (Tremor), stepper, bar list.
