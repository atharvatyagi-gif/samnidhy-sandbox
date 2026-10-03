"""
NEXUS impact score: how exposed a stock is, through the dependencies its own filings disclose, to what its customers/suppliers are doing.

For focal stock i and each disclosed edge to a listed counterparty j on which i depends:
    I_i = clip( -100 * sum_j  w_ij * conf_ij * tanh(z_j / 2),  -100, +100 )          positive = adverse
  w_ij  the dependency share (summed over edges, capped at 1). An edge counts for i only when i is the supplier and the share is of i's REVENUE,
        or i is the customer and the share is of i's PURCHASES - i.e. only shares that measure i's own dependence.
  z_j   counterparty j's 5-day return after removing its NIFTY 50 beta (beta from the previous 250 days, so no look-ahead), divided by its own
        residual volatility, capped at +/-3.
Everything is "as of" the last close; it is computed nightly, never intraday. Sector-level edges (kind sector_io) never count.

It also writes the shock table (counterparties with |z| >= 1.5 and the linked stocks' moves that day) and a walk-forward test of whether the
signal predicts the focal stock's next-5-day residual return at all. If that test's t-statistic is below 2 the impact term is labelled
"prior, unvalidated". The weights are fixed; they are never tuned to pass the test.

    python scripts/graph_impact.py            -> data/aladin/impact.json, data/aladin/shocks.json
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
GRAPH = ROOT / "data" / "supply_graph.json"
CFG = ROOT / "data" / "config" / "aladin_config.json"
OUT = ROOT / "data" / "aladin" / "impact.json"
SHOCKS = ROOT / "data" / "aladin" / "shocks.json"
BETA_WIN, WINDOW, Z_CAP = 250, 5, 3.0


def load_cfg():
    base = {"min_conf": 0.5, "z_cap": Z_CAP, "impact_window_d": WINDOW, "concentration_min": 0.10}
    try:
        base.update(json.loads(CFG.read_text(encoding="utf-8")).get("nexus", {}))
    except (OSError, ValueError):
        pass
    return base


def residuals(rets, mret, win=BETA_WIN):
    """Daily returns minus beta * market, beta estimated on the PREVIOUS `win` days (shifted by one day)."""
    var = mret.rolling(win, min_periods=win // 2).var()
    out = {}
    for c in rets.columns:
        beta = (rets[c].rolling(win, min_periods=win // 2).cov(mret) / var).shift(1)
        out[c] = rets[c] - beta * mret
    return pd.DataFrame(out)


def zscores(resid, window=WINDOW, hist=BETA_WIN, cap=Z_CAP):
    """5-day cumulative residual / (residual volatility over the earlier `hist` days * sqrt(window)), capped."""
    cum = resid.rolling(window, min_periods=window).sum()
    sd = resid.shift(window).rolling(hist, min_periods=hist // 2).std()
    return (cum / (sd * math.sqrt(window))).clip(-cap, cap)


def exposures(graph, listed, min_conf=0.5):
    """-> {focal: [{cp, rel, w, conf, edge}]} of edges that measure the focal stock's OWN dependence on a listed counterparty."""
    raw = {}
    for e in graph.get("edges", []):
        if e.get("kind") not in ("disclosed", "resolved") or e.get("conf", 0) < min_conf or e.get("w") is None:
            continue
        for focal, cp, basis in ((e["s"], e["d"], "revenue"), (e["d"], e["s"], "purchases")):
            if e.get("wb") == basis and focal in listed and cp in listed and focal != cp:
                raw.setdefault(focal, []).append({"cp": cp, "rel": e["rel"], "w": float(e["w"]), "conf": float(e["conf"]), "edge": e["id"]})
    out = {}
    for focal, items in raw.items():
        tot = sum(i["w"] for i in items)
        scale = 1.0 / tot if tot > 1 else 1.0               # shares summed over edges are capped at 1
        out[focal] = [{**i, "w": round(i["w"] * scale, 4)} for i in items]
    return out


def impact_from(z_row, items):
    """-> (I in [-100, 100], rows [[cp, rel, w, z, conf]]) using only counterparties that have a z-score."""
    tot, rows = 0.0, []
    for it in items:
        z = z_row.get(it["cp"])
        if z is None or not np.isfinite(z):
            continue
        tot += it["w"] * it["conf"] * math.tanh(z / 2)
        rows.append([it["cp"], it["rel"], it["w"], round(float(z), 2), it["conf"]])
    if not rows:
        return None, []
    rows.sort(key=lambda r: -abs(r[2] * r[4] * math.tanh(r[3] / 2)))
    return round(float(np.clip(-100 * tot, -100, 100)), 1), rows


