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

`scripts/aladin_ticker_daemon.py` polls NSE's free website feed about every 3 seconds (index levels plus the stocks on NSE's own movers / most-active lists, a few hundred at most) and serves it only to your own browser at `ws://127.0.0.1:8787/ws/ticks`.

1. `scripts/start_aladin_local.bat` (Windows) or `scripts/start_aladin_local.sh` (Mac/Linux). Leave it running.
2. In the desk's command line type `TICKS ON`. The top-right chip then reads "LIVE · NSE WEB (THIS PC, ~3 s)". `TICKS OFF` stops it.

Things to know:
- It is a polled website feed, not an exchange feed: other stocks keep their delayed price (the age is shown). It only runs Mon-Fri 09:00-15:45 IST.
- Chrome and Edge allow a secure page to talk to `127.0.0.1` (they may ask once). Safari blocks it.
- The ticks stay on your machine: `data/live_extra/` is gitignored and never published (NSE's website terms restrict redistributing this data).
- If NSE blocks the connection the daemon backs off and says so; it does not try to get around a block.
- Sub-second prices for every stock would need an Angel One SmartAPI login (the existing relay in `relay/`). That source is not part of this daemon.
- Tests: `python -m pytest tests -q` (no network needed).

### Geopolitical news attention (Globe layer)

`scripts/geo_tension.py` scores ten regions (Hormuz, Red Sea, Israel/Gaza/Lebanon, Russia/Ukraine, India/Pakistan, India/China border, Taiwan Strait, US tariffs, Malacca, OPEC+) by how much and in what tone the news is talking about them, compared with each region's own 30-day history. It measures news attention, not events. Switch it on in the Globe's layer control. The exposure lists are in `data/config/geo_exposure.json` (checked by `scripts/check_geo.py`).

- Source is Google News RSS (no key). GDELT, the usual choice, answers HTTP 429 from GitHub Actions and from a home PC, so it is not used.
- Google returns at most 100 items per query and has no history, so the baseline is collected by the hourly Globe workflow itself (`data/aladin/geo_history.json`). A region shows "Building baseline" and no score until it has 48 samples over 3 days. Busy regions that hit the 100-item cap are marked as a lower bound.
- Tone is a transparent word-list count over headlines (`data/config/tone_words.json`), not a language model.

### ALADIN sentiment engine

`scripts/aladin_sentiment_engine.py --once` (or `--loop 900` on your PC) scores headlines from Mint, the news wire (ET, Business Standard) and Google News (Moneycontrol headlines, queried per company) with FinBERT, matches them to NSE stocks, and blends in retail chatter (Reddit) and FII/DII flow into `data/aladin/sentiment.json`. The "ALADIN sentiment" workflow runs it every 30 minutes in market hours and hourly otherwise, started by the heartbeat.

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

Separate calm-market and turbulent-market model sets are trained and used only if they scored better than a single model on years the models never saw. Probabilities are then calibrated (isotonic regression) on the pooled results from those unseen years. The technical score T is 200 times (p minus 0.5), limited to the range -100 to +100.

**Fundamental view**

From Yahoo Finance statements: Value (earnings before interest and tax over enterprise value, free cash flow over market value, book to price, enterprise value over assets, and the growth rate the price implies), Quality (return on invested capital, gross profit over assets, accruals, return on equity, earnings stability) and Fundamental momentum (revenue acceleration, operating-margin change). Each metric is trimmed at the 2.5th and 97.5th percentiles, standardised across stocks, and averaged. The composites are then made independent of company size and industry, and Quality is removed from Value, and Quality and Value from momentum, so the three do not repeat each other.

Banks, finance companies and insurers use only book to price, return on equity, earnings stability and momentum. A distress band is the worse of the Merton distance to default and the Altman Z'' score; it is not applied to financials or to companies with no debt. There is no free labelled data set of Indian defaults, so no machine-learned default model is used. Announcements on NSE are scored for tone (FinBERT) and hedging; earnings-call transcripts are read by a cloud language model when a key is configured, otherwise by a local fallback. Delivery percentage trend and bulk and block deals are shown as context.

The fundamental score is F = 100 times tanh(z / 1.5), where z = 0.35 Value + 0.35 Quality + 0.20 Fundamental momentum + 0.10 filings tone, minus a penalty for a Moderate (0.4) or High (1.0) distress band. A missing part is left out and the weights of the others are rescaled; coverage shows how much was present.

**Sentiment view**

Headlines from Mint, Economic Times, Business Standard and Google News (Moneycontrol headlines, found through Google News) are scored by FinBERT and matched to stocks by symbol, company name or alias. A headline that names no company counts for its business group. Sector and market-wide headlines only add a little context. Retail sentiment from Reddit counts only when at least five different authors mention the stock in 24 hours. Market-wide net inflows or outflows of foreign and domestic institutional money are added to every scored stock with weight 0.15. A stock with no specific headline in 72 hours shows NO NEWS and has no sentiment score; it is not treated as neutral.

The score runs from -100 to +100: BAD (up to -60), POOR (-60 to -20), NEUTRAL (-20 to +20), GOOD (+20 to +60), EXCELLENT (+60 and above). A small adjustment of at most 20 points reflects regions in the news-attention index that are known to affect the stock's sector.

**Liquidity sweeps**

When the local tick program is running on a PC during market hours, 15-minute bars are built from NSE's free website feed and compared with nearby price levels: yesterday's high and low, the 20-day extremes and clusters of equal highs and lows. A sweep is a short break through such a level on unusually heavy volume (above 1.8 times the normal volume for that time of day, or the recent average when that is missing) that closes back inside with a long wick. A sweep above a level leans down and a sweep below leans up. The score fades with a 45-minute half-life and resets each day. The free feed covers only index levels and the stocks on NSE's own movers and most-active lists, so most stocks have no sweep reading. The sweep weight is a prior; it has not been validated against past data.

**How the views are combined**

logit(p) = logit(p_technical) + 0.20 x F/100 + 0.12 x S/100 + 0.18 x S_sweep/100. A missing view adds nothing. p is limited to the range 0.02 to 0.98. Confidence is Low when p is within 0.03 of 0.5, Medium within 0.07 and High beyond that. Agreement counts how many of the available views (Fundamental, Technical, Sentiment) lean the same way as p; a view leans up above +10 and down below -10.

These weights are priors chosen in advance. Every night the model saves its predictions. Once at least 120 trading days of them have matured, a logistic stacker is fitted on them and replaces the priors only if it is better on days it was not fitted on.

**How it was tested**

Walk-forward: each test year from 2013 onward is predicted by models trained only on earlier years, with a gap of 10, 15 or 25 trading days (for the 5, 10 and 20-day horizons) between training and test so no answer leaks across. All accuracy, AUC, Brier score and decile figures on this page come from those unseen years. The training universe is the NIFTY 500 plus main-board stocks trading at least Rs 5 crore a day on average; other securities are scored with the same models. Securities with fewer than 250 daily bars get no probability.

Out of sample, the model's edge over the base rate is small. The yearly table shows that it varies from year to year and is sometimes no better than chance.

**Not measured, and why**

Satellite imagery and card-spend data (no free source), job postings (the sites' terms forbid scraping), ESG scores (no free source), order-book models (no free NSE order-book history), reinforcement-learning execution (it improves trade execution, not direction), Heston option-model calibration (no free options history), EPS surprise and analyst revisions (Yahoo has none for NSE names), and an LSTM neural network (optional, not tried). Yahoo returns only about four annual and five quarterly periods, so earnings stability and quarter-on-quarter revenue acceleration are usually missing, and annual figures are used instead where that is stated.

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
