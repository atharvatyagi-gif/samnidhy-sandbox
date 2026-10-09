# ALADIN paper-trading bot (2026-10-09)

Written for: the project owner, to judge what the paper account shows and what it does not.

## What it is
A simulated, long-only account with a fixed budget of Rs 10,00,000. It trades the weekly Friday book of positive signals by written rules (see `scripts/aladin2/paper.py`, top of file; the same rules are printed on the page). Nothing touches a broker.
One simulator serves both the history and the live test, so they cannot drift apart. The live test is replayed from the immutable ledger every night, so it is auditable.

## Rule v3 (current, owner's choice O7, 2026-10-09, before any live trade)
Exit only at the open of the 5th trading day (the stop level still sizes the trade and is shown, but is not an order); 2% of the account at risk per trade, at most 20% in one stock (the Kelly cap of 18.75% often binds); cash not in stocks earns a liquid fund's return (India call-money rate from FRED IRSTCI01INM156N minus 0.30% a year), kept in its own pot. Chosen from `scripts/aladin2/paper_options.py` (data/aladin2/paper/options.json). O7 was added after the first option results were seen, so its history is the weaker claim.

| History 2013 to 2026 (same caveats as below) | Return | Per year | Worst fall | Win rate | Profit factor |
|---|---|---|---|---|---|
| v3 (the bot now) | +1,249% (Rs 10 lakh to Rs 1.35 crore) | +20.8% | -27.5% | 51.6% | 1.26 |
| v2 (dropped) | +223% | +8.9% | -24.4% | 51% | 1.20 |
| NIFTY 50 held (price index) | +285% | +10.3% | -38.4% | | |
Losing years: 2022 (-1.8%), 2025 (-6.9%). Bigger positions magnify the survivorship bias (stocks listed today) as much as the edge. Average 57% of the account in stocks.

## Rules (v2, kept for the record)
Enter at the next trading day's open. Size: 1% of the account at risk to the stop, at most 10% in one stock, at most 5% of its daily volume, at most 10 stocks, at most 30% in one sector. Exit at the stop (or the open if the stock gaps through it) or at the open of the 5th trading day after entry. Every leg pays the full Indian delivery cost model at the stock's liquidity decile. The price goal is shown but is not an order.

## Rule history (kept in the open)
- v1 (declared before any result): stop + goal + time. Full 13-year history: **-6.9%**. 62% of trades hit the goal, but the average win was +2.3% against an average loss of -3.8%: a take-profit at the 50% range edge cuts the winners.
- v2 (the same day, before any live trade existed, so the live record is untouched): stop + time.
Both and "time only" stay in the output as an ablation.

## History result (HISTORICAL SIMULATION 2013 to 2026)
ALADIN 1's walk-forward scores, stocks listed today (flatters the positive signals), goal is a volatility stand-in, cash earns nothing, no tax.

| | Return | Per year | Worst fall |
|---|---|---|---|
| Bot (stop + time) | +223% | +8.9% | -24% |
| Market held at the bot's average exposure (40% stocks, 60% cash) | +120% | +6.5% | -24% |
| Market, all money in the liquid stocks every week, before costs | +485% | +15.1% | -51% |
| Time-only exit (no stop) | +324% | +11.1% | -21% |

So the bot beats the fair comparison (same exposure) with the same fall, but it does NOT beat simply holding the market fully invested: its edge is small and it only deploys 40% of the account. Costs paid over 13 years: Rs 25 lakh on an account that grew from 10 to 32 lakh. 3,075 trades, 51% profitable, profit factor 1.20. Worst years: 2022 (-17%) and 2025 (-11%). The stop did not help in the history (time-only was better); it is kept because the page promises an exit level and because it bounds the loss in a gap-down.

## Live front test
Counts only Friday books written before the entry open, from the forward clock (2026-10-06). The first one is the 2026-10-09 book (entry Monday 2026-10-12 open). Until then the page says "No live trade yet". Judge it after months, not weeks.

## What would change my mind
A live record with a profit factor below 1 after ~100 closed trades, a live win rate far from 51%, or costs above the modelled ones.
