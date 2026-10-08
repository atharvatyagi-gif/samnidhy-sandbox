"""
ALADIN 2.0 discovery (section 5.3): new strategies from a FIXED, TYPED grammar. No code is ever generated or executed: a candidate is DATA (a spec dict) and one fixed interpreter turns it into a 0/1 signal.

Grammar
  rule      := condition ( AND condition ){0,2}  [ AND regime ]  + holding
  condition := primitive  (<|>)  threshold          primitives and their threshold grids are listed in PRIM / GRID below
  regime    := "calm"  (filtered stress probability < 0.5)                         optional, needs the stress series
  holding   := fixed 5 | fixed 10 | fixed 20 | flip (until the signal turns off) | ATR trail
Search      constrained mutation (move a threshold one grid step, swap a primitive or operator, add or drop a condition, change the holding rule) and crossover (conditions from two parents,
            at most 3), seeded from a few textbook ideas plus random restarts, ranked by a complexity penalty: fitness = t-statistic - lam * (conditions + regime).
Honesty     every distinct rule has a stable hash. A hash tested before on data that has not changed much is never re-tested (data/aladin2/state/discovery_tested.json), and the TOTAL number of
            distinct rules ever tested sets the bar: a candidate must have p <= fdr_q / (number tested so far) on the training window (Bonferroni over the whole search history, deliberately harsh)
            AND a positive mean with p < 0.2 on a holdout window the search never saw. Most candidates fail. That is expected and is journalled.
"""
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import evaluate as E
from . import pooled as PL
from .strategies.base import Strategy

ROOT = Path(__file__).resolve().parent.parent.parent
STATE = ROOT / "data" / "aladin2" / "state"

PRIM = {   # name -> function of ctx.F (causal features)
    "z5": lambda F: F["r5"] / (F["vol20"] * np.sqrt(5)), "z20": lambda F: F["r20"] / (F["vol20"] * np.sqrt(20)), "z60": lambda F: F["r60"] / (F["vol20"] * np.sqrt(60)),
    "rsi2": lambda F: F["rsi2"], "rsi14": lambda F: F["rsi14"], "bb_z": lambda F: F["bb_z"], "d_sma20": lambda F: F["d_sma20"], "d_sma50": lambda F: F["d_sma50"], "d_sma200": lambda F: F["d_sma200"],
    "hi52": lambda F: F["hi52"], "lo52": lambda F: F["lo52"], "vz20": lambda F: F["vz20"], "vol_ratio": lambda F: F["vol_ratio"], "atr_pct": lambda F: F["atr_pct"], "gap": lambda F: F["gap"], "mom12_1": lambda F: F["mom12_1"]}
GRID = {"z5": [-2, -1, -0.5, 0, 0.5, 1, 2], "z20": [-2, -1, -0.5, 0, 0.5, 1, 2], "z60": [-2, -1, -0.5, 0, 0.5, 1, 2], "rsi2": [5, 10, 20, 50, 80, 90], "rsi14": [20, 30, 40, 50, 60, 70, 80],
        "bb_z": [-2, -1, 0, 1, 2], "d_sma20": [-0.1, -0.05, 0, 0.05, 0.1], "d_sma50": [-0.1, -0.05, 0, 0.05, 0.1], "d_sma200": [-0.2, -0.1, 0, 0.1, 0.2], "hi52": [-0.3, -0.2, -0.1, -0.05, -0.02],
        "lo52": [0.05, 0.1, 0.25, 0.5, 1.0], "vz20": [-0.5, 0, 0.5, 1.0], "vol_ratio": [0.6, 0.8, 1.0, 1.2, 1.5], "atr_pct": [0.01, 0.02, 0.03, 0.05], "gap": [-0.03, -0.01, 0.01, 0.03], "mom12_1": [-0.2, 0.0, 0.2, 0.5]}
HOLD = [{"type": "fixed", "n": 5}, {"type": "fixed", "n": 10}, {"type": "fixed", "n": 20}, {"type": "flip", "max_n": 250}, {"type": "atr_trail", "mult": 3.0, "max_n": 60}]
MAX_COND = 3
STRESS_BPS = 100.0     # survivorship stress: a candidate must still earn something after losing this much per trade (the break-even missing-loser share found in Phase 2b was 1.5-3% of trades at a 50-100% loss)
SEEDS = [{"conds": [{"p": "rsi2", "op": "<", "t": 10}, {"p": "d_sma200", "op": ">", "t": 0}], "regime": None, "hold": 2},
         {"conds": [{"p": "z60", "op": ">", "t": 1}, {"p": "hi52", "op": ">", "t": -0.05}], "regime": None, "hold": 3},
         {"conds": [{"p": "z5", "op": "<", "t": -1}, {"p": "vz20", "op": ">", "t": 0.5}], "regime": "calm", "hold": 1}]


