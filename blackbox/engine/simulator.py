"""The simulation engine: every strategy x every scenario x seeds (main grid), the one-parameter-at-a-time GAP sweeps, and the module checks.

One job = one (scenario, seed): the panel is generated once and every strategy (and every sweep variant) runs on it. Jobs run in parallel
(multiprocessing) and the results are cached in results/<config hash>/ so a rerun with the same config is instant.
Timing convention, enforced in every strategy and tested in tests/test_lookahead.py: decisions use data up to the close of day t, fills happen at t+1.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..data import loader as LD
from ..data import synthetic as SY
from ..scenarios import library as LIB
from ..strategies import REGISTRY
from ..strategies import benchmarks as B
from . import costs as CO
from . import metrics as ME
from . import modules as MO

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
KEEP = ("total_ret", "ann_ret", "sharpe", "max_dd", "cost_drag", "n_trades", "win_rate", "profit_factor", "ruin", "gross_ret")


def load_config(path: str | Path | None = None) -> dict:
    return yaml.safe_load(open(path or ROOT / "blackbox" / "config.yaml", encoding="utf-8"))


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]


def results_dir(cfg: dict, quick: bool) -> Path:
    d = ROOT / cfg["run"]["results_dir"] / f"{config_hash(cfg)}{'_quick' if quick else ''}"; d.mkdir(parents=True, exist_ok=True); return d


def run_strategy(name: str, panel, params: dict, cfg: dict):
    fn, kind, _ = REGISTRY[name]
    cm = CO.for_panel(cfg, panel, params.get("cost_mult", 1.0), params.get("slip_mult", 1.0))
    return fn(panel, params, cm, panel.eval_start), cm, kind


def make_panel(cfg: dict, sid: str, seed: int):
    return LD.load(cfg, seed) if sid == LD.SCENARIO["id"] else SY.generate(cfg, LIB.by_id(cfg, sid), seed)


def _scenario_ids(cfg: dict) -> list:
    return [s["id"] for s in LIB.scenarios(cfg)] + ([LD.SCENARIO["id"]] if LD.available() else [])


def _main_job(cfg: dict, sid: str, seed: int, do_modules: bool, keep_paths: bool) -> dict:
    panel = make_panel(cfg, sid, seed); cm0 = CO.for_panel(cfg, panel); floor = cfg["run"]["ruin_floor"]
    bh = {"stocks": ME.run_stats(B.buy_hold(panel, cm0, panel.eval_start), floor), "crypto": ME.run_stats(B.buy_hold(panel, cm0, panel.eval_start, "btc"), floor)}
    rows, paths = [], []
    if keep_paths:
        E = panel.eval_start
        paths.append({"scenario": sid, "seed": seed, "series": "market_index", "values": (panel.index[E - 1:] / panel.index[E - 1]).tolist()})
        paths.append({"scenario": sid, "seed": seed, "series": "btc", "values": (panel.extras["btc"]["c"][E - 1:] / panel.extras["btc"]["c"][E - 1]).tolist()})
    for kind, s in bh.items():
        rows.append({"scenario": sid, "seed": seed, "strategy": f"buy_hold_{kind}", **s})
    for name in REGISTRY:
        params = dict(cfg["strategies"][name]["defaults"]); res, cm, kind = run_strategy(name, panel, params, cfg); st = ME.run_stats(res, floor)
        st["beat_bh"] = float(st["total_ret"] > bh[kind]["total_ret"])
        rng = np.random.default_rng([int(cfg["run"]["seed_base"]), 7, seed, zlib.crc32(name.encode())])
        n_tr = len(res.trades); hold = np.mean([t["days"] for t in res.trades]) if res.trades else 5
        cap = np.mean([t["capital"] for t in res.trades]) if res.trades else 0.0; short = np.mean([t["side"] == "short" for t in res.trades]) if res.trades else 0.0
        crate = (sum(t["cost"] for t in res.trades) / sum(t["capital"] for t in res.trades)) if n_tr and sum(t["capital"] for t in res.trades) > 0 else None
        rnd = B.random_entry(panel, cm, panel.eval_start, n_tr, hold, cap, float(res.equity[0]), rng, "btc" if kind == "crypto" else None, short, crate)
        rs = ME.run_stats(rnd, floor); st["beat_random"] = float(st["total_ret"] > rs["total_ret"]) if n_tr else np.nan
        rows.append({"scenario": sid, "seed": seed, "strategy": name, **st, **{f"rand_{k}": rs[k] for k in ("total_ret", "sharpe", "max_dd", "gross_ret")}})
        if keep_paths:
            paths.append({"scenario": sid, "seed": seed, "series": name, "values": (res.equity / res.equity[0]).tolist()})
            pnl = [t["pnl_pct"] for t in res.trades]
            paths.append({"scenario": sid, "seed": seed, "series": f"{name}__trades", "values": pnl})
    mod = None
    if do_modules:
        mod = {"scenario": sid, "seed": seed, **MO.run_all(panel, cfg, np.random.default_rng([int(cfg["run"]["seed_base"]), 11, seed]))}
    return {"rows": rows, "paths": paths, "modules": mod}


def _sweep_job(cfg: dict, sid: str, seed: int) -> list:
    panel = make_panel(cfg, sid, 10_000 + seed); floor = cfg["run"]["ruin_floor"]; out = []
    for name in REGISTRY:
        base = dict(cfg["strategies"][name]["defaults"]); variants = [("default", None, None)]
        for prm, vals in (cfg["strategies"][name].get("sweep") or {}).items():
            variants += [(prm, prm, v) for v in vals if v != base.get(prm)]
        for label, prm, v in variants:
            params = dict(base)
            if prm:
                params[prm] = v
            res, _, _ = run_strategy(name, panel, params, cfg); st = ME.run_stats(res, floor)
            out.append({"scenario": sid, "seed": seed, "strategy": name, "param": label, "value": json.dumps(v if prm else None), **{k: st[k] for k in KEEP}})
    return out


def _workers(cfg: dict) -> int:
    w = int(cfg["run"].get("workers") or 0); return w if w > 0 else max(1, (os.cpu_count() or 2) - 1)


def run_main(cfg: dict, quick: bool = False, force: bool = False) -> Path:
    d = results_dir(cfg, quick); f = d / "main.parquet"
    if f.exists() and not force:
        log.info("main grid cached: %s", f); return d
    seeds = cfg["run"]["quick_seeds"] if quick else cfg["run"]["seeds"]; keep = cfg["run"]["keep_paths"]; mseeds = min(seeds, cfg["run"].get("module_seeds", 40))
    jobs = [(sid, k) for sid in _scenario_ids(cfg) for k in range(seeds)]; rows, paths, mods = [], [], []; t0 = time.time()
    with ProcessPoolExecutor(_workers(cfg)) as ex:
        futs = [ex.submit(_main_job, cfg, sid, k, k < mseeds, k < keep) for sid, k in jobs]
        for n, fu in enumerate(as_completed(futs), 1):
            r = fu.result(); rows += r["rows"]; paths += r["paths"]
            if r["modules"]:
                mods.append(r["modules"])
            if n % max(1, len(jobs) // 20) == 0:
                log.info("main grid: %d / %d jobs (%.0fs)", n, len(jobs), time.time() - t0)
    sev = {s["id"]: s["severity"] for s in cfg["scenarios"]}; sev[LD.SCENARIO["id"]] = 0
    df = pd.DataFrame(rows); df["severity"] = df["scenario"].map(sev); df.to_parquet(f, index=False)
    pd.DataFrame(paths).to_parquet(d / "paths.parquet", index=False); pd.DataFrame(mods).to_parquet(d / "modules.parquet", index=False)
    log.info("main grid done: %d rows in %.0fs -> %s", len(df), time.time() - t0, d)
    return d


def run_sweeps(cfg: dict, quick: bool = False, force: bool = False) -> Path:
    d = results_dir(cfg, quick); f = d / "sweeps.parquet"
    if f.exists() and not force:
        log.info("sweeps cached: %s", f); return d
    seeds = cfg["run"]["quick_gap_seeds"] if quick else cfg["run"]["gap_seeds"]; jobs = [(sid, k) for sid in _scenario_ids(cfg) for k in range(seeds)]
    rows = []; t0 = time.time()
    with ProcessPoolExecutor(_workers(cfg)) as ex:
        futs = [ex.submit(_sweep_job, cfg, sid, k) for sid, k in jobs]
        for n, fu in enumerate(as_completed(futs), 1):
            rows += fu.result()
            if n % max(1, len(jobs) // 10) == 0:
                log.info("sweeps: %d / %d jobs (%.0fs)", n, len(jobs), time.time() - t0)
    pd.DataFrame(rows).to_parquet(f, index=False); log.info("sweeps done: %d rows in %.0fs", len(rows), time.time() - t0)
    return d


def summarize(d: Path, cfg: dict) -> pd.DataFrame:
    """Per strategy x scenario: medians, percentile bands, bootstrap intervals, probabilities (metrics.aggregate)."""
    df = pd.read_parquet(d / "main.parquet"); out = []
    for (st, sc), g in df.groupby(["strategy", "scenario"]):
        agg = ME.aggregate(g.drop(columns=["strategy", "scenario"]).to_dict("records"))
        out.append({"strategy": st, "scenario": sc, "severity": int(g["severity"].iloc[0]), **agg})
    s = pd.DataFrame(out); s.to_parquet(d / "summary.parquet", index=False); return s
