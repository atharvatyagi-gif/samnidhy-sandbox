# INVENTORY: everything in the terminal the Black Box knows about

Generated from `blackbox/inventory.py` (`python -m blackbox.inventory`). Paths are relative to the repository root.

The terminal is vanilla JavaScript + Python scripts (not React/shadcn/Recharts); all trading, scoring and risk logic is in Python.

## 1. Strategies, signals, indicators, screeners, scores, predictions

- **ALADIN paper bot v3 (live)** - `scripts/aladin2/paper.py (BOT line 48, simulate line 110, run_bot line 95, books_from_scores)` - STAND-IN; blackbox: strategies/aladin_weekly.py v3; notes: Weekly: best 1% by ALADIN 1's 5-day score, entry next open, exit 5 days later, 2% risk sizing, 20% a stock, 10 open, sector 30%, idle cash in a liquid fund.
- **ALADIN v4 shadow (F&O shorts + 3 ATR protective stop)** - `scripts/aladin2/paper.py SHADOW line 437; scripts/aladin2/trader.py` - STAND-IN; blackbox: strategies/aladin_weekly.py v4_shadow
- **ALADIN Rs 10,000 account** - `scripts/aladin2/paper.py SMALL line 47` - STAND-IN; blackbox: strategies/aladin_weekly.py small_10k
- **ALADIN swing rules round 1 (failed gate, kept as record)** - `scripts/aladin2/swing.py` - STAND-IN; blackbox: strategies/swing_r1.py
- **ALADIN movers forward-test portfolio (top tenth)** - `scripts/aladin_movers.py make_book/realised/evaluate_forward` - STAND-IN; blackbox: strategies/movers_top_tenth.py
- **ALADIN paper trader v1 (P(up) > 0.60, 10 days)** - `scripts/paper_trader.py` - STAND-IN; blackbox: strategies/paper_trader_v1.py; ambiguity: Requires confidence High and 3/3 front agreement; the fronts do not exist on synthetic data, so only the probability test is applied.
- **Bitcoin TREND (all-weather quant, round 2 daily)** - `scripts/crypto_quant.py rule_score/positions/ROUNDS[2]` - SIMULATED; blackbox: strategies/crypto_trend.py; notes: 4-hour bars in the terminal, daily here (same horizons in days). Funding not modelled.
- **Bitcoin Heikin-Ashi trend** - `scripts/crypto_flow.py signals() ha_trend` - SIMULATED; blackbox: strategies/crypto_ha_trend.py; notes: 1h/4h in the terminal, daily here.
- **Bitcoin order-flow strategies (ha_flow, flow_momentum, flow_absorb, flow_breakout)** - `scripts/crypto_flow.py` - NOT SIMULATED; why: need taker-buy volume (order flow), which the synthetic market does not generate
- **Bitcoin ML / ML+TREND / CARRY candidates and the crypto shadow** - `scripts/crypto_quant.py, scripts/crypto_shadow.py` - NOT SIMULATED; why: LightGBM/ridge refits and funding rates; only the TREND component is price-only
- **Bitcoin regime + champion/challenger (crypto_adapt)** - `scripts/crypto_adapt.py` - NOT SIMULATED; why: failed its walk-forward test and is not traded; needs the same order-flow inputs
- **ALADIN 1 technical model (LightGBM P(up) 5/10/20 days) + combiner** - `scripts/aladin_model.py; desk-aladin.js combine() lines 24-32` - STAND-IN; notes: Replaced by panel.score(h, ic): calibrated ic 0.04 (best-1% excess of the real bot); AUC-implied 0.14 in the sweeps.
- **ALADIN fundamental front (Value / Quality / F-score, distress)** - `scripts/aladin_fund.py` - NOT SIMULATED; why: needs company fundamentals; the synthetic market has prices only
- **ALADIN sentiment front (FinBERT news, Reddit, FII/DII flow)** - `scripts/aladin_sentiment_engine.py` - WIRED (flow_score only); why: headline text scoring needs real text; the flow score is a pure function and is run as is
- **ALADIN 2.0 rule discovery, pooled trend rules, lifecycle/kill switches** - `scripts/aladin2/discover.py, pooled.py, lifecycle.py, kill.py` - NOT SIMULATED; why: a research pipeline over 15,594 tested rules (all retired today), not a traded strategy
- **B-LAB outlook (LightGBM: beats NIFTY 50 over 20 days)** - `scripts/predict_model.py` - NOT SIMULATED; why: a displayed probability with no trading rule attached
- **Stock screener (Magic Formula + Piotroski F-score) and live re-rank** - `scripts/screener.py, scripts/screener_live.py` - NOT SIMULATED; why: fundamentals-driven
- **Advanced-page price signals (200-day trend, 50/200 cross, 12-1 momentum, 52-week high, low volatility)** - `scripts/live_technicals.py analyse() lines 81-145` - SIMULATED (module check); blackbox: engine/modules.py price_signals
- **Liquidity-sweep detector** - `scripts/aladin_sweep_eval.py, desk-ticks.js` - NOT SIMULATED; why: needs tick-by-tick data
- **NEXUS impact score and predicted links** - `scripts/graph_impact.py, scripts/nexus_predict.py` - NOT SIMULATED; why: needs a supply-chain graph; the synthetic market has sectors only
- **Chart indicators (SMA, EMA, RSI, MACD, stochastic, Bollinger, VWAP)** - `chart-indicators.js (smaA line 7, emaA 18, rsiA 59, macdA 64, stochA 68, vwapA 120)` - NOT SIMULATED; why: chart tools with no trading rule; RSI/SMA logic is exercised inside swing_r1
- **Daily top gainers/losers picker** - `scripts/pick_movers.py` - NOT SIMULATED; why: content selection for the lessons page, not a strategy

