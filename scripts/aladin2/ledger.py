"""
ALADIN 2.0 append-only ledger (section 10 of the brief). Git history is the audit trail.

Files: data/aladin2/ledger/YYYY-MM.jsonl, one JSON object per line, written ONLY by append(). Line types (all columnar so a day costs about 100 KB, not 3 MB):
  fc   a forecast batch for one as-of close:  d (as-of date), created (UTC timestamp), v (model version), h (hash of the inputs), syms, close, sigma (per-horizon forecast std of the log return),
       bands (per horizon: [lo50, hi50, lo80, hi80, lo95, hi95] as PRICE levels, one list per stock), p_up (per horizon, null when no calibrated number is shown), and the horizons H.
  sig  the signals of that day: per stock the product state, label key, strategies behind it and the trade plan (only for Validated stocks)
  out  the resolution of one (as-of date, horizon): on (resolution date), syms, px (realised close), in50 / in80 / in95 (1 = inside the band), up (1 = closed above the as-of close)
  corr a correction to an earlier line (never an edit): ref (as-of date + type) and a note
A forecast is LIVE (counts in the public statistics) only if it was created before the day it targets: created date < as-of date + horizon trading days. A forecast written after the
outcome was already public (for instance a 1-day forecast made the next morning) is stored but excluded from live statistics.
Immutability: append() refuses a second `fc`, `sig` or `out` for the same key unless it is byte-identical; nothing is ever rewritten. stats() recomputes every displayed live number from the raw lines.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER = ROOT / "data" / "aladin2" / "ledger"


def _file(d, folder=None):
    return Path(folder or LEDGER) / f"{str(d)[:7]}.jsonl"


def _key(rec):
    return (rec["t"], rec.get("d"), rec.get("H"))


def read_all(folder=None):
    out = []
    for f in sorted(Path(folder or LEDGER).glob("*.jsonl")):
        with open(f, encoding="utf-8") as h:
            for line in h:
                if line.strip():
                    out.append(json.loads(line))
    return out


def has(t, d, folder=None, H=None):
    """True when a line of type t for as-of date d (and horizon H) is already in the ledger."""
    return any(r["t"] == t and r.get("d") == str(d) and (H is None or r.get("H") == H) for r in read_all(folder))


def append(rec, folder=None):
    """Append one record. Returns 'written', or 'duplicate' when an identical record is already there. Raises ValueError for a different record with the same key."""
    if rec["t"] not in ("fc", "sig", "out", "corr"):
        raise ValueError(f"unknown ledger line type {rec['t']}")
    line = json.dumps(rec, separators=(",", ":"), sort_keys=True)
    if rec["t"] != "corr":
        for old in read_all(folder):
            if _key(old) == _key(rec):
                if json.dumps(old, separators=(",", ":"), sort_keys=True) == line:
                    return "duplicate"
                raise ValueError(f"ledger is append-only: a different {rec['t']} for {rec.get('d')} (H={rec.get('H')}) already exists; write a 'corr' line instead")
    f = _file(rec.get("d") or rec.get("on") or pd.Timestamp.utcnow().date(), folder); f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8", newline="\n") as h:
        h.write(line + "\n")
    return "written"


def r3(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 3)


def forecast_record(d, created, version, inputs_hash, H_list, syms, close, sigma, bands, p_up):
    """bands[i][j] = [lo50, hi50, lo80, hi80, lo95, hi95] price levels of stock i, horizon j. sigma[i][j] = std of the log return. p_up[i][j] = calibrated number or None."""
    return {"t": "fc", "d": str(d), "created": str(created), "v": version, "h": inputs_hash, "H": list(H_list), "syms": list(syms), "close": [r3(x) for x in close],
            "sigma": [[round(float(s), 5) for s in row] for row in sigma], "bands": [[[r3(x) for x in b] for b in row] for row in bands], "p_up": [[None if p is None else round(float(p), 3) for p in row] for row in p_up]}


def resolve(fc, H, px_lookup, on, calendar):
    """The `out` record for forecast batch `fc`, horizon H, resolved on date `on` (the H-th trading day after the as-of date). px_lookup(sym, date) -> close or None."""
    j = fc["H"].index(H); syms, ins, up, px = [], [[], [], []], [], []
    for i, s in enumerate(fc["syms"]):
        p = px_lookup(s, on)
        if p is None or not np.isfinite(p):
            continue
        b = fc["bands"][i][j]
        if b[0] is None:
            continue
        syms.append(s); px.append(r3(p)); up.append(int(p > fc["close"][i]))
        for k in range(3):
            ins[k].append(int(b[2 * k] < p < b[2 * k + 1]))
    return {"t": "out", "d": fc["d"], "H": H, "on": str(on), "syms": syms, "px": px, "in50": ins[0], "in80": ins[1], "in95": ins[2], "up": up}


def target_date(as_of, H, calendar):
    i = calendar.searchsorted(pd.Timestamp(as_of)); return calendar[min(i + H, len(calendar) - 1)] if i + H < len(calendar) else None


def stats(folder=None, ece_fn=None):
    """Every live statistic, recomputed from the raw lines. Only LIVE forecasts count (created before their target date)."""
    L = read_all(folder); fcs = {r["d"]: r for r in L if r["t"] == "fc"}; outs = [r for r in L if r["t"] == "out"]
    res = {"forecast_batches": len(fcs), "outcomes": {}}
    for H in sorted({o["H"] for o in outs}):
        n = 0; hit = {"50": 0, "80": 0, "95": 0}; ups = []; ps = []
        for o in [o for o in outs if o["H"] == H]:
            f = fcs.get(o["d"])
            if f is None or pd.Timestamp(f["created"]).tz_localize(None).normalize() >= pd.Timestamp(o["on"]):
                continue
            n += len(o["syms"])
            for k, name in enumerate(("50", "80", "95")):
                hit[name] += int(sum(o["in" + name]))
            j = f["H"].index(H); idx = {s: i for i, s in enumerate(f["syms"])}
            for s, u in zip(o["syms"], o["up"]):
                p = f["p_up"][idx[s]][j]
                if p is not None:
                    ps.append(p); ups.append(u)
        if n:
            res["outcomes"][H] = {"n": n, "coverage": {k: round(v / n, 4) for k, v in hit.items()}}
            if ps and ece_fn:
                res["outcomes"][H]["p_up_n"] = len(ps); res["outcomes"][H]["ece"] = round(ece_fn(ps, ups), 4)
    return res
