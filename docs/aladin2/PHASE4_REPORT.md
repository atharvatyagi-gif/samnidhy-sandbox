# ALADIN 2.0, Phase 4: meta-learner, signals, risk, ledger, kill switches (2026-10-08)

Branch `feature/aladin-learning`. Nothing pushed or merged. `python -m pytest tests/aladin2` : **110 tests pass**.

## What was built
- `ledger.py`: append-only monthly JSONL (`data/aladin2/ledger/YYYY-MM.jsonl`). Line types: forecast batch, signals, outcome, correction. A second, different line for the same key is refused; identical re-writes are no-ops; corrections are new lines. `stats()` recomputes every live number from the raw lines. A forecast counts as LIVE only if it was created before the day it targets.
- `signals.py`: product states (Learning, Provisional, Validated, Suspended), the signal rule, stop choice, entry zone, profit levels, plan evaluation by simulation (stop-out probability, expected R, touch days), position sizing, portfolio layer, paper book. All wording goes through one `label()` lookup.
- `meta.py`: Hedge weights per regime with floor and cap (exact projection), Thompson weights, filtered 2-state HMM stress probability (fit on a fixed early window, so later data never changes earlier values), isotonic calibrator with pooled fallback.
- `kill.py`: engine, sector and stock suspension from live ECE, live interval coverage, CUSUM; banners.
- `live.py`: the daily run. `sample_plans.py`: ten illustrative plans.

## The forward clock has started
First batch written: as-of close **2026-10-06**, 500 stocks (point-in-time top 500), horizons 1, 5, 10, 20, 60 days, 50/80/95% price bands, P(up) for 1 and 5 days only. Created 2026-10-08 05:46 UTC. Size 169 KB for the day (about 40 MB a year before git compression; `check_aladin2.py` in Phase 5 will watch the 250 MB cap).
**Caveat built into the rules:** the 1-day forecast targets 2026-10-07, which had already happened when I wrote it, so it is stored but excluded from live statistics. The 5-day and longer forecasts are genuinely forward. Run time of the whole daily job: 76-81 seconds (panel 36 s, five horizon fits 9 s each).

## Product states and abstention today
| State | Stocks |
|---|---|
| Validated | 0 |
| Provisional | 0 |
| Learning | **500 (100%)** |
| Suspended | 0 |
All five trend strategies that had passed the pooled test in the replay are **Retired** at the end of the replay (their evidence faded in 2025), so no strategy is on today. Abstention rate: **100%, every stock reads NO EDGE: stand aside and shows only its forecast range.** No trade plan is produced for any stock.

