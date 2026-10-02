"""
ALADIN paper trader: a VIRTUAL, long-only portfolio that "takes" ALADIN's strongest leans so the model's real-world record builds up.
Simulated. Not real trades. Nothing here touches a broker or real money.

  python scripts/paper_trader.py          update data/paper_trades/portfolio.json from data/aladin/latest.json

Rules (from the brief; the thresholds are NOT loosened to create activity):
* Signal: 10-day P(up) > 0.60, confidence High, agreement 3/3 (all of Fundamental, Technical and Sentiment available and leaning up),
  in the NIFTY 500 or a liquid main-board stock. Expect very few: the count is reported.
* Entry: the OPEN of the first session AFTER the signal date (never the close that produced the signal). Until that bar exists
  the signal waits in `pending`; if no entry bar appears within 7 days it is skipped and the reason logged.
* Exit: the CLOSE of the 10th trading day after the entry session.
* Costs: 0.5% round trip (0.25% a side) deducted from the gross return. Rs 1,00,000 per position, one position per symbol,
  at most 10 open (highest P(up) first).
* Excess return is the net return minus NIFTY 50's return over the same window (open of the entry day to close of the exit day).
* Decile spread: using ALL saved nightly predictions that have matured (not only the paper trades), the average realised 10-day
  return of the top P(up) decile minus the bottom decile, measured close to close like the model's own label.
"""

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TERM = ROOT / "data" / "terminal"
ALADIN = ROOT / "data" / "aladin" / "latest.json"
HISTORY = ROOT / "data" / "aladin" / "history"
OUT = ROOT / "data" / "paper_trades" / "portfolio.json"
CFG = ROOT / "data" / "config" / "aladin_config.json"
DEFAULT = {"threshold": 0.60, "hold_days": 10, "cost_roundtrip": 0.005, "max_open": 10, "notional": 100000, "entry_wait_days": 7}
CAPTION = "Simulated. Not real trades. Costs of 0.5% round trip assumed."


def now_utc():
    return datetime.now(timezone.utc)


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_cfg():
    c = dict(DEFAULT)
    c.update(load_json(CFG, {}).get("paper", {}))
    return c


def load_bars(sym, root=TERM):
    """{'dates': [YYYY-MM-DD...], 'o': np.array, 'c': np.array} from the split-adjusted daily file, or None."""
    d = load_json(Path(root) / "daily" / f"{key(sym)}.json", {}).get("d")
    if not d:
        return None
    return {"dates": [r[0] for r in d], "o": np.array([r[1] for r in d], float), "c": np.array([r[4] for r in d], float)}


# ------------------------------------------------------------------ signals

def eligible_symbols(universe_stocks):
    """NIFTY 500 plus main-board stocks whose 20-day average traded value is at least Rs 5 crore. No ETFs, no SME."""
    return {s["s"] for s in universe_stocks if s.get("board") == "Main" and s.get("series") == "EQ" and not s.get("etf")
            and (s.get("n500") or (s.get("avgv20") or 0) * (s.get("c") or 0) >= 5e7)}


def new_signals(aladin, cfg, eligible=None):
    """P(up, 10D) above the threshold, confidence High, agreement 3/3. -> list of dicts, highest P(up) first."""
    h = str(cfg.get("signal_horizon", 10))
    out = []
    for sym, e in (aladin.get("stocks") or {}).items():
        c = (e.get("comb") or {}).get(h)
        if not c or eligible is not None and sym not in eligible:
            continue
        p, conf, agree = c
        if p > cfg["threshold"] and conf == "High" and agree == "3/3":
            out.append({"sym": sym, "signal_date": aladin["as_of"], "p_up": p, "conf": conf, "agree": agree})
    return sorted(out, key=lambda s: -s["p_up"])


# ------------------------------------------------------------------ portfolio mechanics

def empty_portfolio(cfg):
    return {"meta": {"caption": CAPTION, "cost_roundtrip": cfg["cost_roundtrip"], "notional": cfg["notional"], "hold_days": cfg["hold_days"], "max_open": cfg["max_open"],
                     "threshold": cfg["threshold"], "started_utc": now_utc().isoformat(timespec="seconds")},
            "pending": [], "open": [], "closed": [], "skipped": [], "stats": {}, "decile": {}, "equity_curve": []}


