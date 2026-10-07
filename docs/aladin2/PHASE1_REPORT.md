# ALADIN 2.0, Phase 1: foundations (2026-10-07)

Branch `feature/aladin-learning`. Nothing pushed, nothing merged. No UI or model changes yet.

## Files
`scripts/aladin2/` : `costs.py`, `data_lake.py`, `backtest.py`, `synthetic.py`, `history_backfill.py`
`data/config/` : `aladin2.json` (every tunable, documented in `_doc`), `aladin2_sources.json` (source registry)
`tests/aladin2/` : `test_costs.py`, `test_backtest.py`, `test_leakage.py`, `test_synthetic.py`: **28 tests, all pass** (`python -m pytest tests/aladin2`)

## Cost model, worked trade (`python scripts/aladin2/costs.py`)
Long 500 x Rs 800, sold at Rs 830, cash delivery, liquidity decile 3 (slippage 6 bps a leg). Gross P&L Rs 15,000.

| | brokerage | STT | exchange | SEBI | GST | stamp | slippage | leg total |
|---|---|---|---|---|---|---|---|---|
| Buy, Rs 4,00,000 | 120.00 | 400.00 | 14.00 | 4.00 | 24.84 | 60.00 | 240.00 | **862.84** |
| Sell, Rs 4,15,000 | 124.50 | 415.00 | 14.53 | 4.15 | 25.77 | 0.00 | 249.00 | **832.95** |

Total cost Rs 1,695.79; net P&L Rs 13,304.21; 42.39 bps of the entry value. The test suite reproduces every line.

Round-trip cost, basis points, liquidity decile 0 / 5 / 9: delivery long 33.6 / 49.6 / 99.6; intraday 14.9 / 30.9 / 80.9; futures 9.2 / 25.2 / 75.2.
Rules built in: STT on both delivery legs but only the sell leg for intraday and futures; stamp duty on the buy leg only; GST on brokerage + exchange + SEBI only; **a cash-equity delivery short raises an error** (only intraday or futures shorts are costed).

**Please review these numbers.** Differences from the config in the brief (I added keys, I did not change yours): `sebi_bps` 0.1, `stamp_intraday_bps` 0.3, and a `futures` block (brokerage 1, STT on sell 2, exchange 0.183, stamp on buy 0.2 bps). Rates are the statutory ones as I know them for 2026; check them against a real contract note, because rates change and I cannot verify them from here. Brokerage 3 bps assumes a full-service-style fee; a discount broker charges less on delivery, which would lower the delivery figure.

## Backtest engine
Signal at close t, fill at open t+1 (tested: never at the signal day's close). Fixed, signal-flip and ATR-trailing exits; stop gaps fill at the open (worse than the stop). No fill on missing/zero-volume bars, one-price circuit-locked opens, or when the Rs 1 lakh reference order is above 5% of that day's traded value. One position at a time. Daily P&L compounds to the trade return (tested). Speed: features + a full backtest for 490 NIFTY 500 stocks takes 13 s.

## Point-in-time store and leakage tests
Causal features only (trailing windows). Publication lags are applied before joining: same-close sources 0 days, delivery/OI/FII-DII/FX/commodities/global indices 1 trading day, fundamentals the filing date or period end + 60 days. Tests: +50% shift of all prices after D leaves every feature up to D identical; permuting future returns leaves past features identical; truncating the data equals the full run; backtest trades decided up to D are identical when the future changes; lag rules on side series.

## Data-quality findings (new, from real data)
- The price history joined from `daily` + `archive` goes back to 1996 for many stocks (median 2,125 bars; 2,049 stocks have >= 750 bars; 1,304 have >= 2,500).
- **136 single-bar bad prints** in the 497 NIFTY 500 names (e.g. RELIANCE 2005-07-28, price 4x for one day). They are dropped (a missing day, no fill).
- **78 of 497 NIFTY 500 stocks have at least one persistent unadjusted jump** (117 events; mostly before 2010, plus real demergers such as ADANIENT 2015). None sits at the archive/daily seam. They are flagged, no new entry is allowed for 250 bars after one, and any trade holding across one is discarded (49 of 109,270 trades in a trial). I did not rescale old prices, so no number is invented.
- Prices are split-adjusted but **not dividend-adjusted**.

## History backfill (`history_backfill.py`, running in the background on this PC)
Macro done: India VIX (from 2008), USDINR, Brent, S&P 500, Nikkei (from 2000), US 10-year (FRED, your key works; the key is never printed or committed). NSE delivery % (from 2020-01-01) is downloading at about one file per 1.5 s (485 of about 1,700 so far); F&O open interest follows. Files go to the gitignored `data/terminal/aladin2/`; it resumes if interrupted. `--report` prints depth per source.

## Not done / differences from the brief
- `.env.example`, the startup source table and `check_aladin2.py` come in later phases.
- The F&O ban list (404), BSE (403) and historical index constituents are unavailable (see `aladin2_sources.json`).
- `data/config/aladin2.json` contains BUY/SELL wording in its `directional` dictionary. `scripts/check_banned.py` does not scan it yet; when the UI phase wires it in, the checker will exempt that one dictionary and keep scanning the rest, as decision 3 says.
- Product-state shares: Validated 0%, Provisional 0%, Learning 100%.

## GATE: what I need from you
1. Review the cost numbers above (rates, brokerage level, slippage by liquidity decile).
2. OK to continue to Phase 2 (strategy library, nested walk-forward evaluator, lifecycle, null and planted-edge tests)? The backfill finishes in the background meanwhile.