## 2. Geopolitical, macro, news and event modules

- **Geopolitical news-attention index (Globe layer)** - `scripts/geo_tension.py score_region() line 139` - WIRED; blackbox: engine/modules.py geo_lead_lag
- **FII/DII institutional flow** - `scripts/institutional.py -> aladin_sentiment_engine.flow_score() line 315` - WIRED; blackbox: engine/modules.py flow_lead_lag
- **Globe: flights, vessels, hazards, news pins, lanes, cables, power plants** - `scripts/globe_data.py, globe_layers.py, aladin_telemetry.py; desk-globe*.js` - NOT SIMULATED; why: informational map layers with no score that feeds a decision
- **Supply-chain shock ranking (NEXUS shocks)** - `data/aladin/shocks.json; desk-deps.js rankShocks` - NOT SIMULATED; why: needs the supply-chain graph
- **Board-meeting calendar (results days)** - `scripts/events_calendar.py` - NOT SIMULATED; why: an input of the movers model (inside the stand-in)
- **News wire** - `scripts/news_wire.py, terminal.js renderNews` - NOT SIMULATED; why: display only

## 3. Portfolio, sizing, risk, P&L, trade logs, backtests

- **Position sizing (risk %, max position %, volume cap, fractional Kelly)** - `scripts/aladin2/signals.py position_size() line 122` - SIMULATED
- **Portfolio layer (max open, sector cap, correlation cut, DRAWDOWN BRAKE)** - `scripts/aladin2/signals.py portfolio_apply() line 139` - NOT USED BY THE PAPER BOT; why: the paper bot's simulate() applies max open and the sector cap itself; the drawdown brake and correlation cut are never applied
- **Cost model (statutory fees, slippage by liquidity decile)** - `scripts/aladin2/costs.py leg_cost() line 44; data/config/aladin2.json costs` - SIMULATED; blackbox: engine/costs.py (plus scenario widening and partial fills)
- **Paper account statistics, timeline, trade book, blotter** - `scripts/aladin2/paper.py stats()/timeline(); desk-signals.js tradeBookHtml/blotterHtml` - SIMULATED (metrics); blackbox: engine/metrics.py
- **Crypto live account (hard budget, stops, sleeves)** - `scripts/crypto_live.py live_step()` - NOT SIMULATED; why: the live engine of the order-flow strategies

## 4. Data sources

- **NSE end-of-day bhavcopies** - `scripts/nse_eod.py`; returns: daily OHLCV, delivery % for every NSE stock
- **NSE public site API (live numbers, board meetings, BRSR, annual reports, F&O)** - `scripts/nse_live_poll.py, events_calendar.py, brsr_profile.py, revenue_graph_builder.py`; returns: live quotes, corporate filings, XBRL
- **Yahoo Finance (yfinance)** - `scripts/terminal_live.py, fetch_data.py, terminal_fund.py, live_technicals.py`; returns: delayed prices, history, fundamentals, world markets
- **FRED (India call-money rate)** - `scripts/aladin2/paper.py india_rate()`; returns: monthly rate for idle cash
- **Binance (BTCUSDT candles, taker volume, funding)** - `scripts/crypto_data.py, crypto_funding.py, crypto_live.py`; returns: 1-minute bars, funding every 8 hours, order book
- **Google News RSS, Mint RSS, ET/BS RSS, Reddit** - `scripts/geo_tension.py, aladin_sentiment_engine.py, news_wire.py`; returns: headlines
- **Groq / Gemini / GitHub Models (free tiers)** - `scripts/revenue_graph_builder.py LLM`; returns: filing extraction (NEXUS)
- **OpenSky, AISstream, Nominatim** - `scripts/aladin_telemetry.py, geocode_facilities.py`; returns: flight/vessel positions, coordinates