## Ten illustrative plans (not signals; machinery check on real forecasts, as of 2026-10-06)
Horizon 20 days, zero-drift simulation fitted to the conformal 80% band; size for Rs 10 lakh capital at 1% risk with a **hypothetical** +1% per-trade edge (sd 8%), because the real shrunk edge is zero and the size would be 0. "Profit levels" are band levels and levels with at least 50% touch probability (in a neutral-wording build these are "profit levels").
| Stock | Close | Entry zone | Invalidation level | 80% range | Levels (P(touch), typical day) | P(stopped out in 20d) | Expected R | Hypothetical qty / loss at stop |
|---|---|---|---|---|---|---|---|---|
| BAJFINANCE | 959.55 | 953.69-965.41 | 924.37 (3.67%) | 895.8-1040.41 | 974.73 (65%, d4); 1000.63 (37%, d9); 1040.41 (14%, d13) | 41% | 0.041 | 104 / Rs 3,659 |
| HDFCBANK | 712.5 | 708.98-716.02 | 691.4 (2.96%) | 659.8-764.17 | 723.43 (65%, d4); 738.16 (42%, d8); 764.17 (18%, d10) | 51% | 0.026 | 140 / Rs 2,954 |
| INFY | 1007.0 | 1000.59-1013.41 | 968.55 (3.82%) | 918.27-1100.5 | 1026.3 (63%, d4); 1053.93 (39%, d8); 1100.5 (17%, d12) | 47% | 0.033 | 99 / Rs 3,807 |
| ITC | 265.25 | 263.98-266.52 | 255.12 (3.82%) | 246.25-284.7 | 269.39 (63%, d5); 274.33 (41%, d8); 284.7 (18%, d13) | 39% | 0.057 | 377 / Rs 3,820 |
| LT | 3754.4 | 3739.65-3769.15 | 3655.9 (2.62%) | 3557.02-3982.68 | 3798.22 (66%, d4); 3870.96 (37%, d8); 3982.68 (15%, d13) | 44% | 0.035 | 26 / Rs 2,561 |
| MARUTI | 11567.0 | 11509.25-11624.75 | 11220.53 (3.0%) | 10751.56-12480.77 | 11756.41 (65%, d4); 12036.47 (39%, d8); 12480.77 (17%, d12) | 48% | 0.117 | 8 / Rs 2,772 |
| RELIANCE | 1215.2 | 1210.18-1220.22 | 1175.01 (3.31%) | 1144.54-1294.84 | 1231.39 (64%, d5); 1253.42 (40%, d8); 1294.84 (15%, d12) | 38% | 0.03 | 82 / Rs 3,295 |
| SUNPHARMA | 1789.0 | 1781.82-1796.18 | 1745.91 (2.41%) | 1690.9-1914.85 | 1812.18 (62%, d4); 1854.39 (35%, d9); 1914.85 (13%, d12) | 52% | 0.002 | 55 / Rs 2,370 |
| TATASTEEL | 177.7 | 176.62-178.78 | 171.21 (3.65%) | 162.67-195.08 | 181.09 (63%, d4); 185.84 (39%, d8); 195.08 (15%, d12) | 48% | 0.061 | 562 / Rs 3,647 |
| TCS | 2087.6 | 2074.29-2100.91 | 2007.72 (3.83%) | 1894.28-2295.34 | 2130.35 (65%, d5); 2192.29 (41%, d8); 2295.34 (17%, d12) | 48% | 0.11 | 47 / Rs 3,754 |
Reading: with a 2-ATR stop, a stock is stopped out in 4 of 10 20-day windows even with no drift at all; expected R is about zero because the simulation has zero drift (the small positive values are volatility convexity). Every position size is bound by the 10% max-position rule, not by risk. The loss shown is the loss if the stop fills exactly at the stop; the plan simulation exits at the breach close, because stops are not guaranteed fills (overnight gaps and circuit limits can exceed the stop).

## Tests (acceptance items 8-11 and 15 in part)
- Ledger: append-only, duplicate and conflict handling, corrections as new lines, resolution marks, statistics reproduce from raw lines, late forecasts excluded.
- Risk maths with fixtures: each limit binds in turn (risk per trade, max position, liquidity 5% of ADV, fractional Kelly), zero for a non-positive edge, drawdown brake halves, correlation reduces, sector cap, open-signal cap, capital at risk is one function (`capital_at_risk`) that the UI must call.
- Abstention and states: Learning/Provisional/Validated/Suspended ladder; a forced calibration break flips a stock to Suspended and its signal to NO EDGE; sector and engine suspension.
- Meta-learner: weights respect floor and cap and follow outcomes; stress probability does not change when later data arrives.
- Neutral wording contains none of the banned words; the disclaimer string is the configured one.

## Not done, and deviations
- **Deviation:** the brief gates a signal on p >= 0.58. Phase 3 showed P(up) has no skill, so a signal needs a Validated stock, an Active strategy and an edge above the cost buffer instead.
- **Not measured, stated in the plans:** results, ex-dividend and RBI dates (no calendar wired), so "event warnings" cannot fire yet; correlation clusters (the function hook exists, no matrix yet); strength buckets (Low until a bucket has 100 live outcomes).
- Nightly workflow, discovery, journal and the size checks are Phase 5. Live statistics will take weeks to show anything: coverage needs 300 resolved forecasts per horizon (a few days at 500 stocks), calibration of P(up) needs 300 resolved 1-5 day forecasts, and a Validated stock needs 60 live days.
- Product-state shares: Validated 0%, Provisional 0%, Learning 100%.

## GATE: what I need from you
1. Review the ten sample plans and the abstention rate (100% NO EDGE today).
2. OK to start Phase 5: the nightly workflow (`aladin2.yml`), grammar-bounded discovery, journal, probation logic with drift detection, historical replay showing promotions and retirements, size checks? The first ledger file should be committed on this branch so the forward clock is in git history; say if you want that committed now on its own.
