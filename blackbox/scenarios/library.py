"""The scenario catalogue: reads the severity ladder from config.yaml and turns one scenario + one seed into a concrete ShockState."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from . import shocks as S

log = logging.getLogger(__name__)


def _draw(v: Any, rng: np.random.Generator) -> Any:
    """[a, b] -> a uniform draw; anything else unchanged."""
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        lo, hi = sorted(v); return float(rng.uniform(lo, hi)) if isinstance(v[0], float) or isinstance(v[1], float) else int(rng.integers(lo, hi + 1))
    return v


def scenarios(cfg: dict) -> list[dict]:
    """The ladder, most tragic first (severity 1 .. 10; the black swan and the mixed chain sit at their configured severity)."""
    return sorted(cfg["scenarios"], key=lambda s: (s["severity"], s["id"]))


def by_id(cfg: dict, sid: str) -> dict:
    for s in cfg["scenarios"]:
        if s["id"] == sid:
            return s
    raise KeyError(sid)


def build(cfg: dict, scenario: dict, T: int, offset: int, rng: np.random.Generator) -> tuple[S.ShockState, dict]:
    """-> (ShockState over T days, a record of what was drawn). `offset` = index of the first evaluated day."""
    st = S.ShockState(T); drawn: dict = {"id": scenario["id"], "shocks": []}
    for sh in scenario.get("shocks", []):
        t = sh["type"]; p = {k: (v if (t == "regime_chain" or k in ("block", "regimes")) else _draw(v, rng)) for k, v in sh.items() if k != "type"}
        for k in ("start", "day"):
            if k in p:
                p[k] = int(p[k]) + offset
        if t == "crash":
            S.crash(st, p["start"], p["length"], p["depth"], p.get("recovery", 0.0))
        elif t == "drift":
            S.drift(st, p["start"], p["length"], p["total"])
        elif t == "vol":
            S.vol(st, p["start"], p["length"], p["mult"], p.get("idio_mult"))
        elif t == "corr_spike":
            S.corr_spike(st, p["start"], p["length"], p["idio_mult"], p["mkt_vol_mult"])
        elif t == "liquidity":
            S.liquidity(st, p["start"], p["length"], p.get("spread_mult", 1.0), p.get("fill_haircut", 0.0), p.get("volume_mult", 1.0))
        elif t == "gaps":
            S.gaps(st, p["start"], p["length"], p["n"], p["size"], rng)
        elif t == "flash":
            S.flash(st, p["day"], p["low"], p["close"], p["rebound_days"])
        elif t == "sector":
            S.sector(st, p["sector"], p["start"], p["length"], p["move"])
        elif t == "extra":
            S.extra(st, p["asset"], p["start"], p["length"], p["move"])
        elif t == "chop":
            S.chop(st, p["start"], p["length"], p["band"], p["half_life"])
        elif t == "single_gap":
            S.single_gap(st, p["day"], p["size"], p["target"])
        elif t == "regime_chain":
            p["chain"] = S.regime_chain(st, offset, T - offset, p["block"], p["regimes"], rng)
        else:
            raise ValueError(f"unknown shock type {t}")
        drawn["shocks"].append({"type": t, **{k: v for k, v in p.items() if not isinstance(v, np.ndarray)}})
    return st, drawn
