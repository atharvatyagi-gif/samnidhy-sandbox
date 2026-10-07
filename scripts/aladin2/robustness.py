"""
ALADIN 2.0 robustness of the pooled reversal result (the survivorship and fill checks promised before building on it).

  python -m scripts.aladin2.robustness --workers 14      -> data/aladin2/robustness_reversal.json

Everything is on the unseen blocks (2012-07 .. 2026-10) of the NIFTY 500 liquid universe, excess = trade net of costs minus the stock's own drift over the same days.
Checks, per strategy of the pooled-significant reversal family:
  outliers    median, 5%-winsorised mean, mean without the 10 best trades (is a handful of rebounds the whole story?)
  liquidity   excess by liquidity tercile (spread/fill risk is worst in the least liquid names)
  years       excess by calendar year
  stress      excess after an EXTRA round-trip cost of 50 / 100 / 150 bps (panic-day spreads and bad fills)
  survivors   BREAK-EVEN missing-loser rate: the share of additional sell-off trades that would have to be missing from today's list, each ending at -50% / -70% / -100%,
              for the average excess to be zero. The true rate of such names is NOT measurable from free data; this says how big it would have to be.
"""
import argparse
import json
import pickle
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import evaluate as E
from . import run_phase2 as P

FAMILY = ["reversal5_vol_1.0", "reversal5_vol_1.5", "reversal5_vol_2.0", "bb_z_below_1.5", "bb_z_below_2.0", "bb_z_below_2.5", "rsi2_below_5"]


def load_universe(workers, cache, kind="n500", top=500):
    """kind 'n500': today's NIFTY 500 liquid members (survivor list with index look-ahead). kind 'pit': every liquid Main-board stock, restricted day by day to the top `top`
    by trailing traded value known the day before (point-in-time)."""
    cfg = C.load_cfg(); nifty = L.load_index(); cal = nifty.index[nifty.index >= pd.Timestamp(cfg["eval"]["data_start"])]
    if cache and Path(cache).exists():
        U, cal = pickle.load(open(cache, "rb"))
    else:
        rows = P.universe(cfg) if kind == "n500" else P.universe_pit(cfg); jobs = [(s, sec, d, cal.values, cfg) for s, sec, d in rows]
        with ProcessPoolExecutor(workers) as ex:
            U = {sd.sym: sd for sd in ex.map(P._build, jobs, chunksize=4) if sd is not None}
        if cache:
            pickle.dump((U, cal), open(cache, "wb"))
    E.attach_benchmark(U, cal, top=top if kind == "pit" else None)
    return U, cal, cfg


def check(g, U):
    x = g["excess"].values; n = len(x); m = float(x.mean()); srt = np.sort(x)
    lo, hi = np.percentile(x, [5, 95]); win = np.clip(x, lo, hi).mean()
    out = {"trades": n, "mean_bps": round(m * 1e4, 1), "median_bps": round(float(np.median(x)) * 1e4, 1), "winsorised5_mean_bps": round(float(win) * 1e4, 1),
           "mean_without_10_best_bps": round(float(srt[:-10].mean()) * 1e4, 1), "share_positive": round(float((x > 0).mean()), 3)}
    dec = g["sym"].map(lambda s: U[s].decile).values; ter = np.digitize(dec, [3.5, 6.5])           # 0 = most liquid third
    out["by_liquidity_third_bps"] = {k: round(float(x[ter == i].mean() * 1e4), 1) for i, k in enumerate(["most liquid", "middle", "least liquid"]) if (ter == i).any()}
    out["by_liquidity_third_ci"] = {k: E.month_bootstrap(g[ter == i], "excess")["ci95_bps"] for i, k in enumerate(["most liquid", "middle", "least liquid"]) if (ter == i).sum() > 200}
    yr = g["entry_date"].dt.year.values; out["by_year_bps"] = {int(y): round(float(x[yr == y].mean() * 1e4)) for y in np.unique(yr)}
    out["extra_cost_stress_bps"] = {str(c): E.month_bootstrap(g.assign(excess=g["excess"] - c / 1e4), "excess") for c in (50, 100, 150)}
    out["break_even_missing_loser_share"] = {f"loss_{int(l * 100)}pct": round(float(m / (m + l)), 4) for l in (0.5, 0.7, 1.0)}
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--cache", default="../U_pit.pkl"); ap.add_argument("--universe", default="pit"); ap.add_argument("--top", type=int, default=500); ap.add_argument("--out", default="data/aladin2/robustness_pooled.json"); a = ap.parse_args()
    t = time.time(); U, cal, cfg = load_universe(a.workers, a.cache, a.universe, a.top); print(f"universe {len(U)} stocks ({time.time() - t:.0f}s)", flush=True)
    res = {}
    for sid in FAMILY:
        g = E.baseline_rows(U, cal, cfg, sid); res[sid] = check(g, U); print(sid, res[sid]["mean_bps"], res[sid]["median_bps"], res[sid]["mean_without_10_best_bps"], flush=True)
    json.dump({"note": "survivor-only universe; see module docstring", "strategies": res}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
