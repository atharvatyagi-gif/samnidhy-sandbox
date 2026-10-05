"""
Does a liquidity sweep predict the NEXT day's direction?   python scripts/aladin_sweep_eval.py   ->  data/aladin/sweep_eval.json

The local tick program (aladin_ticker_daemon.py) logs every CONFIRMED sweep to data/aladin_cache/sweep_log/<date>.jsonl: stock, direction (+1 a sweep of lows, a bullish
rejection; -1 a sweep of highs), the level, and the price of the 15-minute bar it closed. This script waits until the next trading day's close exists, and compares:
    hit  =  the next close is on the side the sweep pointed to (above the bar's close for +1, below it for -1).
One outcome is counted per stock, day and direction (the first sweep that day), so a stock that sweeps the same level three times does not vote three times.
Once at least 60 outcomes have matured it reports the hit rate with a 95% Wilson interval. The sweep weight in the combiner (0.18) is labelled "prior, unvalidated" until
the interval's LOWER bound is above 50%; this script never changes the weight, it only reports whether the evidence supports it. Outcomes of the same day move together, so
the interval is, if anything, a little too narrow: the label is deliberately hard to earn.
The log exists only on the machine that runs the daemon, so run this there; aladin_model.py reads the small result file into aladin.json when it is present.
"""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "aladin_cache" / "sweep_log"
DAILY = ROOT / "data" / "terminal" / "daily"
OUT = ROOT / "data" / "aladin" / "sweep_eval.json"
MIN_EVENTS = 60
Z95 = 1.959964


def ist_date(ms):
    return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def wilson(hits, n, z=Z95):
    """95% Wilson score interval for a proportion -> (low, high); (None, None) when n is 0."""
    if n <= 0:
        return None, None
    p = hits / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def load_events(log_dir=LOG_DIR):
    """One event per (stock, day, direction): the first one logged that day."""
    seen, out = set(), []
    for f in sorted(Path(log_dir).glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                k = (e["sym"], ist_date(e["ts"]), int(e["dir"]))
            except (ValueError, KeyError, TypeError):
                continue
            if k in seen or not e.get("close"):
                continue
            seen.add(k)
            out.append({**e, "date": k[1], "dir": k[2]})
    return out


def next_close(rows, date):
    """The close of the first trading day AFTER `date`, or None while it has not happened yet. rows: [[date, o, h, l, c, v], ...]"""
    for r in rows:
        if r[0] > date:
            return r[4]
    return None


def evaluate(events, closes_of):
    """closes_of(sym) -> daily rows or None. -> the result document (see the module text)."""
    done = []
    for e in events:
        rows = closes_of(e["sym"])
        nc = next_close(rows, e["date"]) if rows else None
        if nc is None or not e["close"]:
            continue
        ret = nc / e["close"] - 1
        done.append({"sym": e["sym"], "date": e["date"], "dir": e["dir"], "lvl": e.get("lvl"), "ret": ret, "hit": (ret > 0) == (e["dir"] > 0) and ret != 0})
    n, hits = len(done), sum(1 for d in done if d["hit"])
    lo, hi = wilson(hits, n)
    doc = {"events_logged": len(events), "n": n, "hits": hits, "needed": MIN_EVENTS, "min_events": MIN_EVENTS,
           "hit_rate": None if n == 0 else round(hits / n, 4), "wilson_low": None if lo is None else round(lo, 4), "wilson_high": None if hi is None else round(hi, 4)}
    doc["validated"] = bool(n >= MIN_EVENTS and lo is not None and lo > 0.5)
    by = {}
    for d in done:
        g = by.setdefault(str(d["lvl"]), [0, 0])
        g[0] += 1
        g[1] += 1 if d["hit"] else 0
    doc["by_level"] = {k: {"n": v[0], "hits": v[1]} for k, v in sorted(by.items())}
    doc["note"] = ("validated: the interval's lower bound is above 50%" if doc["validated"] else
                   f"prior, unvalidated: {n} of the {MIN_EVENTS} outcomes needed have matured" if n < MIN_EVENTS else
                   "prior, unvalidated: the hit rate's 95% interval still includes 50%")
    return doc


def main(argv=None):
    if not LOG_DIR.exists():
        print("No sweep log on this machine (it is written by the local tick program during market hours): nothing to evaluate.")
        return 0

    def closes_of(sym):
        p = DAILY / f"{key(sym)}.json"
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("d")
        except (OSError, ValueError):
            return None
    doc = evaluate(load_events(), closes_of)
    doc["generated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(f"sweep evaluation: {doc['events_logged']} events logged, {doc['n']} matured, hit rate {doc['hit_rate']}, 95% interval {doc['wilson_low']}-{doc['wilson_high']} -> {doc['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
