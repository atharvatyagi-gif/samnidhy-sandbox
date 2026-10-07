# Samnidhy Sandbox

An interactive website that teaches beginners how the stock market works, using the **top
gainers and top losers of the last NSE trading session**. The site picks new stocks and
refreshes itself automatically every weekday morning. It was built for Samnidhy, a student
committee at TAPMI.

**Live site:** https://atharvatyagi-gif.github.io/samnidhy-sandbox/

> Educational analysis only. Not investment advice. All figures are historical; past
> performance does not predict future results.

---

## What it teaches

Every lesson runs on the session's picked stocks. By default these are the 3 top gainers and the
3 top losers, and each is labelled "Top Gainer #1–3" or "Top Loser #1–3" with its session move.

| Lesson | Idea | What you can do |
|---|---|---|
| **1. How a price is set** | A price is just the last trade. The bid-ask spread pays the people who are always ready to trade. | Trade against a simulated order book that starts at each stock's real closing price. |
| **2. What a company is worth** | Market cap measures size. P/E measures how expensive a share is relative to profit. | Compare the stocks, and see which look pricier or cheaper than the group median. Drag an earnings-growth slider. |
| **3. Risk and return** | Combining stocks that don't move together lowers risk (diversification). | Build portfolios with sliders or presets, including "gainers only" and "losers only". Explore correlations and each stock's volatility, drawdown and beta. |
| **4. The power of compounding** | Returns on earlier returns make wealth grow faster over time. | Use a SIP calculator whose default return is the Nifty 50's real 5-year return, or try each stock's own past return. |
| **5. The longer story** | One day's move says little on its own. | Watch an animated race of ₹1,00,000 in each stock and the Nifty 50, through real weekly prices. |
| **6. Test yourself** | Recap. | Answer a quiz whose answers are calculated from the day's data. |
| **Past sessions** | | Open any earlier day's page, exactly as it was. |

The top of every page shows **"Data for trading session: …"** and **"Last updated: … IST"**.
If the latest update failed, or the last success is more than 4 days old, an amber
**"Data not updated"** warning appears. The site then keeps showing the last good day and never
substitutes other stocks.

---

## Where the data comes from

| Data | Source | Notes |
|---|---|---|
| Which stocks are picked, and their session move | NSE's official end-of-day file ("bhavcopy") on `nsearchives.nseindia.com` | The move is close price vs previous close. The session date is read **from inside the file**, never worked out from the calendar. This matters because NSE serves copies of the previous file for some holidays and weekends. |
| Stocks that can be picked | NIFTY 500 list from `niftyindices.com` | A saved copy in `data/universe/` is used if the download fails. |
| Nifty 50's session move | NSE's official index-closing file | Yahoo's index history sometimes skips a day. |
| Price history (up to 5 years), P/E, market cap | Yahoo Finance via `yfinance` | See the notes below. |

No API keys are needed.

Notes on the Yahoo Finance data:
- **Adjusted prices.** Prices are adjusted for splits, bonus issues and dividends
  (`auto_adjust=True`). The Nifty 50 is a *price* index, so it excludes dividends.
- **Holiday rows removed.** Yahoo adds fake rows for market holidays, with a flat price and zero
  volume. These are removed.
- **Session-day check.** Each stock's session-day close must match NSE's official close.
- **When Yahoo is late.** If Yahoo hasn't published the session yet, NSE's official prices are
  used for that day. This only happens when Yahoo's latest close matches NSE's "previous close",
  which proves no day is missing in between.
- **Missing figures.** A missing P/E or market cap is shown as "n/a" and never estimated.

---

## Settings (`config.toml`)

Every setting is in one file. Change a number, save, and the next update uses it.

| Setting | Default | Meaning |
|---|---|---|
| `gainers_count` / `losers_count` | 3 / 3 | How many of each to pick. |
| `universe_name` / `universe_url` | NIFTY 500 | Only stocks in this index are considered. |
| `series` | `["EQ"]` | Only normal equity shares. |
| `min_price` | 50 | The closing price must be above ₹50. |
| `min_turnover_crore` | 10 | At least ₹10 crore must have traded in the session. |
| `min_history_years` | 1 | Stocks with less price history are skipped as "too new to analyse", and the next-ranked stock takes their place. The site names the skipped stock. `0` turns this off. |
| `max_abs_move_pct` | 30 | Bigger moves are skipped, because they're almost always a split or bonus issue. |
| `exclude_prefixes` / `exclude_symbols` | `DUMMY…` / none | Placeholder symbols, and any stock you want to block. |
| `years`, `benchmark` | 5, `^NSEI` | How much history to use, and the market comparison. |

---

## How the automatic update works

`.github/workflows/daily-update.yml` runs on GitHub's servers at **07:30 IST, Monday to Friday**,
with a backup run at 09:00 IST. Each run does the following:

1. **Update the data:** `python scripts/update.py`
   - Picks the stocks, downloads and checks their history, and computes every figure.
   - Saves the day **only if every step worked**.
   - Otherwise it records the error in `data/status.json` and changes nothing else.
2. **Build the site:** `python scripts/embed_data.py` and `python scripts/build_site.py`
   - Puts the data, or the "Data not updated" warning, into the page.
   - Builds `site/`, which has the latest page and one page per past session.
3. **Save the day:** commits `data/` and `dashboard.html` to this repository. The day's picks are
   saved as `data/picks/<date>.json` and its full analysis as `data/archive/<date>.json`.