def newey_west_t(x, lags=5):
    import statsmodels.api as sm
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return None, len(x)
    fit = sm.OLS(x, np.ones(len(x))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(fit.tvalues[0]), len(x)


def validate(z, resid, exp, min_w=0.10, horizon=5, step=5, warm=BETA_WIN + 60):
    """Walk-forward: on every `step`-th day, the signal of each focal stock (what its counterparties' z-scores say, weighted by w*conf, positive = good news)
    is rank-correlated across stocks with the focal's own NEXT-`horizon`-day residual return. Reports mean rank correlation and its Newey-West t-statistic."""
    items = {f: [i for i in its if i["w"] >= min_w] for f, its in exp.items()}
    items = {f: its for f, its in items.items() if its and f in resid.columns}
    fwd = resid.rolling(horizon).sum().shift(-horizon)
    ics, dates = [], z.index
    for k in range(warm, len(dates) - horizon, step):
        d = dates[k]
        sig, tgt = [], []
        for f, its in items.items():
            vals = [(i["w"] * i["conf"], z.at[d, i["cp"]]) for i in its if i["cp"] in z.columns and np.isfinite(z.at[d, i["cp"]])]
            y = fwd.at[d, f]
            if vals and np.isfinite(y):
                sig.append(sum(w * zz for w, zz in vals))
                tgt.append(y)
        if len(sig) >= 5:
            r = pd.Series(sig).rank().corr(pd.Series(tgt).rank())
            if np.isfinite(r):
                ics.append(r)
    t, n = newey_west_t(ics, lags=max(1, horizon // step + 1))
    return {"horizon": horizon, "n_dates": n, "ic_mean": round(float(np.mean(ics)), 4) if ics else None, "t": round(t, 2) if t is not None else None,
            "focal_stocks": len(items), "min_w": min_w}


def build(graph, closes, nifty, cfg, now=None):
    """closes: DataFrame (date x symbol) of adjusted closes; nifty: Series. -> (impact doc, shocks doc)."""
    now = now or datetime.now(timezone.utc)
    listed = set(closes.columns)
    exp = exposures(graph, listed, cfg["min_conf"])
    need = sorted({f for f in exp} | {i["cp"] for its in exp.values() for i in its})
    rets = closes[need].pct_change()
    m = nifty.pct_change().reindex(rets.index)
    resid = residuals(rets, m)
    z = zscores(resid, cfg.get("impact_window_d", WINDOW), BETA_WIN, cfg.get("z_cap", Z_CAP))
    last = z.dropna(how="all").index[-1] if len(z.dropna(how="all")) else None
    items, shocks = {}, []
    if last is not None:
        zl = z.loc[last].to_dict()
        for f, its in exp.items():
            i, rows = impact_from(zl, its)
            if i is not None:
                items[f] = {"i": i, "n": len(rows), "top": rows[:5]}
        day = rets.loc[last]
        for f, its in exp.items():
            for it in its:
                zj = zl.get(it["cp"])
                if zj is not None and np.isfinite(zj) and abs(zj) >= 1.5:
                    shocks.append({"focal": f, "cp": it["cp"], "rel": it["rel"], "w": it["w"], "conf": it["conf"], "z": round(float(zj), 2), "edge": it["edge"],
                                   "cp_ret": round(float(day[it["cp"]]), 4) if np.isfinite(day[it["cp"]]) else None,
                                   "focal_ret": round(float(day[f]), 4) if np.isfinite(day[f]) else None})
        shocks.sort(key=lambda s: -(s["w"] * abs(s["z"])))
    val = validate(z, resid, exp) if exp else {"n_dates": 0, "t": None}
    ok = val.get("t") is not None and val["t"] >= 2
    asof = last.strftime("%Y-%m-%d") if last is not None else None
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    impact = {"generated_utc": stamp, "as_of": asof, "window_d": cfg.get("impact_window_d", WINDOW), "market": "NIFTY 50",
              "validation": {**val, "validated": bool(ok), "note": "Impact term: validated" if ok else "Impact term: prior, unvalidated"},
              "coverage": {"focal_stocks": len(items), "edges_used": sum(len(v) for v in exp.values())}, "stocks": items}
    return impact, {"generated_utc": stamp, "as_of": asof, "min_abs_z": 1.5, "shocks": shocks[:200]}


def main(argv=None):
    if not GRAPH.exists():
        print("supply_graph.json not built yet: no impact scores (every stock shows 'not measured')")
        return 0
    import aladin_model as am
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    cfg = load_cfg()
    nifty = am.load_prices("^NSEI", 300)
    if nifty is None:
        print("NIFTY 50 history missing: no impact scores")
        return 0
    listed = {n["id"] for n in graph.get("nodes", []) if n.get("k") == "co"}
    cols = {}
    for s in sorted(listed):
        df = am.load_prices(s)
        if df is not None:
            cols[s] = df["c"]
    closes = pd.DataFrame(cols).sort_index()
    impact, shocks = build(graph, closes, nifty["c"], cfg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(impact, separators=(",", ":")), encoding="utf-8")
    SHOCKS.write_text(json.dumps(shocks, separators=(",", ":")), encoding="utf-8")
    v = impact["validation"]
    print(f"impact as of {impact['as_of']}: {impact['coverage']['focal_stocks']} stocks scored, {len(shocks['shocks'])} shocks; "
          f"lead-lag test: IC {v.get('ic_mean')}, t {v.get('t')} over {v.get('n_dates')} dates -> {v['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
