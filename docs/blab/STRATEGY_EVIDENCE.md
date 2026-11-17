# B-Lab Technical division: simple strategies, the evidence, and how they evolve

Written 2026-11-17, **before any test of these strategies was run**. Owner's brief (2026-11-17): simple technical strategies
that are operated properly, chosen from published research, scanning every Indian stock, replacing the old ranking lab;
then "self-taking and self-evolving: searching the top strategies of the time and actually using them". Owner's choices:
setting variants plus a free AI scout of new papers; re-pick monthly; the top 3 live, equal money.

## 1. What the research supports (read 2026-11-17)

| Family | Simple rule | Key research | Grade |
|---|---|---|---|
| Trend filter | hold a stock only while its close is above its N-day average | Brock, Lakonishok & LeBaron (J. Finance 1992); Faber (2007, 10-month average); Moskowitz, Ooi & Pedersen (JFE 2012, time-series momentum); Hurst, Ooi & Pedersen (century of trend following); Han, Yang & Zhou (JFQA 2013). India: Gunasekarage & Power (Emerging Markets Review 2001, BSE); Mitra (Quantitative Finance 2011): rules catch direction but costs bite | strong worldwide, medium in India |
| Moving-average distance | hold the stocks whose short average is furthest above their long average | Avramov, Kaplanski & Subrahmanyam (Rev. Fin. Econ. 2021): 21/200-day ratio, about 9% a year alpha, survives costs, stronger long side; Han, Zhou & Zhu (JFE 2016) trend factor | medium (US) |
| 52-week high | hold the stocks closest to their 52-week high | George & Hwang (J. Finance 2004); international: profits mostly not significant after costs; India: Raju (2023 working paper) | medium |
| Moving-average crossover | in when the short average crosses above the long one, out when back below | Brock et al.; but Sullivan, Timmermann & White (J. Finance 1999) and Bajgrowicz & Scaillet (JFE 2012): data snooping, low costs offset early gains | weak to medium |
| Channel breakout | in on a close above the N-day high, out on a close below the M-day low | Brock et al. trading-range break; Szakmary & Lancaster (Financial Review 2015): profitable in US stocks to 2007, gone after | weak to medium |
| RSI bounce | in when RSI(14) closes back above its oversold line, out at a higher line or after K days | Chong & Ng (Applied Econ. Letters 2008, FT30) positive; India: Muruganandan (Colombo Business J. 2020, Sensex 2000-2018) RSI failed; 2025 BRICS study negative | weak (kept to test a popular rule) |

Left out: MACD and Bollinger bands (weak or negative evidence, India included), daily/weekly reversal (costs), 12-month
momentum (model E already runs it).

**The warning that shapes everything below.** Bajgrowicz & Scaillet (2012): over a century of data, an investor could not
have picked the next period's best rules from the past period's best. "Use the recent top strategies" chases luck unless
the selection is penalised for how many strategies it looked at and is itself tested out of sample.

## 2. How every strategy is operated (rules fixed now)

- Universe each evening: every NSE main-board stock with prices. Tradable that day: close >= Rs 10, 260+ sessions of
  prices, 20-session average traded value >= Rs 1 Cr (so a position is a small share of a day's trading). The rest are
  scanned, never bought. A stock whose close moved more than 45% in one day is not bought for the next 20 sessions (a check of
  the data found 65 such moves in about 3 million tradable stock-days, several of them plain data errors).
- Each strategy: its own paper account of Rs 1,00,000, at most 10 positions of equal size (one tenth of the account's value
  at entry), long only, no borrowing. Signals at the close; orders fill at the NEXT session's open; the full Indian cost
  model of model E (STT, exchange, SEBI, stamp duty, GST, DP charge, slippage by liquidity).
- Ranking families (moving-average distance, 52-week high) rebalance every 21 sessions to their top 10. In/out families
  (trend filter, crossover, breakout, RSI) enter on their signal while slots are free; more signals than slots: the most
  traded first (a neutral tie-break). A held stock exits on its own exit rule.
- Benchmarks: NIFTY 50 held over the same days; the equal-money blend of ALL candidates (the honest baseline for "evolving").

## 3. The candidate pool (variants)

| Family | Settings tried |
|---|---|
| Trend filter | average of 100, 150, 200, 250 days |
| Moving-average distance | short 10/21/50 x long 150/200/250 days |
| 52-week high | lookback 126, 252 sessions |
| Crossover | short 20/50 x long 100/150/200 days |
| Channel breakout | entry 20/50/100-day high x exit 10/20/50-day low (exit window shorter than entry) |
| RSI bounce | oversold 25/30 x exit 50/55/60 x at most 10/20 days |

39 candidates to start. The AI scout may add new candidates (section 5); each is a plain rule in the same grammar.

## 4. The selector (self-evolving, monthly)

Every 21 sessions, using only prices up to that day:
1. **Eligible:** a candidate with at least 126 sessions (about 6 months) of its own paper record.
2. **Score:** the Sharpe ratio of its daily net returns over the last 252 sessions (or all it has, if less), then
   **deflated** for the number of candidates tried (Bailey & Lopez de Prado's deflated Sharpe ratio): the more
   candidates looked at, the higher the bar.
3. **Live:** the top 3 by deflated score, among those whose deflated probability of real skill is at least 0.5; equal
   money each. Fewer than 3 qualify: the empty share stays in the baseline (all candidates equally).
4. **Retire:** a candidate whose deflated probability is under 0.1 for 3 re-picks in a row leaves the pool.
5. **Breed:** at each re-pick, up to 3 new candidates: a neighbouring setting of a live one (one step on its grid) or two
   live rules combined with AND. New candidates start at zero record and wait 126 sessions like any other.

**The selector is replayed over 2010-2026 exactly as it would have run** (no future data at any step), and reported
against (a) the equal-money blend of all candidates and (b) NIFTY 50, after costs, with the last 2 years held out. If the
selector does not beat the blend over the whole period, the dashboard says so and the live account follows the blend.

**Changed 2026-11-17 after the FIRST replay, recorded honestly.** The first replay showed the mechanism, not the results,
was broken: the rule "3 re-picks under 0.1 = retired" retired all 39 candidates by 2024 (strategies have long losing
stretches), and with no live strategy nothing was ever bred. Changed once, to fix the extinction, not to raise returns:
retirement needs 6 re-picks in a row under 0.1 and never takes the pool below 15; when nothing qualifies as live, the 3 best
scores are the parents for breeding. The first replay's numbers (selector 22.9% a year, blend 23.3%, NIFTY 50 10.3%) are kept
in the record. (The grid gives 39 starting candidates, not "about 60" as first estimated.)

## 5. The AI paper scout (monthly, free)

Reads new abstracts from arXiv's free API (q-fin.TR, q-fin.PM, q-fin.ST), asks a free model whether a paper proposes a
simple price-or-volume rule that fits the grammar above, and if so writes it as a candidate (family + settings) with the
paper's link. Nothing proposed is used until it has its own 126-session paper record and passes the selector like the rest.

## 6. Honest limits

- Free data covers companies listed today (survivorship), so every candidate looks somewhat better than reality.
- Before 2021 the price history covers about 1,800 stocks (the history branch), after Oct 2021 about 3,000.
- A paper account fills every order at the open; real fills can be worse for small companies.
