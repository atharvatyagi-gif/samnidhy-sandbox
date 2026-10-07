# ALADIN 2.0, Phase 2 (and 2b): strategies, the evaluation machine, pooled-first selection (2026-10-08)

Branch `feature/aladin-learning`. Nothing pushed or merged. `python -m pytest tests/aladin2` : **84 tests pass**.

## CORRECTION to my earlier Phase 2 message (read this first)
My first Phase 2 summary said short-term reversal rules earned +80 to +208 bps per trade and survived correction. **That was an artifact of my benchmark and is withdrawn.**
I measured "excess" against the stock's own average daily return over the test block. The sell-off that triggers a reversal signal sits inside that very block, so the benchmark was dragged down exactly for the trades that buy after drops. I then tried the stock's trailing drift (ex ante) and got the opposite bias, in favour of trend rules (drift persists, winners keep rising). Both are rejected in `evaluate.attach_benchmark` (docstring). The benchmark used from here on is the **equal-weight universe's return over the same trade days** (market-adjusted), which carries neither bias. The reversal result vanishes under it (reversal5_vol_2.0: +29 bps per trade, 95% interval -12 to +77, p = 0.11, not significant). The robustness file I built for it has been deleted. Tests now cover the benchmark and the point-in-time rules.

A second bias found and removed: "is in the NIFTY 500 **today**" already favours stocks that rose. The pooled work below uses a **point-in-time universe**: on each day only the 500 stocks with the highest trailing 250-day traded value *as of the previous close* count (1,445 stocks built from every liquid main-board name). Survival to today is still required (delisted stocks have no data), so a survivorship bias of unknown sign remains.

## What exists
- 34 strategies in 5 families (trend 11, reversion 12, volatility 6, relative strength 3, delivery flow 2) plus a naive 12-1 momentum baseline; each has a look-ahead unit test. Not built: fundamental, event, text/graph, ML families.
- `evaluate.py`: nested walk-forward, bootstrap, BH false-discovery control, empirical-Bayes shrinkage, stability/plateau/recent-window checks, market-adjusted benchmark, **block bootstrap over calendar months (block = twice the holding time, because long trend trades overlap)**.
- `lifecycle.py`: Candidate, Probation, Active, Demoted, Retired with PSR/DSR, CUSUM, active cap, fresh-evidence re-entry; every transition emits an evidence event.
- `pooled.py` (new, the design you chose): strategies are promoted on pooled evidence across the universe, then each stock's own record tilts or vetoes.

## 1. Per-stock selection (the original design), real data
NIFTY 500 liquid members, 425 stocks, 56 unseen blocks 2012-2026, real costs, 2,951 to 6,532 pairs per block: **0 pairs pass the false-discovery filter in any block** (best pair p = 0.001 against a bar near 1.6e-5). Unchanged by the benchmark correction: per-stock evidence is too thin (30-70 trades with 5-15% standard deviation against a 0.5% cost).

## 2. Pooled-first selection, nested walk-forward (point-in-time top-500 universe)
Strategies are promoted when, using only earlier data, the pooled mean excess passes BH (q = 0.10) across the 34 strategies, its lower bound is above 0, neighbouring settings agree, at least 60% of years are positive and the last 500 days are still positive. Replay over the same 56 blocks; paper-trading every Probation or Active strategy:

| | Trades | Avg days held | Excess per trade (95% interval, month blocks) | Excess per day invested | Win rate |
|---|---|---|---|---|---|
| Pooled-first policy, Probation + Active (with stock veto) | 4,663 | 73 | **+123 bps** [+9, +263] | **+1.7 bps** | 37% |
| Same, no stock veto | 5,387 | 68 | +142 bps [+11, +271] | +2.1 bps | 37% |
| **Active tier only** | 496 | 113 | +12 bps [-200, +221] (not distinguishable from zero) | **+0.1 bps** | 30% |
| Naive 12-1 momentum, every stock | 103,841 | 10 | -20 bps [-27, -13] | -2.0 bps | 49% |
| All 34 strategies, no selection | 1,116,628 | 15 | -11 bps [-22, +3] | -0.7 bps | 43% |

Reading it plainly: the policy beats the naive baseline, but **it is weak and unstable.** It was promoting something in only 7 of 56 blocks (trades happened in 48 of 172 months), strategies churned (15 Probation to Demoted, 15 Demoted to Retired, 10 re-entries), the gain is concentrated in 2014 (+703 bps) and 2016 (+171), it was negative in 2015, 2024 (-144) and 2025 (-49), and the Active tier, the one meant to be trusted, shows no excess. The stock veto did not help. I would not call this an edge.

### Pooled evidence over the whole 2012-2026 unseen period (34 pre-defined hypotheses, BH q = 0.10, no selection)
**7 of 34 pass, all trend-following**: ma_cross_50_200 (+682 bps per trade, +4.9 per day, [+326, +1,072]), donchian_100 (+523, +4.7/day), ma_cross_20_100 (+376, +4.8/day), donchian_55 (+228, +3.3/day), tsmom_250 (+140, +3.1/day), ma_cross_10_50 (+116, +2.9/day), tsmom_120 (+83, +3.0/day). Reversal, breakout, volatility, relative-strength and delivery rules do not pass. These per-day figures (+3 to +5 bps a day, roughly 8-12% a year while invested, over an equal-weight market, after costs) are the best honest estimate of a trend-following edge in this data; but see the instability above: the same rules were not provable at the time in most blocks.

## 3. Why I am not calling any of this an edge yet
1. Survival to today is required, so the loser tail (delisted names) is missing. Trend rules would partly have avoided losers and partly never held them: the sign is unknown.
2. The benchmark question already cost one false result. The market-adjusted benchmark is the cleanest I have, not a proof.
3. Instability: real-time promotion was intermittent and the last two years are negative.
4. Trend trades are long (40-140 days) with a 30-37% win rate: they pay off through a few large winners; the evidence rests on tails.

## 4. Honesty experiments (brief 6.7)
Rerunning with the corrected benchmark (the earlier numbers are retired). Pending in the background: planted edges, 2,000 noise series with real costs and with zero costs. They will be added in `data/aladin2/honesty_*.json` and to this report. For orientation, before the correction: noise 0 of 58,000 pairs promoted; planted reversion found 12 of 12, momentum 92% at its middle strength; a vanished edge took a median 628 days to be demoted (a real limitation, not met).

## 5. Product states and compute
Validated 0%, Provisional 0%, Learning 100%: nothing has a live record. Per-stock run 117 s; pooled-first run about 3 minutes on 14 cores; universe build (1,445 stocks x 35 strategies) about 3 minutes.

## GATE: what I need from you
1. Phase 3 (forecast ranges, calibration) does not depend on the signal question: a forecast range with honest coverage is useful even where there is no directional edge. OK to proceed with Phase 3 now, with directional signals shown only as "NO EDGE" unless a strategy is Active?
2. Or first spend one more experiment on the trend result: a delisting-risk stress test and a run on a smaller-cap universe (free data may not allow this).
