"""
Which companies the supply-chain graph reads next, and why.   python scripts/nexus_priority.py [--next N] [--write]

The graph only matters for the impact score where BOTH ends of an edge are listed companies and the filing states a share. So the order is not "biggest first": it is
the companies whose filings are most likely to name another listed company with a number. The reasons below are WHY a company was chosen (a hypothesis the run then
tests); they are not claims about what its filings say. Nothing here is read by the model: it only orders the work.
Writes data/config/nexus_priority.json; --next N prints the next N symbols (not yet read) as a comma list for `revenue_graph_builder.py --symbols`.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GROUPS = [
    ("group", "Business-group company: SEBI LODR related-party notes list transactions with group companies, and some of those are listed (group companies are the most likely listed-to-listed edges)",
     "TMPV TMCV TATASTEEL TATAPOWER TATACHEM VOLTAS ADANIENT ADANIPORTS ADANIPOWER ADANIGREEN ADANIENSOL ATGL ACC AMBUJACEM GRASIM ULTRACEMCO HINDALCO M&M TECHM BAJAJ-AUTO "
     "JSWSTEEL JSWENERGY VEDL HINDZINC TIINDIA COROMANDEL TVSMOTOR ASHOKLEY BHARATFORG KEC"),
    ("auto", "Auto OEM or auto-component maker: customer concentration (a top customer above 10% of revenue) is routinely disclosed, and the customers are listed OEMs",
     "MARUTI EICHERMOT HEROMOTOCO UNOMINDA EXIDEIND ARE&M BALKRISIND APOLLOTYRE MRF SCHAEFFLER SANSERA CEATLTD"),
    ("ems", "Electronics manufacturing or electronic components: a few large customers account for most revenue, often listed consumer-electronics or auto companies",
     "DIXON KAYNES AMBER CYIENTDLM SYRMA"),
    ("chem", "Chemicals and specialty chemicals: long supply contracts with named customers and raw-material suppliers, with disclosed concentration",
     "PIIND SRF DEEPAKNTR NAVINFLUOR AARTIIND UPL ATUL VINATIORGA"),
    ("pharma", "Pharma contract manufacturing and API makers: concentration on a few innovator customers and listed API suppliers",
     "SYNGENE PPLPHARMA NEULANDLAB SUVEN LUPIN CONCORDBIO"),
    ("power", "Power equipment and utilities: equipment suppliers and the utilities and EPC companies that buy from them are all listed",
     "CGPOWER POWERINDIA GVT&D THERMAX KALPATARU NTPC POWERGRID CESC"),
    ("capital", "Capital goods and defence electronics: public-sector and large private buyers, and listed component suppliers",
     "HAL BEL LT SUZLON INOXWIND HAVELLS"),
]


def build(universe, done):
    listed = {s["s"]: s for s in universe if s.get("board") == "Main" and s.get("series") == "EQ" and not s.get("etf")}
    out, seen = [], set(done)
    for gid, why, syms in GROUPS:
        for sym in syms.split():
            if sym in seen:
                continue
            seen.add(sym)
            if sym not in listed:
                continue                                           # not on the NSE main board in the universe file: never invent a row
            out.append({"sym": sym, "name": listed[sym].get("n"), "group": gid, "why": why, "n500": bool(listed[sym].get("n500"))})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", type=int, default=0)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    uni = json.loads((ROOT / "data" / "terminal" / "universe.json").read_text(encoding="utf-8"))["stocks"]
    g = json.loads((ROOT / "data" / "supply_graph.json").read_text(encoding="utf-8")) if (ROOT / "data" / "supply_graph.json").exists() else {}
    done = set((g.get("cos") or {}))
    rows = build(uni, done)
    if a.write:
        (ROOT / "data" / "config" / "nexus_priority.json").write_text(json.dumps({"note": "Order of work for the supply-chain graph and WHY (a hypothesis the run tests, not a statement about any filing).", "rows": rows},
                                                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    if a.next:
        print(",".join(r["sym"] for r in rows[: a.next]))
    else:
        print(f"{len(rows)} companies not yet read, in this order:")
        for r in rows:
            print(f"  {r['sym']:<11} {r['group']:<8} {r['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
