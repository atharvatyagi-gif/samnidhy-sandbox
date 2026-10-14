"""
ALADIN paper-trading bot: a VIRTUAL, long-only account with a small fixed budget that trades the weekly signal book by fixed, written rules. Nothing here touches a broker or real money.

  python -m scripts.aladin2.paper --backtest [--workers 12]     replay 2013-2026 with the walk-forward scores (HISTORICAL SIMULATION)   -> data/aladin2/paper/backtest.json
  python -m scripts.aladin2.paper --live                         replay the live ledger books from the forward clock (FRONT TEST)       -> data/aladin2/paper/live.json
                                                                 and the small account (Rs 10,000, same rules, same lists)             -> data/aladin2/paper/live_small.json

ONE simulator (`simulate`) serves both, so the history and the live test cannot drift apart. The rules are declared before any result is looked at (RULES below, also written into the output):
  * Which books: the Friday book only (the weekly study was measured on Friday-close signals). BUY names only: cash shares cannot be shorted, a SELL name is simply never bought.
  * Entry: the OPEN of the next trading day, at the open price (no peeking at the day's range). Skipped if the stock is suspended, opens at or below its stop, or there is no cash or room.
  * Size: signals.position_size() on the account's current equity: risk 1% of equity to the stop, at most 10% of equity in one stock, at most 5% of its average daily volume, fractional Kelly of the measured edge.
  * Exits, first one that happens: the stop (a stop order: fills at the stop, or at the open if the stock gaps through it) or the OPEN of the 5th trading day after entry.
    The target price is shown to the visitor but is NOT an order: see RULE HISTORY below.
  * Costs: every leg is charged the full Indian delivery cost model (costs.py) at the stock's liquidity decile, in rupees, from the cash.
  * At most max_open positions, at most 30% of equity in one sector. Positions are valued at the close.
RULE HISTORY (kept in the output): v1, declared 2026-10-09 before any result was seen: stop + target + time. The first full backtest of v1 LOST money (-6.9% over 13 years: 62% of trades hit the target, but the average win was +2.3% and the
average loss -3.8%, so a take-profit at the 50% range edge cuts the winners and leaves the losers). v2, the same day, before any live trade existed: stop + time, the target stays information. All three variants stay in the output (ablation).
HISTORICAL caveats are written into the output: the scores are ALADIN 1's walk-forward (out-of-sample) probabilities, the universe is stocks listed today (flatters BUY), and the target in the history is a
PROXY from past volatility (the live target is the forecast range edge; no such forecast exists for 2013-2025). The live part is the only result that counts as evidence.
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import ledger as LG
from . import signals as SG
from . import weekly as W

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "aladin2"
OUT = DATA / "paper"
START_CASH = 1_000_000
RULE_HISTORY = [{"v": 1, "declared": "2026-10-09", "exits": "stop + goal + time", "backtest_return_pct": -6.87, "why_dropped": "a take-profit at the 50% range edge cut the winners (average win +2.3%) and left the losers (average loss -3.8%)"},
                {"v": 2, "declared": "2026-10-09", "exits": "stop + time (the price goal is information only)", "backtest_return_pct": 224.3, "why_dropped": "replaced by v3 the same day, before any live trade (the first live entry is 2026-10-12)"},
                {"v": 3, "declared": "2026-10-09", "exits": "time only (5th trading day); 2% risk, at most 20% a stock; idle cash in a liquid fund", "why": "the owner's choice (option O7) from paper_options.py, before any live trade. O7 was added AFTER the first option results were seen, so its history is the weaker claim; the live record decides"}]
# The small account (owner, 2026-10-13: "apart from the 10L budget, also a 10k budget"). Declared before its first list: the same rules on the same Friday lists, with
# Rs 10,000, starting with the list of Friday 2026-10-16 (the lists before it had already been traded when it was declared). Whole shares only, so a stock whose one share
# is more than the per-stock cap cannot be held. It also pays the depository (DP) charge on every stock sold, Rs 15.93 incl. GST (a typical discount broker's CDSL charge):
# negligible on a Rs 10 lakh account, but a real cost on Rs 2,000 positions. The Rs 10 lakh account's cost model is unchanged mid-test.
SMALL = {"budget_inr": 10_000, "from_book": "2026-10-16", "dp_charge_per_sale_inr": 15.93, "declared": "2026-10-13"}
BOT = {"exits": ("time",), "risk_pct": 2.0, "max_pos_pct": 20.0}             # v3 (option O7); the stop level is still computed: it sizes the trade and is shown, but it is not an order
RULES = {"budget_inr": START_CASH, "books": "Friday book, positive-signal names only (long-only cash equity)", "entry": "open of the next trading day", "hold_trading_days": 5, "exit_order": "the open of the 5th trading day after entry (the stop level sizes the trade and is shown, but is not an order; the price goal is information)", "risk_per_trade_pct": 2.0, "max_position_pct": 20, "adv_participation_max": 0.05, "max_open": 10, "max_sector_pct": 30, "costs": "full delivery cost model at the stock's liquidity decile",
         "edge_for_kelly_bps": 27.0, "sd_for_kelly": 0.06, "idle_cash": "cash not in stocks earns a liquid fund's return: India call-money rate (FRED IRSTCI01INM156N) minus 0.30% a year for fund costs, kept in its own pot (not fed back into position sizes)"}
RATE_FILE = OUT / "india_call_rate.json"
FUND_FEE = 0.003


def india_rate(refresh=False):
    """Monthly India call-money rate in % a year (FRED IRSTCI01INM156N), cached in the repository so tests and runs without the key still work. refresh: try FRED (needs FRED_API_KEY), keep the cache on any failure."""
    import os
    if refresh:
        key = os.environ.get("FRED_API_KEY", "")
        for f in (ROOT / ".env", ROOT.parent / "SAMNIDHY_EDUCATIONAL_DASHBOARD" / ".env"):
            if not key and f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.startswith("FRED_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
        if key:
            try:
                import requests
                r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={"series_id": "IRSTCI01INM156N", "file_type": "json", "api_key": key}, timeout=40); r.raise_for_status()
                d = {"src": "FRED IRSTCI01INM156N (India, immediate rates: call money / interbank, % a year, monthly)", "d": [[o["date"], float(o["value"])] for o in r.json()["observations"] if o["value"] not in (".", "")]}
                RATE_FILE.parent.mkdir(parents=True, exist_ok=True); RATE_FILE.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
            except Exception as e:                                       # noqa: BLE001
                print("india rate refresh failed (", type(e).__name__, "); the cached file is used")          # never print the request: it carries the key
    d = json.loads(RATE_FILE.read_text(encoding="utf-8"))
    return pd.Series({pd.Timestamp(a): b for a, b in d["d"]}).sort_index()


def fund_daily(cal, rate=None):
    """Daily liquid-fund return on each trading day of cal: the latest known monthly call rate minus the fund fee, over 252 days."""
    rate = india_rate() if rate is None else rate
    return ((rate - FUND_FEE * 100).clip(lower=0) / 100 / 252).reindex(pd.DatetimeIndex(cal).union(rate.index)).ffill().reindex(pd.DatetimeIndex(cal)).fillna(0.0)


def overlay(equity, daily_ret, switch_cost=0.0):
    """equity rows [date, equity, cash, n_open] of the bot; daily_ret: Series of the idle-cash asset's daily return on the same dates. The cash held at the previous close earns that day's return;
    the gains sit in their own pot that compounds. switch_cost: fraction paid on every change of the cash amount (money moved into or out of the fund). -> new equity rows."""
    out, pot, prev_cash = [], 0.0, None
    for d, e, cash, n in equity:
        r = float(daily_ret.get(pd.Timestamp(d), 0.0))
        if prev_cash is not None:
            pot = pot * (1 + r) + prev_cash * r - abs(cash - prev_cash) * switch_cost
        out.append([d, round(e + pot, 2), round(cash + pot, 2), n]); prev_cash = cash
    return out


def run_bot(books, prices, cal, cfg, rate=None, cash0=START_CASH, sell_fee=0.0, short_cap_pct=50.0):
    """The bot's current rules (BOT, v3): the one simulator, then idle cash in the liquid fund."""
    r = simulate(books, prices, cal, cfg, cash0=cash0, exits=BOT["exits"], risk_pct=BOT["risk_pct"], max_pos_pct=BOT["max_pos_pct"], sell_fee=sell_fee, short_cap_pct=short_cap_pct)
    r["equity"] = overlay(r["equity"], fund_daily(cal, rate)); return r


