# ALADIN 2.0, Phase 0: audit and protocol (2026-10-07)

Branch `feature/aladin-learning` (worktree `../SAMNIDHY_ALADIN2`), cut from `feature/aladin-nexus-desk` at ac95415. Nothing pushed, nothing merged to `main`. No product code yet.

## 1. What ALADIN is today, and its honest out-of-sample numbers
Walk-forward LightGBM ensembles (5/10/20-day "does it close higher" probability), isotonic calibration **nested year by year**, Fundamental/Sentiment/sweep/impact views combined in the browser, plus a paper trader with a 0.60 threshold.

| Item | Measured |
|---|---|
| ALADIN 5-day (2015-2026, n=303,966) | AUC 0.544, accuracy 53.2% vs base rate 49.2%, Brier 0.2483 vs 0.2502 base, top-decile hit 53.0%, bottom 42.4%, IC 0.067 (t 7.8) |
| Outlook (`predict_model.py`, 20-day beat-NIFTY, 2013-2026, n=1.22M) | AUC 0.534, accuracy 52.5% vs 49.7%, top-decile hit 54.3% / bottom 43.7%, top-decile excess +2.08% (gross) |
| Paper trader (since 2026-10-02) | 0 signals, 0 trades: P(up) never reached 0.60 |
| Regime blend, LSTM | tested, no out-of-sample gain, not used |

**Why it feels like jargon:** the tab shows AUC / Brier / "top 10% went up" and a sortable P(up) table. It never says what price range to expect, where a plan would be invalidated, how much to hold, or when to stand aside, and its one tradable output (paper trades) is empty. A probability near 53% cannot be acted on without those.

## 2. Corrections to the prompt's section 2
- **Theme:** the desk today is the dark "Midnight Slate" theme (`--paper #09090b`, `--ink #fafafa`, white accent), not beige/pine. Decision 1 says "keep the existing theme", so I keep what is on screen (tokens in `terminal.css :root`) and add nothing new. Please confirm. Screenshots: `docs/aladin2/phase0/`.
- `tests/test_no_lookahead.py` already tests that features up to date D do not change when later prices change (technical, jump, PCA, Kalman, pairs, HMM filtered), the purge gap per horizon and the paper trader's entry. Phase 1's `test_leakage.py` extends this; it does not start from zero.

## 3. Leakage audit of the existing code
Clean: purge gaps asserted (25 days Outlook, per-horizon in ALADIN); HMM filtered not smoothed; nested calibration in ALADIN's headline numbers; paper trader enters after the signal day's close.

Findings (disclosed, none changed, because Outlook stays as a benchmark):
1. **Outlook calibration is in-sample** (`predict_model.py:249`): isotonic is fitted on the full OOS record and then used to report Brier, decile calibration and "expected excess return". AUC, IC and top-decile hit are unaffected (monotone map); Brier and calibrated deciles are mildly optimistic. ALADIN's own code fixes this with nested calibration.
2. **ALADIN regime-blend choice** compares Brier over all years (a small selection leak); the blend lost and is unused, so no effect.
3. **Survivorship:** the universe is today's listings. Absolute returns below are flattering, especially for small caps; comparisons *between* benchmarks on the same names are fair.
4. **Labels have no costs**, and the headline metric is AUC, not tradable net expectancy.
5. The first two ALADIN test years lack earlier calibration and are excluded from headlines (fine).

## 4. Benchmark set measured (`scripts/aladin2/phase0_audit.py`, `data/aladin2/phase0_report.json`)
Long-only (no delivery shorts), 10-day hold, entry at next open, liquid names only (20-day avg traded value >= Rs 2 crore), 1,594 stocks, 660 weekly dates 2013-01-04 to 2026-09-15, **placeholder 50 bps round trip** (real model in Phase 1). Block-bootstrap 95% intervals.

| Benchmark | Gross per 10d | Net per 10d | Net minus equal-weight universe |
|---|---|---|---|
| Buy-and-hold, equal weight | +0.64% | +0.64% (one entry, no churn) | 0 by definition |
| Naive 12-1 momentum (long if > 0) | +0.78% | +0.28% | **-0.37%** [-0.47, -0.28] |
| ALADIN top decile (existing OOS score) | +1.20% | +0.70% | **+0.06%** [-0.16, +0.28] |
| Random walk reference | P(up) 49.8%, Brier 0.2500 | | |

