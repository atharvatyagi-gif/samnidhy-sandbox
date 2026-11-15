"""B-Lab research desk: run the bots (docs/blab/PLAN.md).

  python scripts/blab/run.py --division technical --out part.json   one division, its bots in parallel (one GitHub job each)
  python scripts/blab/run.py --collect part1.json part2.json ...    merge, add findings to the ledger, score, write the status
  python scripts/blab/run.py --all                                  all divisions at once, then collect (local use)

-> data/blab/status.json (the dashboard, lab.html) and data/blab/ledger.json (every finding, kept for scoring).
Standard library only. Prices for scoring come from the published site (t/d/<stock>.json, t/x/d/Nifty_20500.json)."""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blab import core  # noqa: E402
from blab.bots import BOTS  # noqa: E402


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def site_prices(syms, fetch=core.fetch_json):
    """{sym: {date: close}} and the NIFTY 500 {date: close} from the published site; a stock that cannot be read is left out."""
    def one(s):
        try:
            return s, {r[0]: r[4] for r in fetch(core.SITE_URL + f"t/d/{key(s)}.json").get("d", [])}
        except Exception:  # noqa: BLE001
            return s, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(r for r in ex.map(one, sorted(syms)) if r[1])
    idx = {r[0]: r[4] for r in fetch(core.SITE_URL + "t/x/d/Nifty_20500.json").get("d", [])}
    return got, idx


def collect(parts, now=None, prices=None, out=core.OUT):
    now = now or datetime.now(timezone.utc)
    out.mkdir(parents=True, exist_ok=True)
    seen = {p["division"] for p in parts}
    for d in core.DIVISIONS:                      # a division whose job did not report: its bots show as errors, never vanish
        if d not in seen:
            parts.append({"division": d, "ran_utc": None, "bots": [{**{k: getattr(b, k) for k in ("id", "division", "name", "role", "does", "sources", "wraps", "step", "fresh_h")},
                          "state": "planned" if b.fn is None else "error", "detail": "Arrives in a later step." if b.fn is None else "The division's job did not report this run.",
                          "items": None, "as_of": None, "age_h": None, "took_s": None, "errors": [] if b.fn is None else ["no report from the division job"], "findings": []}
                         for b in BOTS if b.division == d]})
    lp = out / "ledger.json"
    ledger = json.loads(lp.read_text(encoding="utf-8"))["findings"] if lp.exists() else []
    new = [f for p in parts for b in p["bots"] for f in b.get("findings", [])]
    added = core.add_findings(ledger, new, now.date())
    syms = {f["sym"] for f in ledger if f.get("sym") and f.get("direction") in (1, -1)}
    try:
        px, idx = prices if prices is not None else (site_prices(syms) if syms else ({}, {}))
        card = core.scorecard(ledger, px, idx)
        card_note = None
    except Exception as e:  # noqa: BLE001  scoring needs the site's prices; without them the status still publishes
        card, card_note = {}, f"Scoring skipped this run: prices could not be read ({type(e).__name__})."
    doc = core.status_doc(parts, BOTS, ledger, card, now)
    doc["findings_added"] = added
    if card_note:
        doc["scorecard_note"] = card_note
    lp.write_text(json.dumps({"findings": ledger}, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--division", choices=list(core.DIVISIONS))
    ap.add_argument("--out")
    ap.add_argument("--collect", nargs="+")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.division:
        part = core.run_division(BOTS, a.division)
        Path(a.out or f"blab_{a.division}.json").write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
        print(f"blab {a.division}: " + ", ".join(f"{b['id']} {b['state']}" for b in part["bots"]))
        return 0
    if a.collect or a.all:
        if a.all:
            ctx = core.Ctx()
            with ThreadPoolExecutor(max_workers=len(core.DIVISIONS)) as ex:
                parts = list(ex.map(lambda d: core.run_division(BOTS, d, ctx), core.DIVISIONS))
        else:
            parts = [json.loads(Path(p).read_text(encoding="utf-8")) for p in a.collect]
        doc = collect(parts)
        for d in doc["divisions"]:
            print(f"blab {d['id']}: {d['ok']} ok, {d['stale']} stale, {d['error']} error, {d['planned']} planned")
        print(f"blab: {doc['findings_added']} new findings, {doc['findings_total']} in the ledger")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
