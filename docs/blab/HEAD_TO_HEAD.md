# Head-to-head: the self-evolving strategy desk against model E, on bias-free data

Written 2026-11-17, **before any result on this data existed**. Owner (2026-11-17): "I want this to be the main predictability
model highlight if it works, but for that I want you to backtest the entire thing, keeping in mind that there are no biases
in data. If it works, then you will need to replace the existing ALADIN model."

## 1. The data: every NSE equity that traded, 2008 to today

- Source: NSE's own daily files (bhavcopy), every trading day, every security that traded that day, including companies
  later delisted, merged away or suspended (scripts/bhav_history.py; data branch `bhav`, one file per day).
- **Survivorship:** gone. The tradable list on any day is built only from that day's and earlier files.
- **Splits and bonuses:** each day's return is close / (previous close x the split or bonus factor on its ex-date), from
  NSE's own corporate-actions record (scripts/corp_actions.py: split Rs 10 -> 2 = 0.2, bonus 1:1 = 0.5). Where a file's
  previous-close field already differs from the last close by more than 2% (NSE adjusted it), that field is used instead.
  **Changed 2026-11-17, before any result:** the first plan assumed NSE always adjusts the previous close; a check of the
  2008-2009 files showed it does not (ACE's 10 -> 2 split on 13 Mar 2008 appears as 344.25 -> 70.75), so the corporate
  actions record is used. A one-day fall beyond 45% with no recorded action is kept as a real loss (real collapses must
  stay in) and the number of such cases is reported. Rights issues and dividends are not adjusted (price returns).
  An adjusted price index is chained from those returns; opens are scaled by the same day's factor.
- **Renamed symbols:** when a symbol stops and a new symbol with the same ISIN starts on the next trading day, the two are
  joined (one company, one history).
- **Series:** EQ only (main board, rolling settlement). BE/BZ (trade-to-trade, suspended) and SME series are not tradable.
- **Dividends:** not included (price returns), the same as the NIFTY 50 price index used as the benchmark.

## 2. Trading realism

- Signals at the close, fills at the next session's open (unchanged, tested for no look-ahead).
- **No fill** when the stock does not trade that day, or is locked at its circuit (open = high = low = close).
- Tradable: close >= Rs 10, 260+ sessions of history, 20-session average traded value >= Rs 1 Cr, and no one-day move beyond
  45% in the last 20 sessions.
- Costs: model E's full Indian cost model (STT, exchange, SEBI, stamp, GST, DP charge, slippage by liquidity).
- **Delisted or suspended holdings** (no trade for 10 sessions in a row): two cases, both reported.
  - Base: sold at the last traded close.
  - Stress: worth nothing (a total loss), whatever the reason it stopped trading.

## 3. Equal risk control for both

Both run with model E's market risk control, unchanged: 70% of the money invested, 35% while the NIFTY 500 is below its
200-day average (from the bhav data's own NIFTY 500 history where available, otherwise NIFTY 50). The desk's money rule is
the one already fixed (selector if it beats the blend over the replay, otherwise the blend of all active strategies).

## 4. The four gates (the desk replaces model E as ALADIN only if it passes all four)

| Gate | Test |
|---|---|
| 1 Risk | worst fall from peak no deeper than **-25%** (the owner's limit from the audit), base case, whole period |
| 2 Quality | higher return per unit of risk (Sharpe of daily returns) than model E, 2010 to the hold-out start |
| 3 Hold-out | over the last 2 years (never used for any design), yearly return no more than 2 points below model E's |
| 4 Stress | in the stress case (vanished holdings worth nothing), Sharpe still above model E's stress case |

If any gate fails, model E stays as the public ALADIN, the desk stays a research page, and the report names the failed gate.
No gate is changed after a result is seen. Any fix to the code after a result (a bug, not a preference) is recorded here with
the result before and after.

## 5. What is reported either way

Both models' whole-period, design-years and hold-out results (yearly return, worst fall, Sharpe, trades, costs paid), the
base and stress cases, and how much the survivorship-free data changed each model against the old cache (the size of the
bias that was removed).
