# ALADIN audit, Phase 0: plan and inventory

Written 2026-11-08. Read-only: nothing in ALADIN was changed in this phase.

## 0. First lead on "every long is red" (to be proven in Phase 2, not a conclusion)

On the live ALADIN tab (weekly view as of the 2026-11-06 close) all 13 BUY rows show a **red number**. That number is the
**stop loss**, written as the distance below today's price (for example `-9.9%`). For a long trade the stop is always below
the price, so this number is always negative, and the page colours every negative number red. In the same rows the
"target price" column says `not measured` for 12 of the 13 BUYs. So the red may be a display choice, not a bearish
prediction. Phase 1 will trace it in the code and Phase 2 will test it.

## 1. What "ALADIN" actually is today

ALADIN is not one model. There are **five separate prediction systems** shown in different places, plus the paper bots that
trade one of them.

| # | System | What it predicts | Where you see it |
|---|---|---|---|
| 1 | **ALADIN 1** (`scripts/aladin_model.py` + inputs) | Chance a stock closes higher in 5, 10, 20 trading days, blending a technical model with fundamental, sentiment, liquidity-sweep and supply-chain scores | Tools tab (ALADIN table), the ALADIN box in the terminal's Details, Movers → ALADIN probability, home stock page "What our models see" |
| 2 | **Outlook** (`scripts/predict_model.py`) | Chance a NIFTY 500 stock beats the NIFTY 50 over 20 trading days | Outlook tab; the "students' model" line in the terminal's "In plain English" |
| 3 | **ALADIN 2.0 engine** (`scripts/aladin2/*`) | Per-stock strategy library with a forecast price range (1–60 days); a stock gets a signal only when a strategy is "Validated" | "ALADIN 2.0 brief" at the top of the terminal's Details (today: "HOLD: stand aside"), research pages |
| 4 | **ALADIN weekly signal** (`scripts/aladin2/weekly.py`) | BUY = best 1% of a weekly ranking, SELL = worst 2%, hold 5 trading days, with a stop loss | **The ALADIN tab** (13 BUY, 26 SELL, 1,245 HOLD on 6 Nov) |
| 5 | **ALADIN movers** (`scripts/aladin_movers.py`) | Which stocks move most in the next 5 days and which way | Paper account → "Weekly ranking (forward test)" |
| – | Paper bots | Virtual trades only: `paper_trader.py` (old, on #1), `aladin2/paper.py` rule v5.1 (on #4, live since 16 Oct), v4 shadow, plus backtest-only rule sets (swing, trader, v5) | ALADIN tab → Paper account; ALADIN BOT (locked) |

## 2. Files involved

### Python, ALADIN 1 and its inputs
| File | Lines | What it does |
|---|---|---|
| scripts/aladin_model.py | 770 | Technical model, the combiner (blend of all fronts), writes data/aladin/latest.json |
| scripts/aladin_quant.py | 307 | Building blocks for the technical model: hidden-market-state model (HMM), factor residuals, etc. |
| scripts/aladin_fund.py | 422 | Fundamental front: value, quality, fundamental momentum, distress band, F score (Yahoo statements) |
| scripts/aladin_filings.py | 381 | Tone of NSE announcements (FinBERT), delivery trend, bulk/block deals |
| scripts/aladin_sentiment_engine.py | 623 | News sentiment (Mint RSS, site news wire, Google News for Moneycontrol), FinBERT scoring, Reddit only with keys |
| scripts/graph_impact.py | 222 | NEXUS supply-chain impact score |
| scripts/aladin_moves.py | 108 | How much each stock's probability changed since the last night |
| scripts/aladin_sweep_eval.py | 118 | Tests whether liquidity sweeps predict the next day |
| scripts/aladin_ticker_daemon.py | 774 | Local tick program on the owner's PC (sweeps); not on GitHub |
| scripts/aladin_lstm_test.py | 183 | One-off test of a neural network (verdict: no gain, not used) |
| scripts/paper_trader.py | 252 | Old virtual portfolio on ALADIN 1's 10-day probability > 0.60 |
| scripts/aladin_env.py, aladin_telemetry.py, angel_feed.py, nse_live_poll.py | | Settings, flight/vessel data, Angel One feed (unused: no account), NSE live poll |

### Python, Outlook and ALADIN 2.0
| File | What it does |
|---|---|
| scripts/predict_model.py | Outlook: 20-day "beats NIFTY 50" model |
| scripts/aladin2/data_lake.py | Point-in-time feature store (only past data in each row) |
| scripts/aladin2/strategies/* | Strategy families: trend, mean reversion, volatility, relative strength, delivery flow |
| scripts/aladin2/evaluate.py, pooled.py, lifecycle.py, meta.py, kill.py, drift.py | Walk-forward testing, pooled selection, strategy life cycle, blending of active strategies, kill switches, drift checks |
| scripts/aladin2/forecast.py | Forecast price ranges (volatility model + quantiles) |
| scripts/aladin2/signals.py | Per-stock signals and trade plans (only for Validated stocks) |
| scripts/aladin2/weekly.py, weekly_run.py, weekly_study.py, precision_study.py | **The weekly BUY/SELL signal** shown on the ALADIN tab, its study and checks |
| scripts/aladin2/paper.py, paper_options.py, swing.py, trader.py, v5.py | Paper bot and the trading-rule experiments |
| scripts/aladin2/costs.py | Indian cost model (reads data/config/aladin2.json) |
| scripts/aladin2/ledger.py, journal.py, publish.py, bot.py, live.py, run_nightly.py, history_backfill.py, sources_status.py, acceptance.py, check_aladin2.py | Record keeping, site files, bot console data, nightly job, data backfill, checks |
| scripts/aladin_movers.py | ALADIN movers (5-day move forecast, forward test) |

### Website (JavaScript)
| File | What it shows |
|---|---|
| desk-signals.js | The ALADIN tab: weekly BUY/SELL list, stock sheet, paper account |
| desk-aladin.js | ALADIN 1 table (Tools tab), ALADIN box in Details, combiner in the browser |
| desk-aladin2.js, desk-a2views.js, desk-a2live.js | ALADIN 2.0 brief, research pages, live overlays |
| desk-a2bot.js | ALADIN BOT console (locked) |
| desk-movers.js | Movers → ALADIN probability view |
| terminal.js (outlookHtml, plain English), ui-home.js (modelCard, plainWords) | Outlook and model lines on the terminal and home stock page |

### Settings
- `data/config/aladin_config.json`: ALADIN 1 weights (fundamental 0.20, sentiment 0.12, sweep 0.18), paper rule (P > 0.60, 10 days)
- `data/config/aladin2.json`: costs, universe (₹2 Cr a day, 750 days of history), test settings, risk, weekly rule (BUY top 1%, SELL bottom 2%)
- `data/config/aladin_method.json`, `aladin2_method.json`: method text shown on the site; `tone_words.json`: word lists

### Scheduled jobs (GitHub Actions)
| Job | When | What |
|---|---|---|
| ALADIN nightly (aladin.yml) | after each Daily update | fundamentals, filings, NEXUS impact, ALADIN 1 probabilities, moves, old paper trader; then starts ALADIN2 |
| ALADIN2 nightly (aladin2.yml) | after ALADIN nightly | ALADIN 2.0 learning job (110-minute budget), weekly signal, movers forward test, paper bot |
| ALADIN sentiment (aladin-sentiment.yml) | about every 30 min (heartbeat) | news wire + FinBERT scoring |
| Daily update (daily-update.yml) | evening + mornings | prices, screener, FII/DII, Outlook model |

Tests: 25 files in tests/aladin2, 13 ALADIN tests in tests/, 6 browser-code tests in tests/js, 1 browser check.

## 3. Data sources

| Source | Address | How often | Stored in | When it fails |
|---|---|---|---|---|
| Daily prices | NSE end-of-day files + Yahoo split-adjusted candles | daily after close | data/terminal (Actions cache) + history branch | keeps the last saved copy |
| India VIX, USD/INR, Brent, S&P 500, Nikkei | Yahoo chart API (^INDIAVIX, INR=X, BZ=F, ^GSPC, ^N225) | daily | ALADIN2 cache | feature missing that day (Phase 1 checks exactly how) |
| US 10-year yield | FRED (needs FRED_API_KEY) | daily | ALADIN2 cache | missing without the key |
| Delivery % | NSE sec_bhavdata_full CSV | daily | data/terminal/aladin2/deliv | exists only from 2020 |
| F&O open interest | NSE F&O bhavcopy | daily | ALADIN2 cache | backfill |
| F&O ban list | NSE fo_secban | – | – | **not reachable (404), not used** |
| Bulk/block deals | NSE bulk.csv / block.csv | daily, latest day only | accumulates from the start date | history only from when collection began |
| FII/DII flows | NSE FII/DII report | daily | data/institutional | keeps saved days |
| Fundamentals | Yahoo annual + quarterly statements, ~400 companies a night | nightly rotation | data/aladin_cache/statements | **past filing dates are not stored** (a look-ahead risk to check) |
| Filings tone | NSE corporate announcements (FinBERT) | nightly, last 90 days | alt_scores.json | stops at the time budget |
| News sentiment | Mint RSS, site news wire (ET, Business Standard, Mint), Google News RSS | about every 30 min | data/aladin/sentiment.json | word list if FinBERT fails; history only since the job began |
| Reddit | PRAW with keys only | – | – | no keys, so not used |
| NEXUS supply chain | data/supply_graph.json | weekly | repository | sparse; "expected to add nothing measurable" |
| Liquidity sweeps | owner's PC tick program | live, market hours | local only | not on GitHub, so absent from nightly scores |
| Past NIFTY 500 membership | none free | – | – | **not available**: today's list is used for the past (survivorship bias) |

## 4. Every model, rule and threshold that changes a signal (first pass; Phase 1 gives each one in full)

- ALADIN 1: technical model probabilities for 5/10/20 days (calibrated), combined with fundamental (weight 0.20),
  sentiment (0.12), sweep (0.18) and NEXUS impact; paper rule P(10 days) > 0.60.
- Outlook: probability of beating the NIFTY 50 over 20 days; deciles.
- ALADIN 2.0: strategy promoted only after testing and 60 days of paper evidence ("Validated"), calibration error at most 5%,
  net expectancy at least 5 bps; kill switches; stop 1.5 to 2.5 ATR; risk 1% a trade; Kelly fraction capped at 0.25.
- Weekly signal: BUY = rank percentile ≥ 99%, SELL = rank percentile ≤ 2%, 5-day hold, a stop loss and a "target"
  (shown only when measured).
- Universe filters: at least ₹2 Cr average daily traded value, 750 days of history, no SME, no ETF.

## 5. What I need from you, and what I could not find

- **Nothing blocking.** Your answers to my 11 questions are recorded as "use the defaults".
- **Please confirm** the red you mean is the red stop-loss numbers on the ALADIN tab (section 0), or name another page.
- **Not found or not available:** past NIFTY 500 membership (no free source); past filing dates for fundamentals; the F&O
  ban list; delivery data before 2020; news history before the sentiment job started.
- **Not yet explained:** the ALADIN nightly job ran 6 times between 18:43 UTC on 7 Nov and 08:57 UTC on 8 Nov (all
  started by hand or by another job, on a weekend). Phase 1 will find out why.

## 6. Plan for Phases 1 to 7

| Phase | What | Rough time |
|---|---|---|
| 1 | Explain how each of the five systems works: diagram, data, features, models, blending, the colour rules, three worked examples, health | 1–2 days of work |
| 2 | Diagnose the red: bug checks, design checks, is the market weak, event study, scorecard and a verdict per model | 1–2 days, plus computer time |
| 3 | Read and grade published evidence on Indian markets for each option | about 1 day |
| 4 | Test options A–F (and any G) on the same setup, after costs, walk-forward, with baselines and robustness checks | 3–5 days, mostly computer time |
| 5 | Write the spec of the chosen single model; after your OK build it, archive the rest, tests, before/after table | 2–3 days |
| 6 | Put it on the dashboard: market strip, ranked list, reasons, model health, paper log, alerts | 1–2 days |
| 7 | Four weeks of automatic paper trading with a Friday report; then Continue / Fix / Stop | 4 calendar weeks |

## 7. How to undo this phase

This phase only adds two files in `aladin-audit/` on the branch `aladin-audit`. Delete the branch to undo.
