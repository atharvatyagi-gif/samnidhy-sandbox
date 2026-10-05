"""
ALADIN probability movers: how much each stock's P(up) changed between the last two saved nightly runs, and which front moved it most.

  python scripts/aladin_moves.py            ->  data/aladin/moves.json   (small: the 15 biggest rises and falls per horizon)

Reads data/aladin/history/<date>.json, which holds per stock [F, S, T, p10, p5, p20, I] (F fundamental, S sentiment, T technical, p* the Technical model's
calibrated probability for 10/5/20 days, I the supply-chain impact score; I is missing in runs saved before it existed). The combined P(up) for each day is
recomputed with the SAME combiner the page uses (combine_py, without a sweep score, which only exists intraday), so a move is never an artefact of comparing
two different formulas.

Which front moved it most: the combiner adds four terms in log-odds,  logit(p_tech) + wF*F/100 - wF*I/100 + wS*S/100.  The change in each term between the two
days is its contribution; the largest in absolute size is named (Technical, Fundamental, Supply-chain impact or Sentiment). A front that was missing on one
of the days counts as 0 on that day, exactly as the combiner treats it. Needs at least two saved nights; otherwise the file says how many it has.
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
HIST = ROOT / "data" / "aladin" / "history"
LATEST = ROOT / "data" / "aladin" / "latest.json"
OUT = ROOT / "data" / "aladin" / "moves.json"
HORIZONS = {5: 4, 10: 3, 20: 5}                       # horizon -> index of its probability in a history row
TOP = 15
FRONTS = {"T": "Technical", "F": "Fundamental", "I": "Supply-chain impact", "S": "Sentiment"}


def load_history(d=HIST):
    out = []
    for f in sorted(Path(d).glob("*.json")):
        try:
            out.append((f.stem, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def weights(latest=LATEST):
    try:
        w = json.loads(Path(latest).read_text(encoding="utf-8")).get("weights") or {}
    except (OSError, ValueError):
        w = {}
    return {"wF": w.get("wF", 0.20), "wS": w.get("wS", 0.12), "wSweep": w.get("wSweep", 0.18)}


def _logit(p):
    p = min(0.999999, max(1e-6, p))
    return math.log(p / (1 - p))


def front_moves(now, prev, ptn, ptp, w):
    """Change in each log-odds term between two rows. -> {T, F, I, S}"""
    g = lambda r, i: (r[i] if len(r) > i and r[i] is not None else 0.0)       # noqa: E731 - a missing front counts as 0, as in the combiner
    return {"T": _logit(ptn) - _logit(ptp),
            "F": w["wF"] * (g(now, 0) - g(prev, 0)) / 100,
            "I": -w["wF"] * (g(now, 6) - g(prev, 6)) / 100,
            "S": w["wS"] * (g(now, 1) - g(prev, 1)) / 100}


def compute(hist, w, combine):
    """hist: [(date, doc)] sorted. combine(p_tech, F, S, sweep, w, I=) -> {"p", "conf"} (aladin_model.combine_py)."""
    if len(hist) < 2:
        return {"ok": False, "days": len(hist), "reason": "Needs at least two saved nightly runs to compare; ALADIN has saved %d." % len(hist), "generated_utc": _now()}
    (d0, a), (d1, b) = hist[-2], hist[-1]
    prev, now = a.get("s", {}), b.get("s", {})
    out = {"ok": True, "days": len(hist), "as_of": d1, "prev_as_of": d0, "weights": w, "generated_utc": _now(), "h": {}}
    for h, ix in HORIZONS.items():
        rows = []
        for sym, rn in now.items():
            rp = prev.get(sym)
            if rp is None or len(rn) <= ix or len(rp) <= ix or rn[ix] is None or rp[ix] is None:
                continue
            tn, tp = rn[ix], rp[ix]
            cn = combine(rn[ix], rn[0], rn[1], None, w, I=rn[6] if len(rn) > 6 else None)
            cp = combine(rp[ix], rp[0], rp[1], None, w, I=rp[6] if len(rp) > 6 else None)
            dp = (cn["p"] - cp["p"]) * 100
            mv = front_moves(rn, rp, tn, tp, w)
            top = max(mv, key=lambda k: abs(mv[k]))
            rows.append({"s": sym, "p": cn["p"], "prev": cp["p"], "dp": round(dp, 1), "conf": cn["conf"], "front": FRONTS[top], "fronts": {k: round(v, 3) for k, v in mv.items()}})
        up = sorted((r for r in rows if r["dp"] > 0), key=lambda r: (-r["dp"], r["s"]))[:TOP]
        dn = sorted((r for r in rows if r["dp"] < 0), key=lambda r: (r["dp"], r["s"]))[:TOP]
        out["h"][str(h)] = {"compared": len(rows), "up": up, "down": dn}
    return out


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None):
    import aladin_model as am
    doc = compute(load_history(), weights(), am.combine_py)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    if doc["ok"]:
        h10 = doc["h"]["10"]
        print(f"moves {doc['prev_as_of']} -> {doc['as_of']}: {h10['compared']:,} stocks compared; 10D biggest rise "
              f"{(h10['up'] or [{'s': '-', 'dp': 0}])[0]['s']} {(h10['up'] or [{'dp': 0}])[0]['dp']:+} pts, biggest fall {(h10['down'] or [{'s': '-', 'dp': 0}])[0]['s']} {(h10['down'] or [{'dp': 0}])[0]['dp']:+} pts")
    else:
        print(doc["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