4. **Publish:** puts `site/` on GitHub Pages.

If step 1 fails, the run is marked as failed and GitHub emails the account owner. You can also
start a run any time: open the **Actions** tab, click **Daily update**, then **Run workflow**.

GitHub pauses scheduled workflows in public repositories after 60 days with no activity. The
daily commits count as activity, so this shouldn't happen. If it ever does, the Actions tab shows
an **Enable workflow** button.

### Running it on your own computer

You need Python 3.11 or newer.

```bash
pip install -r requirements.txt
python scripts/update.py        # pick the stocks and compute everything
python scripts/embed_data.py    # refresh dashboard.html
python scripts/build_site.py    # build site/ (open site/index.html in a browser)
```

Useful extras:
- `python scripts/pick_movers.py` previews the picks without saving anything.
- `python scripts/update.py --as-of 2026-09-18` rebuilds the last session on or before that date,
  which is useful for filling in past days.

---

## Formulas

*P<sub>t</sub>* is the adjusted close on day *t*. There are 252 trading days per year.

All comparisons between stocks use one **analysis period**: the dates on which every picked stock
and the Nifty 50 have a price, up to 5 years. The site shows this period and explains it whenever
it's shorter than 5 years.

| Figure | Formula |
|---|---|
| Session move | NSE close ÷ NSE previous close − 1 |
| Daily return | *P<sub>t</sub>* / *P<sub>t−1</sub>* − 1 |
| Annualised return | (*P*<sub>end</sub> / *P*<sub>start</sub>)<sup>1/years</sup> − 1, where years = calendar days ÷ 365.25 |
| Annualised volatility | standard deviation of daily returns (sample) × √252 |
| Maximum drawdown | min over *t* of ( *P<sub>t</sub>* / max<sub>s≤t</sub> *P<sub>s</sub>* − 1 ) |
| Beta | Cov(stock, Nifty 50) ÷ Var(Nifty 50), using daily returns |
| Correlation / covariance | Pearson correlation of daily returns; covariance × 252 |
| Portfolio return | Σ *w<sub>i</sub>* *R<sub>i</sub>* |
| **Portfolio volatility** | **√(*w*ᵀ Σ *w*)**, using the covariance matrix Σ, not an average of the individual volatilities |
| Implied EPS / implied price | price ÷ P/E; price × (1 + *g*)³, where *g* is the growth-rate slider and the P/E is assumed constant |
| **SIP value** | **FV = *P* × [((1 + *i*)<sup>*n*</sup> − 1) / *i*] × (1 + *i*)**, compounded monthly |
| Race value | ₹1,00,000 × weekly close ÷ the close in the first week of the analysis period |

For the SIP: *i* is the annual return ÷ 12, and *n* is the number of months. Each instalment is
invested at the start of its month. At a 0% return, the formula becomes FV = *P* × *n*. The
default return is the Nifty 50's annualised return over its last 5 years.

### Parts that are simulated or illustrative, not market data

- **The lesson 1 order book.** It starts at the stock's real close, but the bid and ask
  quantities are random. Price steps are simplified; real NSE steps are as small as 1–5 paise.
- **The P/E worked example** (₹10 of earnings at a ₹200 share price).
- **Slider defaults and presets.** These are user inputs.
- **The quiz's wrong answers.** They are principled alternatives, such as simple interest
  instead of compounding.
- **Decoration.** The ticker animation, glow effects, word bands and confetti show no data.

---

## Project structure

```
config.toml                      all settings
scripts/update.py                runs the whole daily update (pick -> history -> calculations -> save)
scripts/pick_movers.py           picks the stocks from NSE's file
scripts/fetch_data.py            downloads and checks price history
scripts/process_data.py          computes every statistic
scripts/embed_data.py            puts the data into dashboard.html
scripts/build_site.py            builds the public site into site/
dashboard.html                   the page (also works offline by double-clicking)
data/data.json                   the latest analysis
data/status.json                 did the last update work? when?
data/picks/<date>.json           each day's picks (kept)
data/archive/<date>.json         each day's full analysis (kept)
.github/workflows/daily-update.yml   the scheduled job
```

`site/` and `data/raw/` are rebuilt by every run, so they aren't stored in git.

## Undoing the changes

The original 5-stock version is saved as the git tag `baseline-5-stocks`. To look at it, run
`git switch --detach baseline-5-stocks`, and run `git switch main` to come back.

## Advanced page (stock screener + live technicals)

`advanced.html` (on the website: `/advanced.html`, linked as **◆ Advanced** in the menu) is a second page:

1. **Daily screen** (`scripts/screener.py`, settings in `[screener]` of `config.toml`), run by the daily update:
   NIFTY 500 → drop banks/NBFCs/insurers/power utilities → price ≥ ₹50 and ≥ ₹10 Cr traded a day
   → complete annual-report data → **Piotroski F-Score** ≥ 6 → best 10 by **Greenblatt's Magic Formula**
   (return on capital + earnings yield). Saved to `data/screener/latest.json` and `data/screener/history/<date>.json`.
   A stock with any missing number is left out, never estimated.
