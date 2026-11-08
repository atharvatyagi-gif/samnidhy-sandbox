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
