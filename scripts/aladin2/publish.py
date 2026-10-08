"""
ALADIN 2.0 site shards (section 11.6). Called by scripts/build_site.py (never allowed to break the site build) and runnable alone:

  python -m scripts.aladin2.publish --out site/aladin2
Writes, from the ledger, the strategy states, the journal and the cached prices:
  index.json        one short row per stock: state, signal key, 80% range at 5 and 20 days (% from the close), sector (about 100 bytes a stock), plus labels, counts and the disclaimer
  stock/<SYM>.json  the brief for one stock: forecast bands per horizon, product state and why, signal, strategy cards, 150 closes for the chart, plan (only when a stock is Validated), risk-calculator inputs
  scoreboard.json   live statistics recomputed from the raw ledger, state shares, learning curve points, and the OUT-OF-SAMPLE HISTORICAL SIMULATION results kept apart and labelled as such
  journal.json      the latest 500 learning events
  market_map.json   one row per stock: sector, area (traded value: market cap is not available free), 80% range width, state
Every number is read from a file the engine wrote; a missing input is "not measured" with its reason. Wording comes from the labels dictionary in data/config/aladin2.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import forecast as FC
from . import ledger as LG
from . import signals as SG

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "aladin2"
SERIES_N = 150


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True); s = json.dumps(obj, separators=(",", ":"), default=str); path.write_text(s, encoding="utf-8"); return len(s.encode())


def _latest(kind, folder):
    xs = [r for r in LG.read_all(folder) if r["t"] == kind]; return xs[-1] if xs else None


def _strategy_cards(state):
    import re
    from . import journal as J
    out = []
    for sid, v in (state.get("strategies") or {}).items():
        ev = (v.get("last_events") or [])[-1:] ; why = J.text_for({**ev[0], "sym": "*POOL*"}) if ev else "no events yet"
        out.append({"id": sid, "name": J.name(sid), "state": v["state"], "since": str(v.get("since", ""))[:10], "last_change": why})
    order = {"Active": 0, "Probation": 1, "Demoted": 2, "Retired": 3, "Candidate": 4, "Suspended": 5}
    return sorted(out, key=lambda c: (order.get(c["state"], 9), c["id"]))


def build(out, ledger_dir=None, state_dir=None, journal_dir=None, term=None, mode=None, weekly_path=None, paper_dir=None):
    out = Path(out); cfg = C.load_cfg()
    if mode:
        cfg["signal_labels"] = mode
    ledger_dir = ledger_dir or LG.LEDGER; state_dir = Path(state_dir or DATA / "state"); journal_dir = Path(journal_dir or DATA)
    fc = _latest("fc", ledger_dir)
    if fc is None:
        return {"built": False, "why": "no forecast batch in the ledger yet"}
    summ = json.loads((state_dir / "latest_summary.json").read_text()) if (state_dir / "latest_summary.json").exists() else {}
    state = json.loads((state_dir / "strategies.json").read_text()) if (state_dir / "strategies.json").exists() else {}
    p3 = json.loads((DATA / "phase3_report.json").read_text()) if (DATA / "phase3_report.json").exists() else {}
    uni = {}
    try:
        for s in json.loads((L.TERM / "universe.json").read_text())["stocks"]:
            uni[s["s"]] = s
    except Exception:                                                      # noqa: BLE001  names and sectors are nice to have, not required
        pass
    wkf = Path(weekly_path) if weekly_path else DATA / "weekly.json"; wk = json.loads(wkf.read_text(encoding="utf-8")) if wkf.exists() else None; wsig = {}
    if wk and wk.get("built"):
        for side, key in (("bull", "bull"), ("bear", "bear")):
            for r_ in wk["book"][side]:
                wsig[r_["sym"]] = r_
    cards = _strategy_cards(state); active = [c for c in cards if c["state"] == "Active"]; Hs = fc["H"]; sizes = {}
    labels = cfg["labels"][cfg["signal_labels"]]; base = {int(h): v["p_up"]["base_rate"] for h, v in (p3.get("horizons") or {}).items()}
    rows = []; mm = []
    for i, sym in enumerate(fc["syms"]):
        u = uni.get(sym, {}); close = fc["close"][i]; b = fc["bands"][i]; j5 = Hs.index(5) if 5 in Hs else 0; j20 = Hs.index(20) if 20 in Hs else len(Hs) - 1
        lo5, hi5 = (b[j5][2] / close - 1) * 100, (b[j5][3] / close - 1) * 100; lo20, hi20 = (b[j20][2] / close - 1) * 100, (b[j20][3] / close - 1) * 100
        stt = "Learning" if not active else "Provisional"; ws = wsig.get(sym)
        if ws:
            stt = "Provisional"
        sector = u.get("ind") or "Unknown"
        rows.append([sym, stt[0], ("b" if ws and ws["signal"] == "bull" else "s" if ws else "n"), round(lo5, 1), round(hi5, 1), round(lo20, 1), round(hi20, 1), sector]); mm.append([sym, sector, round((u.get("avgv20") or 0) * (u.get("c") or close) / 1e7, 1), round(hi20 - lo20, 1), stt[0]])
        try:
            px = L.load_prices(sym, term); px = px.tail(SERIES_N) if px is not None else None
        except Exception:                                                  # noqa: BLE001
            px = None
        wr = ((wk or {}).get("book") or {}).get("ranks", {}).get(sym)
        shard = {"sym": sym, "name": u.get("n") or sym, "weekly_p": ({"rank": wr[0], "closes_higher": wr[1], "beats_market": wr[2]} if wr else None), "sector": sector, "as_of": fc["d"], "created": fc["created"], "close": close, "state": stt, "state_why": ["no strategy has passed the evaluation protocol for this stock yet"] if stt == "Learning" else ["Probation only"],
                 "signal": ws["signal"] if ws else "none", "signal_why": (ws["state_why"] if ws else f"state is {stt}"), "weekly": ws, "horizons": Hs, "sigma": fc["sigma"][i],
                 "bands": [{"H": h, "lo50": b[k][0], "hi50": b[k][1], "lo80": b[k][2], "hi80": b[k][3], "lo95": b[k][4], "hi95": b[k][5], "p_up": fc["p_up"][i][k], "base_rate": base.get(h)} for k, h in enumerate(Hs)],
                 "strategies": cards, "plan": None, "plan_why": "A trade plan is shown only for Validated stocks. None is Validated yet: the live record is too short.",
                 "series": {"d": [str(x.date()) for x in px.index] if px is not None else [], "c": [round(float(x), 2) for x in px["c"]] if px is not None else []}, "disclaimer": cfg["disclaimer"]}
        if ws and ws["signal"] == "bull":                    # the weekly plan, in the shape the brief's risk panel reads (sizing is done in the browser with the visitor's own capital)
            shard["plan"] = {"entry": ws["close"], "zone": ws["entry_zone"], "stop": ws["invalidation"], "atr": ws["atr"], "adv_shares": ws["adv_shares"], "mu": (ws["expected_net_bps"] or 0) / 1e4, "sd": cfg["weekly"]["weekly_sd"], "p_stop": None, "horizon": 5}
        elif ws:
            shard["plan_why"] = ws["what_to_do"]
        sizes[sym] = _w(out / "stock" / f"{sym}.json", shard)
    for sym, ws in wsig.items():                              # signal stocks outside the 500 forecast stocks: a shard without ranges, so the brief can still show the signal
        if sym in fc["syms"]:
            continue
        u = uni.get(sym, {}); px = L.load_prices(sym, term); px = px.tail(SERIES_N) if px is not None else None
        shard = {"sym": sym, "name": ws["name"], "sector": ws["sector"], "as_of": wk["book"]["as_of"], "created": wk["book"]["as_of"], "close": ws["close"], "state": "Provisional", "state_why": [ws["state_why"]], "signal": ws["signal"], "signal_why": ws["state_why"], "weekly": ws, "horizons": [], "sigma": [], "bands": [],
                 "strategies": cards, "plan": None, "plan_why": ws["what_to_do"], "series": {"d": [str(x.date()) for x in px.index] if px is not None else [], "c": [round(float(x), 2) for x in px["c"]] if px is not None else []}, "disclaimer": cfg["disclaimer"]}
        if ws["signal"] == "bull":
            shard["plan"] = {"entry": ws["close"], "zone": ws["entry_zone"], "stop": ws["invalidation"], "atr": ws["atr"], "adv_shares": ws["adv_shares"], "mu": (ws["expected_net_bps"] or 0) / 1e4, "sd": cfg["weekly"]["weekly_sd"], "p_stop": None, "horizon": 5}
        sizes[sym] = _w(out / "stock" / f"{sym}.json", shard)
    states = {}
    for r in rows:
        states[r[1]] = states.get(r[1], 0) + 1
    live = (summ.get("live_stats") or {}).get("outcomes", {}); hist = {}
    for h, v in (p3.get("horizons") or {}).items():
        hist[h] = {"coverage": v["coverage"], "coverage_80_by_year": v.get("coverage_80_by_year"), "width80_sigma": v.get("mean_width_in_sigma", {}).get("80"), "rows": v["rows"], "ece_p_up": v["p_up"]["ece_after_isotonic"], "auc_p_up": v["p_up"]["auc"], "reliability": v["p_up"]["reliability"]}
    score = {"as_of": fc["d"], "forecast_batches": (summ.get("live_stats") or {}).get("forecast_batches", 1), "live": live, "live_note": "Live forecasts only: made before the day they are about. Statistics appear once forecasts have resolved.",
             "state_shares": {k: round(v / max(len(rows), 1), 3) for k, v in states.items()}, "engine_suspended": summ.get("engine_suspended", False), "kill_reasons": summ.get("kill_reasons", []),
             "historical_simulation": {"label": "HISTORICAL SIMULATION (out of sample, 2012-2026, survivors to today only): not live results", "horizons": hist,
                                       "policy": "the pooled trend-following rules passed the evaluation in many past years, faded in 2025 and are all Retired today"},
             "strategies": cards, "labels": labels, "disclaimer": cfg["disclaimer"]}
    cf = state_dir / "learning_curve.jsonl"; curve = [json.loads(x) for x in cf.read_text().splitlines() if x.strip()] if cf.exists() else []
    score["learning_curve"] = curve; score["barrier_check_20d"] = {k: v for k, v in (p3.get("barrier_check_20d") or {}).items() if k in ("touch_up_1sigma", "touch_down_1sigma", "paths_80pct_band_coverage_20d")}
    index = {"as_of": fc["d"], "created": fc["created"], "mode": cfg["signal_labels"], "labels": labels, "counts": states, "horizons": Hs, "cols": ["sym", "state", "signal", "lo80_5d", "hi80_5d", "lo80_20d", "hi80_20d", "sector"], "rows": rows, "disclaimer": cfg["disclaimer"]}
    for name, src in (("paper_live.json", Path(paper_dir or DATA / "paper") / "live.json"), ("paper_backtest.json", Path(paper_dir or DATA / "paper") / "backtest.json")):          # the paper account: the live front test and the historical simulation
        if src.exists():
            (out / name).write_bytes(src.read_bytes()); sizes[name] = src.stat().st_size
    index["weekly"] = {"as_of": wk["book"]["as_of"], "counts": wk["book"]["counts"]} if wk and wk.get("built") else None
    if wk and wk.get("built"):
        wk["labels"] = labels; wk["mode"] = cfg["signal_labels"]; sizes["weekly.json"] = _w(out / "weekly.json", wk); score["weekly_live_record"] = wk["live_record"]
    sizes["index.json"] = _w(out / "index.json", index); sizes["scoreboard.json"] = _w(out / "scoreboard.json", score)
    sizes["market_map.json"] = _w(out / "market_map.json", {"as_of": fc["d"], "cols": ["sym", "sector", "traded_value_cr", "range80_20d_pct", "state"], "area": "20-day average traded value, Rs crore (market capitalisation is not available from free data)", "rows": mm, "disclaimer": cfg["disclaimer"]})
    try:                                                    # market-wide stress ribbon for the chart (filtered probabilities only: a value never changes when later data arrives)
        from . import meta as MT
        nf = L.load_index(term=term)
        if nf is not None and len(nf) > 800:
            pr = MT.stress_probability(nf).tail(750); sizes["regime.json"] = _w(out / "regime.json", {"d": [str(x.date()) for x in pr.index], "p": [round(float(v), 2) for v in pr.values], "note": "filtered probability of the high-volatility regime, NIFTY 50"})
    except Exception:                                       # noqa: BLE001  the ribbon is optional
        pass
    mf = ROOT / "data" / "config" / "aladin2_method.json"
    if mf.exists():
        sizes["method.json"] = _w(out / "method.json", json.loads(mf.read_text(encoding="utf-8")))
    jf = journal_dir / "journal.json"
    sizes["journal.json"] = _w(out / "journal.json", json.loads(jf.read_text()) if jf.exists() else {"events": []})
    total = sum(sizes.values()); biggest = max((v for k, v in sizes.items() if k not in ("index.json", "scoreboard.json", "journal.json", "market_map.json", "weekly.json", "paper_live.json", "paper_backtest.json", "method.json", "regime.json")), default=0)
    return {"built": True, "as_of": fc["d"], "stocks": len(rows), "total_bytes": total, "index_bytes": sizes["index.json"], "biggest_stock_shard_bytes": biggest, "states": states}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="site/aladin2"); ap.add_argument("--ledger", default=None); ap.add_argument("--state", default=None); a = ap.parse_args()
    r = build(a.out, a.ledger, a.state); print(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
