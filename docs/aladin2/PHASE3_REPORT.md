# ALADIN 2.0, Phase 3: forecasts (2026-10-08)

Branch `feature/aladin-learning`. Nothing pushed or merged. `python -m pytest tests/aladin2` : **90 tests pass**. Raw numbers: `data/aladin2/phase3_report.json`.

## What was built (`forecast.py`, `run_phase3.py`)
For each stock and horizon 1, 5, 10, 20, 60 trading days: (1) a **HAR volatility model** (pooled OLS on log Garman-Klass daily variance at 1/5/22/66 days plus the market's variance) gives the forecast standard deviation; (2) **LightGBM quantile regression** of the return in volatility units, 7 quantile levels, sorted so they never cross; (3) **split-conformal (CQR) correction** per 50/80/95% band, learned on the most recent 730 calendar days before each test year (purged 100 days), never on training data; (4) **P(up)** read off the corrected curve then calibrated by isotonic regression on the same untouched window; (5) a **path simulator** (GARCH-type variance recursion with bootstrapped standardised residuals), rescaled so its 80% band matches the conformal band, for the fan, P(touch a level before a date) and excursions.

Evaluation: point-in-time top-500 universe (the 500 most-traded stocks as known the day before; survivors to today only), 467,500 rows (every 5th day), 1,121 stocks, **test years 2012-2026, each forecast by models trained and calibrated only on earlier data**. About 360,000 unseen forecasts per horizon. Run time 3.5 minutes on 8 cores.

## Result 1: interval coverage (nominal 50 / 80 / 95%, tolerance 4 points)
| Horizon | 50% band | 80% band | 95% band | Before conformal 50/80/95 | Plain "HAR + normal" 50/80/95 |
|---|---|---|---|---|---|
| 1 day | 49.4% | 79.4% | 94.6% | 43 / 73 / 91 | 67 / 89 / 96 |
| 5 days | 49.3% | 79.9% | 95.0% | 41 / 72 / 91 | 62 / 86 / 96 |
| 10 days | 49.2% | 79.3% | 94.8% | 41 / 70 / 90 | 62 / 87 / 96 |
| 20 days | 48.9% | 79.0% | 94.5% | 40 / 68 / 89 | 61 / 86 / 96 |
| 60 days | 48.4% | 78.2% | 93.7% | 40 / 69 / 88 | 60 / 86 / 96 |

**Pooled coverage is within the 4-point tolerance everywhere (worst gap 1.8 points).** The conformal step is what does it: the raw quantile model is overconfident (70% for an 80% band), and the normal-distribution baseline is too wide in the middle (fat tails). Coverage by volatility third at 80%: calm 77-78%, middle 79%, turbulent 80-81% (slightly narrow in calm periods).
**Not within tolerance year by year at long horizons:** the worst single-year gap is 4-6 points at 1 to 10 days, 14 points at 20 days and 22 points at 60 days (stress years such as 2020). A calibration window of the previous two years cannot know a crash is coming. The live system therefore keeps the brief's rule: realised coverage is tracked on the ledger and, when it leaves the tolerance, the bands widen automatically and the stock is flagged (Phase 4).

Typical band widths (80%, in forecast standard deviations): 1.94 at 1 day, 2.20 at 5-10 days, 2.26 at 20 days, 2.29 at 60 days.

## Result 2: the median and sharpness
The quantile model's pinball loss is **not better** than the unconditional quantiles of the volatility-scaled return (for example at the median: 0.315 vs 0.309 at 1 day; 0.366 vs 0.342 at 20 days). The value is in the **volatility scaling and the honest coverage**, not in a directional centre. The forecast is a range centred near zero drift.

## Result 3: P(up) calibration (the ECE gate, limit 0.05)
| Horizon | Base rate up | ECE raw | ECE after isotonic | AUC | Brier vs base-rate Brier |
|---|---|---|---|---|---|
| 1 day | 46.9% | 0.054 | **0.029** | 0.504 | 0.2531 vs 0.2491 |
| 5 days | 49.6% | 0.069 | **0.036** | 0.505 | 0.2543 vs 0.2500 |
| 10 days | 50.9% | 0.089 | 0.053 | 0.492 | 0.2543 vs 0.2499 |
| 20 days | 52.4% | 0.092 | 0.065 | 0.490 | 0.2548 vs 0.2494 |
| 60 days | 54.1% | 0.105 | 0.089 | 0.475 | 0.2619 vs 0.2483 |

**Gate: met at 1 and 5 days; just missed at 10 (0.053); missed at 20 and 60.** Written explanation: the model has **no directional skill** (AUC 0.48 to 0.50, Brier no better than always saying the base rate), so P(up) is essentially "the base rate", and the base rate itself swings by year: the share of 60-day returns that are positive was 33% in 2018, 74% in 2023, 71% in 2014, 68% in 2020. A calibrator trained on the previous two years is off by 12.7 points on average in the next year at 60 days (7.4 at 20 days). Even a constant, all-history base rate is off by 9.8 points (60 days) and 5.6 (20 days) year by year, so no probability built from this information can reach ECE 0.05 at long horizons across regimes. This is a property of markets, not a bug.
**Plan (to be applied in Phase 4/6):** show P(up) as a number only for 1-5 days (calibrated); for 10 days and longer show the range and the plain statement "about X% of the time stocks like this closed higher over N days historically: no directional information", using a long-run base rate (slightly better than the isotonic version: 0.065 vs 0.074 and 0.112 vs 0.127 yearly gap), never a confident-looking probability.

## Result 4: path simulator and barrier probabilities (20 days, 4,000 random forecasts)
Predicted vs realised probability that the close touches +1 sigma / -1 sigma of the 20-day range at some close before the date:
| | Predicted | Realised | ECE |
|---|---|---|---|
| Touch up | 20.5% | 18.7% | 0.038 |
| Touch down | 19.4% | 16.6% | 0.030 |
| Simulator before band-fitting: up / down | 22.3% / 21.4% | | 0.041 / 0.059 |
| 80% band from paths, coverage | 82.5% (nominal 80%) | | |
The simulator overstates touch probabilities by 2 to 3 points after fitting to the conformal band (5 points before). Acceptable for a displayed probability rounded to 5 points; flagged in the methodology text. Not validated: touch probabilities at other levels, horizons other than 20, and expected-date-of-touch.
A bug found and fixed along the way: a stretch of zero returns made the filtered volatility tiny and one standardised residual astronomical, which collapsed every simulated path to zero width (predicted touch probability 0.0); residuals are now winsorised at 8 sigma.

## What this means for the product
- **The forecast range is real and honest**: 80% of the time the price stays inside the 80% band, pooled, out of sample, including 2020, with the caveat above for individual crash years.
- **There is no directional edge in this engine**: P(up) is the base rate.
- Honesty numbers from Phase 2 (reproduced with the corrected benchmark) are in `PHASE2_REPORT.md`: noise 0 of 58,000 pairs promoted (real and zero costs); planted reversion found 100%; momentum 92% / 75% / 25%; vanishing edge not met (median 848 days to demotion).

## Other items
- Not done in Phase 3: the "dates on which each level is most probable to be touched", event-day jump adjustments (results dates), India VIX blending beyond its use as a feature. The path simulator works from one pooled residual pool, not each stock's own history.
- Sources: all inputs are prices, India VIX and the NIFTY index, which are reachable. No new data was needed.
- Product-state shares: Validated 0%, Provisional 0%, Learning 100% (ledger starts in Phase 4).

## GATE: what I need from you
1. Accept the P(up) plan above (number only for 1-5 days, base-rate statement for longer horizons)? It means the ECE gate is met where a calibrated number is shown and explained where it cannot be.
2. OK to start Phase 4: signal rules, trade plan and sizing, ledger, kill switches, and the start of the live forward clock? With no Active strategy the signal will read "NO EDGE: stand aside" and show only the forecast range, unless the pooled trend rules reach Active in live paper-forward trading.
