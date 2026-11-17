"""B-Lab research desk: one card per stock for the dashboard's "One stock, every division" search (owner, 2026-11-17: every
stock must be findable, not only those with a finding).

Built by the collect step from the scouts' stores already in data/blab/store/ and the ledger -> data/blab/stocks.json:
  "names": every NSE main-board stock (symbol, name, covered or not), for the search suggestions;
  "cards": for each of the 500 stocks the bots cover, what each division holds on it right now, findings or not.
Real data only: a fact the stores do not have is left out (the page says "nothing collected"), never filled in."""
from __future__ import annotations

import json
from datetime import date, timedelta

from .core import DATA, SITE_URL, fetch_json

STORE = DATA / "blab" / "store"


def _load(name, default):
    try:
        return json.loads((STORE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def promoter(q):
    """Shareholding rows [[quarter, promoter %, public %, broadcast, id]] newest first -> latest and 1-year change."""
    if not q:
        return None
    d1, p1 = q[0][0], q[0][1]
    old = [x for x in q if (date.fromisoformat(d1) - date.fromisoformat(x[0])).days >= 330]
    return {"quarter": d1, "pct": p1, "chg_1y": round(p1 - old[0][1], 2) if old else None, "public": q[0][2]}


def build(universe_rows, covered, stores, ledger, study, today):
    """-> {"names": [[sym, name, covered]], "cards": {sym: card}}. Pure: tests pass the stores in."""
    shp, ann, sast, deals, ai, hist = (stores.get(k) for k in ("shp", "ann", "sast", "deals", "ai", "hist"))
    d90, d30, d7 = ((today - timedelta(days=n)).isoformat() for n in (90, 30, 7))
    by_sym = {}
    for f in ledger:
        if f.get("sym"):
            by_sym.setdefault(f["sym"], []).append(f)
    names = sorted([[u["s"], u.get("n", ""), u["s"] in covered] for u in universe_rows if u.get("board") != "SME" and not u.get("etf")], key=lambda x: x[0])
    known = {n[0] for n in names}
    names += [[s, "", True] for s in sorted(covered - known)]
    cards = {}
    for s in sorted(covered):
        fs = sorted(by_sym.get(s, []), key=lambda f: f.get("seen", ""), reverse=True)
        pick = lambda div: [{"seen": f["seen"], "bot": f["bot"], "kind": f.get("kind"), "dir": f.get("direction"), "text": f.get("text")} for f in fs if f.get("division") == div][:8]  # noqa: E731
        gov = sorted([r for r in ann or [] if r[1] == s and (r[3] or "") >= d90], key=lambda r: r[3], reverse=True)
        sa = [r for r in sast or [] if r[1] == s and (r[3] or "") >= d90]
        dl = sorted([r for r in deals or [] if r[2] == s and r[0] != "short" and r[1] >= d30], key=lambda r: r[1], reverse=True)
        reads = sorted([r for r in ai or [] if s in (r.get("syms") or [])], key=lambda r: r["analysed"], reverse=True)
        evs = sorted([r for r in hist or [] if r[1] == s and r[3] >= d30], key=lambda r: r[3], reverse=True)
        cards[s] = {
            "fundamental": {"promoter": promoter((shp or {}).get(s, {}).get("q")),
                            "governance": [[r[3], r[2]] for r in gov[:5]], "governance_n": len(gov),
                            "sast": [[r[3], r[2], r[8], r[7]] for r in sa[:3]], "sast_n": len(sa), "findings": pick("fundamental")},
            "technical": {"deals": [[r[1], r[0], r[3], r[4], r[5], r[6]] for r in dl[:5]], "deals_n": len(dl),
                          "picks": sorted({f["kind"].split(": ", 1)[-1] for f in fs if f.get("bot") == "T4" and f.get("seen", "") >= d7}), "findings": pick("technical")},
            "sentiment": {"ai": [{"date": r["analysed"][:10], "title": r["title"], "url": r.get("url"), "effect": r.get("effect"), "confidence": r.get("confidence")} for r in reads[:5]],
                          "announcements": [[r[3], r[2], ((study or {}).get(r[2]) or {}).get("21")] for r in evs[:5]], "findings": pick("sentiment")},
        }
    return {"names": names, "cards": cards}


def write(ledger, status_bots, today):
    covered = set(json.loads((DATA / "aladin_e" / "latest.json").read_text(encoding="utf-8")).get("stocks", {}))
    try:
        uni = fetch_json(SITE_URL + "t/universe.json")
        rows = uni.get("stocks", []) if isinstance(uni, dict) else uni
    except Exception:  # noqa: BLE001  without the site's list, the 500 covered stocks are still searchable
        rows = []
    stores = {"shp": _load("shareholding.json", {}), "ann": _load("announcements.json", {"rows": []})["rows"], "sast": _load("sast29.json", {"rows": []})["rows"],
              "deals": _load("deals.json", {"rows": []})["rows"], "ai": _load("ai_news.json", {"rows": []})["rows"], "hist": _load("events_hist.json", {"rows": []})["rows"]}
    s7 = next((b for b in status_bots if b.get("id") == "S7"), {})
    doc = build(rows, covered, stores, ledger, (s7.get("data") or {}).get("study"), today)
    doc["generated"] = today.isoformat()
    (DATA / "blab" / "stocks.json").write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return doc
