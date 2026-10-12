import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dependency_profile as D  # noqa: E402

NODES = [{"id": "AAA", "k": "co", "n": "Aaa Ltd", "sym": "AAA"}, {"id": "BBB", "k": "co", "n": "Bbb Ltd", "sym": "BBB"},
         {"id": "ANON_AAA_ONE_CUSTOMER", "k": "anon", "n": "one customer"}, {"id": "ANON_CCC_DEF", "k": "anon", "n": "Indian Defence Services"}]


def edge(s, d, w=None, wb=None, per="FY2025-26", wd=None, cpn=None):
    return {"own": s, "s": s, "d": d, "rel": "supplies", "w": w, "wb": wb, "wd": wd, "per": per, "q": f"{s} supplies {d}", "url": "u", "pg": 1, "conf": 0.8, "cpn": cpn}


def test_levels_follow_the_largest_single_customer_share():
    g = {"cos": {"AAA": {}, "BBB": {}, "CCC": {}}, "nodes": NODES, "edges": [
        edge("AAA", "ANON_AAA_ONE_CUSTOMER", 0.108, "revenue", "FY2024-25"), edge("AAA", "ANON_AAA_ONE_CUSTOMER", 0.31, "revenue", "FY2025-26"),     # the latest year wins
        edge("BBB", "AAA", 0.02, "revenue", wd="derived"), edge("CCC", "ANON_CCC_DEF", 0.97, "revenue")]}
    out = D.build(g, {"cos": {}})["cos"]
    assert out["AAA"]["lvl"] == "high" and out["AAA"]["top"]["share"] == 0.31 and out["AAA"]["top"]["name"] is None          # "one customer" is not a name worth showing
    assert out["CCC"]["top"]["name"] == "Indian Defence Services" and "97%" in out["CCC"]["why"]
    assert out["BBB"]["lvl"] == "unknown" and out["BBB"]["listed_customers"] == ["AAA"] and out["AAA"]["listed_suppliers"] == ["BBB"]


def test_the_segment_note_gives_moderate_low_and_never_low_without_a_statement():
    g = {"cos": {"AAA": {}, "BBB": {}, "CCC": {}}, "nodes": NODES, "edges": []}
    prof = {"cos": {"AAA": {"major": {"status": "disclosed", "customers": [{"share": None, "min_share": 0.10, "q": "one customer more than 10%"}]}},
                    "BBB": {"major": {"status": "none_over_10", "customers": []}, "geo": {"rows": [{"region": "India", "share": 0.8}, {"region": "Others", "share": 0.2}]}},
                    "CCC": {"major": {"status": "not_found", "customers": []}}}}
    out = D.build(g, prof)["cos"]
    assert out["AAA"]["lvl"] == "moderate" and "10% or more" in out["AAA"]["why"]
    assert out["BBB"]["lvl"] == "low" and out["BBB"]["abroad"] == 0.2
    assert out["CCC"]["lvl"] == "unknown"


def test_a_stated_share_overrides_a_none_over_ten_claim():
    g = {"cos": {"AAA": {}}, "nodes": NODES, "edges": [edge("AAA", "ANON_AAA_ONE_CUSTOMER", 0.15, "revenue")]}
    out = D.build(g, {"cos": {"AAA": {"major": {"status": "none_over_10", "customers": []}}}})["cos"]
    assert out["AAA"]["lvl"] == "moderate"
