"""
NEXUS impact score: how exposed a stock is, through the dependencies its own filings disclose, to what its listed customers and suppliers are doing.

For focal stock i and each disclosed edge to a listed counterparty j on which i depends (all as of the same close as the other fronts, nightly, never intraday):
    dR_j        counterparty j's beta-adjusted RESIDUAL return in %, summed over `impact_window_d` trading days (default 5). Beta is estimated on the 250 days
                that END BEFORE the window starts (so the window never leaks into its own beta), against NIFTY 50, on split-adjusted closes; capped at +/- dr_cap_pct (15).
    impact_pct  = sum_j dR_j * w_ij * conf_ij       w_ij is the share as a fraction (0-1); conf_ij the deterministic rubric (quote verified 0.5, counterparty named
                0.2, share stated 0.2, period recent 0.1). This is the "linked-move estimate (% pts)" users see.
    I           = clip(-impact_scale * impact_pct, -100, +100)         impact_scale k = 25: a linked estimate of -4 pts maps to I = +100. POSITIVE I = ADVERSE.
                I appears only inside the model: F_adj = clip(F - I, -100, 100). k is a prior; it is never tuned on the test period.
A share is attributed only to the node whose revenue or purchases it measures (`wb`): a supplier's revenue share is the SUPPLIER's dependence on the customer, a
customer's purchases share is the CUSTOMER's dependence on the supplier. The counterparty's exposure back to i is unknown unless separately disclosed. Sector-level edges never count.

It also writes the shock table (counterparties whose |dR| >= shock_min_pct and the linked stocks' moves that day) and a walk-forward test of whether the lagged impact_pct
predicts the focal stock's next-5-day residual return (rank correlation, Newey-West t; windows 1, 3 and 5 days are reported for information, only the configured window
decides). Fewer than 200 edge-days of data means "cannot validate: insufficient data", never a result. If t < 2 the impact term is "prior, unvalidated".

    python scripts/graph_impact.py            -> data/aladin/impact.json, data/aladin/shocks.json
"""
import json
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
BETA_WIN, WINDOW, DR_CAP, SCALE, SHOCK_MIN = 250, 5, 15.0, 25.0, 3.0
MIN_EDGE_DAYS = 200


def load_cfg():
    base = {"min_conf": 0.5, "dr_cap_pct": DR_CAP, "impact_scale": SCALE, "impact_window_d": WINDOW, "shock_min_pct": SHOCK_MIN, "concentration_min": 0.10}
    try:
        base.update(json.loads(CFG.read_text(encoding="utf-8")).get("nexus", {}))
    except (OSError, ValueError):
        pass
    return base


