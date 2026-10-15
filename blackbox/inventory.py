"""Discovery: everything in the terminal that trades, scores, warns, sizes, costs or fetches, with file paths, and every GAP.
One source of truth: `python -m blackbox.inventory` writes blackbox/inventory.json and blackbox/INVENTORY.md from the dict below.
Status: SIMULATED (re-implemented in blackbox/strategies or run as is), STAND-IN (rules simulated, the model replaced by a score of measured skill),
WIRED (the terminal's own Python function is called with synthetic inputs), NOT SIMULATED (with the reason), NOT IMPLEMENTED (placeholder in the UI).
Note: the terminal is vanilla JavaScript + Python scripts (not React/shadcn/Recharts as the brief assumed); all trading logic lives in Python.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

INVENTORY = {
    "strategies_signals_scores": [
        {"name": "ALADIN paper bot v3 (live)", "path": "scripts/aladin2/paper.py (BOT line 48, simulate line 110, run_bot line 95, books_from_scores)", "status": "STAND-IN",
         "blackbox": "strategies/aladin_weekly.py v3", "notes": "Weekly: best 1% by ALADIN 1's 5-day score, entry next open, exit 5 days later, 2% risk sizing, 20% a stock, 10 open, sector 30%, idle cash in a liquid fund."},
        {"name": "ALADIN v4 shadow (F&O shorts + 3 ATR protective stop)", "path": "scripts/aladin2/paper.py SHADOW line 437; scripts/aladin2/trader.py", "status": "STAND-IN", "blackbox": "strategies/aladin_weekly.py v4_shadow"},
        {"name": "ALADIN Rs 10,000 account", "path": "scripts/aladin2/paper.py SMALL line 47", "status": "STAND-IN", "blackbox": "strategies/aladin_weekly.py small_10k"},
        {"name": "ALADIN swing rules round 1 (failed gate, kept as record)", "path": "scripts/aladin2/swing.py", "status": "STAND-IN", "blackbox": "strategies/swing_r1.py"},
        {"name": "ALADIN movers forward-test portfolio (top tenth)", "path": "scripts/aladin_movers.py make_book/realised/evaluate_forward", "status": "STAND-IN", "blackbox": "strategies/movers_top_tenth.py"},
        {"name": "ALADIN paper trader v1 (P(up) > 0.60, 10 days)", "path": "scripts/paper_trader.py", "status": "STAND-IN", "blackbox": "strategies/paper_trader_v1.py",
         "ambiguity": "Requires confidence High and 3/3 front agreement; the fronts do not exist on synthetic data, so only the probability test is applied."},
        {"name": "Bitcoin TREND (all-weather quant, round 2 daily)", "path": "scripts/crypto_quant.py rule_score/positions/ROUNDS[2]", "status": "SIMULATED", "blackbox": "strategies/crypto_trend.py",
         "notes": "4-hour bars in the terminal, daily here (same horizons in days). Funding not modelled."},
        {"name": "Bitcoin Heikin-Ashi trend", "path": "scripts/crypto_flow.py signals() ha_trend", "status": "SIMULATED", "blackbox": "strategies/crypto_ha_trend.py", "notes": "1h/4h in the terminal, daily here."},
        {"name": "Bitcoin order-flow strategies (ha_flow, flow_momentum, flow_absorb, flow_breakout)", "path": "scripts/crypto_flow.py", "status": "NOT SIMULATED", "why": "need taker-buy volume (order flow), which the synthetic market does not generate"},
        {"name": "Bitcoin ML / ML+TREND / CARRY candidates and the crypto shadow", "path": "scripts/crypto_quant.py, scripts/crypto_shadow.py", "status": "NOT SIMULATED", "why": "LightGBM/ridge refits and funding rates; only the TREND component is price-only"},
        {"name": "Bitcoin regime + champion/challenger (crypto_adapt)", "path": "scripts/crypto_adapt.py", "status": "NOT SIMULATED", "why": "failed its walk-forward test and is not traded; needs the same order-flow inputs"},
        {"name": "ALADIN 1 technical model (LightGBM P(up) 5/10/20 days) + combiner", "path": "scripts/aladin_model.py; desk-aladin.js combine() lines 24-32", "status": "STAND-IN",
         "notes": "Replaced by panel.score(h, ic): calibrated ic 0.04 (best-1% excess of the real bot); AUC-implied 0.14 in the sweeps."},
        {"name": "ALADIN fundamental front (Value / Quality / F-score, distress)", "path": "scripts/aladin_fund.py", "status": "NOT SIMULATED", "why": "needs company fundamentals; the synthetic market has prices only"},
        {"name": "ALADIN sentiment front (FinBERT news, Reddit, FII/DII flow)", "path": "scripts/aladin_sentiment_engine.py", "status": "WIRED (flow_score only)", "why": "headline text scoring needs real text; the flow score is a pure function and is run as is"},
        {"name": "ALADIN 2.0 rule discovery, pooled trend rules, lifecycle/kill switches", "path": "scripts/aladin2/discover.py, pooled.py, lifecycle.py, kill.py", "status": "NOT SIMULATED", "why": "a research pipeline over 15,594 tested rules (all retired today), not a traded strategy"},
        {"name": "B-LAB outlook (LightGBM: beats NIFTY 50 over 20 days)", "path": "scripts/predict_model.py", "status": "NOT SIMULATED", "why": "a displayed probability with no trading rule attached"},
        {"name": "Stock screener (Magic Formula + Piotroski F-score) and live re-rank", "path": "scripts/screener.py, scripts/screener_live.py", "status": "NOT SIMULATED", "why": "fundamentals-driven"},
        {"name": "Advanced-page price signals (200-day trend, 50/200 cross, 12-1 momentum, 52-week high, low volatility)", "path": "scripts/live_technicals.py analyse() lines 81-145", "status": "SIMULATED (module check)", "blackbox": "engine/modules.py price_signals"},
        {"name": "Liquidity-sweep detector", "path": "scripts/aladin_sweep_eval.py, desk-ticks.js", "status": "NOT SIMULATED", "why": "needs tick-by-tick data"},
        {"name": "NEXUS impact score and predicted links", "path": "scripts/graph_impact.py, scripts/nexus_predict.py", "status": "NOT SIMULATED", "why": "needs a supply-chain graph; the synthetic market has sectors only"},
        {"name": "Chart indicators (SMA, EMA, RSI, MACD, stochastic, Bollinger, VWAP)", "path": "chart-indicators.js (smaA line 7, emaA 18, rsiA 59, macdA 64, stochA 68, vwapA 120)", "status": "NOT SIMULATED", "why": "chart tools with no trading rule; RSI/SMA logic is exercised inside swing_r1"},
        {"name": "Daily top gainers/losers picker", "path": "scripts/pick_movers.py", "status": "NOT SIMULATED", "why": "content selection for the lessons page, not a strategy"},
    ],
    "geopolitical_macro_event": [
        {"name": "Geopolitical news-attention index (Globe layer)", "path": "scripts/geo_tension.py score_region() line 139", "status": "WIRED", "blackbox": "engine/modules.py geo_lead_lag"},
        {"name": "FII/DII institutional flow", "path": "scripts/institutional.py -> aladin_sentiment_engine.flow_score() line 315", "status": "WIRED", "blackbox": "engine/modules.py flow_lead_lag"},
        {"name": "Globe: flights, vessels, hazards, news pins, lanes, cables, power plants", "path": "scripts/globe_data.py, globe_layers.py, aladin_telemetry.py; desk-globe*.js", "status": "NOT SIMULATED", "why": "informational map layers with no score that feeds a decision"},
        {"name": "Supply-chain shock ranking (NEXUS shocks)", "path": "data/aladin/shocks.json; desk-deps.js rankShocks", "status": "NOT SIMULATED", "why": "needs the supply-chain graph"},
        {"name": "Board-meeting calendar (results days)", "path": "scripts/events_calendar.py", "status": "NOT SIMULATED", "why": "an input of the movers model (inside the stand-in)"},
        {"name": "News wire", "path": "scripts/news_wire.py, terminal.js renderNews", "status": "NOT SIMULATED", "why": "display only"},
    ],
    "portfolio_risk_pnl": [
        {"name": "Position sizing (risk %, max position %, volume cap, fractional Kelly)", "path": "scripts/aladin2/signals.py position_size() line 122", "status": "SIMULATED"},
        {"name": "Portfolio layer (max open, sector cap, correlation cut, DRAWDOWN BRAKE)", "path": "scripts/aladin2/signals.py portfolio_apply() line 139", "status": "NOT USED BY THE PAPER BOT", "why": "the paper bot's simulate() applies max open and the sector cap itself; the drawdown brake and correlation cut are never applied"},
        {"name": "Cost model (statutory fees, slippage by liquidity decile)", "path": "scripts/aladin2/costs.py leg_cost() line 44; data/config/aladin2.json costs", "status": "SIMULATED", "blackbox": "engine/costs.py (plus scenario widening and partial fills)"},
        {"name": "Paper account statistics, timeline, trade book, blotter", "path": "scripts/aladin2/paper.py stats()/timeline(); desk-signals.js tradeBookHtml/blotterHtml", "status": "SIMULATED (metrics)", "blackbox": "engine/metrics.py"},
        {"name": "Crypto live account (hard budget, stops, sleeves)", "path": "scripts/crypto_live.py live_step()", "status": "NOT SIMULATED", "why": "the live engine of the order-flow strategies"},
    ],
    "data_sources": [
        {"name": "NSE end-of-day bhavcopies", "path": "scripts/nse_eod.py", "returns": "daily OHLCV, delivery % for every NSE stock"},
        {"name": "NSE public site API (live numbers, board meetings, BRSR, annual reports, F&O)", "path": "scripts/nse_live_poll.py, events_calendar.py, brsr_profile.py, revenue_graph_builder.py", "returns": "live quotes, corporate filings, XBRL"},
        {"name": "Yahoo Finance (yfinance)", "path": "scripts/terminal_live.py, fetch_data.py, terminal_fund.py, live_technicals.py", "returns": "delayed prices, history, fundamentals, world markets"},
        {"name": "FRED (India call-money rate)", "path": "scripts/aladin2/paper.py india_rate()", "returns": "monthly rate for idle cash"},
        {"name": "Binance (BTCUSDT candles, taker volume, funding)", "path": "scripts/crypto_data.py, crypto_funding.py, crypto_live.py", "returns": "1-minute bars, funding every 8 hours, order book"},
        {"name": "Google News RSS, Mint RSS, ET/BS RSS, Reddit", "path": "scripts/geo_tension.py, aladin_sentiment_engine.py, news_wire.py", "returns": "headlines"},
        {"name": "Groq / Gemini / GitHub Models (free tiers)", "path": "scripts/revenue_graph_builder.py LLM", "returns": "filing extraction (NEXUS)"},
        {"name": "OpenSky, AISstream, Nominatim", "path": "scripts/aladin_telemetry.py, geocode_facilities.py", "returns": "flight/vessel positions, coordinates"},
    ],
    "gaps": [
        {"name": "risk_pct", "where": "scripts/aladin2/paper.py BOT line 48 (2.0) vs data/config/aladin2.json risk.risk_per_trade_pct (1.0)", "default": 2.0, "proposed": "see GAPS tab (robust value)", "range": [0.5, 3.0],
         "terminal_change": "Make the paper bot's risk per trade and max position read the config (2% and 20% in code vs 1% and 10% in data/config/aladin2.json)", "priority": "Medium",
         "why": "Two different numbers for the same rule: the page's documentation and the bot can disagree.", "effect": "One source of truth."},
        {"name": "max_pos_pct", "where": "paper.py BOT (20) vs config risk.max_position_pct (10)", "default": 20, "range": [5, 30]},
        {"name": "hold_days", "where": "paper.py simulate(hold=5)", "default": 5, "range": [2, 10], "why": "fixed from the weekly study"},
        {"name": "max_open", "where": "paper.py simulate(max_open=10) vs config risk.max_open_signals (20)", "default": 10, "range": [3, 15]},
        {"name": "kelly_mu / kelly_sd", "where": "paper.py simulate(mu=0.0027, sd=0.06) hard-coded", "default": [0.0027, 0.06], "range": [0.0015, 0.005],
         "terminal_change": "Derive the Kelly edge (mu=0.0027, sd=0.06, hard-coded in scripts/aladin2/paper.py simulate) from the live record once it has 100 closed trades", "priority": "Low",
         "why": "An unjustified constant sizes every trade.", "effect": "Sizing follows the measured edge."},
        {"name": "drawdown_brake_pct", "where": "data/config/aladin2.json risk.drawdown_brake_pct = 10, used only by signals.portfolio_apply", "default": "not applied",
         "terminal_change": "Apply the configured drawdown brake (halve new sizes 10% below the peak) in the paper bot: scripts/aladin2/paper.py simulate() never calls portfolio_apply()", "priority": "High",
         "why": "The config promises a brake the bot does not have.", "effect": "Smaller losses in crashes."},
        {"name": "account_max_loss", "where": "none (no account-level stop anywhere in scripts/aladin2/paper.py or crypto_live.py)", "default": "none",
         "terminal_change": "Add an account-level loss limit (e.g. stop new entries 25% below the peak until a review) to the paper bots", "priority": "Medium", "why": "No safeguard exists.", "effect": "Caps the worst case."},
        {"name": "slippage in stress", "where": "data/config/aladin2.json slippage_bps_by_adv_decile (fixed)", "default": "fixed table",
         "terminal_change": "Scale the slippage table with volatility (e.g. x today's India VIX / its 1-year median) in scripts/aladin2/costs.py", "priority": "Low",
         "why": "Fixed slippage understates costs in crashes (the blackbox widens it).", "effect": "More honest stress results."},
        {"name": "futures lot sizes", "where": "scripts/aladin2/paper.py shorts (v4 shadow) - stated limitation", "default": "not modelled",
         "terminal_change": "Model stock-futures lot sizes and basis for the v4 shadow's shorts (scripts/aladin2/paper.py); a Rs 10 lakh account cannot hold a fraction of a lot", "priority": "Medium",
         "why": "Unmodelled lots overstate how finely shorts can be sized.", "effect": "Realistic short sizes."},
        {"name": "movers round-trip cost", "where": "scripts/aladin_movers.py COST_RT = 0.30% flat", "default": 0.003, "range": [0.0015, 0.006]},
        {"name": "paper trader cost / notional", "where": "scripts/paper_trader.py DEFAULT line 34 (0.5% round trip, Rs 1,00,000)", "default": [0.005, 100000]},
        {"name": "crypto vol target / band / smoothing", "where": "scripts/crypto_quant.py TV=0.40, ROUNDS[2] band 0.25, smooth 3", "default": [0.40, 0.25, 3], "range": [[0.2, 0.8], [0.0, 0.5], [1, 7]]},
        {"name": "crypto cost per fill", "where": "scripts/crypto_flow.py COST = 0.0012", "default": 0.0012},
        {"name": "geo index thresholds", "where": "scripts/geo_tension.py LEVELS (High >= 65), MIN_SAMPLES 48, KEEP_DAYS 30", "default": "65 / 48 / 30"},
        {"name": "stand-in skill (ic) and probability scale", "where": "blackbox/config.yaml oracle; blackbox/strategies/paper_trader_v1.py PROB_SCALE", "default": [0.04, 0.035], "range": [0.0, 0.14],
         "why": "Assumptions of the blackbox, not terminal settings: the model-driven results depend on them."},
    ],
    "not_implemented_placeholders": [
        {"name": "Order-book models, RL execution, Heston calibration", "path": "scripts/aladin_model.py docstring 'Not done'", "status": "NOT IMPLEMENTED (shown as 'not measured' in the terminal)"},
        {"name": "Real-time tick feed for the public site", "path": "scripts/aladin_ticker_daemon.py (local PC only)", "status": "NOT IMPLEMENTED on the public site"},
    ],
}


def write() -> None:
    (HERE / "inventory.json").write_text(json.dumps(INVENTORY, indent=1), encoding="utf-8")
    md = ["# INVENTORY: everything in the terminal the Black Box knows about", "", "Generated from `blackbox/inventory.py` (`python -m blackbox.inventory`). Paths are relative to the repository root.", "",
          "The terminal is vanilla JavaScript + Python scripts (not React/shadcn/Recharts); all trading, scoring and risk logic is in Python.", ""]
    titles = {"strategies_signals_scores": "1. Strategies, signals, indicators, screeners, scores, predictions", "geopolitical_macro_event": "2. Geopolitical, macro, news and event modules",
              "portfolio_risk_pnl": "3. Portfolio, sizing, risk, P&L, trade logs, backtests", "data_sources": "4. Data sources", "gaps": "5. GAPS: undefined or hard-coded parameters",
              "not_implemented_placeholders": "6. Placeholders (NOT IMPLEMENTED)"}
    for key, title in titles.items():
        md += [f"## {title}", ""]
        for it in INVENTORY[key]:
            line = f"- **{it['name']}** - `{it.get('path', it.get('where', ''))}`"
            if it.get("status"):
                line += f" - {it['status']}"
            for k in ("blackbox", "notes", "why", "ambiguity", "returns"):
                if it.get(k):
                    line += f"; {k}: {it[k]}"
            if key == "gaps":
                line += f"; default: `{json.dumps(it.get('default'))}`" + (f"; test range: `{json.dumps(it['range'])}`" if it.get("range") else "") + (f"; proposed: {it['proposed']}" if it.get("proposed") else "")
                if it.get("terminal_change"):
                    line += f"; **terminal change:** {it['terminal_change']}"
            md.append(line)
        md.append("")
    (HERE / "INVENTORY.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    write()