## 5. GAPS: undefined or hard-coded parameters

- **risk_pct** - `scripts/aladin2/paper.py BOT line 48 (2.0) vs data/config/aladin2.json risk.risk_per_trade_pct (1.0)`; why: Two different numbers for the same rule: the page's documentation and the bot can disagree.; default: `2.0`; test range: `[0.5, 3.0]`; proposed: see GAPS tab (robust value); **terminal change:** Make the paper bot's risk per trade and max position read the config (2% and 20% in code vs 1% and 10% in data/config/aladin2.json)
- **max_pos_pct** - `paper.py BOT (20) vs config risk.max_position_pct (10)`; default: `20`; test range: `[5, 30]`
- **hold_days** - `paper.py simulate(hold=5)`; why: fixed from the weekly study; default: `5`; test range: `[2, 10]`
- **max_open** - `paper.py simulate(max_open=10) vs config risk.max_open_signals (20)`; default: `10`; test range: `[3, 15]`
- **kelly_mu / kelly_sd** - `paper.py simulate(mu=0.0027, sd=0.06) hard-coded`; why: An unjustified constant sizes every trade.; default: `[0.0027, 0.06]`; test range: `[0.0015, 0.005]`; **terminal change:** Derive the Kelly edge (mu=0.0027, sd=0.06, hard-coded in scripts/aladin2/paper.py simulate) from the live record once it has 100 closed trades
- **drawdown_brake_pct** - `data/config/aladin2.json risk.drawdown_brake_pct = 10, used only by signals.portfolio_apply`; why: The config promises a brake the bot does not have.; default: `"not applied"`; **terminal change:** Apply the configured drawdown brake (halve new sizes 10% below the peak) in the paper bot: scripts/aladin2/paper.py simulate() never calls portfolio_apply()
- **account_max_loss** - `none (no account-level stop anywhere in scripts/aladin2/paper.py or crypto_live.py)`; why: No safeguard exists.; default: `"none"`; **terminal change:** Add an account-level loss limit (e.g. stop new entries 25% below the peak until a review) to the paper bots
- **slippage in stress** - `data/config/aladin2.json slippage_bps_by_adv_decile (fixed)`; why: Fixed slippage understates costs in crashes (the blackbox widens it).; default: `"fixed table"`; **terminal change:** Scale the slippage table with volatility (e.g. x today's India VIX / its 1-year median) in scripts/aladin2/costs.py
- **futures lot sizes** - `scripts/aladin2/paper.py shorts (v4 shadow) - stated limitation`; why: Unmodelled lots overstate how finely shorts can be sized.; default: `"not modelled"`; **terminal change:** Model stock-futures lot sizes and basis for the v4 shadow's shorts (scripts/aladin2/paper.py); a Rs 10 lakh account cannot hold a fraction of a lot
- **movers round-trip cost** - `scripts/aladin_movers.py COST_RT = 0.30% flat`; default: `0.003`; test range: `[0.0015, 0.006]`
- **paper trader cost / notional** - `scripts/paper_trader.py DEFAULT line 34 (0.5% round trip, Rs 1,00,000)`; default: `[0.005, 100000]`
- **crypto vol target / band / smoothing** - `scripts/crypto_quant.py TV=0.40, ROUNDS[2] band 0.25, smooth 3`; default: `[0.4, 0.25, 3]`; test range: `[[0.2, 0.8], [0.0, 0.5], [1, 7]]`
- **crypto cost per fill** - `scripts/crypto_flow.py COST = 0.0012`; default: `0.0012`
- **geo index thresholds** - `scripts/geo_tension.py LEVELS (High >= 65), MIN_SAMPLES 48, KEEP_DAYS 30`; default: `"65 / 48 / 30"`
- **stand-in skill (ic) and probability scale** - `blackbox/config.yaml oracle; blackbox/strategies/paper_trader_v1.py PROB_SCALE`; why: Assumptions of the blackbox, not terminal settings: the model-driven results depend on them.; default: `[0.04, 0.035]`; test range: `[0.0, 0.14]`

## 6. Placeholders (NOT IMPLEMENTED)

- **Order-book models, RL execution, Heston calibration** - `scripts/aladin_model.py docstring 'Not done'` - NOT IMPLEMENTED (shown as 'not measured' in the terminal)
- **Real-time tick feed for the public site** - `scripts/aladin_ticker_daemon.py (local PC only)` - NOT IMPLEMENTED on the public site
