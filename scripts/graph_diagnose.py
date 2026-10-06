"""
Where the supply-chain graph is thin, company by company.   python scripts/graph_diagnose.py [--md out.md]

Per company read: edges by relation type, edges with a stated share, edges where BOTH ends are listed securities (the only ones that can feed the impact score),
edges still anonymous, and what went wrong with filings (the reasons the builder noted). Then the one number that matters: how many stocks can receive a
non-zero impact score today. Reads data/supply_graph.json and data/terminal/universe.json only; no network.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import graph_impact as gi  # noqa: E402

FAIL_WORDS = ("no filing", "failed", "not recorded", "unreadable", "no readable", "too short", "not in the source", "refus", "stopped", "rate", "budget", "429", "scan")


def listed_set():
    u = json.loads((ROOT / "data" / "terminal" / "universe.json").read_text(encoding="utf-8"))["stocks"]
    return {s["s"] for s in u if not s.get("etf")}


def diagnose(graph, listed, min_conf=0.5):
    edges = graph.get("edges", [])
    anon_nodes = {n["id"] for n in graph.get("nodes", []) if n.get("k") == "anon"}
    per = collections.OrderedDict()
    for sym, c in sorted((graph.get("cos") or {}).items()):
        per[sym] = {"edges": 0, "rel": collections.Counter(), "share": 0, "ll": 0, "anon": 0, "fac": c.get("fac", 0), "notes": c.get("notes", []), "at": c.get("at", "")}
    for e in edges:
        r = per.setdefault(e["own"], {"edges": 0, "rel": collections.Counter(), "share": 0, "ll": 0, "anon": 0, "fac": 0, "notes": [], "at": ""})
        r["edges"] += 1
        r["rel"][e["rel"]] += 1
        r["share"] += e.get("w") is not None
        r["ll"] += e["s"] in listed and e["d"] in listed
        r["anon"] += e["s"] in anon_nodes or e["d"] in anon_nodes
    exp = gi.exposures(graph, listed, min_conf)
    usable = sum(1 for e in edges if e["s"] in listed and e["d"] in listed and e.get("w") is not None and e.get("conf", 0) >= min_conf and e.get("kind") in ("disclosed", "resolved"))
    return per, {"companies": len(per), "edges": len(edges), "with_share": sum(e.get("w") is not None for e in edges),
                 "listed_to_listed": sum(e["s"] in listed and e["d"] in listed for e in edges), "usable_for_impact": usable,
                 "anonymous": sum(e["s"] in anon_nodes or e["d"] in anon_nodes for e in edges),
                 "stocks_with_nonzero_I_possible": len(exp), "stocks": sorted(exp)}


def failures(c):
    return [n for n in c.get("notes", []) if any(w in n.lower() for w in FAIL_WORDS)]


def table(per, tot, graph):
    rows = ["| Company | Edges | By relation | With share | Listed-to-listed | Anonymous | Facilities | Filing problems |", "|---|---|---|---|---|---|---|---|"]
    for sym, r in per.items():
        probs = failures(graph["cos"].get(sym, {}))
        rows.append(f"| {sym} | {r['edges']} | {', '.join(f'{k} {v}' for k, v in r['rel'].most_common()) or '-'} | {r['share']} | {r['ll']} | {r['anon']} | {r['fac']} | {len(probs)}: {'; '.join(sorted(set(probs)))[:110]} |")
    rows.append(f"| **TOTAL {tot['companies']}** | **{tot['edges']}** | | **{tot['with_share']}** | **{tot['listed_to_listed']}** | **{tot['anonymous']}** | | |")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="")
    a = ap.parse_args(argv)
    graph = json.loads((ROOT / "data" / "supply_graph.json").read_text(encoding="utf-8"))
    per, tot = diagnose(graph, listed_set())
    t = table(per, tot, graph)
    print(t)
    print(f"\nlisted-to-listed edges: {tot['listed_to_listed']}; of those usable for the impact score (share stated, confidence >= 0.5, disclosed): {tot['usable_for_impact']}")
    print(f"stocks that can receive a non-zero impact score today: {tot['stocks_with_nonzero_I_possible']} {tot['stocks']}")
    if a.md:
        Path(a.md).write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
