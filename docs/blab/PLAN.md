# B-Lab research bots: plan for the owner's approval (2026-11-15)

Owner's decisions (15 Nov 2026): three divisions split **by source of the information** (MECE); rule and statistics bots
plus GitHub Models' free tier for the reading/analyst bots (Rs 0); a **hidden page with no login** for the backend
dashboard; promotion to the main site only after the owner sees how each bot performs.

## 1. The MECE rule

Every piece of information has exactly one source, so it belongs to exactly one division (Macro added by the owner, 15 Nov 2026, as a fourth source):

| Division | Source | Includes | Never includes |
|---|---|---|---|
| **Fundamental** | what the **company or a regulator files** about the company | results and statements (XBRL), annual-report notes, related-party deals, auditor and director changes, shareholding pattern, promoter pledges and invocations, SEBI insider (PIT) trades, corporate actions, credit ratings, BRSR | news articles about these, price reaction |
| **Technical** | what **trading produces** | prices, volume, delivery %, circuits, F&O open interest, bulk and block deals, FII/DII flows, index breadth, market regimes, strategy back-tests | anything written by people |
| **Macro** | **official economic statistics** from governments and central banks, plus market-priced macro (oil, gold, USD/INR, US 10-year) | rates, inflation, growth, liquidity, credit, currency, commodities, global risk | company data, stock prices, opinions |
| **Sentiment** | what **other people write or say** | Indian business media, global and macro news, sector news, social chatter where its terms allow, and the analyst bot's reading of all of these | the company's own filings (Fundamental) |

Edge cases are settled once, here: an exchange announcement is the company's own filing (Fundamental); a news story
about it is Sentiment; a bulk deal is exchange trade data (Technical); a promoter's own disclosed trade is a filing
(Fundamental).

## 2. The organisation

```
B-Lab desk (orchestrator: schedules, collects, never blends the divisions)
├── Fundamental
│   ├── F1 Statements scout      quarterly and annual results, statements (NSE XBRL; Yahoo as fallback)    [reuses terminal_fund, aladin_fund]
│   ├── F2 Ownership scout       shareholding pattern, pledges, invocations, SEBI PIT insider trades
│   ├── F3 Governance scout      auditor / director / KMP changes, ratings, corporate actions             [reuses aladin_filings]
│   ├── F4 Related-party scout   related-party transactions, group companies                               [reuses NEXUS, business houses]
│   └── F5 Blind-spot analyst    red-flag tests on F1-F4: profit vs operating cash flow, receivables or inventory
│                                outgrowing sales, other-income share, tax-rate oddities, contingent liabilities,
│                                pledge rising, auditor exit, related-party share rising. Each flag cites its filing.
├── Technical
│   ├── T1 Price scout           end-of-day prices, volume, delivery, circuits                            [reuses terminal_hist, indices_eod]
│   ├── T2 Flows scout           F&O open interest, bulk and block deals, FII/DII                         [reuses aladin_filings deals, fii_dii]
│   ├── T3 Regime bot            today's market state: trend, volatility, breadth, rates (a small fixed set of states)
│   ├── T4 Strategy lab          a fixed library (momentum, reversal, breakout, low volatility, quality-trend, ...)
│   │                            tested in every past regime: "what has worked in markets like this one"
│   └── T5 Analog finder         the past periods most like today, and what the market and sectors did next
├── Macro
│   ├── M1 India scout          RBI (repo, liquidity, credit, reserves), MOSPI (CPI, IIP, GDP)              [no key]
│   ├── M2 Global scout         FRED (US and global rates, inflation, dollar; India series too), World Bank [FRED: free key]
│   ├── M3 Market-macro scout   crude, gold, USD/INR, US 10-year from Yahoo, daily                          [no key]
│   └── M4 Macro analyst        today's macro state (rates, inflation, rupee, oil, global risk) and its tested outcome:
│                               what the NIFTY 500, each sector and each T4 strategy did over the next 1 and 3 months
│                               in past periods with the same state, with error ranges; "no measurable effect" when so
└── Sentiment
    ├── S1 India media scraper   Indian business media RSS                                                  [reuses news_wire, sentiment engine]
    ├── S2 Global & macro scraper GDELT, global wires: policy, commodities, geopolitics                      [reuses globe_data]
    ├── S3 Sector scraper        industry and regulator news per sector
    ├── S4 Social scraper        only sources whose terms allow it; otherwise shown as "not measured"
    ├── S5 News analyst (AI)     reads the day's most important items: event type, who is named, direction, and which
    │                            stocks are exposed WITHOUT being named (via sector and the NEXUS supply graph)
    └── S6 Event historian       for each event type, which stocks moved after similar events in the past
                                 (GDELT event history goes back years for free; our own news only since the job began)
```

