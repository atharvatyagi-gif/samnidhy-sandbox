# ALADIN 2.0, Phase 5: the self-learning loop (2026-10-08)

Branch `feature/aladin-learning`. Nothing pushed or merged. `python -m pytest tests/aladin2 tests/test_workflows.py tests/test_check_banned.py` : **133 tests pass**.

## What was built
- `run_nightly.py`: the orchestrator. Steps ingest, resolve, learn, drift, discover, forecast, publish; time budget (default 110 min); `--resume` skips steps done earlier that day; each step may fail without stopping the others (failures go to `run_report.json`); job summary table; weekly (Sunday) refit flag.
- `discover.py`: a typed grammar of rules (16 primitives with fixed threshold grids, up to 3 conditions, optional calm-market filter, 5 holding rules). A candidate is data, not code: one fixed interpreter turns it into a signal (a test shows unknown primitives, off-grid thresholds and strings are refused). Search by mutation, crossover and random restarts with a complexity penalty. Every distinct rule has a canonical hash (the same rule in a different condition order is one rule); a rule is never tested twice; the bar rises with the number of rules ever tested (p <= 0.1 / number tested), plus a survivorship stress (the edge must survive losing 100 bps a trade) and a positive result on a holdout the search never saw.
- `journal.py`: every transition and search result becomes a plain-language event built from its numbers; written once (key), newest 500 published as `journal.json`.
- `drift.py`: PSI, KS and volatility-regime-break checks on the features a strategy uses.
- `lifecycle.py` / `pooled.py`: probation with paper-forward evidence, promotion by month-clustered test, CUSUM, drift alarms feeding the next block boundary, retirement and fresh-evidence re-entry, all as in Phase 2b.
- `aladin2.yml` (workflow), `requirements-aladin2.txt`, `check_aladin2.py` (fails above 250 MB total, 60 MB per ledger month, 5 MB per shard, any model binary above 5 MB; warns at 150 MB / 30 MB).

## Replay: the engine fed one day at a time (2025-07-30 to 2025-08-08, 8 trading days, 60 most-traded stocks for the forecast step)
`ALADIN2_ASOF` makes every loader (including worker processes) see only data up to the simulated day; a new ledger, state and journal are written under `data/aladin2/replay/`.
| Day | Notes | Total |
|---|---|---|
| 07-30 | learn 93 s: rebuilt 1,445 stocks x 35 strategies and replayed all blocks to that date: **47 lifecycle events written to the journal** | 110 s |
| 07-31 | learn took 1,877 s: this PC paused mid-run (the clock jumped; same machine pauses noted before), not the engine | 1,892 s |
| 08-01 | learn: cache hit (no new block, same strategies); forecast 14 s | 15 s |
| 08-04 | cache hit | 14 s |
| 08-05 | a new block had started on 08-04: **two events appear**, both Retired | about 75 s |
| 08-06 to 08-08 | cache hits | 14-16 s |
A normal day on this 14-core PC: **about 15 seconds on 60 stocks when no block boundary is crossed, about 75-110 seconds on a boundary day.** Ledger: 1-day to 5-day forecasts written and **resolved** as the simulated days passed (1 outcome line from 07-31, 2 per day later).

### The journal after the replay: 50 events
5 started paper-trading (Probation), 2 promoted to Active, 17 demoted, 15 retired, 10 re-entered with fresh evidence, 1 search summary. Examples, verbatim:
- 2014-01-17: *Started paper-trading Moving-average crossover (ma_cross_50_200) across the universe: out of sample it earned +407 bps per trade over 2330 trades (lower bound +88 bps, positive in 5/7 years, false-discovery test p = 0.00167).*
- 2014-04-25: *Demoted Moving-average crossover (ma_cross_50_200) across the universe: it no longer passes the evaluation protocol on the latest data.*
- 2014-07-24: *Restored Moving-average crossover (ma_cross_50_200) across the universe to Active: it passes the evaluation protocol again (2448 trades, +390 bps).*
- 2025-08-04: *Retired Moving-average crossover (ma_cross_50_200) across the universe: did not recover within 40 days. It is archived, never deleted, and can return only with fresh out-of-sample evidence.* (and the same for Time-series momentum, tsmom_250_skip21)
So promotions and retirements with evidence are shown. Over 2012-2026 the five trend rules were each promoted, demoted and retired repeatedly: the churn itself is the finding (see Phase 2b).
The one gap: a block that starts on the very last day of data is only processed the next day (a one-day lag in `folds()`); harmless, noted.

## Discovery: what it found, and an error I caught
First run (24 rules a batch, 150 stocks, 3 generations, replay as of 2025-08-05): **72 rules, 9 "passed"**. Reading them: all nine were oversold / deep-drawdown dip-buying rules held while the signal is on (for example "price more than 20% below its 200-day average"), three of them the same rule written in a different condition order (so my hash let duplicates through and counted them as separate tests). Buying stocks that have fallen deeply and are still listed today is exactly the case where a survivors-only history flatters results (the Phase 2b break-even: if only 1.5-3% of such entries ended at -50% to -100% and are missing, the edge is gone). Fixes: canonical rule hash; a survivorship stress of 100 bps a trade; and the rule that discovered rules are only Candidates (they must still pass the pooled lifecycle and earn live paper-forward evidence, which has no survivorship problem because the forward universe is known at the time).
Second run after the fixes: **96 distinct rules tested, 0 passed** (one summary line in the journal). A pure-noise universe promotes nothing through the same pipeline (tested). Discovery cost: about 10 seconds per generation of 24 rules on 150 stocks with 14 cores.

## Compute: measured here, estimated for GitHub (not measured there)
| Step | This PC (14 cores), measured | GitHub 2 vCPU, my estimate (about 7x) |
|---|---|---|
| ingest (10 days of NSE files, macro) | not run in replay | 3-5 min |
| learn, boundary day | 60-95 s (U build included) | 7-12 min |
| learn, other days | 0 s (cache) | 0 |
| forecast, 500 stocks | 76-81 s | 8-10 min |
| discover, capped by `discovery_budget_min` | 10 s a generation | 25 min cap |
| install, caches, git | | 5-10 min |
Estimated total 25-60 minutes against the 110-minute budget. **Unverified until the workflow runs on GitHub.** The workflow cannot run until this branch is merged to `main`, and it needs a `FRED_API_KEY` repository secret (without it the 10-year yield is skipped and said so).

## Other items and honesty notes
- Drift alarms and Active-strategy demotions are unit-tested but never fired on real data in the replay, because no strategy was Probation or Active at the end of 2025-07; the drift step reported "no Probation/Active strategy to check".
- The ledger is already running (the forward clock): the replay ledger is separate and is not the live one.
- Weekly full refit: the quantile models are refit every night in this version (about 45 s for 500 stocks), so the Sunday flag changes nothing yet except being recorded.
- Product-state shares: Validated 0%, Provisional 0%, Learning 100%.
- Deviation: discovery's search-wide bar is a Bonferroni-style p <= q / (rules tested so far), stricter than the BH used elsewhere, because the number of tests has no natural block.

## GATE: what I need from you
1. Review the journal sample and the discovery finding (nothing passes once survivorship is stressed).
2. OK to start Phase 6 (UI and charts): ALADIN brief with the fan chart, strategy panel, risk panel, scoreboard, market map, sector rotation, learning journal and learning curve, in the existing dark theme?
3. For the workflow to run on GitHub: merge to `main` (your decision) and add the `FRED_API_KEY` secret. Nothing is pushed until you say so.