2. **Live prices, signals and market conditions** (`scripts/live_technicals.py`), run every 15 minutes during market
   hours by `.github/workflows/live-prices.yml`: delayed price (Yahoo Finance) plus four research-backed price signals,
   each ranked against the NIFTY 500: trend vs the 200-day average and the 50/200 cross (Brock, Lakonishok & LeBaron 1992;
   Faber 2007), 12-1 month momentum (Jegadeesh & Titman 1993), nearness to the 52-week high (George & Hwang 2004) and
   1-year volatility (Blitz & van Vliet 2007). Also Nifty 50, Bank Nifty, India VIX, USD/INR, Brent, gold, US 10-year
   yield, S&P 500 and Nikkei. Written to `data/screener/live.json` (not stored in git) and published as `site/live.json`;
   an open page picks up new prices every 2 minutes.
3. **Institutions**: per stock, institutional and promoter holdings and analyst consensus/targets (Yahoo Finance, saved
   with the screen); market-wide FII/DII net buying from NSE's daily FII/DII report (`scripts/institutional.py`), saved
   day by day to `data/institutional/fii_dii.json` because NSE only shows the latest day.

Run locally: `python scripts/screener.py`, `python scripts/institutional.py`, `python scripts/live_technicals.py`, `python scripts/embed_data.py`,
then open `advanced.html`. Educational analysis only. Not investment advice.

## The B-Lab Cohort: (landing page, Expert access, terminal)

Flow: `index.html` (scroll landing page) → **Enter the Cohort** → `sandbox.html` (main page, daily movers) → **◆ Advanced**
→ **Expert Mode** → `auth.html` → `expert-terminal.html`. Reloading any page on the website returns to the home page.

### Expert access (Firebase, email + password, TAPMI students only)
Registering needs a `@learner.manipal.edu` email, the student's **roll number + date of birth** (checked against the TAPMI student
list) and a **new** B-Lab password. Each student can register once; the terminal opens only for completed registrations.
The student list itself never goes online: `scripts/student_allowlist.py` turns it into one-way SHA-256 keys.

Setup (once):
1. Firebase console: create a project → add a **Web app** → copy its config into `config.js` (lines 7–12).
2. Authentication → Get started → enable **Email/Password**.
3. Firestore Database → Create database (production mode).
4. On your computer: `pip install openpyxl`, then
   `python scripts/student_allowlist.py "Student List for ID Card- Batch 2026-29.xlsx"`. It writes
   `private/firestore.rules`: the rules with the students' one-way keys filled in.
5. Firestore → Rules: paste `private/firestore.rules` → Publish. (Repeat 4–5 when the student list changes.)
6. Authentication → Settings → Authorized domains: add `atharvatyagi-gif.github.io`.
The Excel file and `private/` are never committed or published; `firestore.rules.template` in git is only the template (its student list is empty).

### Expert terminal: every NSE stock
- `scripts/nse_eod.py` (daily): NSE's official bhavcopies for ~1 year → all ~3,500 NSE stocks, SME boards and ETFs
  (`data/terminal/`, kept in the GitHub Actions cache, not in git).
- `scripts/terminal_live.py` (every 15 min in market hours): delayed 5-minute prices from Yahoo Finance for ~2,950
  main-board stocks; prices that disagree with NSE's own close are rejected. SME stocks show NSE end-of-day prices.
- `scripts/terminal_fund.py` (daily): fundamentals for the NIFTY 500.
- Developer preview without signing in (local only): `python scripts/dev_preview.py` → `expert-dev.html`.

### Local tick feed (optional, runs on your own PC)

