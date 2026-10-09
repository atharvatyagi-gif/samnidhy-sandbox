"""
ALADIN paper-trading bot: a VIRTUAL, long-only account with a small fixed budget that trades the weekly signal book by fixed, written rules. Nothing here touches a broker or real money.

  python -m scripts.aladin2.paper --backtest [--workers 12]     replay 2013-2026 with the walk-forward scores (HISTORICAL SIMULATION)   -> data/aladin2/paper/backtest.json
  python -m scripts.aladin2.paper --live                         replay the live ledger books from the forward clock (FRONT TEST)       -> data/aladin2/paper/live.json

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
                {"v": 2, "declared": "2026-10-09", "exits": "stop + time (the price goal is information only)", "why": "no live trade existed yet, so the live record is untouched"}]
RULES = {"budget_inr": START_CASH, "books": "Friday book, positive-signal names only (long-only cash equity)", "entry": "open of the next trading day", "hold_trading_days": 5, "exit_order": "the stop, or the open of the 5th trading day after entry (the price goal is information, not an order)", "risk_per_trade_pct": 1.0, "max_position_pct": 10, "adv_participation_max": 0.05, "max_open": 10, "max_sector_pct": 30, "costs": "full delivery cost model at the stock's liquidity decile",
         "edge_for_kelly_bps": 27.0, "sd_for_kelly": 0.06}


def _f(x):
    return x is not None and isinstance(x, (int, float, np.floating)) and math.isfinite(x)


def entry_index(cal, as_of):
    """Index of the first trading day strictly after the signal date."""
    return int(cal.searchsorted(pd.Timestamp(as_of), side="right"))


def simulate(books, prices, cal, cfg, cash0=START_CASH, exits=("stop", "time"), max_open=10, hold=5, mu=0.0027, sd=0.06, sector_cap_pct=30.0, end=None, risk_pct=None, max_pos_pct=None):
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
        return cash + sum(p["qty"] * lastc.get(s, p["entry"]) for s, p in pos.items())
    def close_pos(sym, i, fill, reason):
        nonlocal cash
        p = pos.pop(sym); value = p["qty"] * fill; cost_out = float(C.leg_cost("sell", value, "delivery", p["decile"], cfg)["total"]); cash += value - cost_out
        gross = p["qty"] * (fill - p["entry"]); costs = p["cost_in"] + cost_out; net = gross - costs
        trades.append({"sym": sym, "as_of": p["as_of"], "rank": p["rank"], "entry_date": str(cal[p["i"]].date()), "exit_date": str(cal[i].date()), "days": int(i - p["i"]), "qty": p["qty"], "entry": round(p["entry"], 2), "exit": round(float(fill), 2),
                       "stop": round(p["stop"], 2), "goal": round(p["goal"], 2) if p["goal"] else None, "reason": reason, "gross": round(gross, 2), "costs": round(costs, 2), "net": round(net, 2), "ret_pct": round(net / (p["qty"] * p["entry"]) * 100, 3)})
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
                    o = float(b["o"][i]); stop = float(pk["stop"]) if _f(pk.get("stop")) else None; goal = float(pk["goal"]) if _f(pk.get("goal")) else None
                    if stop is None or o <= stop: why = "opened at or below the stop"
                    else:
                        eq = equity_now(); sec = pk.get("sector") or "?"
                        sec_val = sum(q["qty"] * lastc.get(s, q["entry"]) for s, q in pos.items() if q["sector"] == sec)
                        size = SG.position_size(eq, o, stop, pk.get("adv_shares") or 0, mu, sd, cfg, risk_pct=risk_pct, max_pos_pct=max_pos_pct); qty = int(size["qty"])
                        qty = min(qty, int(max(0.0, eq * sector_cap_pct / 100 - sec_val) // o))
                        while qty > 0:
                            cost_in = float(C.leg_cost("buy", qty * o, "delivery", pk["decile"], cfg)["total"])
                            if qty * o + cost_in <= cash + 1e-9: break
                            qty -= 1
                        if qty < 1: why = f"size 0 ({size.get('binding')}) or no cash/sector room"
                        else:
                            cash -= qty * o + cost_in
                            pos[sym] = {"qty": qty, "entry": o, "stop": stop, "goal": goal, "i": i, "exit_i": i + hold, "cost_in": cost_in, "decile": pk["decile"], "sector": sec, "as_of": bk["as_of"], "rank": pk.get("rank")}
                if why:
                    skipped.append({"sym": sym, "as_of": bk["as_of"], "why": why})
        for sym, p in list(pos.items()):                                                    # 3. stop and target during the day (the stop first when both are touched)
            b = bar(sym)
            if not b or not _f(b["o"][i]):
                continue
            o, h, l = b["o"][i], b["h"][i], b["l"][i]
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
              "pnl": round(p["qty"] * (lastc.get(s, p["entry"]) - p["entry"]) - p["cost_in"], 2), "days_held": int(last - p["i"]), "days_left": int(max(0, p["exit_i"] - last)), "as_of": p["as_of"], "rank": p["rank"], "sector": p["sector"]} for s, p in pos.items()]
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
            "exits": {k: sum(1 for t in tr if t["reason"] == k) for k in ("stop", "goal", "time", "no data")}, "avg_invested_pct": round(float(invested.mean()) * 100, 1) if len(invested) else None, "by_year_pct": by_year}


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


def books_from_scores(O, prep, cfg, universe):
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
            picks.append({"sym": sym, "rank": round(pct, 4), "stop": plan["stop"], "goal": plan["goal"], "adv_shares": plan["adv_shares"], "decile": C.adv_decile(universe[sym]["adv_cr"], allv), "sector": universe[sym]["sector"]})
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
    for name, ex in (("stop + time (the bot)", ("stop", "time")), ("stop + goal + time (first design, dropped)", ("stop", "goal", "time")), ("time only", ("time",))):
        r = simulate(books, prices, cal, cfg, exits=ex); runs[name] = {"stats": stats(r), "equity": r["equity"], "trades": r["trades"], "skipped": r["skipped"]}
        print(f"  {name}: end {runs[name]['stats']['end_equity']:,.0f}  return {runs[name]['stats']['return_pct']}%  max dd {runs[name]['stats']['max_drawdown_pct']}%  trades {runs[name]['stats']['trades']}  ({time.time() - t0:.0f}s)", flush=True)
    bench = _benchmark(O, prep)
    main = runs["stop + time (the bot)"]; skip_why = {}
    for s in main["skipped"]:
        skip_why[s["why"].split(" (")[0]] = skip_why.get(s["why"].split(" (")[0], 0) + 1
    doc = {"kind": "HISTORICAL SIMULATION", "label": "HISTORICAL SIMULATION 2013-2026: ALADIN 1's walk-forward (out-of-sample) scores, stocks listed today (flatters the positive signals), the price goal is a volatility proxy. Not live trading, not real money.",
           "created_utc": pd.Timestamp.utcnow().isoformat(), "rules": RULES, "rule_history": RULE_HISTORY, "books": len(books), "picks": sum(len(b["picks"]) for b in books), "stats": main["stats"], "equity": main["equity"][::1],
           "benchmark": {"label": "equal-weight average of the liquid stocks each signal week, compounded, before costs (the same weeks, the same holding period)", "mean_weekly_pct": round(float(bench.mean()) * 100, 3), "weekly": [[str(d.date()), round(float(r), 5)] for d, r in bench.items()]},
           "ablation": {k: v["stats"] for k, v in runs.items()}, "skipped_reasons": skip_why, "recent_trades": main["trades"][-120:], "all_trades_n": len(main["trades"]), "runtime_s": round(time.time() - t0)}
    f = Path(out or OUT / "backtest.json"); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8"); print("wrote", f, f.stat().st_size)
    return doc


# ------------------------------------------------------------------ the live front test
def live_books(ledger_dir=None, cfg=None, start=None):
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
            picks.append({"sym": sym, "rank": rank, "stop": stop, "goal": goal, "adv_shares": adv_sh or 0, "decile": C.adv_decile(m["adv_cr"], allv), "sector": m["sector"]})
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


def timeline(lines, trades, openp, start, today=None, n_target=100):
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
            "expect_from_history": {"win_rate": 0.51, "profit_factor": 1.2, "note": "what the 13-year history did; the live record is judged against these after about 100 closed trades"}}


def run_live(ledger_dir=None, out=None):
    cfg = C.load_cfg(); books = live_books(ledger_dir, cfg); start = cfg["forward_clock_start"]
    syms = sorted({p["sym"] for b in books for p in b["picks"]}); prices = {}
    for s in syms:
        p = L.load_prices(s)
        if p is not None:
            prices[s] = L.clean_prices(p)
    idx = trading_calendar(prices, pd.Timestamp(start) - pd.Timedelta(days=10))
    last_bar = str(idx[-1].date()); doc = {"kind": "LIVE FRONT TEST (paper)", "label": "LIVE FRONT TEST: simulated trades on real prices from the forward clock. Simulated money, no broker.", "created_utc": pd.Timestamp.utcnow().isoformat(), "rules": RULES,
           "rule_history": RULE_HISTORY, "forward_clock_start": start, "books_used": [b["as_of"] for b in books], "last_price_date": last_bar}
    if not books:
        nxt = pd.Timestamp(start)
        doc.update({"stats": {"started": False}, "equity": [], "open": [], "trades": [], "skipped": [], "note": "No live Friday book has been written in time yet. The first one is the Friday book; the bot enters at the next trading day's open."})
    else:
        r = simulate(books, prices, idx, cfg); doc.update({"stats": stats(r), "equity": r["equity"], "open": r["open"], "trades": r["trades"][-200:], "skipped": r["skipped"][-100:], "note": None})
    doc["timeline"] = timeline(LG.read_all(ledger_dir), doc["trades"], doc["open"], start)
    f = Path(out or OUT / "live.json"); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(f"live paper account: {len(books)} book(s) {[b['as_of'] for b in books]}; stats {doc['stats'].get('end_equity', 'not started')}; wrote {f}")
    return doc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--backtest", action="store_true"); ap.add_argument("--live", action="store_true"); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--sample", type=int, default=None, help="use only the first N symbols (a quick check)")
    a = ap.parse_args()
    if a.backtest:
        run_backtest(a.workers, sample=a.sample)
    if a.live:
        run_live()


if __name__ == "__main__":
    main()