def _next_bar_index(bars, signal_date):
    """Index of the first session strictly after `signal_date`, or None if the data has not reached it yet."""
    for i, d in enumerate(bars["dates"]):
        if d > signal_date:
            return i
    return None


def add_signals(pf, signals, cfg):
    """Queue new signals unless the symbol is already open/pending or the signal was already taken."""
    have = {p["sym"] for p in pf["pending"]} | {p["sym"] for p in pf["open"]}
    seen = {(p["sym"], p["signal_date"]) for p in pf["pending"] + pf["open"] + pf["closed"] + pf["skipped"]}
    for s in signals:
        if s["sym"] in have or (s["sym"], s["signal_date"]) in seen:
            continue
        pf["pending"].append({**s, "queued_utc": now_utc().isoformat(timespec="seconds")})
        have.add(s["sym"])


def open_positions(pf, bars_by_sym, cfg, today=None):
    """Move pending signals to open positions at the next session's open, highest P(up) first, respecting the cap."""
    today = today or now_utc().date()
    still = []
    for p in sorted(pf["pending"], key=lambda x: -x["p_up"]):
        bars = bars_by_sym.get(p["sym"])
        i = _next_bar_index(bars, p["signal_date"]) if bars else None
        if i is None:
            age = (today - date.fromisoformat(p["signal_date"])).days
            if age > cfg["entry_wait_days"]:
                pf["skipped"].append({**p, "reason": f"no entry bar after {p['signal_date']} within {cfg['entry_wait_days']} days"})
            else:
                still.append(p)
            continue
        if len(pf["open"]) >= cfg["max_open"]:
            pf["skipped"].append({**p, "reason": f"portfolio full ({cfg['max_open']} open positions)"})
            continue
        px = float(bars["o"][i])
        if not (px > 0):
            pf["skipped"].append({**p, "reason": "entry bar has no valid open price"})
            continue
        due = np.busday_offset(bars["dates"][i], cfg["hold_days"], roll="forward")          # estimate (ignores exchange holidays); exits use real bars
        pf["open"].append({"id": f"{p['sym']}-{bars['dates'][i]}", "sym": p["sym"], "signal_date": p["signal_date"], "entry_date": bars["dates"][i], "entry_px": round(px, 2),
                           "p_up": p["p_up"], "conf": p["conf"], "agree": p["agree"], "notional": cfg["notional"], "due_date": str(due), "due_estimated": True})
    pf["pending"] = still


def close_due(pf, bars_by_sym, nifty, cfg):
    """Close every open position whose 10th trading day after entry has a bar. Exit = that day's close."""
    keep = []
    for pos in pf["open"]:
        bars = bars_by_sym.get(pos["sym"])
        if not bars or pos["entry_date"] not in bars["dates"]:
            keep.append(pos)
            continue
        i = bars["dates"].index(pos["entry_date"])
        j = i + cfg["hold_days"]
        if j >= len(bars["dates"]):
            keep.append(pos)
            continue
        exit_date, exit_px = bars["dates"][j], float(bars["c"][j])
        gross = exit_px / pos["entry_px"] - 1
        net = gross - cfg["cost_roundtrip"]
        nret = None
        if nifty and pos["entry_date"] in nifty["dates"] and exit_date in nifty["dates"]:
            a, b = nifty["dates"].index(pos["entry_date"]), nifty["dates"].index(exit_date)
            nret = float(nifty["c"][b] / nifty["o"][a] - 1)
        closed = {k: v for k, v in pos.items() if k not in ("due_estimated",)}
        closed.update({"due_date": exit_date, "exit_date": exit_date, "exit_px": round(exit_px, 2), "gross_ret": round(gross, 5), "net_ret": round(net, 5),
                       "nifty_ret": None if nret is None else round(nret, 5), "excess": None if nret is None else round(net - nret, 5), "pnl": round(net * pos["notional"], 2)})
        pf["closed"].append(closed)
    pf["open"] = keep


