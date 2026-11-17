"""B-Lab Technical division: the self-evolving strategy desk (T4) and the AI paper scout (T6), operating scripts/blab/evolve.py
every run. Rules: docs/blab/STRATEGY_EVIDENCE.md (written before any test; one recorded change after the first replay).

Live money rule (declared before the replay): if the selector does not beat the equal-money blend of all active candidates
over the whole replay (by return per unit of risk), the live paper account follows the blend and the page says so."""
from __future__ import annotations

import json
from datetime import date, timedelta

from . import evolve as V
from .core import DATA, Limit, NoKey

STORE = DATA / "blab" / "store"
SCOUT_EVERY_DAYS = 28
DEFAULT_IDS = {f: V.cid(f, p) for f, p in V.DEFAULTS.items()}


def _load(name, default):
    try:
        return json.loads((STORE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(name, doc):
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / name).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False, default=str), encoding="utf-8")


def t6_scout(ctx):
    """Monthly: read the newest arXiv finance abstracts, propose simple rules in the desk's grammar. Nothing proposed is used
    until it has its own 126-session paper record and passes the selector."""
    pool = _load("evolve_pool.json", {"extra": [], "scout_runs": []})
    today = ctx.now.date()
    last = pool["scout_runs"][-1]["date"] if pool["scout_runs"] else None
    ctx.shared["T6_extra"] = pool["extra"]
    if last and (today - date.fromisoformat(last)).days < SCOUT_EVERY_DAYS:
        r = pool["scout_runs"][-1]
        return {"items": len(pool["extra"]), "as_of": ctx.now.isoformat(), "runs": pool["scout_runs"][-6:], "extra": pool["extra"],
                "detail": f"Reads new finance papers (arXiv) every {SCOUT_EVERY_DAYS} days; last read {last}: {r['read']} abstracts, {len(r['proposed'])} rule(s) proposed. "
                          f"{len(pool['extra'])} scout-proposed candidates in the pool so far; next read on or after {(date.fromisoformat(last) + timedelta(days=SCOUT_EVERY_DAYS)).isoformat()}."}
    known = {c["id"] for c in V.grid_candidates()} | {c["id"] for c in pool["extra"]}
    new, notes = V.scout(ctx, known, today.isoformat(), llm=getattr(ctx, "llm", None), fetch=getattr(ctx, "arxiv_fetch", None))
    pool["extra"] += new
    pool["scout_runs"].append({"date": today.isoformat(), "read": notes["read"], "proposed": notes["proposed"]})
    _save("evolve_pool.json", pool)
    ctx.shared["T6_extra"] = pool["extra"]
    return {"items": len(pool["extra"]), "as_of": ctx.now.isoformat(), "runs": pool["scout_runs"][-6:], "extra": pool["extra"],
            "detail": f"Read {notes['read']} new finance abstracts (arXiv q-fin) today; {len(new)} simple rule(s) proposed and added to the pool "
                      f"({', '.join(n['candidate'] for n in notes['proposed']) or 'none fitted the simple-rule grammar'}). Each must earn its own 126-session record first."}


def state_table(M, runs, ids):
    """Each strategy's average daily return (a year's worth) in each market state of the regime bot, next to NIFTY 50's."""
    import numpy as np
    from .technical import states
    st, _v, _m = states(M.n50)
    by_day = dict(zip(M.dates, st))
    n50r = dict(zip(M.dates[1:], (M.n50[1:] / M.n50[:-1] - 1).tolist()))
    out = {}
    for name, rets in [("NIFTY 50", n50r)] + [(k, runs[k]["ret"]) for k in ids if k in runs]:
        g = {}
        for d, r in rets.items():
            s = by_day.get(d)
            if s and d >= V.START:
                g.setdefault(s, []).append(r)
        out[name] = {s: {"days": len(v), "yearly_pct": round(float(np.mean(v)) * 252 * 100, 1)} for s, v in g.items() if len(v) >= 60}
    return out


def macro_daily(M, runs):
    """The macro analyst's input (strategy_lab.json "daily"): each family's default rule, 21-session return minus NIFTY 50's,
    every 5th session."""
    import numpy as np
    n50 = dict(zip(M.dates, M.n50))
    dates = [d for d in M.dates if d >= V.START][::5]
    vals = {}
    for fam, k in DEFAULT_IDS.items():
        if k not in runs:
            continue
        e = dict(zip(runs[k]["dates"], runs[k]["eq"]))
        ds = runs[k]["dates"]
        pos = {d: i for i, d in enumerate(ds)}
        row = []
        for d in dates:
            i = pos.get(d)
            if i is None or i + 21 >= len(ds):
                row.append(None); continue
            d2 = ds[i + 21]
            row.append(round(float((e[d2] / e[d] - 1) - (n50[d2] / n50[d] - 1)), 5))
        vals[V.LABEL[fam]] = row
    return {"dates": dates, "values": vals}


