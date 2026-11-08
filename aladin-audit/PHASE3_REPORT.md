# ALADIN audit, Phase 3: what works in Indian markets (evidence review)

Written 2026-11-08. How I searched: OpenAlex (the open scholarly database, official API) for 23 searches across options A–G,
about 280 records (`aladin-audit/phase3/search.json`, made by `scripts/phase3_search.py`); Semantic Scholar for missing abstracts;
the IIM Ahmedabad data library page and its data files. Web search engines answered with a bot check, so I did not use them.

**What "read" means here.** For most papers I read the **abstract** (the authors' own summary), not the full text; the table says
which. I list a source only if I opened at least its abstract. Two papers had no abstract anywhere and are listed as "not read",
not used. NSE's factor-index factsheets (niftyindices.com) answered with a script-only page, so they are **not read**.

**Grades.** Strong = many stocks and years, India, and either held on later data or includes costs. Medium = India and a
reasonable sample, but no costs or no later test. Weak = small sample, short period, no trading test, or not India.

## 3.1 and 3.2 Sources and grades

| # | Source (link) | Read | India sample | Costs | Held later? | Finding | Grade |
|---|---|---|---|---|---|---|---|
| 1 | IIM Ahmedabad Fama-French and Momentum data library, release to **December 2025** (not March 2023 as the brief said) — https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/ | page + monthly data files | BSE+NSE, micro-caps and penny stocks removed, survivorship-adjusted, Oct 1993–Dec 2025 | no | **yes**: the method was published in 2013 and momentum kept working 2014–2025 | Winners-minus-losers +10.6% a year since 1994 (+11.5% 2016–2025). Long-only big-cap winners +18.6% a year 2016–2025 vs market +9.2%; worst fall −26.5% vs −34.4%. Crash months −27.6% (Nov 2001), −25.0% (May 2009) | **Strong** |
| 2 | Implementing a systematic long-only momentum strategy: evidence from India (SSRN 2019) — https://doi.org/10.2139/ssrn.3510433 | abstract | NIFTY 100, top tenth, monthly | **yes** (discount broker) | – | +10.7% a year over the NIFTY 100; 32% turnover a month; occasional crashes | Medium |
| 3 | Momentum anomaly: evidence from the Indian stock market (J. Adv. Mgmt Research 2017) — https://doi.org/10.1108/jamr-11-2015-0081 | abstract | 470 BSE stocks, 1997–2013 | no | no | Momentum profitable; **driven by winners**, so long-only works; not a size or liquidity effect | Medium |
| 4 | Are prominent equity market anomalies in India fading away? (Global Business Review 2019) — https://doi.org/10.1177/0972150918811248 | abstract | NSE 500, 2005–2016 | no | – | **Disagrees**: value and momentum explained by risk models in this period; anomalies fading | Medium |
| 5 | Risk-managed momentum: evidence from Indian stock market (FIIB Business Review 2021) — https://doi.org/10.1177/23197145211023001 | abstract | 450 BSE stocks | no | – | Momentum has rare severe crashes; scaling it by risk **doubles** the risk-adjusted return | Medium |
| 6 | Equity market anomalies, VIX and asset pricing: trading strategies for India (Indian Economic Journal 2019) — https://doi.org/10.1177/0019466220951978 | abstract | 2001–2019 | no | – | Size, value, profitability, investment, momentum all significant; only size reverses with VIX | Medium |
| 7 | The cross-section of Indian stock returns: evidence using machine learning (Applied Economics 2021) — https://doi.org/10.1080/00036846.2021.1982132 | abstract | **all listed firms, survivorship-free**, 1994–2019 | not stated | **rolling out-of-sample** | 14 of 35 characteristics significant; machine learning beats linear forecasts; strategies on the forecasts earn significant returns | **Strong** (no costs stated) |
| 8 | Quality investing in the Indian stock market (Managerial Finance 2018) — https://doi.org/10.1108/mf-07-2017-0248 | abstract | BSE 500 | no | – | Two of four quality measures (Grantham quality, gross profitability) beat the market after size, value, momentum | Medium |
| 9 | Machine-learning quality minus junk (Finance Research Open 2025) — https://doi.org/10.1016/j.finr.2025.100041 | abstract | BSE non-financials, 2013–2022 | no | – | Quality premium exists but **weakens after COVID** | Medium |
| 10 | Does profitability explain the low-risk anomaly in India? (Quarterly Rev. Econ. Finance 2025) — https://doi.org/10.1016/j.qref.2025.102060 | abstract | NIFTY 500, 2003–2022 | no | – | Low-risk stocks do not earn less; profitable stocks do better | Medium |
| 11 | The volatility effect: evidence from India (Applied Finance Letters 2016) — https://doi.org/10.24135/afl.v5i1.32 | abstract | 2001–2015 | no | – | Low-volatility tenth +11.4% a year excess vs high +1.3% | Medium |
| 12 | Volatility effect and the role of firm quality (IIMB Management Review 2017) — https://doi.org/10.1016/j.iimb.2017.01.001 | abstract | BSE 500, 2000–2013 | no | – | **Disagrees**: no low-volatility anomaly; high-volatility stocks did better | Medium |
| 13 | A first look at the properties of India's volatility index (Int. J. Emerging Markets 2012) — https://doi.org/10.1108/17468801211209938 | abstract | India VIX | – | – | India VIX carries information about future market volatility | Medium |
| 14 | Post-earnings-announcement drift anomaly in India (Theoretical Economics Letters 2018) — https://doi.org/10.4236/tel.2018.814197 | abstract | 2002–2017 | no | sub-periods | Drift significant and robust | Weak (low-tier journal) |
| 15 | PEAD and value-glamour anomalies in NSE firms (Trends Econ. Mgmt 2021) — https://doi.org/10.13164/trends.2021.37.27 | abstract | 100 NSE firms, 2014–2018 | no | – | **Disagrees**: stocks properly priced after results; no inefficiency | Weak (small) |
| 16 | Price, earnings and revenue momentum: Indian evidence (2015) — RePEc, no DOI | abstract | BSE 500, 2002–2010 | no | – | Earnings momentum the most profitable long-short; it subsumes price momentum | Medium |
| 17 | Impact of corporate earnings announcements (European Economic Letters 2026) — https://doi.org/10.52783/eel.v16i1.4174 | abstract | BSE 500, 2015–2024 | no | – | Post-announcement drift present; bad news reacts more strongly | Weak |
| 18 | Optimizing LSTM for time series prediction in the Indian stock market (Procedia CS 2020) — https://doi.org/10.1016/j.procs.2020.03.257 | abstract | prices | no | no | Price forecasting accuracy only, no trading test | Weak |
| 19 | Ensemble machine learning for Indian banks (J. Risk Fin. Mgmt 2022) — https://doi.org/10.3390/jrfm15080350 | abstract | bank stocks | no | no | Error measures only, no trading test | Weak |
| 20 | Pair trading with cointegration for the Indian market (ASIANCON 2022) — https://doi.org/10.1109/asiancon55314.2022.9909455 and a 2023 preprint https://doi.org/10.36227/techrxiv.23539989 | abstract | a few sectors, 2018–2022 | no | 1 year | Pairs can be found; needs short selling | Weak |
| 21 | Investor sentiment and asset returns: the case of India (Afro-Asian J. Fin. Acc. 2017) — https://doi.org/10.1504/aajfa.2018.089198 | abstract | 2004–2016 | – | – | **Sentiment index fails to predict market returns**; only small low-priced stocks | Medium |
| 22 | Aggregate news sentiment and stock market returns in India (J. Risk Fin. Mgmt 2023) — https://doi.org/10.3390/jrfm16080376 | abstract | market level | – | – | News sentiment effect is **short-lived** | Medium |
| 23 | Twitter sentiment and the Indian stock market (2025) — https://doi.org/10.52783/jisem.v10i3.5768 | abstract | 2015–2022 | – | – | No causal link from Twitter sentiment to returns | Weak |
| 24 | Physical momentum in the Indian stock market (arXiv 2023) — https://doi.org/10.48550/arxiv.2302.13245 | abstract | NSE 500, 2014–2021 | no | – | Strong **daily reversal** effect | Weak |
| – | Risk-adjusted returns from statistical arbitrage in Indian stock futures (Asia-Pacific Fin. Markets 2020) — https://doi.org/10.1007/s10690-020-09317-1 | **not read** (no abstract) | | | | | not used |
| – | Momentum, reversals and liquidity: Indian evidence (Pacific-Basin Finance J. 2023) — https://doi.org/10.1016/j.pacfin.2023.102193 | **not read** (no abstract) | | | | | not used |
| – | NSE factor indices (NIFTY200 Momentum 30, Quality 30, Low Volatility 30) — niftyindices.com | **not read** (script-only page) | | | | | not used; can be saved by hand from a browser if you want them |

**ALADIN's own evidence** (from Phase 2, 2015–2026, after 37 bps costs, vs the market, survivorship not removed):
the weekly SELL list (bottom 2%) lagged the market by −89 bps a week on 2021–2026; ALADIN 1's best 5% at a 20-day hold
earned +56 bps per trade (+42 on 2021–2026); 5- and 10-day holds did not survive costs once the filter was loosened.

## 3.3 Summary per option

### A. Momentum + quality ranking — evidence: **strong for momentum, medium for quality**
Momentum is the best-documented effect in India: the IIMA data show it kept working for 12 years after it was published, it is
driven by **winners** (so it works long-only), and a long-only version of the 100 most liquid stocks beat its index by about
11% a year with costs considered. Against it: one study finds it was explained by risk in 2005–2016, and it has rare crashes
(−25% to −28% in a month, after sharp market rebounds). Quality helps in some studies but weakened after COVID. Evidence runs to
December 2025. Fit with your −25% limit: the long-only winners' worst fall in 2016–2025 was −26.5%, so it needs risk control (E).

### B. Earnings-surprise drift (PEAD) — evidence: **mixed, weak**
Two weak papers find drift after results; one small study finds none; a medium study finds earnings momentum the strongest
long-short signal (2002–2010). India-specific evidence is mostly from low-tier journals and short samples. It also needs
point-in-time result dates: ALADIN does not store filing dates today (it does keep a board-meeting file for the movers test).
Confidence: low.

### C. Machine-learning probability model — evidence: **one strong study, many weak**
The one high-quality study (survivorship-free, all listed firms, 1994–2019, rolling out-of-sample) finds machine learning beats
simple models and its forecasts earn significant returns, but costs are not stated in the abstract. Most other Indian ML papers
only measure price-forecast error, which says nothing about profit. ALADIN's own LightGBM ranking is real but small after costs,
better at a 20-day hold. Confidence: medium; the overfitting risk is high.

### D. Regime-gated blend — evidence: **weak**
I found no Indian study that tests switching factor weights by market state with a trading result. Studies show India has
calm and turbulent states (Markov-switching papers) and that most anomalies do not reverse with VIX (source 6). Confidence: low.

### E. Risk-first model (predict risk, then size and filter a simple ranking) — evidence: **medium**
India VIX carries information about future volatility (source 13), and scaling momentum by risk doubled its risk-adjusted return
in India (source 5). Risk is more predictable than direction, and this is the option that most directly serves your −25% limit.
Confidence: medium as an overlay on A, not on its own.

### F. Pairs trading — evidence: **weak**
Only conference papers and a preprint with short test periods; the one journal paper could not be read. It also needs shorting,
which retail traders can do only intraday or through futures. Confidence: low.

### G. Other ideas found
- **"Avoid" list from the weekly SELL side** (ALADIN's own evidence): the most reliable result in this whole audit; useful as an
  exit or no-buy filter, not as a source of profit on its own (shorting needs futures).
- **Low-volatility / low-risk**: contested in India (one study for, one against).
- **News and social sentiment**: Indian studies find it short-lived or not predictive; supports keeping sentiment out of the
  signal, as ALADIN's own tests also found.
- **Short-term reversal**: one weak study; costs are the big risk at daily and weekly holds.

## What this means for Phase 4

Order of testing, strongest evidence first: **A (momentum, long-only) with E (risk control)**, then **C (machine learning at a
20-day hold)**, then quality and low-risk variants, then B, D and F as checks. Each will be tested at tight, medium and loose
filters, as you asked, inside your −25% limit.
