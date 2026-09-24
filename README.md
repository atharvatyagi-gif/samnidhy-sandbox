# Understanding the Indian Stock Market — Interactive Dashboard

An interactive, single-file dashboard that teaches complete beginners how the stock market works,
using real data on five NSE-listed companies and the Nifty 50 index.

Open `dashboard.html` by double-clicking it. You don't need a server, an install or a build step,
and it works offline (see [Offline behaviour](#offline-behaviour)).

---

## What it teaches

| Lesson | Idea | What you can do |
|---|---|---|
| **1. How a price is set** | A price is just the last trade between a buyer and a seller. The bid-ask spread is what liquidity providers earn. | Place buy/sell orders against a live order book for RELIANCE and watch the price and spread move. |
| **2. What a company is worth** | Market cap measures size. P/E measures how expensive a share is relative to profit. | Compare all five on both. See which are pricier or cheaper than the group median. Drag an earnings-growth slider to see implied prices 3 years out. |
| **3. Risk and return** | Combining stocks that don't move together lowers risk below the average of the parts (diversification). | Allocate a portfolio with sliders or presets and watch its risk drop on the scatter plot. Click the correlation heatmap to build pairs. Compare each stock's volatility, max drawdown and beta. |
| **4. The power of compounding** | Returns earned on earlier returns make wealth grow faster over time. | Run a SIP calculator whose return defaults to the real Nifty 50 figure. Compare what you put in with what it becomes, and see the cost of starting 5 years later. |
| **5. Five years in the market** | Averages hide the journey. The same five years produced very different outcomes, and a stock can rise a long way and then give most of it back. | Watch an animated race of ₹1,00,000 invested in each stock and the Nifty 50, using real weekly prices. Play, pause, change the speed or drag the timeline, with a live leaderboard. |
| **6. Test yourself** | Recap. | Answer six quiz questions with instant feedback and a score. Every answer is calculated live from the data, so it stays correct after a refresh. |

Every chart has a plain-English caption, and every term is defined in the same lesson that uses it.

The page also has a landing section that includes a ticker tape, a self-drawing Nifty 50 chart and
count-up statistics, all built from the real data. Scrolling triggers reveal and parallax effects.
All animation is switched off automatically for anyone whose operating system asks for reduced
motion.

---

## Data

- **Source:** Yahoo Finance, via the [`yfinance`](https://pypi.org/project/yfinance/) library,
  using NSE tickers. The NSE and BSE websites are not scraped.
- **Tickers:** `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, `ITC.NS`, `INFY.NS`, and `^NSEI` (the Nifty
  50, used as the benchmark).
- **Date range in the current build:** daily prices from **15 Sep 2021 to 22 Sep 2026** (the Nifty
  50 series ends on 21 Sep 2026). Statistics based on returns cover **16 Sep 2021 to 22 Sep 2026**.
  The data was generated on **23 Sep 2026 at 23:43 UTC**. The exact dates are stored in
  `data/data.json` and shown in the dashboard's footer.
- **Adjustments:** prices are fetched with `auto_adjust=True`. yfinance then uses Yahoo's adjusted
  prices, which account for splits, bonus issues **and dividends**. Stock returns are therefore
  close to total returns. The Nifty 50 (`^NSEI`) is a *price* index and excludes dividends, so
  comparisons between the stocks and the index slightly favour the stocks. The dashboard states
  this wherever the two are compared, and the SIP's default Nifty return is conservative for the
  same reason.
- **Company fundamentals:** trailing P/E, market cap, sector and name come from yfinance's `.info`
  and describe the companies *at the time of the fetch*. If a field is missing, the script stores
  `null` and never estimates it. In the current build, no fields are missing.

---

## Project structure

```
dashboard.html            the deliverable: one self-contained file (CSS, JS and data inline)
requirements.txt          pinned Python dependencies
scripts/fetch_data.py     downloads raw daily prices   -> data/raw/*.csv
scripts/process_data.py   computes every statistic     -> data/data.json
scripts/embed_data.py     copies data.json into dashboard.html
data/raw/                 one raw CSV per ticker (so the download needn't be repeated)
data/data.json            processed statistics used by the dashboard
```

---

## Refreshing the data

These steps need Python 3.11 or newer, because the pinned numpy 2.3.4 requires it. The current
build was made with Python 3.14.

```bash
pip install -r requirements.txt

python scripts/fetch_data.py     # 1. download 5 years of daily prices to data/raw/
python scripts/process_data.py   # 2. compute statistics and write data/data.json
python scripts/embed_data.py     # 3. embed data/data.json into dashboard.html
```

Notes:

- `fetch_data.py` retries each ticker up to 4 times, waiting longer after each failure
  (2s, 4s, 8s). If a ticker still fails, the script names it and exits with an error rather than
  carrying on without it. At the end it prints a summary table for each ticker: date range, number
  of rows, missing values, and first and last close.
- If you run it during market hours, Yahoo may return today's unfinished trading session with no
  prices. The script drops that row and says so.
- **Step 3 is required.** The dashboard never loads `data.json` at runtime, because browsers block
  that on `file://`. Its copy is embedded in the page, so the page shows new data only after
  `embed_data.py` has run.

---

## Formulas

**Notation:** *P<sub>t</sub>* is the adjusted close on day *t*, *r<sub>t</sub>* is the daily
return, and there are 252 trading days per year.

### Per-stock metrics (`process_data.py`)

| Metric | Formula |
|---|---|
| Daily return | *r<sub>t</sub>* = *P<sub>t</sub>* / *P<sub>t−1</sub>* − 1 |
| Annualised return (CAGR) | (*P*<sub>end</sub> / *P*<sub>start</sub>)<sup>1/years</sup> − 1, where years = calendar days ÷ 365.25 |
| Annualised volatility | std. dev. of daily returns (sample, ddof = 1) × √252 |
| Maximum drawdown | min over *t* of ( *P<sub>t</sub>* / max<sub>s≤t</sub> *P<sub>s</sub>* − 1 ) |
| Beta vs Nifty 50 | Cov(*r*<sub>stock</sub>, *r*<sub>Nifty</sub>) / Var(*r*<sub>Nifty</sub>), on dates both traded |
| Latest close | last adjusted close in the raw data |
| Trading days | number of daily prices in the raw data |
| Weekly growth series | *P* at each week's last trading day ÷ *P* on the first day. The series starts at 1.0 on the first date, and its last point is the final trading date, so its final value equals *P*<sub>end</sub> / *P*<sub>start</sub>. No prices are filled or interpolated. This is also computed for the Nifty 50. |
| Trailing P/E, market cap, sector | read directly from yfinance `.info`, or `null` if missing |

### Across the five stocks

| Metric | Formula |
|---|---|
| Correlation matrix | Pearson correlation of daily returns, on dates all five traded |
| Covariance matrix (annualised) | covariance of daily returns × 252 |
| Nifty 50 annualised return | same CAGR formula, applied to `^NSEI` |

### Computed live in the dashboard

| Figure | Formula |
|---|---|
| Bid-ask spread | best ask − best bid (also shown as % of the last traded price) |
| Implied EPS | latest close ÷ trailing P/E |
| Median P/E | middle value of the five trailing P/Es. "Pricier" or "Cheaper" is relative to this. |
| Implied price in 3 years | latest close × (1 + *g*)³, where *g* is the growth-rate slider. This assumes the P/E multiple stays the same. |
| Portfolio return | Σ *w<sub>i</sub>* · *R<sub>i</sub>*, where *w* is the weights and *R* is each stock's annualised return |
| **Portfolio volatility** | **√( *w*ᵀ Σ *w* )**, using the annualised covariance matrix Σ, **not** a weighted average of the individual volatilities |
| "No diversification" comparison | Σ *w<sub>i</sub>* · σ<sub>*i*</sub> (weighted average of individual volatilities). This is shown only to contrast with the line above. |
| **SIP future value** | **FV = *P* × [ ((1 + *i*)<sup>*n*</sup> − 1) / *i* ] × (1 + *i*)**, compounded **monthly** |
| SIP total invested | *P* × *n* |
| SIP total gains | FV − total invested |
| Race value (lesson 5) | ₹1,00,000 × weekly growth series |
| Race "gave back" figure | 1 − final value ÷ peak value, for the stock with the largest peak-to-end fall |
| Hero statistics | number of companies; the largest trading-day count; Σ market cap ÷ 10<sup>12</sup> (lakh crore); (end date − start date) ÷ 365.25 |
| Quiz answers | highest trailing P/E; ask − bid; highest pairwise correlation; the equal-weight √(*w*ᵀ Σ *w*); the SIP FV above; lowest maximum drawdown |

For the SIP: *P* is the monthly amount, *i* is the annual return ÷ 12, and *n* is the number of
monthly instalments. Each instalment is invested at the start of its month (an annuity-due), which
is the convention Indian SIP calculators use. At a 0% return, the formula becomes FV = *P* × *n*.
The expected return defaults to the Nifty 50's annualised return over the data period, currently
**5.95%**, and the dashboard labels it as that figure.

---

## Parts of the dashboard that are not real market data

Everything *measured* comes from `data/data.json`. The following parts are simulated, simplified,
illustrative or user input.

- **The order book in lesson 1 is simulated.** Yahoo Finance doesn't provide live order-book
  depth. The book is centred on RELIANCE's real latest close, but the bid and ask quantities are
  randomly generated each time it's reset. Prices move in steps of ₹1 to keep it readable (the real
  NSE step is ₹0.05).
- **The P/E worked example** (₹10 of earnings, ₹200 share price, P/E of 20) is the illustrative
  example from the project brief. It isn't company data.
- **Slider defaults and presets are user inputs, not data.** These include the growth rates
  (−5% to 25%), SIP amounts, the 3-year horizon in lesson 2 and the 5-year delay comparison in
  lesson 4. The one exception is the SIP's default return, which is the real Nifty 50 figure.
- **The lesson 3 portfolio presets are chosen from the data.** The "most similar pair" and the
  "least-correlated trio" are found by searching the correlation matrix, not hard-coded.
- **The quiz's wrong options are principled alternatives, not random numbers.** For the SIP
  question they are: the total deposited, the gain on its own, and simple interest (no
  compounding).
- **The confetti, aurora glow and scrolling word bands are decoration.** They don't show any data.

---

## Offline behaviour

The data, CSS and JavaScript are all inside `dashboard.html`. The only external file is Chart.js
4.5.1, loaded from cdnjs and pinned to that exact version. If the CDN can't be reached, each chart
is replaced by a table of the same numbers. Every other part of the page, including the order book,
sliders, calculators and heatmap, keeps working.

---

## Disclaimer

This dashboard is for education only. All figures are **historical**: past returns, volatility
and correlations don't predict future results. **Nothing here is investment advice.**
