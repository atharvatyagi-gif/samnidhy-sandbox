"""
ALADIN 2.0 honesty experiments (section 6.7): does the learner promote nothing on pure noise, and find real edges when they are planted?

  python -m scripts.aladin2.experiments --null 2000 --planted 200 --costs real --out data/aladin2/honesty_real.json
Universe of synthetic stocks -> the SAME walk_forward() the live engine uses. Reports:
  null     pairs evaluated, pairs promoted to Probation at least once (share), blocks in which ANY pair was promoted (share; BH at q controls this at <= q under the global null)
  planted  power = share of planted-edge series in which a strategy of the planted family was promoted; per-strength table
  vanish   for the series whose edge disappears halfway: blocks from the vanishing point until every promoted strategy of the family is Demoted/Retired
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import time

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import evaluate as E
from . import synthetic as S
from .strategies import registry as R

FAMILY = {"momentum": ("trend",), "reversion": ("reversion",), "regime": ("trend",), "vanishing": ("trend",)}


def zero_costs(cfg):
    c = json.loads(json.dumps(cfg)); k = c["costs"]
    for n in ("brokerage_bps", "stt_delivery_bps", "stt_intraday_bps", "exchange_bps", "sebi_bps", "stamp_bps", "stamp_intraday_bps"):
        k[n] = 0
    k["slippage_bps_by_adv_decile"] = [0] * 10
    return c


def _one(args):
    kind, seed, strength, frac, n, cfg = args
    strategies = [s for s in R.all_strategies() if s.family not in ("relative", "flow")]
    d = S.make(kind, n=n, seed=seed, strength=strength, frac=frac)
    px = L.clean_prices(d[["o", "h", "l", "c", "v"]]); F = L.price_features(px); cal = pd.bdate_range("2012-01-02", periods=n)
    sd = E.build_stock(f"{kind}{seed}", "syn", px, F, strategies, cal, 5, cfg)
    return sd, kind, seed, strength


def build_universe(specs, cfg, workers=4, n=6000):
    jobs = [(k, sd, st, fr, n, cfg) for k, sd, st, fr in specs]
    with ProcessPoolExecutor(workers) as ex:
        out = list(ex.map(_one, jobs, chunksize=4))
    U = {o[0].sym: o[0] for o in out}; meta = {o[0].sym: (o[1], o[2], o[3]) for o in out}
    return U, meta


def experiment_cfg(cfg, n=6000, first=2000, test_d=63):
    c = json.loads(json.dumps(cfg)); cal = pd.bdate_range("2012-01-02", periods=n)
    c["eval"]["first_test"] = str(cal[first].date()); c["eval"]["data_start"] = str(cal[0].date()); c["eval"]["test_d"] = test_d
    return c, cal


def run(null_n, planted_n, costs, workers, seed=0, n=6000, log=print, lookback=None, scale=1.0, extra_vanish=0):
    cfg0 = C.load_cfg(); cfg0 = zero_costs(cfg0) if costs == "zero" else cfg0
    if lookback:
        cfg0["eval"]["select_lookback_d"] = lookback
    cfg, cal = experiment_cfg(cfg0, n)
    rng = np.random.default_rng(seed); specs = [("noise", 10_000 + i, 0, 0.5) for i in range(null_n)]
    strengths = {k: [int(v * scale) for v in vs] for k, vs in {"momentum": [60, 120, 240], "reversion": [20, 40, 80], "regime": [120, 240], "vanishing": [120]}.items()}
    k = 0
    for kind, ss in strengths.items():
        per = planted_n // sum(len(v) for v in strengths.values())
        for st in ss:
            for j in range(per):
                specs.append((kind, 50_000 + k, st, 0.5)); k += 1
    for j in range(extra_vanish):
        specs.append(("vanishing", 70_000 + j, int(120 * scale), 0.5))
    t = time.time(); U, meta = build_universe(specs, cfg, workers, n); E.attach_benchmark(U, cal); log(f"built {len(U)} synthetic stocks in {time.time() - t:.0f}s")
    selectable = [s for s in R.all_strategies() if s.family not in ("relative", "flow")]
    t = time.time(); res = E.walk_forward(U, selectable, cal, cfg, seed=seed, log=log); log(f"walk-forward {time.time() - t:.0f}s")
    recs = res["records"]; folds = res["folds"]; ev = res["events"]
    nullsyms = {s for s, m in meta.items() if m[0] == "noise"}
    n_null_pairs = len(nullsyms) * len([s for s in selectable if not s.baseline])
    ever = {(s, sid) for (s, sid), r in recs.items() if any(h["to"] == "Probation" for h in r.history)}
    null_ever = [p for p in ever if p[0] in nullsyms]
    # blocks in which any NULL pair was newly eligible: derive from events with date per fold
    any_blocks = {}
    for e in ev:
        if e["sym"] in nullsyms and e["to"] == "Probation":
            any_blocks[e["date"]] = any_blocks.get(e["date"], 0) + 1
    nblocks = len(folds); blk = [any(sym in nullsyms for sym, _ in pairs) for pairs in res["eligible_by_fold"]]
    tot_elig = [len(p) for p in res["eligible_by_fold"]]; null_elig = [sum(1 for sym, _ in p if sym in nullsyms) for p in res["eligible_by_fold"]]
    out = {"costs": costs, "null": {"stocks": len(nullsyms), "pairs": n_null_pairs, "promoted_ever": len(null_ever), "share_pairs_promoted": round(len(null_ever) / max(n_null_pairs, 1), 5),
                                   "blocks": nblocks, "blocks_with_any_promotion": len(any_blocks), "share_blocks_with_any_promotion": round(len(any_blocks) / max(nblocks, 1), 3),
                                   "fdr_q": cfg["eval"]["fdr_q"],
                                   "p_any_null_pair_eligible_in_a_block": round(float(np.mean(blk)), 3), "mean_null_pairs_eligible_per_block": round(float(np.mean(null_elig)), 3),
                                   "false_discovery_proportion_among_eligible": round(float(sum(null_elig) / max(sum(tot_elig), 1)), 3) if sum(tot_elig) else None}}
    pl = {}
    for sym, (kind, _sd, st) in meta.items():
        if kind == "noise":
            continue
        fam = FAMILY[kind]; found = [(s, sid) for (s, sid) in ever if s == sym and R.by_id()[sid].family in fam]
        d = pl.setdefault(f"{kind}:{st}", {"series": 0, "found": 0}); d["series"] += 1; d["found"] += bool(found)
    for v in pl.values():
        v["power"] = round(v["found"] / v["series"], 3)
    out["planted"] = pl
    # vanishing: blocks after the vanishing point until the last trend strategy of that stock leaves Probation/Active
    van = []; vidx = int(0.5 * n)
    for sym, (kind, _sd, st) in meta.items():
        if kind != "vanishing":
            continue
        rs = [r for (s, sid), r in recs.items() if s == sym and R.by_id()[sid].family == "trend" and any(h["to"] == "Probation" for h in r.history)]
        if not rs:
            continue
        times = []
        for r in rs:
            before = [h for h in r.history if pd.Timestamp(h["date"]) <= cal[vidx]]
            after = [h for h in r.history if pd.Timestamp(h["date"]) > cal[vidx] and h["to"] in ("Demoted", "Retired")]
            if before and before[-1]["to"] in ("Probation", "Active"):
                times.append((pd.Timestamp(after[0]["date"]) - cal[vidx]).days if after else None)
        if times:
            van.append({"sym": sym, "strategies_live_at_vanish": len(times), "days_to_first_demotion": times})
    flat = [t for v in van for t in v["days_to_first_demotion"]]
    out["vanishing"] = {"series_with_live_strategy_at_vanish": len(van), "never_demoted_by_end": int(sum(t is None for t in flat)),
                        "median_days_to_demotion": float(np.median([t for t in flat if t is not None])) if any(t is not None for t in flat) else None,
                        "p90_days": float(np.percentile([t for t in flat if t is not None], 90)) if any(t is not None for t in flat) else None, "detail": van[:20]}
    out["folds"] = folds.to_dict("records")[:3] + folds.to_dict("records")[-2:]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--null", type=int, default=200); ap.add_argument("--planted", type=int, default=60)
    ap.add_argument("--costs", default="real", choices=["real", "zero"]); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--lookback", type=int, default=None); ap.add_argument("--extra_vanish", type=int, default=0); ap.add_argument("--scale", type=float, default=1.0); ap.add_argument("--out", default="data/aladin2/honesty.json")
    a = ap.parse_args(); r = run(a.null, a.planted, a.costs, a.workers, lookback=a.lookback, scale=a.scale, extra_vanish=a.extra_vanish)
    json.dump(r, open(a.out, "w"), indent=1, default=str); print(json.dumps({k: v for k, v in r.items() if k != "folds"}, indent=1, default=str)[:3500])