def complexity(spec):
    return len(spec["conds"]) + (1 if spec.get("regime") else 0)


def canon(spec):
    """Canonical form: conditions sorted, so the same rule written in a different order is the SAME rule (one hash, one test)."""
    return {"conds": sorted(({"p": c["p"], "op": c["op"], "t": c["t"]} for c in spec["conds"]), key=lambda c: (c["p"], c["op"], c["t"])), "regime": spec.get("regime"), "hold": spec["hold"]}


def spec_hash(spec):
    return hashlib.sha1(json.dumps(canon(spec), sort_keys=True).encode()).hexdigest()[:12]


def valid(spec):
    c = spec["conds"]
    return 1 <= len(c) <= MAX_COND and all(x["p"] in PRIM and x["op"] in "<>" and x["t"] in GRID[x["p"]] for x in c) and spec["hold"] in range(len(HOLD)) and spec.get("regime") in (None, "calm") \
        and len({x["p"] for x in c}) == len(c)


def make_fn(spec):
    """The FIXED interpreter: spec (data) -> signal function. Nothing is compiled or evaluated from strings."""
    def fn(ctx, params):
        sig = None
        for c in spec["conds"]:
            v = PRIM[c["p"]](ctx.F); m = (v < c["t"]) if c["op"] == "<" else (v > c["t"]); sig = m if sig is None else (sig & m)
        if spec.get("regime") == "calm" and getattr(ctx, "stress", None) is not None:
            sig = sig & (ctx.stress.reindex(ctx.px.index).ffill().fillna(0) < 0.5)
        return sig.fillna(False).astype(float)
    return fn


def to_strategy(spec):
    h = spec_hash(spec); rule = dict(HOLD[spec["hold"]])
    return Strategy(f"disc_{h[:8]}", "discovered", f"disc_{h[:8]}", 0, spec, rule, 260, tuple(sorted({c["p"] for c in spec["conds"]})), make_fn(spec))


def describe(spec):
    cs = " AND ".join(f"{c['p']} {c['op']} {c['t']}" for c in spec["conds"]) + (" AND calm market" if spec.get("regime") else "")
    h = HOLD[spec["hold"]]; hs = f"hold {h['n']} days" if h["type"] == "fixed" else "hold while the signal is on" if h["type"] == "flip" else "ATR trailing stop"
    return f"{cs}; {hs}"


# ------------------------------------------------------------------ search operators

def mutate(spec, rng):
    s = json.loads(json.dumps(spec)); op = rng.choice(["thr", "prim", "dir", "add", "drop", "hold", "regime"])
    c = s["conds"]
    if op == "thr":
        x = rng.choice(c); g = GRID[x["p"]]; i = g.index(x["t"]); x["t"] = g[min(max(i + rng.choice([-1, 1]), 0), len(g) - 1)]
    elif op == "prim":
        x = rng.choice(c); x["p"] = rng.choice(list(PRIM)); x["t"] = rng.choice(GRID[x["p"]])
    elif op == "dir":
        x = rng.choice(c); x["op"] = "<" if x["op"] == ">" else ">"
    elif op == "add" and len(c) < MAX_COND:
        p = rng.choice(list(PRIM)); c.append({"p": p, "op": rng.choice("<>"), "t": rng.choice(GRID[p])})
    elif op == "drop" and len(c) > 1:
        c.pop(rng.randrange(len(c)))
    elif op == "hold":
        s["hold"] = rng.randrange(len(HOLD))
    elif op == "regime":
        s["regime"] = None if s.get("regime") else "calm"
    return s


def crossover(a, b, rng):
    pool = a["conds"] + b["conds"]; rng.shuffle(pool); seen, out = set(), []
    for x in pool:
        if x["p"] not in seen and len(out) < MAX_COND:
            seen.add(x["p"]); out.append(dict(x))
    return {"conds": out, "regime": rng.choice([a.get("regime"), b.get("regime")]), "hold": rng.choice([a["hold"], b["hold"]])}


def random_spec(rng):
    k = rng.choice([1, 2, 2, 3]); ps = rng.sample(list(PRIM), k)
    return {"conds": [{"p": p, "op": rng.choice("<>"), "t": rng.choice(GRID[p])} for p in ps], "regime": rng.choice([None, None, "calm"]), "hold": rng.randrange(len(HOLD))}


