"""
Review sheet for a human check of the supply-chain graph.   python scripts/graph_audit_sheet.py [--n 50] [--seed 7] [--out data/nexus_cache/audit_g1.md]

Draws a stratified sample (round-robin across companies, so no company dominates; edges first, then facilities if there are fewer than N edges) of records that already passed the
automatic checks (verbatim quote found in the source text), and writes one block per record: company, filing link and page, the exact quote and the parsed fields. The reader
marks each field right or wrong; precision must be at least 0.90 per field before the graph is scaled further. Reads data/supply_graph.json only.
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS_EDGE = [("counterparty", lambda e, n: n.get(e["d"] if e["s"] == e["own"] else e["s"], {}).get("n") or e["cpn"] if "cpn" in e else None),
               ("direction", lambda e, n: "customer (the counterparty buys from the filing company)" if e["s"] == e["own"] else "supplier (the filing company buys from the counterparty)"),
               ("share", lambda e, n: None if e.get("w") is None else f"{round(e['w'] * 100, 2)}%"),
               ("share basis", lambda e, n: e.get("wb")),
               ("period", lambda e, n: e.get("per")),
               ("relation", lambda e, n: e.get("rel"))]


def sample(graph, n=50, seed=7):
    rnd = random.Random(seed)
    by_co = {}
    for e in graph.get("edges", []):
        if e.get("vq") is True:
            by_co.setdefault(e["own"], []).append(("edge", e))
    if sum(len(v) for v in by_co.values()) < n:
        for fid, f in (graph.get("fac") or {}).items():
            by_co.setdefault(f["co"], []).append(("fac", {**f, "id": fid}))
    for v in by_co.values():
        rnd.shuffle(v)
    order = sorted(by_co)
    rnd.shuffle(order)
    picked = []
    while len(picked) < n and any(by_co.values()):
        for co in order:
            if by_co[co] and len(picked) < n:
                picked.append((co,) + by_co[co].pop())
    return picked


def render(graph, rows):
    nodes = {x["id"]: x for x in graph.get("nodes", [])}
    out = ["# Supply-chain graph: review sheet", "",
           f"Graph generated {graph.get('generated_utc')} · {len(rows)} records sampled round-robin across companies · every record's quote was found word for word in its source by the builder.", "",
           "For each field write **R** (right) or **W** (wrong). A field is right only if the quote supports it. Precision per field must reach 0.90 before the graph is scaled further.", ""]
    for i, (co, kind, r) in enumerate(rows, 1):
        out.append(f"## {i}. {co} · {kind} `{r['id']}`")
        out.append(f"- Filing: {r.get('url')} · page {r.get('pg')}" + (f" · {r.get('doc')}" if r.get("doc") else ""))
        out.append(f"- Quote: “{r.get('q')}”")
        if kind == "edge":
            cpn = r.get("cpn") or (nodes.get(r["d"] if r["s"] == co else r["s"]) or {}).get("n")
            out.append("- Parsed fields (mark R or W):")
            parsed = {"counterparty": cpn, "direction": "customer (the counterparty buys from the filing company)" if r["s"] == co else "supplier (the filing company buys from the counterparty)",
                      "share": None if r.get("w") is None else f"{round(r['w'] * 100, 2)}%", "share basis": r.get("wb"), "period": r.get("per"), "relation": r.get("rel")}
            for k, v in parsed.items():
                out.append(f"  - {k}: **{v if v not in (None, '') else '(not stated)'}**  [ ]")
        else:
            out.append("- Parsed fields (mark R or W):")
            for k, v in (("facility", r.get("n")), ("kind", r.get("kind")), ("address as written", r.get("addr")), ("capacity", (r.get("cap") or {}).get("v")), ("product", r.get("prod"))):
                out.append(f"  - {k}: **{v if v not in (None, '') else '(not stated)'}**  [ ]")
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "data" / "nexus_cache" / "audit_g1.md"))
    a = ap.parse_args(argv)
    graph = json.loads((ROOT / "data" / "supply_graph.json").read_text(encoding="utf-8"))
    rows = sample(graph, a.n, a.seed)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(render(graph, rows), encoding="utf-8")
    print(f"wrote {a.out}: {len(rows)} records from {len({r[0] for r in rows})} companies ({sum(1 for r in rows if r[1] == 'edge')} edges, {sum(1 for r in rows if r[1] == 'fac')} facilities)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