def t4_desk(ctx):
    sys_path = str(V.ROOT / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    cfg = json.loads((DATA / "config" / "aladin_e.json").read_text(encoding="utf-8"))
    M = getattr(ctx, "market_all", None) or V.Market()
    if len(M.syms) < 200 or len(M.dates) < 1500:
        raise RuntimeError(f"price history too thin on this runner ({len(M.syms)} stocks, {len(M.dates)} days): the price cache or history branch is missing")
    extra = ctx.shared.get("T6_extra") or _load("evolve_pool.json", {"extra": []})["extra"]
    R = V.replay(M, cfg, extra=extra, log=lambda *a: None)
    res, today = R["result"], M.dates[-1]
    sel, bl = res["selector"]["whole"] or {}, res["blend"]["whole"] or {}
    mode = "selector" if (sel.get("sharpe") or -9) > (bl.get("sharpe") or -9) else "blend"
    active = [k for k, s in R["status"].items() if not s["retired"] and R["pool"][k]["born"] <= today]
    hold = R["holdout_from"]
    ledger = _load("evolve_ledger.json", {"go_live": ctx.now.date().isoformat(), "days": []})
    rows = []
    for k in sorted(active, key=lambda k: -(R["last_scores"].get(k) or -1)):
        run, c = R["runs"][k], R["pool"][k]
        rows.append({"id": k, "family": V.LABEL[c["fam"]], "rule": V.describe(c["fam"], c["p"], c.get("filt")), "origin": c["origin"], "born": c["born"],
                     "p_skill": R["last_scores"].get(k), "live": k in R["live"], "whole": V.stats(run["eq"], run["dates"]), "holdout": V.stats(run["eq"], run["dates"], a=hold),
                     "since_go_live": V.stats(run["eq"], run["dates"], a=ledger["go_live"]), "trades": len(run["trades"]),
                     "positions": run["positions"], "last_trades": run["trades"][-8:], "orders": run["orders"]})
    retired = [{"id": k, "family": V.LABEL[R["pool"][k]["fam"]], "retired": s["retired"], "origin": R["pool"][k]["origin"]} for k, s in R["status"].items() if s["retired"]]
    live_ids = R["live"] if mode == "selector" else []
    findings = []
    for k in live_ids:
        c = R["pool"][k]
        for side, sym in R["runs"][k]["orders"]:
            if side == "enter":
                findings.append({"sym": sym, "kind": f"strategy: {V.LABEL[c['fam']]}", "direction": 1,
                                 "text": f"Entry at the next open by a live strategy ({V.describe(c['fam'], c['p'], c.get('filt'))}); chosen by the selector with a {R['last_scores'].get(k, 0):.0%} probability of real skill.",
                                 "evidence": [{"src": "B-Lab strategy desk (NSE prices)", "url": "", "quote": k}]})
    blend_orders = sum(len(R["runs"][k]["orders"]) for k in active)
    sheet = signal_sheet(M, R, live_ids or active)
    day = {"date": today, "mode": mode, "live": live_ids, "active": len(active), "orders": {k: R["runs"][k]["orders"] for k in (live_ids or active)}}
    ledger["days"] = [d for d in ledger["days"] if d["date"] != today] + [day]
    ledger["days"] = ledger["days"][-400:]
    _save("evolve_ledger.json", ledger)
    states = state_table(M, R["runs"], [r["id"] for r in rows[:8]] + [k for k in DEFAULT_IDS.values() if k in R["runs"]])
    _save("strategy_lab.json", {"created": ctx.now.isoformat(), "from": V.START, "to": today, "rules": "scripts/blab/evolve.py, docs/blab/STRATEGY_EVIDENCE.md",
                                "record": states, "daily": macro_daily(M, R["runs"])})
    explain = ("The selector beat the blend over the replay, so the live strategies run the money." if mode == "selector" else
               f"Over the replay the selector (return per unit of risk {sel.get('sharpe')}) did not beat simply holding all active strategies equally "
               f"({bl.get('sharpe')}), so by the rule written beforehand the live paper account follows the blend. The selector keeps running on paper.")
    return {"items": len(active), "as_of": ctx.now.isoformat(), "findings": findings,
            "mode": mode, "explain": explain, "live": R["live"], "result": res, "holdout_from": hold, "tried": R["tried"], "go_live": ledger["go_live"],
            "candidates": rows, "retired": retired[-40:], "picks": R["picks"][-24:], "states": states,
            "curves": {"selector": R["selector_curve"], "blend": R["blend_curve"]}, "blend_orders": blend_orders,
            "sheet": sheet,
            "detail": f"{len(active)} active simple strategies on {len(M.syms):,} NSE stocks ({R['tried']} tried since {V.START}, {len(retired)} retired). "
                      f"Live now: {', '.join(R['live']) or 'none clears the skill bar'}. {explain} "
                      f"Replay 2010-{today[:4]} after costs: selector {sel.get('cagr_pct')}% a year (worst fall {sel.get('worst_fall_pct')}%), "
                      f"blend {bl.get('cagr_pct')}% ({bl.get('worst_fall_pct')}%), NIFTY 50 {(res['nifty50']['whole'] or {}).get('cagr_pct')}%."}


def stop_rule(M, c, j, t):
    """The exit the strategy's own rule implies, as a price where it has one. -> (price or None, words)."""
    import numpy as np
    fam, p = c["fam"], c["p"]
    if fam == "trend":
        v = float(M.sma(p["n"])[t, j])
        return (round(v, 2) if np.isfinite(v) else None), f"a close below the {p['n']}-day average (today {v:,.2f}) means out at the next open"
    if fam == "breakout":
        v = float(M.lo(p["out"], lag=0)[t, j])
        return (round(v, 2) if np.isfinite(v) else None), f"a close below the lowest close of the last {p['out']} days (today {v:,.2f}) means out at the next open"
    if fam == "cross":
        return None, f"out when the {p['s']}-day average falls below the {p['l']}-day; no fixed price"
    if fam == "rsi":
        return None, f"out when RSI(14) reaches {p['hi']} or after {p['k']} sessions; no fixed price"
    return None, "out at the monthly review if it drops out of the top 10; no fixed price"


def trade_range(trades, since):
    """Low / typical / high net result of the strategy's own closed trades since `since` (10th, 50th, 90th percentile)."""
    import numpy as np
    r = [t[5] for t in trades if t[2] == "exit" and t[5] is not None and t[0] >= since and len(t) <= 7]
    if len(r) < 30:
        return None, len(r)
    q = np.percentile(r, [10, 50, 90])
    days = [(np.datetime64(t[0]) - np.datetime64(t[6])).astype(int) for t in trades if t[2] == "exit" and len(t) <= 7 and t[0] >= since and t[6]]
    return {"low": round(float(q[0]), 4), "typical": round(float(q[1]), 4), "high": round(float(q[2]), 4), "n": len(r), "days": int(np.median(days)) if days else None}, len(r)


def signal_sheet(M, R, ids):
    """One list of tomorrow's entries and exits across the strategies that hold the money (`ids`), each with the strategies that
    agree, the reference price (last close), its rule's stop and the strategy's own tested range turned into prices."""
    t = len(M.dates) - 1
    col = {s: j for j, s in enumerate(M.syms)}
    since = str(int(M.dates[t][:4]) - 3) + M.dates[t][4:]
    rng = {k: trade_range(R["runs"][k]["trades"], since) for k in ids}
    enter, exit_ = {}, {}
    for k in ids:
        c = R["pool"][k]
        for side, sym in R["runs"][k]["orders"]:
            j = col.get(sym)
            if j is None:
                continue
            px = float(M.Cf[t, j])
            row = (enter if side == "enter" else exit_).setdefault(sym, {"sym": sym, "ref_price": round(px, 2), "by": []})
            item = {"strategy": k, "family": V.LABEL[c["fam"]], "rule": V.describe(c["fam"], c["p"], c.get("filt"))}
            if side == "enter":
                stop, words = stop_rule(M, c, j, t)
                r, n = rng[k]
                item.update({"stop": stop, "stop_rule": words, "trades_behind": n,
                             "range": None if not r else {"low": round(px * (1 + r["low"]), 2), "typical": round(px * (1 + r["typical"]), 2), "high": round(px * (1 + r["high"]), 2),
                                                          "days": r["days"], "from_trades": r["n"]}})
            row["by"].append(item)
    order = lambda d: sorted(d.values(), key=lambda x: (-len(x["by"]), x["sym"]))  # noqa: E731
    return {"as_of": M.dates[t], "enter": order(enter), "exit": order(exit_),
            "note": "Orders fill at the next open. Ranges are the 10th, 50th and 90th percentile of the strategy's own closed trades over the last 3 years "
                    "(net of costs; shown only with 30 or more trades) applied to the last close: what similar past trades did, not a forecast. "
                    "Stops are the strategy's own exit rule; strategies without a price rule say what makes them exit. Paper only, not investment advice."}
