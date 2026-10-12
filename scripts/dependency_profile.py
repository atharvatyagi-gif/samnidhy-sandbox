"""
Revenue dependency profile of every company the supply-chain work has read: one record per company that the website, the terminal and the stock page all use.

  python scripts/dependency_profile.py        -> data/dependencies.json   (also run by build_site.py, so the site always has the current version)

Sources (nothing else, nothing estimated):
  data/supply_graph.json     named and unnamed customers and suppliers from filings and calls, each with its quote; stated revenue shares; derived related-party shares
  data/revenue_profile.json  the Ind AS 108 segment note: customers bringing 10% or more of revenue, or the statement that none does; revenue by geography

Dependency level (customer concentration), from the largest single-customer share of revenue the filings support:
  high      one customer is 25% of revenue or more
  moderate  one customer is 10% to 25% of revenue, or the filing says a customer brings "10% or more" without the exact share
  low       the filing states that no single customer reaches 10% of revenue, and nothing above contradicts it
  unknown   none of this is stated (most often: the segment note was not found or not read yet). Never shown as "low".
A share's source is kept: "stated" (the filing writes it), "derived" (a related-party sale ÷ revenue, both from the filing), "at least 10%" (Ind AS 108 threshold only).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH, PROFILE, OUT = ROOT / "data" / "supply_graph.json", ROOT / "data" / "revenue_profile.json", ROOT / "data" / "dependencies.json"
HIGH, MODERATE = 0.25, 0.10
INDIA = ("india", "domestic", "within india", "in india")
import re as _re
GENERIC = _re.compile(r"^(the |a |an |one |our |single |largest |top |major |key |customer|client)*(customer|client|buyer)s?( ?[a-z0-9]{0,2})?$|^customer \w+$", _re.I)   # "one customer", "Customer 1": nothing to show


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _per_key(per):
    """Sort key for a period string: the latest fiscal year mentioned (FY2025-26 > FY2024-25 > 2025)."""
    import re
    ys = [int(y) for y in re.findall(r"20(\d\d)", per or "")]
    return max(ys) if ys else 0


def level(top_share, top_min10, none_over_10):
    if top_share is not None and top_share >= HIGH:
        return "high"
    if (top_share is not None and top_share >= MODERATE) or top_min10:
        return "moderate"
    if none_over_10:
        return "low"
    return "unknown"


def build(graph, profile, now=None):
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    label = lambda nid, e: (e.get("cpn") if nid.startswith("ANON_") else None) or (nodes.get(nid) or {}).get("n") or e.get("cpn") or nid   # an unnamed counterparty: the filing's own words ("Indian Defence Services")
    sym_of = lambda nid: (nodes.get(nid) or {}).get("sym")
    out = {}
    companies = set(graph.get("cos", {})) | set((profile or {}).get("cos", {}))
    for sym in sorted(companies):
        cust, supp = {}, {}
        for e in graph.get("edges", []):
            if e["s"] == sym:                                         # sym supplies e["d"]: a customer of sym
                other, bucket = e["d"], cust
            elif e["d"] == sym:                                       # e["s"] supplies sym: a supplier of sym
                other, bucket = e["s"], supp
            else:
                continue
            row = {"name": label(other, e), "sym": sym_of(other), "anon": other.startswith("ANON_"), "rel": e.get("rel"), "w": e.get("w"), "wb": e.get("wb"),
                   "derived": e.get("wd") == "derived", "per": e.get("per"), "q": e.get("q"), "url": e.get("url"), "pg": e.get("pg"), "doc": e.get("doc"), "conf": e.get("conf"),
                   "own": e.get("own")}
            prev = bucket.get(other)                                  # one row per counterparty: the latest period, then the one with a share
            if prev is None or (_per_key(row["per"]), row["w"] is not None) > (_per_key(prev["per"]), prev["w"] is not None):
                bucket[other] = row
        customers = sorted(cust.values(), key=lambda r: (-(r["w"] or 0) if r["wb"] == "revenue" else 0, r["name"]))
        suppliers = sorted(supp.values(), key=lambda r: (-(r["w"] or 0), r["name"]))
        prof = ((profile or {}).get("cos") or {}).get(sym) or {}
        major, geo = prof.get("major") or {"status": "not_found", "customers": []}, prof.get("geo")
        # the largest single-customer share of THIS company's revenue, and where it comes from
        cands = [(r["w"], "derived" if r["derived"] else "stated", r["name"] if not (r["anon"] and GENERIC.search(r["name"] or "")) else None, r["q"], r["url"], r["pg"]) for r in customers if r["w"] is not None and r["wb"] == "revenue"]
        cands += [(c["share"], "stated", c.get("name"), c.get("q"), prof.get("url"), c.get("pg")) for c in major.get("customers", []) if c.get("share") is not None]
        top = max(cands, key=lambda c: c[0]) if cands else None
        min10 = any(c.get("min_share") for c in major.get("customers", []))
        lvl = level(top[0] if top else None, min10 and not (top and top[0] >= MODERATE), major.get("status") == "none_over_10")
        if lvl == "low" and top and top[0] >= MODERATE:
            lvl = "moderate"
        abroad = None
        if geo and geo.get("rows"):
            home = [r for r in geo["rows"] if r["region"].strip().lower() in INDIA]
            if len(home) == 1:
                abroad = round(1 - home[0]["share"], 4)
        if lvl == "high":
            why = f"one customer brings {top[0] * 100:.0f}% of revenue" + (f" ({top[2]})" if top[2] else "")
        elif lvl == "moderate":
            why = f"one customer brings {top[0] * 100:.0f}% of revenue" if top and top[0] >= MODERATE else "a single customer brings 10% or more of revenue (the exact share is not stated)"
        elif lvl == "low":
            why = "the annual report states that no single customer reaches 10% of revenue"
        else:
            why = "the filings read so far do not state how much revenue depends on single customers"
        out[sym] = {"lvl": lvl, "why": why,
                    "top": {"share": top[0], "src": top[1], "name": top[2], "q": top[3], "url": top[4], "pg": top[5]} if top else None,
                    "major": {"status": major.get("status"), "n": len(major.get("customers", [])), "customers": major.get("customers", []), "q": major.get("q")},
                    "geo": {"rows": geo["rows"], "q": geo.get("q"), "pg": geo.get("pg")} if geo else None, "abroad": abroad,
                    "customers": customers[:25], "suppliers": suppliers[:25],
                    "listed_customers": sorted({r["sym"] for r in customers if r["sym"]}), "listed_suppliers": sorted({r["sym"] for r in suppliers if r["sym"]}),
                    "read": {"graph": (graph.get("cos", {}).get(sym) or {}).get("at"), "segment_note": prof.get("at"), "annual_report": prof.get("url"), "per": prof.get("per")}}
    counts = {k: sum(1 for v in out.values() if v["lvl"] == k) for k in ("high", "moderate", "low", "unknown")}
    return {"v": 1, "generated_utc": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "counts": counts, "cos": out,
            "method": __doc__.strip().split("Dependency level")[1].strip()}


def main():
    doc = build(_load(GRAPH, {"cos": {}, "edges": [], "nodes": []}), _load(PROFILE, {"cos": {}}))
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"dependencies.json: {len(doc['cos'])} companies, levels {doc['counts']}")


if __name__ == "__main__":
    main()
