# ALADIN audit, Phase 5: the single model is built

Written 2026-11-10. Everything is on the `aladin-audit` branch; nothing is on the live site yet.

## What was built
| File | What it does |
|---|---|
| scripts/aladin_e.py | Model E: ranks the 500 most-traded stocks by 6-month return, the best 5% form the portfolio, daily NIFTY 500 risk check, paper account with fills at the next open after all costs, degraded state, kill switch, one-day-loss rule, data-error check |
| data/config/aladin_e.json | Its settings (from the approved spec) and costs |
| data/config/aladin_e_calibration.json | The measured result of each rank group with 95% ranges (aladin-audit/scripts/e_calibration.py) |
| tests/test_aladin_e.py | 11 tests (below) |
| .github/workflows/daily-update.yml | Runs model E every evening after the prices are saved |
| aladin-audit/HOW_ALADIN_WORKS.md | Rewritten for E, with the same three worked examples; the old description kept below it |

Every output carries a rank, a measured result with a 95% range, an as-of date and the model version; there is a clear "No signal"
state; costs are in every fill; position size is equal weight (about 2.8%), capped at 5% (a quarter of the measured Kelly fraction
is 8%); loss limits per trade (the position cap) and per day (no buys after a 4% one-day fall); a kill switch at −25% and a
degraded status when data is stale.

## Tests (11, all passing)
| Test | Phase 2 issue it guards against |
|---|---|
| Ranks use only data up to the signal day | date alignment / look-ahead |
| Orders fill at the next open, never at the signal close | date alignment |
| Running twice on the same evening changes nothing | repeated nightly runs (found in Phase 1) |
| Stale prices make the model degraded with no orders | missing / stale data |
| Index below its 200-day average halves the invested share | risk rule |
| Kill switch stops buying after −25% | the owner's limit |
| Costs include STT, stamp, GST, slippage and the DP charge | costs |
| Position size never above the cap | sizing |
| Calibration groups ordered, each average inside its range | calibration |
| No price target in the page's data; version stated | the "target" display issue |
| A one-day jump beyond any price band is treated as a data error | unadjusted splits / demergers |

The Phase 2 display bugs on the old pages (red stop, < 50% = red, calendar shown as a reason) were fixed on main on 2026-11-08
and have their own test (tests/test_aladin_model.py).

## Before and after (same dates: Jan 2017 to May 2026, after costs, ₹1,00,000 start)
| | Per year | Worst fall | Sharpe | Trades | Won after costs | Net per trade | ₹1 lakh became |
|---|---|---|---|---|---|---|---|
| **E as specified (70% invested)** | **25.2%** | **−24.7%** | **1.37** | 702 | 46.7% | +9.6% | ₹7.85 lakh |
| E fully invested | 33.1% | −36.3% | 1.27 | 702 | 46.7% | +9.6% | ₹13.7 lakh |
| Old: weekly BUY rule (live until now) | 13.2% | −37.1% | 0.62 | 1,746 | 49.3% | +0.3% | ₹3.12 lakh |
| Old: ALADIN 1, 10-day, top tenth | 9.4% | −40.5% | 0.61 | 5,253 | 51.6% | +0.6% | ₹2.28 lakh |
| NIFTY 500 (price index) | 14.0% | −38.3% | 0.88 | – | – | – | – |

What this means: E fits the −25% limit and, in this test, earned far more per trade with far fewer trades. The old weekly rule's
result depends heavily on its start date (7.1% a year in Phase 4's walk-forward from 2015, 13.2% here from 2017): with about five
stocks a week, luck dominates.

Limits that still apply: companies listed today only (about half of E's tested edge may be survivorship), no result passed the
strict luck test, the last six months were flat, and E wins on fewer than half its trades: it relies on a minority of large
winners.

## How to undo
All on the `aladin-audit` branch; nothing merged. Delete the branch or revert its Phase 5 commit.

## Next: Phase 6 (needs your approval)
The public ALADIN tab shows only E (market-state strip, ranked list with "No signal", plain reasons, model health, paper log,
alerts). The old models leave every public page and move inside ALADIN BOT with their data encrypted with the same code; they
keep running and learning every night. The paper account starts on the first nightly run after merging.
