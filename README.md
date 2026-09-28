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
Registering needs a `@tapmi.edu.in` email, the student's **roll number + date of birth** (checked against the TAPMI student
list) and a **new** B-Lab password. Each student can register once; the terminal opens only for completed registrations.
The student list itself never goes online: `scripts/student_allowlist.py` turns it into one-way SHA-256 keys.

Setup (once):
1. Firebase console: create a project → Authentication → enable **Email/Password** → create a Firestore database.
2. Paste the web-app config into `config.js` (lines 7–12).
3. `firestore.rules`: replace `admin_email_here` with your admin email (lower case) → paste into Firestore → Rules → Publish.
4. Authentication → Users → **Add user** with that admin email and a password.
5. Authentication → Settings → Authorized domains: add `atharvatyagi-gif.github.io`.
6. On your computer: `pip install openpyxl`, then
   `python scripts/student_allowlist.py "Student List for ID Card- Batch 2026-29.xlsx"` → `private/allowlist_keys.json`.
7. `python scripts/dev_preview.py` → open `http://127.0.0.1:8765/admin-allowlist.html`, sign in as the admin, upload the file.
The Excel file, `private/` and the admin page are never committed or published.

### Expert terminal: every NSE stock
- `scripts/nse_eod.py` (daily): NSE's official bhavcopies for ~1 year → all ~3,500 NSE stocks, SME boards and ETFs
  (`data/terminal/`, kept in the GitHub Actions cache, not in git).
- `scripts/terminal_live.py` (every 15 min in market hours): delayed 5-minute prices from Yahoo Finance for ~2,950
  main-board stocks; prices that disagree with NSE's own close are rejected. SME stocks show NSE end-of-day prices.
- `scripts/terminal_fund.py` (daily): fundamentals for the NIFTY 500.
- Developer preview without signing in (local only): `python scripts/dev_preview.py` → `expert-dev.html`.
