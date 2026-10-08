"""ALADIN 2.0 Phase 0: measure the benchmark set on real data (no new model).
Benchmarks, all long-only (cash-equity delivery cannot be shorted), 10-trading-day hold, entry at the NEXT open after the signal date's close:
  buy_and_hold   every stock in the sample, equal weight
  random_walk    no-skill reference: expected gross return = the sample mean, P(up) = base rate
  naive_momentum long when 12-1 momentum > 0
  aladin_top10   ALADIN's existing out-of-sample 10-day score, top decile of the day (data/aladin_cache/oos_10.pkl)
Cost is a PLACEHOLDER flat round trip (COST_BPS); the real model arrives in Phase 1.
  python scripts/aladin2/phase0_audit.py --data <dir containing data/terminal>
"""
import argparse, glob, json, os
import numpy as np, pandas as pd

COST_BPS = 50.0
H = 10

def load(sym, tdir):
    fs = [f for f in (f"{tdir}/archive/{sym}.json", f"{tdir}/daily/{sym}.json") if os.path.exists(f)]
    rows = {}
    for f in fs:
        d = json.load(open(f)); d = d["d"] if isinstance(d, dict) else d
        for r in d: rows[r[0] if isinstance(r, list) else r["d"]] = r
    if not rows: return None
    k = sorted(rows); r0 = rows[k[0]]
    if isinstance(r0, list): df = pd.DataFrame([rows[x] for x in k]).iloc[:, :6]; df.columns = ["d", "o", "h", "l", "c", "v"]
    else: df = pd.DataFrame([rows[x] for x in k])[["d", "o", "h", "l", "c", "v"]]
    df["d"] = pd.to_datetime(df["d"]); return df.set_index("d")

def boot_ci(x, n=2000, block=5, seed=1):
    x = np.asarray(x); x = x[~np.isnan(x)]; rng = np.random.default_rng(seed); m = len(x); nb = -(-m // block); out = []
    for _ in range(n):
        s = rng.integers(0, m - block + 1, nb); out.append(np.concatenate([x[i:i + block] for i in s])[:m].mean())
    return float(np.mean(x)), float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--data", default="."); ap.add_argument("--out", default="data/aladin2/phase0_report.json"); a = ap.parse_args()
    tdir = f"{a.data}/data/terminal"; O = pd.read_pickle(f"{a.data}/data/aladin_cache/oos_10.pkl"); O["date"] = pd.to_datetime(O["date"])
    recs = []
    for sym, g in O.groupby("sym"):
        px = load(sym, tdir)
        if px is None or len(px) < 400: continue
        c, o = px["c"], px["o"]
        idx = px.index.searchsorted(g["date"].values)           # signal at close of date d -> enter next open, exit open H days later
        ok = (idx + 1 + H < len(px)) & (idx < len(px)) & (px.index[np.minimum(idx, len(px) - 1)] == g["date"].values)
        g = g[ok]; idx = idx[ok]
        ent = o.values[idx + 1]; ext = o.values[idx + 1 + H]
        mom = np.where(idx >= 252, c.values[np.maximum(idx - 21, 0)] / c.values[np.maximum(idx - 252, 0)] - 1, np.nan)
        adv = (c * px["v"]).rolling(20).mean().values[idx] / 1e7
        recs.append(pd.DataFrame({"date": g["date"].values, "sym": sym, "p": g["p"].values, "ret": ext / ent - 1, "mom": mom, "adv": adv}))
    R = pd.concat(recs); R = R[np.isfinite(R["ret"]) & (R["ret"].abs() < 1.0) & (R["adv"] >= 2.0)]      # liquidity filter: 20d avg traded value >= Rs 2 crore
    R["rank"] = R.groupby("date")["p"].rank(pct=True)
    c = COST_BPS / 1e4; D = {}
    def per_date(mask): return R[mask].groupby("date")["ret"].mean()
    allr = per_date(R["ret"].notna()); top = per_date(R["rank"] > 0.9); mo = per_date(R["mom"] > 0)
    nd = lambda s: s.reindex(allr.index)
    for name, s, trades in (("buy_and_hold_equal_weight", allr, None), ("naive_momentum_12_1", mo, None), ("aladin_top_decile", top, None)):
        gross = s.dropna(); net = gross - c * (0 if name.startswith("buy") else 1)
        d = {"dates": int(len(gross)), "gross_mean_pct": round(100 * gross.mean(), 3), "net_mean_pct": round(100 * net.mean(), 3),
             "net_vs_universe_pct": round(100 * (net - allr.reindex(net.index)).mean(), 3)}
        m, lo, hi = boot_ci((net - allr.reindex(net.index)).values); d["net_vs_universe_ci95_pct"] = [round(100 * lo, 3), round(100 * hi, 3)]
        m, lo, hi = boot_ci(net.values); d["net_mean_ci95_pct"] = [round(100 * lo, 3), round(100 * hi, 3)]
        D[name] = d
    y = (R["ret"] > 0).astype(int); base = y.mean()
    D["random_walk_reference"] = {"p_up": round(float(base), 4), "brier": round(float(((base - y) ** 2).mean()), 4)}
    D["aladin_probability"] = {"brier_raw_p": round(float(((R["p"] - y) ** 2).mean()), 4), "note": "raw uncalibrated rank-averaged score; calibration is nested in data/aladin/latest.json"}
    D["sample"] = {"rows": int(len(R)), "stocks": int(R["sym"].nunique()), "from": str(R["date"].min().date()), "to": str(R["date"].max().date()), "cost_bps_round_trip_placeholder": COST_BPS, "hold_days": H, "entry": "next open", "adv_filter_cr": 2.0}
    json.dump(D, open(a.out, "w"), indent=1); print(json.dumps(D, indent=1))
main()