def _f(x):
    return x is not None and isinstance(x, (int, float, np.floating)) and math.isfinite(x)


def entry_index(cal, as_of):
    """Index of the first trading day strictly after the signal date."""
    return int(cal.searchsorted(pd.Timestamp(as_of), side="right"))


def simulate(books, prices, cal, cfg, cash0=START_CASH, exits=("stop", "time"), max_open=10, hold=5, mu=0.0027, sd=0.06, sector_cap_pct=30.0, end=None, risk_pct=None, max_pos_pct=None, sell_fee=0.0,
             protect_atr=None, short_cap_pct=50.0):
    """protect_atr: a protective stop order at entry -/+ protect_atr x ATR (picks carry "atr"), checked against every day's low/high (exit "protective stop").
    A pick with "side": "short" is a stock-futures short: its stop is ABOVE the entry, it pays the futures cost model, only its costs leave the cash at entry,
    its P/L is (entry - exit) x qty, and all shorts together are capped at short_cap_pct of the account."""
    """Event loop over trading days. books: [{"as_of", "picks": [{sym, rank, stop, goal (or None), adv_shares, decile, sector}]}] (picks best first); prices: {sym: DataFrame o,h,l,c,v};
    cal: DatetimeIndex of trading days. Returns {equity: [[date, equity, cash, n_open]], trades: [...], open: [...], skipped: [...]}."""
    cal = pd.DatetimeIndex(cal); bars = {}
    def bar(sym):
        if sym not in bars:
            p = prices.get(sym); bars[sym] = None if p is None else {k: p[k].reindex(cal).values.astype(float) for k in ("o", "h", "l", "c", "v")}
        return bars[sym]
    due = {}
    for b in sorted(books, key=lambda b: b["as_of"]):
        i = entry_index(cal, b["as_of"])
        if i < len(cal):
            due.setdefault(i, []).append(b)
    if not due:
        return {"equity": [], "trades": [], "open": [], "skipped": []}
    i0, last = min(due), (len(cal) - 1 if end is None else min(len(cal) - 1, int(cal.searchsorted(pd.Timestamp(end), side="right")) - 1))
    cash = float(cash0); pos = {}; lastc = {}; eq_rows = []; trades = []; skipped = []
    def equity_now():
        return cash + sum(p["qty"] * lastc.get(s, p["entry"]) if p["side"] == "long" else p["qty"] * (p["entry"] - lastc.get(s, p["entry"])) for s, p in pos.items())
    def money(p):
        cap = p["qty"] * p["entry"]
        return {"capital": round(cap, 2), "pct_of_account": round(cap / p["account"] * 100, 2), "account_at_entry": round(p["account"], 2), "sized_by": p["sized_by"],
                "risk_to_stop": round(p["qty"] * abs(p["entry"] - p["stop"]), 2), "cost_in": round(p["cost_in"], 2), "sector": p["sector"], "liquidity_decile": p["decile"], "side": p["side"],
                "protective_stop": round(p["pstop"], 2) if p.get("pstop") else None}

    def close_pos(sym, i, fill, reason):
        nonlocal cash
        p = pos.pop(sym); value = p["qty"] * fill
        if p["side"] == "long":
            cost_out = float(C.leg_cost("sell", value, "delivery", p["decile"], cfg)["total"]) + sell_fee; cash += value - cost_out; gross = p["qty"] * (fill - p["entry"])
        else:                                                                                # buying the future back
            cost_out = float(C.leg_cost("buy", value, "futures", p["decile"], cfg)["total"]); gross = p["qty"] * (p["entry"] - fill); cash += gross - cost_out
        costs = p["cost_in"] + cost_out; net = gross - costs
        trades.append({"sym": sym, "as_of": p["as_of"], "rank": p["rank"], "entry_date": str(cal[p["i"]].date()), "exit_date": str(cal[i].date()), "days": int(i - p["i"]), "qty": p["qty"], "entry": round(p["entry"], 2), "exit": round(float(fill), 2),
                       "stop": round(p["stop"], 2), "goal": round(p["goal"], 2) if p["goal"] else None, "reason": reason, "gross": round(gross, 2), "costs": round(costs, 2), "net": round(net, 2), "ret_pct": round(net / (p["qty"] * p["entry"]) * 100, 3),
                       **money(p), "cost_out": round(cost_out, 2), "exit_value": round(value, 2)})
    for i in range(i0, last + 1):
        for sym, p in list(pos.items()):                                                    # 1. exits that happen at the open: the weekly time limit
            b = bar(sym); o = b["o"][i] if b else np.nan
            if i >= p["exit_i"] and _f(o):
                close_pos(sym, i, o, "time")
        for bk in due.get(i, []):                                                           # 2. entries at the open
            for pk in bk["picks"]:
                sym = pk["sym"]; b = bar(sym); why = None
                if sym in pos: why = "already held"
                elif b is None or not _f(b["o"][i]) or not (b["v"][i] > 0): why = "no open price (suspended or no data)"
                elif len(pos) >= max_open: why = f"already {max_open} open positions"
                else:
                    side = pk.get("side", "long"); sg = 1 if side == "long" else -1
                    o = float(b["o"][i]); stop = float(pk["stop"]) if _f(pk.get("stop")) else None; goal = float(pk["goal"]) if _f(pk.get("goal")) else None
                    if stop is None or (o - stop) * sg <= 0: why = "opened at or below the stop" if side == "long" else "opened at or above the stop"
                    else:
                        eq = equity_now(); sec = pk.get("sector") or "?"
                        sec_val = sum(q["qty"] * lastc.get(s, q["entry"]) for s, q in pos.items() if q["sector"] == sec)
                        size = SG.position_size(eq, o, o - abs(o - stop), pk.get("adv_shares") or 0, mu, sd, cfg, risk_pct=risk_pct, max_pos_pct=max_pos_pct); qty = int(size["qty"]); sized_by = size.get("binding")
                        q_sec = int(max(0.0, eq * sector_cap_pct / 100 - sec_val) // o)
                        if q_sec < qty: qty, sized_by = q_sec, f"sector cap {sector_cap_pct:g}%"
                        if side == "short":
                            shorts = sum(q["qty"] * lastc.get(s, q["entry"]) for s, q in pos.items() if q["side"] == "short")
                            q_sh = int(max(0.0, eq * short_cap_pct / 100 - shorts) // o)
                            if q_sh < qty: qty, sized_by = q_sh, f"short cap {short_cap_pct:g}%"
                        q0 = qty
                        while qty > 0:
                            cost_in = float(C.leg_cost("buy" if side == "long" else "sell", qty * o, "delivery" if side == "long" else "futures", pk["decile"], cfg)["total"])
                            if (qty * o if side == "long" else 0.0) + cost_in <= cash + 1e-9: break
                            qty -= 1
                        if qty < 1: why = f"size 0 ({size.get('binding')}) or no cash/sector room"
                        else:
                            cash -= (qty * o if side == "long" else 0.0) + cost_in
                            atr = float(pk["atr"]) if _f(pk.get("atr")) else None
                            pos[sym] = {"qty": qty, "entry": o, "stop": stop, "goal": goal, "i": i, "exit_i": i + hold, "cost_in": cost_in, "decile": pk["decile"], "sector": sec, "as_of": bk["as_of"], "rank": pk.get("rank"),
                                        "account": eq, "sized_by": "cash left" if qty < q0 else sized_by, "side": side,
                                        "pstop": (o - sg * pk.get("protect_atr", protect_atr) * atr) if pk.get("protect_atr", protect_atr) and atr else None}
                if why:
                    skipped.append({"sym": sym, "as_of": bk["as_of"], "why": why})
        for sym, p in list(pos.items()):                                                    # 3. stop and target during the day (the stop first when both are touched)
            b = bar(sym)
            if not b or not _f(b["o"][i]):
                continue
            o, h, l = b["o"][i], b["h"][i], b["l"][i]
            ps = p.get("pstop")
            if ps and (l <= ps if p["side"] == "long" else h >= ps):                     # the protective stop: a gap through it fills at the open (never better than the open)
                close_pos(sym, i, (min(o, ps) if p["side"] == "long" else max(o, ps)) if i > p["i"] else ps, "protective stop"); continue
            if p["side"] == "short":
                continue
            if "stop" in exits and l <= p["stop"]:
                close_pos(sym, i, o if o <= p["stop"] else p["stop"], "stop")
            elif "goal" in exits and p["goal"] and h >= p["goal"]:
                close_pos(sym, i, o if o >= p["goal"] else p["goal"], "goal")
        for sym in list(pos):                                                               # 4. value at the close
            b = bar(sym)
            if b and _f(b["c"][i]):
                lastc[sym] = float(b["c"][i])
        for sym, p in list(pos.items()):                                                    # a stock with no bars for 15 days is treated as gone: out at its last close
            b = bar(sym); seen = [j for j in range(max(p["i"], i - 15), i + 1) if b and _f(b["c"][j])]
            if i - p["i"] >= 15 and not seen:
                close_pos(sym, i, lastc.get(sym, p["entry"]), "no data")
        eq_rows.append([str(cal[i].date()), round(equity_now(), 2), round(cash, 2), len(pos)])
    openp = [{"sym": s, "qty": p["qty"], "entry": round(p["entry"], 2), "entry_date": str(cal[p["i"]].date()), "stop": round(p["stop"], 2), "goal": round(p["goal"], 2) if p["goal"] else None, "last": round(lastc.get(s, p["entry"]), 2),
              "pnl": round(p["qty"] * (lastc.get(s, p["entry"]) - p["entry"]) * (1 if p["side"] == "long" else -1) - p["cost_in"], 2), "days_held": int(last - p["i"]), "days_left": int(max(0, p["exit_i"] - last)), "as_of": p["as_of"], "rank": p["rank"], **money(p),
              "value_now": round(p["qty"] * lastc.get(s, p["entry"]), 2), "exit_due": str(cal[p["exit_i"]].date()) if p["exit_i"] < len(cal) else None} for s, p in pos.items()]
    return {"equity": eq_rows, "trades": trades, "open": openp, "skipped": skipped}


def stats(res, cash0=START_CASH):
    eq = res["equity"]; tr = res["trades"]
    if not eq:
        return {"started": False}
    e = np.array([r[1] for r in eq]); d = pd.to_datetime([r[0] for r in eq]); peak = np.maximum.accumulate(e); dd = e / peak - 1
    yrs = max((d[-1] - d[0]).days / 365.25, 1e-9); win = [t for t in tr if t["net"] > 0]; los = [t for t in tr if t["net"] <= 0]
    gw = sum(t["net"] for t in win); gl = -sum(t["net"] for t in los)
    by_year = {}
    s = pd.Series(e, index=d)
    for y, g in s.groupby(s.index.year):
        prev = s[s.index < g.index[0]]; base = prev.iloc[-1] if len(prev) else cash0; by_year[int(y)] = round(float(g.iloc[-1] / base - 1) * 100, 2)
    invested = np.array([(r[1] - r[2]) / r[1] for r in eq if r[1] > 0])
    return {"started": True, "from": eq[0][0], "to": eq[-1][0], "start_equity": cash0, "end_equity": round(float(e[-1]), 2), "pnl": round(float(e[-1] - cash0), 2), "return_pct": round(float(e[-1] / cash0 - 1) * 100, 2),
            "cagr_pct": round(float((e[-1] / cash0) ** (1 / yrs) - 1) * 100, 2) if yrs >= 1 else None, "max_drawdown_pct": round(float(dd.min()) * 100, 2), "trades": len(tr), "win_rate": round(len(win) / len(tr), 4) if tr else None,
            "avg_win_pct": round(float(np.mean([t["ret_pct"] for t in win])), 3) if win else None, "avg_loss_pct": round(float(np.mean([t["ret_pct"] for t in los])), 3) if los else None, "profit_factor": round(gw / gl, 3) if gl > 0 else None,
            "avg_net_pct_per_trade": round(float(np.mean([t["ret_pct"] for t in tr])), 3) if tr else None, "costs_paid": round(sum(t["costs"] for t in tr), 2), "avg_days": round(float(np.mean([t["days"] for t in tr])), 2) if tr else None,
            "exits": {k: sum(1 for t in tr if t["reason"] == k) for k in ("stop", "goal", "time", "no data", "protective stop")}, "avg_invested_pct": round(float(invested.mean()) * 100, 1) if len(invested) else None, "by_year_pct": by_year}


# ------------------------------------------------------------------ plans from prices (the history; live picks carry the levels the page showed)
def prep_prices(px, cfg):
    """Per-stock arrays known on each date: close, ATR(14), the stop, a volatility PROXY for the target (the live target is the 5-day forecast range edge) and the 250-day average traded value in Rs crore."""
    if px is None or len(px) < 80:
        return None
    px = L.clean_prices(px); F = L.price_features(px); close = px["c"].values.astype(float); atr = F["atr14"].values.astype(float); sig = F["vol20"].values.astype(float) * math.sqrt(5)
    adv = ((px["c"] * px["v"]).rolling(250, min_periods=120).mean() / 1e7).values.astype(float); k = cfg["signals"]; vs = close - k["stop_atr_default"] * atr
    stop = np.minimum(np.maximum(vs, close - k["stop_atr_max"] * atr), close - k["stop_atr_min"] * atr)                    # signals.choose_stop() with no strategy or swing stop
    return {"index": px.index, "close": close, "atr": atr, "stop": stop, "goal": close * (1 + 0.6745 * sig), "adv_cr": adv, "px": px}


def plan_at(pr, date):
    if pr is None:
        return None
    i = pr["index"].searchsorted(pd.Timestamp(date))
    if i >= len(pr["index"]) or pr["index"][i] != pd.Timestamp(date):
        return None
    c, a, st, g, adv = pr["close"][i], pr["atr"][i], pr["stop"][i], pr["goal"][i], pr["adv_cr"][i]
    if not (_f(c) and _f(a) and a > 0 and _f(st) and _f(g) and _f(adv) and c > 0):
        return None
    return {"close": float(c), "atr": float(a), "stop": float(st), "goal": float(g), "adv_cr": float(adv), "adv_shares": int(adv * 1e7 / c)}


def plan_from_prices(px, as_of, cfg):
    return plan_at(prep_prices(px, cfg), as_of)


def books_from_scores(O, prep, cfg, universe, shorts=None):
    """Historical Friday books from ALADIN 1's walk-forward 5-day probabilities (O: date, sym, p). Rank among the stocks liquid that day (trailing 250-day traded value >= Rs 2 crore), best 1% = BUY."""
    Wc = cfg["weekly"]; allv = [v["adv_cr"] for v in universe.values()]; books = []
    for d, g in O.groupby("date"):
        rows = []
        for sym, p in zip(g["sym"].values, g["p"].values):
            if sym not in universe:
                continue
            plan = plan_at(prep(sym), d)
            if plan and plan["adv_cr"] >= 2.0:
                rows.append((sym, float(p), plan))
        n = len(rows)
        if n < 50:
            continue
        rows.sort(key=lambda x: (-x[1], x[0])); picks = []
        for k, (sym, p, plan) in enumerate(rows):
            pct = 1 - (k + 0.5) / n
            if W.decide(pct, Wc) != "bull":
                break
            picks.append({"sym": sym, "rank": round(pct, 4), "stop": plan["stop"], "goal": plan["goal"], "adv_shares": plan["adv_shares"], "decile": C.adv_decile(universe[sym]["adv_cr"], allv), "sector": universe[sym]["sector"], "atr": plan["atr"]})
        if shorts is not None:                                                              # shorts(date) -> the F&O stock set that day, or None before F&O data
            fno = shorts(pd.Timestamp(d))
            for k in range(n - 1, -1, -1):
                sym, p, plan = rows[k]; pct = 1 - (k + 0.5) / n
                if W.decide(pct, Wc) != "bear":
                    break
                if fno and sym in fno:
                    picks.append({"sym": sym, "side": "short", "rank": round(pct, 4), "stop": plan["close"] + (plan["close"] - plan["stop"]), "goal": None, "adv_shares": plan["adv_shares"],
                                  "decile": C.adv_decile(universe[sym]["adv_cr"], allv), "sector": universe[sym]["sector"], "atr": plan["atr"]})
        books.append({"as_of": str(pd.Timestamp(d).date()), "picks": picks, "n": n})
    return books


def _universe_meta():
    u = json.load(open(L.TERM / "universe.json", encoding="utf-8"))["stocks"]
    return {s["s"]: {"adv_cr": (s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7, "sector": s.get("ind") or "Unknown"} for s in u if s.get("board") == "Main" and not s.get("etf")}


def _benchmark(O, prep):
    """The equal-weight average of the liquid stocks over each signal week (entry open to the open 5 trading days later), compounded: what putting the same money in 'the market' would have done, before costs."""
    out = {}
    for sym in O["sym"].unique():
        pr = prep(sym)
        if pr is None or len(pr["index"]) < 400:
            continue
        o = pr["px"]["o"].values; idx = pr["index"]
        for d in O.loc[O["sym"] == sym, "date"]:
            i = idx.searchsorted(pd.Timestamp(d))
            if i < len(idx) - 6 and idx[i] == pd.Timestamp(d) and _f(pr["adv_cr"][i]) and pr["adv_cr"][i] >= 2.0:
                r = float(o[i + 6] / o[i + 1] - 1)
                if math.isfinite(r) and abs(r) < 0.6:
                    out.setdefault(pd.Timestamp(d), []).append(r)
    return pd.Series({d: float(np.mean(v)) for d, v in out.items() if len(v) >= 50}).sort_index()


def run_backtest(workers=12, oos=None, out=None, sample=None):
    cfg = C.load_cfg(); t0 = time.time()
    O = pd.read_pickle(oos or (ROOT.parent / "SAMNIDHY_EDUCATIONAL_DASHBOARD" / "data" / "aladin_cache" / "oos_5.pkl")); O["date"] = pd.to_datetime(O["date"]); O = O.dropna(subset=["p"])
    if sample:
        O = O[O["sym"].isin(sorted(O["sym"].unique())[:sample])]
    cache = {}
    def prep(sym):
        if sym not in cache:
            cache[sym] = prep_prices(L.load_prices(sym), cfg)
        return cache[sym]
    universe = _universe_meta(); universe = {s: v for s, v in universe.items() if s in set(O["sym"])}
    books = books_from_scores(O, prep, cfg, universe); print(f"{len(books)} Friday books, {sum(len(b['picks']) for b in books)} BUY picks ({time.time() - t0:.0f}s)", flush=True)
    syms = sorted({p["sym"] for b in books for p in b["picks"]}); prices = {s: prep(s)["px"] for s in syms if prep(s) is not None}
    cal = L.load_index().index; cal = cal[cal >= pd.Timestamp(books[0]["as_of"]) - pd.Timedelta(days=5)]
    runs = {}
    MAIN = "v3: time exit, 2% risk, 20% a stock, idle cash in a liquid fund (the bot)"
    variants = ((MAIN, None), ("v2: stop + time (dropped before any live trade)", ("stop", "time")), ("v1: stop + goal + time (first design, dropped)", ("stop", "goal", "time")), ("time only, 1% risk, idle cash earns nothing", ("time",)))
    for name, ex in variants:
        r = run_bot(books, prices, cal, cfg) if ex is None else simulate(books, prices, cal, cfg, exits=ex); runs[name] = {"stats": stats(r), "equity": r["equity"], "trades": r["trades"], "skipped": r["skipped"]}
        print(f"  {name}: end {runs[name]['stats']['end_equity']:,.0f}  return {runs[name]['stats']['return_pct']}%  max dd {runs[name]['stats']['max_drawdown_pct']}%  trades {runs[name]['stats']['trades']}  ({time.time() - t0:.0f}s)", flush=True)
    bench = _benchmark(O, prep)
    main = runs[MAIN]; skip_why = {}
    for s in main["skipped"]:
        skip_why[s["why"].split(" (")[0]] = skip_why.get(s["why"].split(" (")[0], 0) + 1
    doc = {"kind": "HISTORICAL SIMULATION", "label": "HISTORICAL SIMULATION 2013-2026: ALADIN 1's walk-forward (out-of-sample) scores, stocks listed today (flatters the positive signals), the price goal is a volatility proxy, idle cash earns the India call-money rate minus fund costs. Not live trading, not real money.",
           "created_utc": pd.Timestamp.utcnow().isoformat(), "rules": RULES, "rule_history": RULE_HISTORY, "books": len(books), "picks": sum(len(b["picks"]) for b in books), "stats": main["stats"], "equity": main["equity"][::1],
           "benchmark": {"label": "equal-weight average of the liquid stocks each signal week, compounded, before costs (the same weeks, the same holding period)", "mean_weekly_pct": round(float(bench.mean()) * 100, 3), "weekly": [[str(d.date()), round(float(r), 5)] for d, r in bench.items()]},
           "ablation": {k: v["stats"] for k, v in runs.items()}, "skipped_reasons": skip_why, "recent_trades": main["trades"][-120:], "all_trades_n": len(main["trades"]), "runtime_s": round(time.time() - t0)}
    f = Path(out or OUT / "backtest.json"); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8"); print("wrote", f, f.stat().st_size)
    return doc


# ------------------------------------------------------------------ the live front test
def live_books(ledger_dir=None, cfg=None, start=None, shorts=None):
    """Books from the ledger that count as LIVE: Friday signal dates on or after the forward clock, written before the entry open. Levels come from the ledger line (what the page showed); an older line without
    levels is recomputed from the prices on its own date (deterministic)."""
    cfg = cfg or C.load_cfg(); start = start or cfg["forward_clock_start"]; books = []; uni = _universe_meta(); allv = [v["adv_cr"] for v in uni.values()]
    for r in LG.read_all(ledger_dir):
        if r["t"] != "wk" or r["d"] < start or pd.Timestamp(r["d"]).weekday() != 4 or not W.made_in_time(r):
            continue
        lv = r.get("levels") or {}; picks = []
        for sym, close, rank in r["buy"]:
            x = lv.get(sym)
            if x and _f(x[0]):
                stop, goal, atr, adv_sh = x[0], x[1], x[2], x[3]
            else:
                pl = plan_from_prices(L.load_prices(sym), r["d"], cfg)
                if not pl:
                    continue
                stop, goal, adv_sh = pl["stop"], None, pl["adv_shares"]
            m = uni.get(sym, {"adv_cr": 1.0, "sector": "Unknown"})
            atr = x[2] if x and _f(x[2]) else (pl or {}).get("atr") if not (x and _f(x[0])) else None
            picks.append({"sym": sym, "rank": rank, "stop": stop, "goal": goal, "adv_shares": adv_sh or 0, "decile": C.adv_decile(m["adv_cr"], allv), "sector": m["sector"], "atr": atr})
        if shorts is not None:                                                  # the SELL bucket of the same line, F&O stocks only, as stock-futures shorts
            fno = shorts(pd.Timestamp(r["d"])) or set()
            for sym, close, rank in sorted(r.get("sell") or [], key=lambda x: x[2]):
                if sym not in fno:
                    continue
                pl = plan_from_prices(L.load_prices(sym), r["d"], cfg)
                if not pl:
                    continue
                m = uni.get(sym, {"adv_cr": 1.0, "sector": "Unknown"})
                picks.append({"sym": sym, "side": "short", "rank": rank, "stop": pl["close"] + (pl["close"] - pl["stop"]), "goal": None, "adv_shares": pl["adv_shares"],
                              "decile": C.adv_decile(m["adv_cr"], allv), "sector": m["sector"], "atr": pl["atr"]})
        books.append({"as_of": r["d"], "picks": picks})
    return books


ANCHORS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "ITC", "LT")


def trading_calendar(prices, since=None):
    """Trading days = every date on which the NIFTY index OR any of a few always-traded large stocks OR any traded name has a bar. The index file alone is not enough: on the GitHub runner its daily
    part was not refreshed and the calendar stopped in 2021, which would have frozen the live front test (found 2026-10-09)."""
    days = set()
    ix = L.load_index()
    if ix is not None:
        days.update(ix.index)
    for s in ANCHORS:
        p = L.load_prices(s)
        if p is not None:
            days.update(p.index)
    for p in prices.values():
        days.update(p.index)
    cal = pd.DatetimeIndex(sorted(days))
    return cal[cal >= pd.Timestamp(since)] if since else cal


def timeline(lines, trades, openp, start, today=None, n_target=100, expect=None):
    """The continuous front test, week by week from the forward clock: for every Friday, was a book written, was it in time (before the next open), how many names, what became of its trades.
    lines: ledger records; trades / openp: the live simulation's closed and open positions. Pure (tests/aladin2/test_paper.py). -> dict for the page."""
    today = pd.Timestamp(today or pd.Timestamp.utcnow().tz_localize(None)).normalize(); wk = {}
    for r in lines:
        if r.get("t") == "wk" and r["d"] >= start:
            wk.setdefault(r["d"], r)
    fridays = [d for d in pd.date_range(pd.Timestamp(start), today, freq="W-FRI")]
    rows = []
    for f in fridays:
        d = str(f.date()); r = wk.get(d); tr = [t for t in trades if t["as_of"] == d]; op = [o for o in openp if o["as_of"] == d]
        if r is None:
            status = "waiting" if f.normalize() >= today - pd.Timedelta(days=3) else "missed"
        else:
            status = "in time" if W.made_in_time(r) else "late"
        rows.append({"friday": d, "entry_day": str(W.W_next_weekday(d).date()), "status": status, "created": r.get("created") if r else None, "names": len(r.get("buy", [])) if r else None,
                     "entered": len(tr) + len(op), "closed": len(tr), "open": len(op), "net": round(sum(t["net"] for t in tr), 2) if tr else None, "wins": sum(1 for t in tr if t["net"] > 0)})
    nxt = pd.Timestamp(today)
    while nxt.weekday() != 4:
        nxt += pd.Timedelta(days=1)
    closed = len(trades)
    return {"start": start, "today": str(today.date()), "days_running": int((today - pd.Timestamp(start)).days), "weeks": rows, "next_book": str(nxt.date()), "next_entry": str(W.W_next_weekday(str(nxt.date())).date()),
            "closed_trades": closed, "judge_after_trades": n_target, "progress": round(min(1.0, closed / n_target), 4),
            "expect_from_history": {**(expect or {"win_rate": 0.51, "profit_factor": 1.2}), "note": "what the 13-year history did; the live record is judged against these after about 100 closed trades"}}


# The v4 shadow (owner, 2026-10-14: "both"): the trading rules that failed their history test (round 2, scripts/aladin2/trader.py) run LIVE beside the bot from
# the list of Friday 2026-10-16: the same lists plus F&O shorts on the SELL bucket and a 3 ATR protective stop. After 26 finished weeks, if the shadow's return
# beats the bot's over exactly the same dates AND its maximum drawdown is no deeper, a promote line is written once (shadow_promote.json) and from the next
# list on the bot itself trades with the v4 rules. Never reversed automatically.
SHADOW = {"from_book": "2026-10-16", "protect_atr": 3.0, "short_cap_pct": 50.0, "promote_after_weeks": 26, "declared": "2026-10-14"}
PROMOTE = OUT / "shadow_promote.json"


def promoted():
    try:
        return json.loads(PROMOTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def shadow_check(shadow_doc, bot_doc, now=None):
    """Pure apart from writing the promote file once. -> {"weeks", "shadow_return_pct", "bot_return_pct", "shadow_dd_pct", "bot_dd_pct", "promoted"}."""
    se, be = shadow_doc.get("equity") or [], bot_doc.get("equity") or []
    out = {"weeks": 0, "promote_after_weeks": SHADOW["promote_after_weeks"], "promoted": promoted()}
    if not se:
        return out
    d0, d1 = se[0][0], se[-1][0]; bw = [r for r in be if d0 <= r[0] <= d1]
    out["weeks"] = len({pd.Timestamp(r[0]).isocalendar()[:2] for r in se}) - 1
    if not bw:
        return out
    ret = lambda rows: round((rows[-1][1] / rows[0][1] - 1) * 100, 2)
    dd = lambda rows: round(float(min(r[1] / max(x[1] for x in rows[:k + 1]) - 1 for k, r in enumerate(rows))) * 100, 2)
    out.update({"from": d0, "to": d1, "shadow_return_pct": ret(se), "bot_return_pct": ret(bw), "shadow_dd_pct": dd(se), "bot_dd_pct": dd(bw)})
    if out["promoted"] is None and out["weeks"] >= SHADOW["promote_after_weeks"] and out["shadow_return_pct"] > out["bot_return_pct"] and out["shadow_dd_pct"] >= out["bot_dd_pct"]:
        rec = {"ts": (now or pd.Timestamp.utcnow()).isoformat(), "weeks": out["weeks"], "shadow_return_pct": out["shadow_return_pct"], "bot_return_pct": out["bot_return_pct"],
               "from_next_list_after": d1}
        PROMOTE.write_text(json.dumps(rec), encoding="utf-8"); out["promoted"] = rec
    return out


def run_live(ledger_dir=None, out=None, small=False, shadow=False):
    """The live front test. small=True: the Rs 10,000 account (SMALL) on the same lists from its own first list, written to live_small.json."""
    cfg = C.load_cfg(); start = cfg["forward_clock_start"]; prom = promoted()
    fno = None
    if shadow or prom:
        from .trader import fno_lookup
        fno = fno_lookup()
    books = live_books(ledger_dir, cfg, shorts=fno)
    cash0, fee = (SMALL["budget_inr"], SMALL["dp_charge_per_sale_inr"]) if small else (START_CASH, 0.0)
    if small:
        books = [b for b in books if b["as_of"] >= SMALL["from_book"]]
    if shadow:
        books = [{**b, "picks": [{**p, "protect_atr": SHADOW["protect_atr"]} for p in b["picks"]]} for b in books if b["as_of"] >= SHADOW["from_book"]]
    else:                                                                       # the bot: v3 lists (no shorts), or v4 from the list after a promotion
        books = [b if prom and b["as_of"] > prom["from_next_list_after"] else {**b, "picks": [p for p in b["picks"] if p.get("side", "long") == "long"]} for b in books]
        if prom:
            books = [{**b, "picks": [{**p, "protect_atr": SHADOW["protect_atr"]} for p in b["picks"]]} if b["as_of"] > prom["from_next_list_after"] else b for b in books]
    syms = sorted({p["sym"] for b in books for p in b["picks"]}); prices = {}
    for s in syms:
        p = L.load_prices(s)
        if p is not None:
            prices[s] = L.clean_prices(p)
    idx = trading_calendar(prices, pd.Timestamp(start) - pd.Timedelta(days=10))
    rules = {**RULES, "budget_inr": cash0, **({"first_list": SMALL["from_book"], "dp_charge_per_sale_inr": fee, "declared": SMALL["declared"]} if small else {}),
             **({"shadow": "rule v4 candidate: the same lists plus F&O shorts on the SELL bucket (at most 50% of the account) and a 3 ATR protective stop on every position",
                 "first_list": SHADOW["from_book"], "declared": SHADOW["declared"]} if shadow else {})}
    last_bar = str(idx[-1].date()); doc = {"kind": "LIVE FRONT TEST (paper)" + (", small account" if small else "") + (", v4 shadow" if shadow else ""), "label": "LIVE FRONT TEST: simulated trades on real prices from the forward clock. Simulated money, no broker." + (f" Small account: Rs {cash0:,}, the same rules and lists as the Rs 10 lakh account." if small else ""), "created_utc": pd.Timestamp.utcnow().isoformat(), "rules": rules,
           "rule_history": RULE_HISTORY, "forward_clock_start": start, "books_used": [b["as_of"] for b in books], "last_price_date": last_bar}
    if not books:
        nxt = pd.Timestamp(start)
        doc.update({"stats": {"started": False}, "equity": [], "open": [], "trades": [], "skipped": [], "note": f"The small account starts with the list of Friday {SMALL['from_book']}; it enters at the next trading day's open." if small else "No live Friday book has been written in time yet. The first one is the Friday book; the bot enters at the next trading day's open."})
    else:
        r = run_bot(books, prices, idx, cfg, india_rate(refresh=True), cash0=cash0, sell_fee=fee, short_cap_pct=SHADOW["short_cap_pct"]); doc.update({"stats": stats(r, cash0), "equity": r["equity"], "open": r["open"], "trades": r["trades"], "skipped": r["skipped"][-100:], "note": None})
    bt = OUT / "backtest.json"; hs = json.loads(bt.read_text(encoding="utf-8")).get("stats", {}) if bt.exists() else {}          # what the current rules did in the history
    first = SMALL["from_book"] if small else SHADOW["from_book"] if shadow else None
    doc["timeline"] = timeline([x for x in LG.read_all(ledger_dir) if not first or x.get("d", "") >= first], doc["trades"], doc["open"], first or start, expect={"win_rate": hs["win_rate"], "profit_factor": hs["profit_factor"]} if hs.get("win_rate") else None)
    if shadow:
        try:
            doc["shadow_vs_bot"] = shadow_check(doc, json.loads((OUT / "live.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            doc["shadow_vs_bot"] = {"weeks": 0, "promote_after_weeks": SHADOW["promote_after_weeks"], "promoted": promoted()}
    doc["promotion"] = prom
    f = Path(out or OUT / ("live_small.json" if small else "live_shadow.json" if shadow else "live.json")); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(f"live paper account{' (small)' if small else ''}: {len(books)} book(s) {[b['as_of'] for b in books]}; stats {doc['stats'].get('end_equity', 'not started')}; wrote {f}")
    return doc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--backtest", action="store_true"); ap.add_argument("--live", action="store_true"); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--sample", type=int, default=None, help="use only the first N symbols (a quick check)")
    a = ap.parse_args()
    if a.backtest:
        run_backtest(a.workers, sample=a.sample)
    if a.live:
        run_live(); run_live(small=True); run_live(shadow=True)


if __name__ == "__main__":
    main()
