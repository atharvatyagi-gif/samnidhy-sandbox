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
    ├── S5 Headline scorer       the tone of headlines that NAME a stock (the existing FinBERT job, news part only)   [step 1]
    ├── S6 News analyst (AI)     reads the day's most important items: event type, who is named, direction, and which
    │                            stocks are exposed WITHOUT being named (via sector and the NEXUS supply graph)
    └── S7 Event historian       for each event type, which stocks moved after similar events in the past
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

1. Framework, dashboard and the scouts that wrap existing jobs, so the page shows real work from day one. **Done 2026-11-15**: scripts/blab/, lab.html, workflow blab.yml; S5 is the first analyst (rule declared before any scoring: average tone beyond ±0.25 over at least 2 headlines naming the stock).
2. Fundamental: F2-F5, ending with the blind-spot analyst. **Done 2026-11-16** (scripts/blab/fundamental.py): F2 ownership
   (NSE shareholding history, SAST Reg 29), F3 governance (NSE announcements by category), F5 blind-spot analyst with rules
   R1-R9 written in that file before scoring (one refinement after reading the first run, recorded there). Not measured, with
   reasons: insider (PIT) trades (NSE's feed returns no recent rows), rating direction and pledges (only in the PDFs).
3. Technical: T3-T5 (regime, strategy lab, analogs). **Done 2026-11-16** (scripts/blab/technical.py, rules written there
   before results): T3 state = NIFTY 50 trend x volatility since 2007 (+ breadth); T4 six strategies by state after a 0.4% cost,
   picks filed only for strategies measurably better in today's state; T5 the 10 nearest past days, a lean only at 8+ of 10;
   T2 adds NSE bulk/block/short deals. F&O open interest: not measured yet. Dashboard: the strategy-by-state table and analogs.
4. Macro: M1-M4, with the freshness checks and the tested outcome. **Built 2026-11-17, waiting for the owner's OK on the
   preview** (scripts/blab/macro.py, factor rules written there before results). India: RBI (daily snapshot), FRED India
   10-year and call-money rate, MOSPI CPI (late: the API stops at Dec 2025 after the base change). US inputs (owner,
   2026-11-16: US and Indian inputs allowed, findings about Indian markets only): FRED fed funds, CPI, sentiment, rupee,
   Brent, dollar, US VIX, US 10-year. First result: no factor measurably changed NIFTY 50's next 63 sessions since 2007.
5. Sentiment: S3, S6 and S7, ending with the AI analyst and the event historian. **Built 2026-11-17, waiting for the owner's
   OK on the preview** (scripts/blab/sentiment.py, rules written there before results, one refinement recorded): S2 adds US
   market headlines (CNBC, Google News US); S3 Indian sector and company news; S6 AI analyst on free tiers (Groq, Gemini,
   GitHub Models), high-confidence effects on named Indian companies plus their NEXUS neighbours; S7 event study of NSE
   announcement kinds over up to 3 years (monthly-clustered ranges, 12+ months, findings only after 2 years of history).
6. Scorecards run at least 8 weeks; then the owner chooses what moves to the main site.

## 6b. The self-evolving strategy desk (owner, 2026-11-17)

The old ranking lab (T4) is replaced by a desk of simple, research-backed strategies operated as paper accounts on every
tradable NSE stock, with a monthly selector that picks the top 3 (penalised for luck), retires losers, breeds variants and
takes rules proposed by an AI scout of new arXiv papers (T6). Evidence, rules and the one recorded change:
docs/blab/STRATEGY_EVIDENCE.md. Code: scripts/blab/evolve.py, scripts/blab/desk.py. First replay (2010-2026): the selector did
not beat the equal-money blend of all active strategies, so by the rule written beforehand the live account follows the blend.

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