ALADIN raw score Brier is 0.2508 (uncalibrated; the calibrated figure is in `latest.json`).

**Reading:** at a realistic cost level the existing ALADIN top decile does not detectably beat holding the liquid universe, and the naive momentum rule loses to it. The ranking skill is real (IC t = 7.8) but small next to a 50 bps round trip at 10-day turnover. That is the bar ALADIN 2.0 must clear. It suggests longer holds, selectivity (abstention) and per-stock evidence matter more than another model. Outlook as a *trading policy* cannot be re-scored: its per-row OOS predictions are not saved (only yearly metrics), so its published numbers are used; Phase 2 will persist them.

## 5. History depth and liquidity
- Daily bars: 2,969 stocks (median 1,238 in `daily`, plus a median 893 in `archive` for 1,782 of them). 2,051 have >= 750 bars; 1,309 have >= 2,500 (back to about 2008).
- Universe 3,523 (2,965 Main, 558 SME). Main-board non-ETF with 20-day avg traded value >= Rs 2 crore: about 1,500 today (1,594 in the 2013-26 sample, including names liquid at the time). NIFTY 500: 497.
- Product-state shares today: Validated 0%, Provisional 0%, Learning 100% (no ledger exists). Expected.

## 6. Source reachability (this PC, 2026-10-07; runner status unknown until a workflow runs)

| Source | Result | Depth / note |
|---|---|---|
| NSE delivery bhavcopy `sec_bhavdata_full_DDMMYYYY.csv` | 200 | **2020 onward** (404 for 2016-2019); has delivery %. Local cache only holds 2025-09 onward: backfill needed |
| NSE F&O bhavcopy (UDiFF 2026, old style 2022) | 200 | has open interest; put-call ratio computable |
| NSE F&O ban list `fo_secban_*.csv` | 404 | URL pattern wrong or moved; to find |
| NSE cash bhavcopy UDiFF | 200 | |
| NSE bulk / block deals csv | 200 | bulk 20 KB; block 111 B (nearly empty today) |
| NSE allIndices, corporate actions, event calendar APIs | 200 | WAF-protected; may block runner IPs (existing code already copes) |
| Yahoo India VIX, USDINR, Brent, S&P 500 (5y daily) | 200 | |
| Wikipedia pageviews API | 200 | |
| FRED | 400 | needs your free key (optional) |
| RBI policy page | 200 | HTML, needs parsing; dates may be hand-listed in config |
| BSE announcements API | 403 | blocked; use NSE filings (existing code) |

Not available free: historical index constituents; filing dates for old quarterly results (60-day lag fallback applies and will be stated).

## 7. Evaluation protocol I propose (section 6 of your prompt, with concrete choices)
1. Nested walk-forward, expanding window, 63-day test blocks, 20-day purge + 5-day embargo; strategy selection re-run inside each fold.
2. Net-of-cost metrics. Eligibility = BH-FDR q=0.10 on block-bootstrap p-values, >= 30 OOS trades, positive bootstrap lower bound, beats buy-and-hold and naive momentum, parameter plateau, >= 60% positive yearly blocks.
3. Hierarchical shrinkage stock -> sector -> universe.
4. Phase 2 headline test: ALADIN-as-policy net return per trade versus the equal-weight universe, 95% bootstrap interval, **reported as measured**; thresholds are not tuned to pass.
5. Benchmarks: the four above, same cost model and sample.
6. Cost model: values in `data/config/aladin2.json`; a worked trade in Phase 1.

## 8. GATE: what I need from you
1. Approve (or change) the protocol in section 7 and the source list in section 6.
2. Confirm: keep today's dark Midnight Slate theme (what is on screen), not beige/pine.
3. Optional key: `FRED_API_KEY`. Nothing else is needed for Phase 1.
4. Phase 1 needs a backfill of daily NSE delivery and F&O files (about 1,700 trading days each, polite rate), stored in gitignored `data/terminal/`. OK to run it in the background on this PC?