## 3. One format for everything

- **Finding**: bot, division, stock (or sector / market), what was found, evidence (source, link, date, quote), direction
  (positive / negative / none), as-of date, how long it is meant to matter.
- **Bot status**: last run, time taken, items scanned, findings, errors, how fresh each source is.
- **Scorecard**: every finding with a direction is checked forward against the NIFTY 500 over 5, 20 and 63 trading days,
  with error ranges. This is what the owner uses to decide what reaches the main site.

## 4. Running at the same time

A new GitHub Actions workflow runs the three divisions as **parallel jobs** every evening after the daily update (the
scrapers also every 30-60 minutes, like today's sentiment job); inside a division the scouts run in parallel, then its
analyst runs on what they found. A final job merges, scores and publishes. Free on a public repository.

## 5. The backend dashboard (hidden page, no login)

`lab.html`, linked from no menu, marked "experimental, not investment advice":
1. **Org chart**: every division and bot with a status light, last run, items scanned, findings, errors, source freshness.
2. **Live feed** of findings, filterable by division, bot and stock.
3. **One stock, three divisions** side by side, never blended into one score.
4. **Scorecards** per bot, with how many findings so far and whether the record is clear of zero yet.
5. **Macro panel**: every series with its latest value, date, source and a freshness light (red when it is later than its
   normal release, e.g. CPI more than about 45 days old); the macro state and its tested outcome.

## 6. Order of work (one step at a time, each tested and merged before the next)

1. Framework, dashboard and the scouts that wrap existing jobs, so the page shows real work from day one.
2. Fundamental: F2-F5, ending with the blind-spot analyst.
3. Technical: T3-T5 (regime, strategy lab, analogs).
4. Macro: M1-M4, with the freshness checks and the tested outcome.
5. Sentiment: S2-S6, ending with the AI analyst and the event historian.
6. Scorecards run at least 8 weeks; then the owner chooses what moves to the main site.

## 7. Free sources only (owner, 15 Nov 2026)

Every source is free. None needs a paid plan, and none needs a key the owner must create:
NSE / BSE filing sites, NSE end-of-day files, Yahoo Finance, media RSS feeds, brutalist.report, GDELT, RBI's data
portal, MOSPI, the World Bank API, and GitHub Models' free tier (through the token GitHub Actions already has).
FRED needs a free key (owner approved, 15 Nov 2026): GitHub secret `FRED_API_KEY` (and `.env` locally); tests never read
it, and without it the bot shows "FRED: no key yet" while the other sources keep working. MOSPI's automatic access is
still to be confirmed. Excluded: X/Twitter (paid). Reddit is skipped: its terms need approval
for commercial use. When a free quota runs out, the bot shows "limit reached" and never switches to a paid service.
Any new external API is put to the owner before it is added.

## 8. Limits stated up front

- GitHub Models' free tier has a small daily request limit (not yet measured by us), so the AI analyst reads only the
  most important items each day; everything else is rule-based.
- Free statement data has gaps (some companies' XBRL, older years); a missing number is shown as "not measured".
- Our own news history is short; deeper "what happened after similar news" uses GDELT's free history.
- Back-tests use companies listed today (survivorship), as in the ALADIN audit.
- These bots report evidence; they do not tell anyone to trade.