def decile_spread(history_dir, bars_by_sym, hold_days=10):
    """Top-decile minus bottom-decile average realised `hold_days`-day return over every saved prediction that has matured.
    Each file in `history_dir` is {'hmm':..., 's': {SYM: [F, S, T, p10, p5, p20]}} saved on that date's close."""
    rows = []
    for f in sorted(Path(history_dir).glob("*.json")):
        snap = load_json(f, {}).get("s", {})
        d = f.stem
        day = []
        for sym, v in snap.items():
            p10 = v[3] if len(v) > 3 else None
            bars = bars_by_sym.get(sym)
            if p10 is None or not bars or d not in bars["dates"]:
                continue
            i = bars["dates"].index(d)
            if i + hold_days >= len(bars["dates"]):
                continue
            day.append((p10, float(bars["c"][i + hold_days] / bars["c"][i] - 1)))
        if len(day) >= 50:
            rows.append((d, day))
    if not rows:
        return {"matured_days": 0, "note": "Saved predictions are scored once their 10 trading days have passed; none have yet. This fills in from the day ALADIN's nightly run first saved a snapshot."}
    top, bot, n = [], [], 0
    for d, day in rows:
        day.sort(key=lambda x: x[0])
        k = max(1, len(day) // 10)
        bot += [r for _, r in day[:k]]
        top += [r for _, r in day[-k:]]
        n += len(day)
    return {"matured_days": len(rows), "n": n, "top_ret": round(float(np.mean(top)), 5), "bottom_ret": round(float(np.mean(bot)), 5),
            "spread": round(float(np.mean(top) - np.mean(bot)), 5), "top_hit": round(float(np.mean(np.array(top) > 0)), 3), "bottom_hit": round(float(np.mean(np.array(bot) > 0)), 3)}


def stats(pf):
    c = pf["closed"]
    net = [x["net_ret"] for x in c]
    exc = [x["excess"] for x in c if x.get("excess") is not None]
    curve, cum = [], 0.0
    for x in sorted(c, key=lambda z: z["exit_date"]):
        cum += x["pnl"]
        curve.append([x["exit_date"], round(cum, 2)])
    return {"open": len(pf["open"]), "pending": len(pf["pending"]), "closed": len(c), "skipped": len(pf["skipped"]),
            "net_win_rate": round(float(np.mean(np.array(net) > 0)), 3) if net else None, "mean_net_ret": round(float(np.mean(net)), 5) if net else None,
            "mean_excess": round(float(np.mean(exc)), 5) if exc else None, "total_pnl": round(cum, 2)}, curve


def run(aladin, universe_stocks, pf=None, bars_loader=load_bars, history_dir=HISTORY, cfg=None, today=None):
    cfg = cfg or load_cfg()
    pf = pf or empty_portfolio(cfg)
    sigs = new_signals(aladin, cfg, eligible_symbols(universe_stocks))
    add_signals(pf, sigs, cfg)
    syms = {p["sym"] for p in pf["pending"] + pf["open"]}
    bars = {s: bars_loader(s) for s in syms}
    nifty = bars_loader("^NSEI")
    open_positions(pf, bars, cfg, today)
    close_due(pf, bars, nifty, cfg)
    pf["stats"], pf["equity_curve"] = stats(pf)
    # decile spread needs bars for every stock in the saved snapshots
    hist_syms = set()
    for f in Path(history_dir).glob("*.json"):
        hist_syms |= set(load_json(f, {}).get("s", {}))
    pf["decile"] = decile_spread(history_dir, {s: bars_loader(s) for s in hist_syms}, cfg["hold_days"])
    pf["meta"].update({"updated_utc": now_utc().isoformat(timespec="seconds"), "aladin_as_of": aladin.get("as_of"), "signals_today": len(sigs), "caption": CAPTION})
    return pf


def main():
    aladin = load_json(ALADIN, None)
    if not aladin:
        print("data/aladin/latest.json is missing: run scripts/aladin_model.py first")
        return 0
    uni = load_json(TERM / "universe.json", {}).get("stocks", [])
    pf = load_json(OUT, None)
    pf = run(aladin, uni, pf)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(pf, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    s = pf["stats"]
    print(f"paper trader: {pf['meta']['signals_today']} signal(s) today (as of {aladin.get('as_of')}); {s['open']} open, {s['pending']} waiting for an entry bar, {s['closed']} closed, "
          f"{s['skipped']} skipped; decile spread: {pf['decile'].get('spread', 'not yet measured')}. {CAPTION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
