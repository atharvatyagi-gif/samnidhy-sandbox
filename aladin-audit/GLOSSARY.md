# ALADIN audit glossary

Every term used in the audit, in plain words. Added to in each phase.

| Term | Meaning |
|---|---|
| Long | A trade that makes money if the price goes up (buy now, sell later). |
| Short | A trade that makes money if the price goes down. In India a retail trader can only do this intraday or through futures. |
| Signal | The model's call for a stock: BUY, SELL or HOLD (no call). |
| Stop loss | The price at which a trade is closed to limit the loss. For a long it sits below today's price. |
| Probability, P(up) | The model's estimate of the chance the price ends higher after a set number of days. |
| Calibration | Checking that when the model says 70%, it is right about 70% of the time. |
| Walk-forward test | Train on an earlier period, test on the next one, roll forward; never test on data the model learned from. |
| Out of sample (unseen data) | Data the model was not trained or tuned on. Only results here count. |
| Survivorship bias | Testing only on companies that still exist today, which makes past results look better than they were. |
| Look-ahead bias | Using information in a test that was not public yet on that date. |
| Rank percentile | Where a stock stands in a list from 0% (worst) to 100% (best). "Top 1%" = rank percentile 99% or more. |
| bps (basis points) | Hundredths of a percent. 10 bps = 0.10%. |
| ATR (average true range) | The typical daily price swing of a stock, used to set stops a sensible distance away. |
| Paper trading | Pretend trades recorded as if real, with no real money. |
| FinBERT | A language model trained on financial text that scores a headline as positive, negative or neutral. |
| Liquidity sweep | A quick push through an obvious price level that reverses at once; measured only by the local tick program. |
| Kelly fraction | A formula for bet size from the edge and the odds. The full Kelly bet is very risky, so only a small fraction is used. |
| Calibrated probability | A raw model score turned into "how often stocks with this score actually went up" in past unseen data. |
| Isotonic calibration | One way to calibrate: a step-shaped map from raw score to observed frequency. It produces only a few distinct values. |
| LightGBM | A machine-learning method that builds many small decision trees, each correcting the last. |
| AUC | How well a model ranks winners above losers: 0.5 = chance, 1.0 = perfect. 0.55 is a small edge. |
| Base rate | The share of cases that went up anyway. A useful model must beat this, not 50%. |
| Log-odds (logit) | Another scale for a probability: 50% = 0, higher is positive, lower negative. Adding to it pushes the probability up or down. |
| Feature (input) | One number the model looks at, for example the 1-month return. |
| Walk-forward with a purge gap | Testing each year with a model trained only on earlier years, leaving a gap so no answer leaks across. |
| HMM (hidden Markov model) | A model that guesses whether the market is in a calm or a turbulent state from recent moves. |
| Kill switch | An automatic stop that hides signals when live results break preset limits. |
| Point in time | Using only what was known on that date (for example the stocks that were liquid then, not today). |
| Rank-average / percentile rank | Ordering all stocks by a score and expressing each one's place from 0 (worst) to 1 (best). |
| Population stability index (PSI) | A score of how much a spread of values has shifted from a reference: under 0.1 stable, 0.1–0.25 moving, over 0.25 shifted. |
| Correlation | How closely two series move together, from −1 (opposite) through 0 (no link) to +1 (in step). |
| Breadth | The share of stocks doing something, for example the share above their 200-day average. |
| Net excess (vs the market) | A trade's return minus the average stock's return on the same days, after costs. |
| Event study | Looking at what happened around a list of dated events (Budgets, elections) to see if there is a pattern. |
| Drawdown | The fall from a high point of an account to its later low point. |
| Momentum | Stocks that rose most over the past year (skipping the last month) tend to keep doing better for a while. |
| Winners minus losers (WML) | A momentum portfolio that owns past winners and shorts past losers; long-only versions own just the winners. |
| Momentum crash | A sudden large loss for momentum, usually when a falling market rebounds sharply. |
| Quality factor | Favouring profitable, stable, low-debt companies. |
| Low-volatility anomaly | The finding in some markets that calmer stocks earn as much or more than jumpy ones. |
| PEAD (post-earnings-announcement drift) | Prices keep drifting in the direction of a results surprise for weeks after the announcement. |
| Statistical arbitrage / pairs trading | Trading the gap between two related stocks when it stretches, expecting it to close. |
| Abstract | The short summary the authors write at the top of a paper. |
| Sharpe ratio | Return per unit of risk (average return divided by how much it swings), per year. Above 1 is good for a stock strategy. |
| Deflated Sharpe ratio (DSR) | The chance a result is real after discounting for how many settings were tried; 0.95 is the usual bar. |
| Purged cross-validation with an embargo | Testing on one block of time with settings chosen on the others, leaving a gap around the test block so nothing leaks in. |
| Hold-out | A recent stretch of data kept untouched until the very end and used once. |
| CAGR | Compound annual growth rate: the steady yearly growth that gives the same end result. |
| Liquid fund | A low-risk debt mutual fund used to park cash; its return is modest and not guaranteed. |
| Position sizing | Choosing how much of the money to put into the strategy, to control how deep losses can go. |
