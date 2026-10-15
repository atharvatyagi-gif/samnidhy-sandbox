"""Optional real-data baseline: drop one CSV per stock into blackbox/data/real/ (columns: date, open, high, low, close, volume; at least 400 rows,
common dates) plus optionally BTC.csv. When at least 50 stock files exist, run.py adds the scenario R00_real_baseline: the last `eval_days` days
evaluated, the rest as warm-up. The stand-in scores use the real forward returns exactly as on synthetic data. Labelled REAL DATA (stand-in scores).
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .synthetic import Panel

log = logging.getLogger(__name__)
REAL = Path(__file__).resolve().parent / "real"
SCENARIO = {"id": "R00_real_baseline", "severity": 0, "name": "Real data baseline (your CSVs)", "shocks": [], "news": None}


def available(min_files: int = 50) -> bool:
    return REAL.exists() and len([f for f in REAL.glob("*.csv") if f.stem.upper() != "BTC"]) >= min_files


def load(cfg: dict, seed: int) -> Panel:
    files = sorted(f for f in REAL.glob("*.csv") if f.stem.upper() != "BTC"); frames = {}
    for f in files:
        d = pd.read_csv(f, parse_dates=["date"]).set_index("date").sort_index()
        if len(d) >= 400:
            frames[f.stem] = d
    idx = sorted(set.intersection(*[set(d.index) for d in frames.values()]))[-(cfg["market"]["warmup_days"] + cfg["market"]["eval_days"]):]
    get = lambda k: np.column_stack([frames[s].loc[idx, k].values.astype(float) for s in frames])
    o, h, l, c, v = get("open"), get("high"), get("low"), get("close"), get("volume"); T, N = c.shape; rng = np.random.default_rng(seed)
    adv = np.nanmean((c * v)[-60:], axis=0) / 1e7; order = np.argsort(-adv); dec = np.empty(N, int); dec[order] = np.minimum(9, (np.arange(N) * 10) // N)
    fno = np.zeros(N, bool); fno[order[: int(N * 0.6)]] = True
    lr = np.diff(np.log(c), axis=0, prepend=np.log(c[:1])); zfwd, noise = {}, {}
    for hz in sorted({int(x["horizon"]) for x in cfg["oracle"].values()}):
        f = np.full((T, N), np.nan); f[: T - hz] = np.log(c[hz:] / c[: T - hz])
        z = (f - np.nanmean(f, 1, keepdims=True)) / (np.nanstd(f, 1, keepdims=True) + 1e-12); z[np.isnan(z)] = 0; zfwd[hz] = z; noise[hz] = rng.normal(0, 1, (T, N))
    index = 100 * np.exp(np.cumsum(np.log(np.nanmean(np.exp(lr), axis=1))))
    btc = REAL / "BTC.csv"
    if btc.exists():
        b = pd.read_csv(btc, parse_dates=["date"]).set_index("date").sort_index().reindex(idx).ffill()
        extras = {"btc": {k: b[x].values.astype(float) for k, x in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}}
    else:
        extras = {"btc": {"o": index.copy(), "h": index.copy(), "l": index.copy(), "c": index.copy()}}
    sd = np.std(np.diff(np.log(index))) * math.sqrt(252)
    vol_ratio = pd.Series(np.diff(np.log(index), prepend=np.nan)).rolling(20, min_periods=5).std().bfill().values * math.sqrt(252) / max(sd, 1e-9)
    return Panel(dates=pd.DatetimeIndex(idx), o=o, h=h, l=l, c=c, v=v, sector=np.zeros(N, int), sectors=["All"], beta=np.ones(N), adv_cr=adv, liq_decile=dec, fno=fno,
                 spread_mult=np.ones(T), haircut=np.zeros(T), vol_ratio=vol_ratio, index=index, extras=extras, zfwd=zfwd, noise=noise, news=np.zeros(T),
                 eval_start=T - cfg["market"]["eval_days"], drawn={"id": SCENARIO["id"], "shocks": []}, label="REAL DATA (stand-in scores)")