`scripts/aladin_ticker_daemon.py` serves live prices only to your own browser at `ws://127.0.0.1:8787/ws/ticks`. It has two sources: the free NSE website feed (the default, no account needed: the index levels plus about 300 stocks, namely NSE's own movers and most-active lists and the spot prices of the futures-and-options stocks, NSE refreshes these lists in bursts about every 1 to 3 minutes, measured on 7 Oct 2026, so faster polling returns the same numbers; every other stock keeps its delayed price) and, if you have your own Angel One SmartAPI login, Angel One's WebSocket feed (every NSE stock, pushed in real time).

1. `scripts/start_aladin_local.bat` (Windows) or `scripts/start_aladin_local.sh` (Mac/Linux). Leave it running.
2. In the desk's command line type `TICKS ON`. The top-right chip then reads "LIVE · NSE WEB (THIS PC, 1-3 min)" for the free feed, or "REAL-TIME · NSE (THIS PC)" for Angel One. `TICKS OFF` stops it.

Things to know:
- It is a polled website feed, not an exchange feed: other stocks keep their delayed price (the age is shown). It only runs Mon-Fri 09:00-15:45 IST.
- Chrome and Edge allow a secure page to talk to `127.0.0.1` (they may ask once). Safari blocks it.
- The ticks stay on your machine: `data/live_extra/` is gitignored and never published (NSE's website terms restrict redistributing this data).
- If NSE blocks the connection the daemon backs off and says so; it does not try to get around a block.
- **Angel One source (optional).** Put `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_MPIN` and `ANGEL_TOTP_SECRET` in `.env` (never committed; see `.env.example`) and `pip install -r requirements-angel.txt`. With all four set the daemon uses Angel One by default (`--source angel` forces it, `--source nse-web` forces the free feed). If the login or the instrument list fails, the reason (never a secret) is printed, shown under `/health` as `session.fallback_from`, and the daemon carries on with the free feed. Focus symbols are applied every 250 ms, the rest every second. The code is `scripts/angel_feed.py`; it repeats the instrument-list parsing, tick conversion and connection grouping of `relay/relay.py` on purpose (the relay is installed on a server on its own and cannot import it), and `tests/test_angel_feed.py` loads `relay.py` with stubbed libraries and checks both give identical results. It has been tested against recorded message shapes and those stubs, **not against a live Angel One account**: nobody on this project has run it with real credentials yet.
- **Licence.** Angel One's market data is licensed to the account holder. The daemon shows it only on your machine (loopback). Showing it to the cohort needs Angel One's written permission and the server relay in `relay/`.
- Tests: `python -m pytest tests -q` (no network needed). Browser checks of the chip use a scripted feed: `python tests/e2e/ticks_check.py`.

### Geopolitical news attention (Globe layer)

`scripts/geo_tension.py` scores ten regions (Hormuz, Red Sea, Israel/Gaza/Lebanon, Russia/Ukraine, India/Pakistan, India/China border, Taiwan Strait, US tariffs, Malacca, OPEC+) by how much and in what tone the news is talking about them, compared with each region's own 30-day history. It measures news attention, not events. Switch it on in the Globe's layer control. The exposure lists are in `data/config/geo_exposure.json` (checked by `scripts/check_geo.py`).

- Source is Google News RSS (no key). GDELT, the usual choice, answers HTTP 429 from GitHub Actions and from a home PC, so it is not used.
- Google returns at most 100 items per query and has no history, so the baseline is collected by the hourly Globe workflow itself (`data/aladin/geo_history.json`). A region shows "Building baseline" and no score until it has 48 samples over 3 days. Busy regions that hit the 100-item cap are marked as a lower bound.
- Tone is a transparent word-list count over headlines (`data/config/tone_words.json`), not a language model.

### Checks that guard the wording and the evidence

- `python scripts/check_banned.py` fails if the words buy / sell / target / recommendation / guaranteed appear in anything new the user can read (the new modules, the new HTML blocks, our own config strings, the README methodology block, and every key of every JSON file the site serves), or if the disclaimer is missing from the ALADIN view, the NEXUS panel or the Globe tab. `--existing` also lists such words in the older desk code (they are internal data-field names such as Yahoo's `strong_buy`, not wording users see).
- `python scripts/aladin_sweep_eval.py` (run on the PC that runs the tick program, whose sweep log is local) checks whether a liquidity sweep predicted the next day's direction and reports the hit rate with a 95% interval. The sweep weight stays "prior, unvalidated" until at least 60 outcomes have matured and the interval's lower bound is above 50%.
- `python scripts/aladin_lstm_test.py` tests whether a small LSTM adds to the Technical model, under a rule fixed before looking at results; its verdict is in `data/aladin/lstm_test.json` and shown on the ALADIN model card.
- `python scripts/aladin_moves.py` (nightly) compares the last two saved nights for the Movers tab's ALADIN probability view.

### ALADIN sentiment engine

`scripts/aladin_sentiment_engine.py --once` (or `--loop 900` on your PC) scores headlines from Mint, the news wire (ET, Business Standard) and Google News (Moneycontrol headlines, queried per company) with FinBERT, matches them to NSE stocks, and blends in retail chatter (Reddit) and FII/DII flow into `data/aladin/sentiment.json`. Earnings-call transcripts are read by a free cloud model: Groq's `openai/gpt-oss-120b`, then `openai/gpt-oss-20b`, then `qwen/qwen3.8-27b`, then Google's `gemini-flash-latest` and `gemini-flash-lite-latest` (override with `GROQ_MODEL`, `GROQ_FALLBACK_MODELS`, `GEMINI_MODEL`). A model that is gone, over its daily allowance or overloaded hands over to the next; with no key, or when all fail, a local FinBERT split of the call is used. The "ALADIN sentiment" workflow runs it every 30 minutes in market hours and hourly otherwise, started by the heartbeat.

- A stock is scored only if a headline in the last 72 hours names it (symbol, company name or alias) or, when no company is named, its business group. Sector and market-wide headlines only add low-weight context. A stock with nothing specific is "NO NEWS" with no score, never "neutral".
- The score is -100 to +100: BAD, POOR, NEUTRAL, GOOD, EXCELLENT. FII/DII flow applies to every scored stock, so a heavy-selling week pulls all scores down together.
- Retail sentiment needs at least 5 different authors in 24 hours, so on most days it is "not measured". Reddit's RSS often answers HTTP 429; with `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` set it uses the official API.
- Earnings-call transcripts (`score_transcript`) use Groq (`GROQ_API_KEY`) or Gemini (`GEMINI_API_KEY`) if a key exists, otherwise a local FinBERT split at the Q&A marker.
- FinBERT needs PyTorch (`pip install torch --index-url https://download.pytorch.org/whl/cpu`) and about 440 MB of model download the first time. Without it the engine falls back to a word list and says so (`method: "lexicon"`).

### ALADIN model (probabilities)

`scripts/aladin_model.py --full` (by hand or weekly) runs the walk-forward test and the final models; `--nightly` re-uses the saved test record in `data/aladin/model_state.json` and just retrains and scores. Both write `data/aladin/latest.json` (published as `aladin.json`) and a snapshot in `data/aladin/history/`.

- **Question asked:** will the stock's close be higher in 5 / 10 / 20 trading days? Accuracy is always shown next to the base rate (the share of up moves), because "always say up" is already right a bit over half the time.
- **Technical front:** LightGBM (3 seeds) on about 80 price and market inputs, plus PCA residual returns, a cointegrated-peer spread (Engle-Granger, Kalman filter), a 2-state market-turbulence HMM (forward-filtered, fitted on training data only) and jump statistics. Calm/stress model sets are used only if they beat the single model out of sample. Probabilities are isotonic-calibrated on the pooled out-of-sample years (2013 onwards, with a 10 / 15 / 25-day purge gap).
- **Fundamental front** (`scripts/aladin_fund.py`): Value, Quality and Fundamental-momentum composites (winsorised, orthogonalised to size and industry), a distress band (worse of Merton distance-to-default and Altman Z''), filing tone and hedging from NSE announcements (`scripts/aladin_filings.py`), delivery % trend and bulk/block deals. Yahoo gives only about 4 annual and 5 quarterly periods, so earnings stability and quarterly revenue acceleration are usually "not measured".
- **Combiner:** `logit(p) = logit(p_tech) + 0.20 F/100 + 0.12 S/100 + 0.18 S_sweep/100` with `combine_py` (Python) and `combine()` (`desk-aladin.js`) both tested against `tests/fixtures/combiner_cases.json`. These weights are priors until 120 trading days of saved predictions have matured; a fitted stacker then replaces them only if it wins out of sample.
- **Not done:** LSTM (optional, not tried), order-book models, RL execution and Heston calibration (no free data).
- The data/aladin/*.json files are generated; the nightly workflow (added with the paper-trader phase) is what keeps them current.

### ALADIN: running it, keys, workflows, tests

- **Nightly (GitHub Actions):** the "ALADIN nightly" workflow starts after a successful "Daily update" (or by hand; choose `full` to redo the slow walk-forward test). It runs `aladin_fund.py` → `aladin_filings.py` → `aladin_model.py --nightly` → `paper_trader.py` and saves `data/aladin/` and `data/paper_trades/` with a `[skip ci]` commit; the next Live prices run publishes them. Sentiment runs separately every 30 minutes in market hours ("ALADIN sentiment", started by the heartbeat) and the geopolitical index hourly (in "Globe data"). Measured on a 16-core PC: fundamentals 5 s without fetching (about 5.5 minutes to fetch 520 Yahoo statements), filings for 497 stocks 13 min, model `--nightly` 3.5 min (a 2-core runner will be several times slower), paper trader 3 s. These are not yet measured on GitHub's runners.
- **Keys** (all optional, see `.env.example`; on GitHub add them under Settings > Secrets and variables > Actions): `GROQ_API_KEY`, `GEMINI_API_KEY` (transcript tone), `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `HF_TOKEN`, `GROQ_MODEL`, `GEMINI_MODEL`, `ALADIN_GIT_PUSH`, `ALADIN_WS_PORT`. Every script prints a table of which are present and what it does without them. Copy `.env.example` to `.env` (gitignored) for local runs.
- **On your PC:** `scripts/start_aladin_local.bat` (or `.sh`) starts the tick daemon; type `TICKS ON` in the desk. `python scripts/aladin_model.py --full` redoes the walk-forward test (about 26 minutes on 16 cores); `--reeval` re-does the evaluation from its saved record.
- **Tests:** `python -m pytest tests -q` and `node --test tests/js/houses.test.mjs tests/js/combiner.test.mjs`. Browser checks (need `python scripts/dev_preview.py --no-browser` running): `python tests/e2e/acceptance.py all` (console on every tab with the daemon on and off, speed with the CPU throttled, lazy loading, missing-file behaviour, accessibility) and `tests/e2e/before_after.py` (image diff against the page code from before ALADIN).
- **Paper trader:** `python scripts/paper_trader.py` keeps `data/paper_trades/portfolio.json`. Simulated. Not real trades.
### ALADIN & NEXUS: the supply-chain graph, the Globe and the command line

NEXUS adds a dependency map to ALADIN. What is built, and where each part runs:

- **Graph (weekly, GitHub Actions "NEXUS graph", Sundays 03:30 UTC or by hand):** `scripts/revenue_graph_builder.py` reads NSE annual reports and earnings-call transcripts with a free model (Groq `openai/gpt-oss-120b`, then `gpt-oss-20b`, `qwen/qwen3.8-27b`, then Gemini `gemini-flash-latest` and `gemini-flash-lite-latest`; each Groq model has a daily token cap, so a run stops cleanly and resumes from its cache next time). Only edges with a quote that is really in the filing survive. `scripts/geocode_facilities.py` looks up facility addresses on OpenStreetMap (one request a second). `scripts/check_graph.py` audits the result; `data/supply_graph.json` is saved with a `[skip ci]` commit only if the audit says ok. The map is small: free filings name few counterparties, and most stocks show Not measured.
- **Impact score (nightly, inside "ALADIN nightly"):** `scripts/graph_impact.py` writes `data/aladin/impact.json` and `shocks.json` before the model runs; `scripts/aladin_moves.py` writes `moves.json` afterwards. The model uses F_adj = F minus I (see the methodology below).
- **Telemetry (every Live prices run):** `scripts/aladin_telemetry.py --once` writes `telemetry.json` for the Globe: flights from OpenSky (OAuth2 login if `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` work, otherwise anonymous) and ships from AISstream (needs `AISSTREAM_API_KEY`; free coverage is thin, so few ships appear; AISHub works for members). Every record carries its source's own fix time. A credit budgeter works out how often every corridor can be refreshed inside OpenSky's daily credits and publishes it as `cadence_s`: 30-second polling is NOT possible on the free quotas (run `python scripts/aladin_telemetry.py --budget-report` to see the real numbers). The local tick daemon runs the same loop and streams it to your browser over its own WebSocket; the public site only has the workflow snapshot, so there markers older than the extrapolation caps are drawn as ghosts labelled "positions not live". Without a vessel key the layer says so.
- **In the desk:** the NEXUS drawer (open from a stock, `SPLC`, or a link such as `#nx=...`), the Map tab (facilities, flights, ships, chokepoints, hotspots), the command line (`SPLC`, `SWEEP`, `FLIGHT`, `VESSEL`, `HOUSE`, `SECTOR`, `GEO`, `MOVERS`) and dependency lines in Movers, Sectors and Houses.
- **The WebGL globe (Globe and Flat on the Map tab):** a Three.js scene (`desk-globe3d.js`; three.js 0.186.1 is imported from jsDelivr only when Globe or Flat is opened, so no other tab pays for it). Flights and vessels are placed from their OWN fix time and moved along their reported course with spherical destination-point maths (not degrees plus metres); a new fix is blended in over about a second (no teleporting); a marker past 120 s (flights) or 300 s (ships) stops and is drawn as a hollow ghost, and is removed after 10 and 30 minutes. On the public site (a snapshot minutes old) every marker is already past its cap, so nothing animates and the chip says "positions not live". Trails fade over a minute; click or tap opens the NEXUS drawer, which on a desktop-width screen docks beside the globe and leaves it usable (a bottom sheet on a phone); Follow keeps the camera on the selected marker; the List view is the keyboard equivalent. A frame-rate governor steps down (trails off, then at most 2,000 markers, then lower sharpness) and back up after 10 s of smooth frames, with a "Reduced detail" chip. `prefers-reduced-motion` turns off trails and auto-rotation. If WebGL is missing or the context is lost the flat 2D map is used with a one-line notice. Measured (`python tests/e2e/globe3d_check.py`): 2,500 flights + 1,500 ships with trails hold 60 frames a second, on this PC's graphics card (`GL_HEADED=1`, our code 2.7 ms a frame) and in the test browser's software WebGL; 20 open/close cycles leave no geometry or texture behind.
- **Keys (all optional, names only; see `.env.example`):** `GROQ_API_KEY`, `GEMINI_API_KEY`, `GEOCODE_CONTACT` (an email for the geocoder's User-Agent), `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`, `AISSTREAM_API_KEY`. On GitHub add the same names under Settings > Secrets and variables > Actions. Never commit real values; `.env*` and `*credentials*.json` are git-ignored.
- **Tests:** `python -m pytest tests -q`; `node --test tests/js/*.test.mjs`; browser checks `python tests/e2e/acceptance.py all`, run with `python scripts/dev_preview.py --no-browser` running. `python scripts/check_banned.py` guards the wording.

### Check the live feed

Without a demat account there are no Angel One keys, and none are needed: the desk's live feed is NSE's own website data, which needs no account. Check it (this is also what the command does by default when no `ANGEL_*` keys are set):

```
python scripts/check_live_feed.py --source nse      # the free feed: session, each list, coverage, freshness, movement
```

It prints PASS, FAIL or SKIP per stage. Measured on 6 Oct 2026: 6 lists answered in 1.6 s, 316 stocks get a live price (194 with open, high, low and volume, 122 price only) plus 139 indices. Outside market hours the freshness and movement stages are skipped. The free feed is unofficial and can change shape, which is why this check exists. No free source covers every stock in real time: Yahoo's NSE prices are delayed 15 minutes (the site's own refresh), and every real-time Indian feed needs a broker account.

**Angel One (optional, account holders only).** The Angel One feed was built and tested against stand-ins (the login, the TOTP, the instrument list, the price messages, reconnecting, and a new login when the daily session ends are all covered by `tests/test_angel_feed.py`); the holder of a real account can test it with:

```
python scripts/check_live_feed.py --source angel            # listens for 30 seconds to RELIANCE, TCS, INFY, HDFCBANK, SBIN
python scripts/check_live_feed.py --source angel --seconds 60 --symbols RELIANCE,SBIN
```

It prints PASS, FAIL or SKIP for five stages (keys, packages, login, feed, ticks), with the delay between the exchange's time stamp and your clock (median, 95th percentile, worst) and the gaps between prices. It prints each `ANGEL_*` setting only as `set` or `missing`, never a key, a token or a TOTP code, and a failure shows its reason, not a traceback. Outside market hours (Mon-Fri 09:15-15:30 IST) no prices are sent, so the last stage is skipped and the first four still prove the login and the connection. Exit code 0 means every stage passed or was skipped for a stated reason; without keys it says which are missing and exits with 2.

### Flights and ships: what the free quotas allow

`python scripts/aladin_telemetry.py --budget-report` prints, for the corridors in `data/config/trade_lanes.json` and your OpenSky login, the credits per request, the requests per day, and the refresh rate every corridor can actually have. With the default corridors that is about 36 minutes anonymously and about 6 minutes with a working login, never every 30 seconds, and the Globe shows the achieved rate (`cadence_s`) and the age of each position instead of promising one.

### When a workflow run fails

Every run of ALADIN nightly, Live prices and the NEXUS graph ends with a **run report**: open the run on GitHub, then the job, then **Summary**. It lists every step with its result and how long it took, what the run produced (files, sizes, row counts, data dates), which sources fell back (for example OpenSky ran anonymously, no vessel feed, prior weights), and which step failed. The same facts are in the `run-report-*` artifact (`run_report.json`). Nobody outside GitHub can read the step logs, so when something fails paste back two things: **(1) the summary table** and **(2) the last 50 lines of the failing step's log** (click the step, scroll to the end). The public run list (`https://api.github.com/repos/<owner>/<repo>/actions/runs`) shows each run's status without a login, but the logs themselves need a token with `actions: read`, which the report step has and nobody else does.

<!-- ALADIN-METHOD:START (generated by scripts/make_aladin_readme.py from data/config/aladin_method.json: edit that file, not this block) -->
### ALADIN methodology (the same text the ALADIN tab shows)

*ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice.*

**What ALADIN is**

ALADIN gives each NSE security a probability that its price will be higher after 5, 10 or 20 trading days. It combines three views of the stock, each shown on its own so you can see where a number comes from: a Technical view (price and market patterns), a Fundamental view (company accounts and filings) and a Sentiment view (news, retail chatter and institutional flows). A fourth input, liquidity sweeps, is added during market hours when the local tick feed is running.

**The question it answers**

Will the stock's close be higher than today's close after 5, 10 or 20 trading days? That is raw direction, not performance against the index. Every accuracy figure is placed next to the base rate, the share of past cases that really did go up, because always saying "up" would already be right about half the time.

**Technical view**

About 80 inputs per stock per day feed three gradient-boosted tree models (LightGBM, three random seeds) for each horizon: returns over several windows, distance from moving averages, RSI, ADX, MACD, Bollinger bands, volatility, 52-week highs and lows, volume, beta to the NIFTY, sector-relative returns, market breadth and dispersion, and where each stock ranks among all stocks that day.

Extra inputs: the part of each NIFTY 500 stock's recent return left over after removing the common market factors (principal-component residuals); the gap between the stock and its most similar same-industry peer when the two are cointegrated (Engle-Granger test, followed by a Kalman filter); the probability that the market is in a turbulent regime (a two-state hidden Markov model, fitted only on training data and used only in its forward-filtered form); and jump statistics (how often and how large the stock's unusual daily moves have been).

Separate calm-market and turbulent-market model sets are trained and used only if they scored better than a single model on years the models never saw. Probabilities are then calibrated (isotonic regression): in the tests, each year is calibrated only on earlier years, so the test is not flattered; the live model uses all unseen years pooled. The technical score T is 200 times (p minus 0.5), limited to the range -100 to +100.

**Fundamental view**

From Yahoo Finance statements: Value (earnings before interest and tax over enterprise value, free cash flow over market value, book to price, enterprise value over assets, and the growth rate the price implies), Quality (return on invested capital, gross profit over assets, accruals, return on equity, earnings stability) and Fundamental momentum (revenue acceleration, operating-margin change). Each metric is trimmed at the 2.5th and 97.5th percentiles, standardised across stocks, and averaged. The composites are then made independent of company size and industry, and Quality is removed from Value, and Quality and Value from momentum, so the three do not repeat each other.

Banks, finance companies and insurers use only book to price, return on equity, earnings stability and momentum. A distress band is the worse of the Merton distance to default and the Altman Z'' score; it is not applied to financials or to companies with no debt. There is no free labelled data set of Indian defaults, so no machine-learned default model is used. Announcements on NSE are scored for tone (FinBERT) and hedging; earnings-call transcripts are read by a cloud language model when a key is configured, otherwise by a local fallback. Delivery percentage trend and bulk and block deals are shown as context.

The fundamental score is F = 100 times tanh(z / 1.5), where z = 0.35 Value + 0.35 Quality + 0.20 Fundamental momentum + 0.10 filings tone, minus a penalty for a Moderate (0.4) or High (1.0) distress band. A missing part is left out and the weights of the others are rescaled; coverage shows how much was present.

**Sentiment view**

Headlines from Mint, Economic Times, Business Standard and Google News (Moneycontrol headlines, found through Google News) are scored by FinBERT and matched to stocks by symbol, company name or alias. A headline that names no company counts for its business group. Sector and market-wide headlines only add a little context. Retail sentiment from Reddit counts only when at least five different authors mention the stock in 24 hours. Market-wide net inflows or outflows of foreign and domestic institutional money are added to every scored stock with weight 0.15. A stock with no specific headline in 72 hours shows NO NEWS and has no sentiment score; it is not treated as neutral.

The score runs from -100 to +100: BAD (up to -60), POOR (-60 to -20), NEUTRAL (-20 to +20), GOOD (+20 to +60), EXCELLENT (+60 and above). A small adjustment of at most 20 points reflects regions in the news-attention index that are known to affect the stock's sector.

**Liquidity sweeps**

When the local tick program is running on a PC during market hours, 15-minute bars are built from NSE's free website feed and compared with nearby price levels: yesterday's high and low, the 20-day extremes and clusters of equal highs and lows. A sweep is a short break through such a level on unusually heavy volume (above 1.8 times the normal volume for that time of day, or the recent average when that is missing) that closes back inside with a long wick. A sweep above a level leans down and a sweep below leans up. The score fades with a 45-minute half-life and resets each day. The free feed covers only index levels and the stocks on NSE's own movers and most-active lists, so most stocks have no sweep reading. The sweep weight is a prior; it has not been validated against past data.

**Supply-chain dependencies (NEXUS)**

NEXUS is a map of which company supplies which, built only from what listed companies themselves disclose: annual reports (segment and major-customer notes) and earnings-call transcripts, read by a free language model. An edge is kept only if the model returns a word-for-word quote that is really in the filing, names a counterparty, and passes a fixed confidence rubric (0.5 for a verified quote, 0.2 for a named counterparty, 0.2 for a stated share, 0.1 for a recent filing). Edges to a group or a parent instead of a named company are dropped. A share of revenue (the supplier's) and a share of purchases (the customer's) are never mixed. Nothing is filled in from the model's general knowledge: where a filing says nothing, the map has nothing.

The map is small. Free filings name few customers and suppliers, and few of the named companies are themselves listed, so most stocks have no edge and show Not measured. The Globe adds facility locations (looked up on OpenStreetMap), flights (OpenSky) and ships (AISstream) when those free feeds respond; each layer shows its own age and says when it has no data.

Impact score I for a stock is 100 times minus the sum, over its disclosed edges to listed companies it depends on, of the dependency share w, the edge confidence and tanh(z / 2), limited to -100 to +100; positive means adverse. z is the counterparty's 5-day return after removing its beta to the NIFTY 50 (beta from the previous 250 days only), divided by its own residual volatility and limited to plus or minus 3. It is computed nightly from the last close, never intraday. A walk-forward test checks whether I predicts the stock's next 5-day residual return; while its t-statistic is below 2 the term is labelled prior, unvalidated. The weights are fixed and never tuned to pass the test.

**How the views are combined**

logit(p) = logit(p_technical) + 0.20 x F_adj/100 + 0.12 x S/100 + 0.18 x S_sweep/100, where F_adj is the fundamental score F minus the NEXUS impact score I, limited to -100 to +100 (so a dependency on a counterparty that is falling pulls the fundamental term down). A missing view adds nothing; a stock with no impact score has F_adj = F. p is limited to the range 0.02 to 0.98. Confidence is Low when p is within 0.03 of 0.5, Medium within 0.07 and High beyond that. Agreement counts how many of the available views (Fundamental, Technical, Sentiment) lean the same way as p; a view leans up above +10 and down below -10.

These weights are priors chosen in advance. Every night the model saves its predictions. Once at least 120 trading days of them have matured, a logistic stacker is fitted on them and replaces the priors only if it is better on days it was not fitted on.

**How it was tested**

Walk-forward: each test year from 2013 onward is predicted by models trained only on earlier years, with a gap of 10, 15 or 25 trading days (for the 5, 10 and 20-day horizons) between training and test so no answer leaks across. All accuracy, AUC, Brier score and decile figures on this page come from those unseen years. A stock is in the training set on a given day only if its own trailing 20-day traded value was at least Rs 5 crore that day (point in time, so today's liquidity does not leak into the past); other securities are scored with the same models. Month-of-year and day-of-month are model inputs: they improved 8 of 13 test years but not all, so treat that gain as modest. Caveat: the saved price history holds only stocks listed today (delisted companies are missing), so the figures are likely a little optimistic. Securities with fewer than 250 daily bars get no probability.

Out of sample, the model's edge over the base rate is small. The yearly table shows that it varies from year to year and is sometimes no better than chance.

An LSTM neural network (one layer of 32 units on the last 60 trading days of returns, range, volume and close position, at most 8 epochs) was tested walk-forward for each year from 2018, under a rule fixed before any result was seen: keep it only if averaging it with the LightGBM model raises the out-of-sample AUC by at least 0.003 on average and in at least two thirds of the years. It lowered the average AUC by 0.0053 and helped in 4 of 9 years, so it is tested, shows no out-of-sample gain, and is not used.

**Not measured, and why**

Satellite imagery and card-spend data (no free source), job postings (the sites' terms forbid scraping), ESG scores (no free source), order-book models (no free NSE order-book history), reinforcement-learning execution (it improves trade execution, not direction), Heston option-model calibration (no free options history), EPS surprise and analyst revisions (Yahoo has none for NSE names). Yahoo returns only about four annual and five quarterly periods, so earnings stability and quarter-on-quarter revenue acceleration are usually missing, and annual figures are used instead where that is stated.

**Paper trading**

A simulated long-only portfolio takes only the strongest cases: 10-day P(up) above 0.60, High confidence and 3 of 3 views agreeing, in the NIFTY 500 or a liquid main-board stock. Entry is at the open of the next session, never at the close that produced the signal; exit is at the close of the 10th trading day after entry. Costs of 0.5% for the round trip are deducted. Each position is Rs 1,00,000, one position per symbol, at most 10 open. Returns are compared with the NIFTY 50 over the same days. The thresholds are not lowered to create activity, so expect long stretches with no trades. Simulated. Not real trades.

**Limits**

Markets are mostly noise over days and weeks; a 55% chance still fails 45% of the time. Figures are before costs and taxes. Past accuracy is no promise of future accuracy. Data from free sources can be late, missing or wrong, and each panel shows how old its data is.

**Not measured, and why**

- Satellite imagery: No free source.
- Card-spend data: No free source.
- Job postings: The sites' terms forbid scraping.
- ESG scores: No free source.
<!-- ALADIN-METHOD:END -->

## Design system & motion

The public pages share one flat "Midnight Slate" system (tokens, components, motion rules, how to add an effect): see `docs/DESIGN_SYSTEM.md`. Motion is opt-in and honest: with reduced motion or no JavaScript every page is fully readable, and every figure shown comes from the site's own published files (`live.json`, `screener.json`, `days.json`, `status.json`). Brand images are regenerated with `python scripts/make_brand_assets.py`. The audit and acceptance results for the immersive pass are in `docs/PHASE0_AUDIT.md` and `docs/PHASE6_ACCEPTANCE.md`.