def propose(n, parents, rng, tested):
    """n new, valid, never-tested specs: mutations and crossovers of the parents (seeds and previously promoted candidates), plus random restarts."""
    out, seen, tries = [], set(), 0
    parents = parents or SEEDS
    while len(out) < n and tries < n * 60:
        tries += 1; r = rng.random()
        s = mutate(rng.choice(parents), rng) if r < 0.5 else crossover(rng.choice(parents), rng.choice(parents), rng) if r < 0.75 else random_spec(rng)
        if not valid(s):
            continue
        h = spec_hash(s)
        if h in tested or h in seen:
            continue
        seen.add(h); out.append(s)
    return out


# ------------------------------------------------------------------ state

def load_tested(folder=None):
    f = Path(folder or STATE) / "discovery_tested.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_tested(d, folder=None):
    f = Path(folder or STATE) / "discovery_tested.json"; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d, indent=0, default=str))


def load_discovered(folder=None):
    """Strategies promoted by earlier nights (specs on disk), rebuilt through the fixed interpreter."""
    f = Path(folder or STATE) / "discovered.json"
    return [to_strategy(x["spec"]) for x in json.loads(f.read_text())["promoted"]] if f.exists() else []


def save_discovered(promoted, folder=None):
    f = Path(folder or STATE) / "discovered.json"; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps({"promoted": promoted}, indent=1, default=str))


# ------------------------------------------------------------------ evaluation of a batch

def evaluate_batch(specs, U, cal, cfg, as_of_pos, holdout_d=250, rng=None):
    """U: StockData with trades for every candidate id (built with the candidates in the strategy list) and benchmark attached. Pooled month-block test on the training window and on the holdout.
    Returns one dict per spec with n, mean_bps, p (train), holdout n / mean_bps / p, fitness."""
    months = np.asarray(cal.year * 12 + cal.month); rng = rng or np.random.default_rng(0); train_end = as_of_pos - holdout_d - 25; win_start = max(train_end - cfg["eval"]["select_lookback_d"], 0); out = []
    for s in specs:
        st = to_strategy(s); x, e, xx, _ = PL.collect(U, st.id, win_start, train_end); r = {"hash": spec_hash(s), "spec": s, "text": describe(s), "complexity": complexity(s), "n": int(len(x))}
        if len(x) < PL._cfgget(cfg, "pooled_min_trades"):
            r.update(mean_bps=None, p=1.0, fitness=-9.0, holdout_n=0, holdout_mean_bps=None, holdout_p=1.0, note="too few trades"); out.append(r); continue
        m, p, lb = PL.month_stats(x, e, months, 20000, rng, float(np.mean(xx - e)))
        hx, he, hxx, _ = PL.collect(U, st.id, train_end + 25, as_of_pos)
        if len(hx) >= 50:
            hm, hp, _ = PL.month_stats(hx, he, months, 5000, rng, float(np.mean(hxx - he)))
        else:
            hm, hp = None, 1.0
        t = m / (np.std(x) / np.sqrt(len(x)) + 1e-12)
        r.update(mean_bps=round(m * 1e4, 1), stress_mean_bps=round(m * 1e4 - STRESS_BPS, 1), p=float(p), lb_bps=round(lb * 1e4, 1), fitness=float(t - 0.3 * complexity(s)), holdout_n=int(len(hx)), holdout_mean_bps=None if hm is None else round(hm * 1e4, 1), holdout_p=float(hp)); out.append(r)
    return out


def verdicts(results, n_tested_before, cfg):
    """Apply the bar: p <= fdr_q / (all distinct rules tested so far, including this batch) on training, and positive holdout with p < 0.2. Mutates results with 'passed' and 'why'."""
    N = n_tested_before + len(results); bar = cfg["eval"]["fdr_q"] / max(N, 1)
    for r in results:
        stress = r.get("stress_mean_bps", r.get("mean_bps") or 0)
        ok = r["p"] <= bar and (r.get("mean_bps") or 0) > 0 and stress > 0 and (r.get("holdout_mean_bps") or 0) > 0 and r["holdout_p"] < 0.2
        r["bar_p"] = bar; r["passed"] = bool(ok)
        r["why"] = ("passes the search-wide false-discovery bar, the survivorship stress and the unseen holdout" if ok else f"training p {r['p']:.4f} above the bar {bar:.5f}" if r["p"] > bar else "gone after the survivorship stress"
                    if (r.get("mean_bps") or 0) > 0 and stress <= 0 else "failed the holdout" if (r.get("mean_bps") or 0) > 0 else "no positive training edge")
    return results