def window_dr(rets, mret, window=WINDOW, cap=DR_CAP, win=BETA_WIN):
    """dR_j(d) in % pts for every date d: the sum over the `window` days ending at d of (r_j - beta_j * r_market), with beta_j estimated on the `win` days that
    end at d - window (shifted by the window length), capped at +/- cap. Uses only data up to d."""
    var = mret.rolling(win, min_periods=win // 2).var()
    beta = rets.rolling(win, min_periods=win // 2).cov(mret).div(var, axis=0).shift(window)
    cum_r = rets.rolling(window, min_periods=window).sum()
    cum_m = mret.rolling(window, min_periods=window).sum()
    return ((cum_r - beta.mul(cum_m, axis=0)) * 100).clip(-cap, cap)


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


def impact_from(dr_row, items, scale=SCALE):
    """-> (impact_pct, I in [-100, 100], rows [[cp, rel, w, dR_pct, conf]]) using only counterparties that have a dR; (None, None, []) when none do."""
    tot, rows = 0.0, []
    for it in items:
        d = dr_row.get(it["cp"])
        if d is None or not np.isfinite(d):
            continue
        tot += d * it["w"] * it["conf"]
        rows.append([it["cp"], it["rel"], it["w"], round(float(d), 2), it["conf"]])
    if not rows:
        return None, None, []
    rows.sort(key=lambda r: -abs(r[2] * r[4] * r[3]))
    return round(float(tot), 3), round(float(np.clip(-scale * tot, -100, 100)), 1), rows


def impact_pct_panel(dr, exp, min_w=0.0):
    """date x focal DataFrame of impact_pct = sum_j dR_j * w * conf over the focal's edges with w >= min_w (NaN where no counterparty has a value)."""
    cols = {}
    for f, its in exp.items():
        its = [i for i in its if i["w"] >= min_w and i["cp"] in dr.columns]
        if its:
            cols[f] = pd.concat([dr[i["cp"]] * (i["w"] * i["conf"]) for i in its], axis=1).sum(axis=1, min_count=1)
    return pd.DataFrame(cols)


def newey_west_t(x, lags=5):
    import statsmodels.api as sm
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return None, len(x)
    fit = sm.OLS(x, np.ones(len(x))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(fit.tvalues[0]), len(x)


def validate(rets, mret, exp, window=WINDOW, cap=DR_CAP, min_w=0.10, horizon=5, step=5, warm=BETA_WIN + 60, windows=(1, 3, 5)):
    """Walk-forward: on every `step`-th day, the lagged impact_pct of each focal stock (edges with w >= min_w) is rank-correlated across stocks with the focal's own
    NEXT-`horizon`-day residual return (beta known at the signal date). Reports the mean rank correlation and its Newey-West t-statistic for the configured window,
    and for the other windows for information. Fewer than MIN_EDGE_DAYS (edge, day) observations -> cannot validate."""
    items = {f: [i for i in its if i["w"] >= min_w and i["cp"] in rets.columns] for f, its in exp.items() if f in rets.columns}
    items = {f: its for f, its in items.items() if its}
    base = {"horizon": horizon, "focal_stocks": len(items), "min_w": min_w, "min_edge_days": MIN_EDGE_DAYS, "window_d": window}
    if not items:
        return {**base, "edge_days": 0, "n_dates": 0, "ic_mean": None, "t": None}
    var = mret.rolling(BETA_WIN, min_periods=BETA_WIN // 2).var()
    beta_now = rets.rolling(BETA_WIN, min_periods=BETA_WIN // 2).cov(mret).div(var, axis=0)                     # known at the signal date: no shift needed
    fwd = (rets.rolling(horizon).sum().shift(-horizon) - beta_now.mul(mret.rolling(horizon).sum().shift(-horizon), axis=0)) * 100

    def run(win):
        dr = window_dr(rets, mret, win, cap)
        panel = impact_pct_panel(dr, items, min_w)
        edge_days = 0
        for f, its in items.items():
            ok = fwd[f].notna()
            for i in its:
                edge_days += int((dr[i["cp"]].notna() & ok).iloc[warm:].sum())
        ics = []
        for k in range(warm, len(panel.index) - horizon, step):
            d = panel.index[k]
            row, y = panel.loc[d], fwd.loc[d]
            both = [f for f in panel.columns if np.isfinite(row.get(f, np.nan)) and np.isfinite(y.get(f, np.nan))]
            if len(both) >= 5:
                r = pd.Series([row[f] for f in both]).rank().corr(pd.Series([y[f] for f in both]).rank())
                if np.isfinite(r):
                    ics.append(r)
        t, n = newey_west_t(ics, lags=max(1, horizon // step + 1))
        return {"edge_days": edge_days, "n_dates": n, "ic_mean": round(float(np.mean(ics)), 4) if ics else None, "t": round(t, 2) if t is not None else None}

    main_res = run(window)
    out = {**base, **main_res}
    if main_res["edge_days"] >= MIN_EDGE_DAYS:
        out["windows"] = {str(w): (main_res if w == window else run(w)) for w in windows}
    return out


def build(graph, closes, nifty, cfg, now=None):
    """closes: DataFrame (date x symbol) of adjusted closes; nifty: Series. -> (impact doc, shocks doc)."""
    now = now or datetime.now(timezone.utc)
    window, cap, scale = cfg.get("impact_window_d", WINDOW), cfg.get("dr_cap_pct", DR_CAP), cfg.get("impact_scale", SCALE)
    closes = closes.loc[closes.index.isin(nifty.index)]            # the index calendar rules: a stock bar on a day the index did not trade (a holiday print) would blank every window containing it
    listed = set(closes.columns)
    exp = exposures(graph, listed, cfg["min_conf"])
    need = sorted({f for f in exp} | {i["cp"] for its in exp.values() for i in its})
    rets = closes[need].pct_change()
    m = nifty.pct_change().reindex(rets.index)
    dr = window_dr(rets, m, window, cap) if need else pd.DataFrame()
    valid = dr.dropna(how="all") if len(dr.columns) else dr
    last = valid.index[-1] if len(valid) else None
    items, shocks = {}, []
    if last is not None:
        dl = dr.loc[last].to_dict()
        for f, its in exp.items():
            ip, i, rows = impact_from(dl, its, scale)
            if i is not None:
                items[f] = {"i": i, "ip": ip, "n": len(rows), "top": rows[:5]}
        day = rets.loc[last]
        smin = cfg.get("shock_min_pct", SHOCK_MIN)
        for f, its in exp.items():
            for it in its:
                dj = dl.get(it["cp"])
                if dj is not None and np.isfinite(dj) and abs(dj) >= smin:
                    shocks.append({"focal": f, "cp": it["cp"], "rel": it["rel"], "w": it["w"], "conf": it["conf"], "dr": round(float(dj), 2), "edge": it["edge"],
                                   "cp_ret": round(float(day[it["cp"]]), 4) if np.isfinite(day[it["cp"]]) else None,
                                   "focal_ret": round(float(day[f]), 4) if np.isfinite(day[f]) else None})
        shocks.sort(key=lambda s: -(s["w"] * abs(s["dr"])))
    val = validate(rets, m, exp, window, cap) if exp else {"n_dates": 0, "t": None, "edge_days": 0, "min_edge_days": MIN_EDGE_DAYS}
    ok = val.get("t") is not None and val["edge_days"] >= MIN_EDGE_DAYS and val["t"] >= 2
    if val["edge_days"] < MIN_EDGE_DAYS:
        note = f"Impact term: cannot validate: insufficient data ({val['edge_days']} edge-days, {MIN_EDGE_DAYS} needed)"
    else:
        note = "Impact term: validated" if ok else "Impact term: prior, unvalidated"
    asof = last.strftime("%Y-%m-%d") if last is not None else None
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    impact = {"generated_utc": stamp, "as_of": asof, "window_d": window, "market": "NIFTY 50", "scale": scale, "dr_cap_pct": cap,
              "validation": {**val, "validated": bool(ok), "note": note},
              "coverage": {"focal_stocks": len(items), "edges_used": sum(len(v) for v in exp.values())}, "stocks": items}
    return impact, {"generated_utc": stamp, "as_of": asof, "min_abs_dr_pct": cfg.get("shock_min_pct", SHOCK_MIN), "shocks": shocks[:200]}


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
          f"lead-lag test: IC {v.get('ic_mean')}, t {v.get('t')} over {v.get('n_dates')} dates, {v.get('edge_days')} edge-days -> {v['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
