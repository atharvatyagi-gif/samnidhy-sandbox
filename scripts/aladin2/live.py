"""
ALADIN 2.0 daily live run: today's forecasts into the ledger (the forward clock), resolution of matured forecasts, strategy states, signals, kill switches, a one-page summary.

  python -m scripts.aladin2.live --workers 8 [--dry]           (--dry: compute and print, write nothing)
Steps and timings are printed as a table (job summary). Nothing here places an order. Inputs are the price cache; every missing input is reported as such.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import forecast as FC
from . import kill as K
from . import ledger as LG
from . import run_phase3 as R3
from . import signals as SG

VERSION = "har-cqr-1"
ROOT = Path(__file__).resolve().parent.parent.parent
STATE = ROOT / "data" / "aladin2" / "state"
SHOW_P_UP = (1, 5)                           # horizons for which a calibrated probability is shown (Phase 3 gate); longer horizons show the range only
BAND_IDX = [2, 4, 1, 5, 0, 6]                # lo50, hi50, lo80, hi80, lo95, hi95 within the 7 quantiles


def timer():
    t = [time.time()]; rows = []
    def lap(name, n=None):
        now = time.time(); rows.append((name, round(now - t[0], 1), n)); t[0] = now
    return lap, rows


def strategy_states(state=None):
    f = Path(state or STATE) / "strategies.json"
    if not f.exists():
        return {}, None
    d = json.loads(f.read_text()); return {k: v["state"] for k, v in d["strategies"].items()}, d.get("as_of")


def resolve_matured(calendar, folder=None):
    """Write the `out` line for every (forecast batch, horizon) whose target date is now in the price data and has none yet."""
    done = {(r["d"], r["H"]) for r in LG.read_all(folder) if r["t"] == "out"}; n = 0; cache = {}
    def px_of(sym, date):
        if sym not in cache:
            p = L.load_prices(sym); cache[sym] = None if p is None else p["c"]
        s = cache[sym]; return None if s is None or pd.Timestamp(date) not in s.index else float(s.loc[pd.Timestamp(date)])
    for fc in [r for r in LG.read_all(folder) if r["t"] == "fc"]:
        for H in fc["H"]:
            if (fc["d"], H) in done:
                continue
            t = LG.target_date(fc["d"], H, calendar)
            if t is None:
                continue
            LG.append(LG.resolve(fc, H, px_of, t.date(), calendar), folder); n += 1
    return n


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=8); ap.add_argument("--dry", action="store_true"); ap.add_argument("--ledger", default=None); ap.add_argument("--limit", type=int, default=None); a = ap.parse_args()
    run(a.workers, a.dry, a.ledger, a.limit)


def run(workers=8, dry=False, ledger_dir=None, limit=None, state_dir=None):
    class a:                                                  # arguments object kept so the body below reads as before
        pass
    a.workers, a.dry, a.ledger, a.limit = workers, dry, ledger_dir, limit
    state = Path(state_dir) if state_dir else STATE
    cfg = C.load_cfg(); lap, rows = timer(); t0 = time.time()
    D, resid, _ = R3.build_panel(a.workers, a.limit); lap("panel (prices, features, 1,100+ stocks)", len(D))
    as_of = D["date"].max(); cal = L.load_index().index
    live = D[(D["date"] == as_of)].dropna(subset=R3.BASE_COLS).copy(); live = live[live["close"] > 0]
    lap("select today's rows (top 500 by trailing traded value)", len(live))
    H_LIST = FC.H_LIST; sig_all, bands_all, p_all = {}, {}, {}
    for H in H_LIST:
        b = R3.fit_bundle(D, as_of + pd.Timedelta(days=1), H, cfg)
        if b is None:
            print(f"horizon {H}: not enough history to fit, skipped"); continue
        sig, Q, A, p, pc = R3.predict_bundle(b, live)
        sig_all[H] = sig; bands_all[H] = np.array([[float(c) * np.exp(sg * A[i, k]) for k in BAND_IDX] for i, (c, sg) in enumerate(zip(live["close"].values, sig))]); p_all[H] = pc
        lap(f"fit + predict H={H}", len(live))
    Hs = [h for h in H_LIST if h in sig_all]; syms = live["sym"].tolist(); close = live["close"].values
    sigma = [[sig_all[h][i] for h in Hs] for i in range(len(syms))]; bands = [[bands_all[h][i] for h in Hs] for i in range(len(syms))]
    p_up = [[(float(p_all[h][i]) if h in SHOW_P_UP else None) for h in Hs] for i in range(len(syms))]
    ih = hashlib.sha1(json.dumps([str(as_of.date()), syms, [round(float(c), 3) for c in close], VERSION]).encode()).hexdigest()[:12]
    rec = LG.forecast_record(as_of.date(), pd.Timestamp.utcnow().isoformat(), VERSION, ih, Hs, syms, close, sigma, bands, p_up)
    status = "dry run" if a.dry else ("already in the ledger, not rewritten" if LG.has("fc", rec["d"], a.ledger) else LG.append(rec, a.ledger)); lap(f"ledger forecast batch ({status})", len(syms))
    n_out = 0 if a.dry else resolve_matured(cal, a.ledger); lap("resolve matured forecasts", n_out)
    # ---- strategy states, signals, kill switches
    states, st_asof = strategy_states(state); active = [s for s, v in states.items() if v == "Active"]; prob = [s for s, v in states.items() if v == "Probation"]
    stats = LG.stats(a.ledger, ece_fn=lambda p, y: FC.ece(p, y)[0]) if not a.dry else {"outcomes": {}}
    ov = {"ece": None, "n": 0, "coverage": None, "n_cov": 0}
    if stats["outcomes"]:
        h = max(stats["outcomes"], key=lambda k: stats["outcomes"][k]["n"]); o = stats["outcomes"][h]; ov = {"ece": o.get("ece"), "n": o.get("p_up_n", 0), "coverage": o["coverage"], "n_cov": o["n"]}
    eng_s, eng_why = K.check(ov, cfg)
    per_stock = {s: ("Suspended" if eng_s else ("Provisional" if prob else "Learning")) for s in syms}
    summ = pd.Series(per_stock).value_counts().to_dict()
    sig_rec = {"t": "sig", "d": str(as_of.date()), "states": summ, "active_strategies": active, "probation_strategies": prob, "strategy_states_as_of": st_asof, "signals": [], "engine_suspended": eng_s, "why": eng_why}
    if not a.dry and not LG.has("sig", sig_rec["d"], a.ledger):
        LG.append(sig_rec, a.ledger)
    lap("states, signals, kill switches", len(syms))
    summary = {"as_of": str(as_of.date()), "created_utc": rec["created"], "stocks_forecast": len(syms), "horizons": Hs, "model_version": VERSION, "product_state_counts": summ, "active_strategies": active, "probation_strategies": prob,
               "bullish_signals": 0, "live_stats": stats, "engine_suspended": eng_s, "kill_reasons": eng_why, "ledger_status": status, "disclaimer": cfg["disclaimer"],
               "timings_s": rows, "total_s": round(time.time() - t0)}
    if not a.dry:
        state.mkdir(parents=True, exist_ok=True); (state / "latest_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print("\nJOB SUMMARY\n" + "-" * 66)
    for n, s, k in rows:
        print(f"{n:<58}{s:>7.1f}s  {'' if k is None else k}")
    print("-" * 66 + f"\nas of {as_of.date()}; {len(syms)} stocks; states {summ}; active strategies {active or 'none'}; ledger {status}; total {summary['total_s']}s")
    return summary


if __name__ == "__main__":
    main()
