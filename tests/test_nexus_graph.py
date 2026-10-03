"""NEXUS graph: nothing gets in without a verified quote; direction, shares, anonymous customers, geocoding honesty."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_graph as cg  # noqa: E402
import geocode_facilities as gf  # noqa: E402
import revenue_graph_builder as rb  # noqa: E402

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
SRC = json.loads((Path(__file__).resolve().parent.parent / "data" / "config" / "nexus_sources.json").read_text(encoding="utf-8"))
PAGE12 = "Our largest customer, Tata Motors Limited, accounted for 24% of our revenue during FY2024-25.   Customer A contributed 31% of revenue."
META = {"url": "https://nsearchives.nseindia.com/annual_reports/AR_x.pdf", "kind": "annual", "period": "FY2024-25"}


def edge(**kw):
    base = {"counterparty_name": "Tata Motors Limited", "counterparty_anon_label": None, "direction": "customer", "rel": "supplies", "w": 0.24,
            "w_basis": "revenue", "period": "FY2024-25", "component": None, "page": 12,
            "quote": "Our largest customer, Tata Motors Limited, accounted for 24% of our revenue"}
    base.update(kw)
    return base


def validate(edges, facs=()):
    return rb.validate_answer({"edges": edges, "facilities": list(facs)}, {12: PAGE12}, META, NOW, SRC["schema"])


# ---------------------------------------------------------------- quotes and numbers

def test_verified_edge_is_kept_with_rubric_confidence():
    e, f, dropped = validate([edge()])
    assert len(e) == 1 and not dropped
    assert e[0]["conf"] == 1.0                    # quote 0.5 + named 0.2 + share 0.2 + period within 18 months 0.1
    assert e[0]["pg"] == 12 and e[0]["wb"] == "revenue" and e[0]["w"] == 0.24


def test_whitespace_differences_in_the_quote_are_tolerated():
    e, _, _ = validate([edge(quote="Our largest  customer,\nTata Motors Limited,   accounted for 24% of our revenue")])
    assert len(e) == 1


def test_fabricated_quote_drops_the_edge():
    e, _, dropped = validate([edge(quote="Tata Motors is our biggest customer and pays us 40% of everything")])
    assert e == [] and "not in the source text" in dropped[0]


def test_wrong_page_number_is_corrected_not_trusted():
    e, _, _ = validate([edge(page=99)])
    assert e and e[0]["pg"] == 12


def test_share_not_written_in_the_quote_is_removed_and_costs_confidence():
    e, _, _ = validate([edge(w=0.5)])
    assert e[0]["w"] is None and e[0]["wb"] is None and e[0]["conf"] == 0.8


def test_old_period_loses_the_recency_point_and_unnamed_costs_the_naming_point():
    e, _, _ = validate([edge(period="FY2021-22")])
    assert e[0]["conf"] == 0.9
    e2, _, _ = validate([edge(counterparty_name=None, counterparty_anon_label="Customer A",
                              quote="Customer A contributed 31% of revenue", w=0.31)])
    assert e2[0]["conf"] == 0.8 and e2[0]["anon"] == "Customer A"


def test_schema_violations_drop_only_the_bad_item():
    bad = edge(rel="buys_from")
    e, _, dropped = validate([bad, edge()])
    assert len(e) == 1 and any("schema" in d for d in dropped)


def test_edge_without_any_counterparty_is_dropped():
    e, _, dropped = validate([edge(counterparty_name=None, counterparty_anon_label=None)])
    assert e == [] and "no counterparty" in dropped[0]


def test_facility_capacity_and_utilisation_only_when_in_the_quote():
    page = "The Pune plant has an installed capacity of 450000 units per annum with utilisation of 82%."
    fac = {"name": "Pune plant", "kind": "plant", "address_text": "Chakan, Pune", "capacity": {"value": 450000, "unit": "units/year"},
           "utilisation_pct": 82, "period": "FY2024-25", "products": ["cars"], "equipment": [], "page": 3,
           "quote": "The Pune plant has an installed capacity of 450000 units per annum with utilisation of 82%"}
    _, f, _ = rb.validate_answer({"edges": [], "facilities": [fac]}, {3: page}, META, NOW, SRC["schema"])
    assert f[0]["cap"]["v"] == 450000 and f[0]["util"]["pct"] == 82
    fac2 = {**fac, "capacity": {"value": 900000, "unit": "units/year"}, "utilisation_pct": 95}
    _, f2, _ = rb.validate_answer({"edges": [], "facilities": [fac2]}, {3: page}, META, NOW, SRC["schema"])
    assert f2[0]["cap"]["v"] is None and f2[0]["cap"]["q"] is None and f2[0]["util"]["pct"] is None


def test_unreadable_answer_is_survived():
    assert rb.validate_answer("nonsense", {}, META, NOW, SRC["schema"])[2]
    assert rb.parse_json_text('```json\n{"edges": [], "facilities": []}\n```') == {"edges": [], "facilities": []}
    assert rb.parse_json_text("no json here") is None


# ---------------------------------------------------------------- names, direction, anonymous

STOCKS = [{"s": "TATAMOTORS", "n": "Tata Motors Limited", "board": "Main", "ind": "Automobile"},
          {"s": "MOTHERSON", "n": "Samvardhana Motherson International Limited", "board": "Main", "ind": "Auto Components"},
          {"s": "BOSCHLTD", "n": "Bosch Limited", "board": "Main", "ind": "Auto Components"},
          {"s": "TATAMTRDVR", "n": "Tata Motors Limited DVR", "board": "Main", "ind": "Automobile"}]


def test_name_resolution_needs_a_single_close_match():
    ix = rb.NameIndex(STOCKS)
    assert ix.resolve("Bosch Ltd.") == "BOSCHLTD"
    assert ix.resolve("Totally Unknown Foreign Corp") is None
    assert ix.resolve("Bosch Limited", exclude="BOSCHLTD") is None      # a company is never its own counterparty


def test_edge_direction_s_is_supplier_d_is_customer():
    ix = rb.NameIndex(STOCKS)
    e, _, _ = validate([edge()])
    cust = rb.to_graph_edges("BOSCHLTD", e, ix)[0]
    assert (cust["s"], cust["d"], cust["wb"]) == ("BOSCHLTD", "TATAMOTORS", "revenue")
    sup = rb.to_graph_edges("TATAMOTORS", [{**e[0], "direction": "supplier", "wb": "purchases", "name": "Bosch Limited"}], ix)[0]
    assert (sup["s"], sup["d"]) == ("BOSCHLTD", "TATAMOTORS")


def test_unlisted_and_anonymous_counterparties():
    ix = rb.NameIndex(STOCKS)
    e, _, _ = validate([edge(counterparty_name="Acme Overseas GmbH")])
    assert rb.to_graph_edges("BOSCHLTD", e, ix)[0]["d"].startswith("EXT_")
    e2, _, _ = validate([edge(counterparty_name=None, counterparty_anon_label="Customer A", quote="Customer A contributed 31% of revenue", w=0.31)])
    assert rb.to_graph_edges("BOSCHLTD", e2, ix)[0]["d"] == "ANON_BOSCHLTD_CUSTOMER_A"


def doc_from(owner_results):
    return rb.assemble({"cos": {}}, owner_results, STOCKS, [{"id": "tata", "symbols": ["TATAMOTORS"]}], 0.75, NOW)


def rec(owner, edges):
    return {"edges": rb.to_graph_edges(owner, edges, rb.NameIndex(STOCKS)), "fac": [], "at": "2026-10-03T00:00:00Z", "notes": []}


def test_anonymous_customer_resolves_only_with_the_counterpartys_own_filing():
    anon, _, _ = validate([edge(counterparty_name=None, counterparty_anon_label="Customer A", quote="Customer A contributed 31% of revenue", w=0.31)])
    d = doc_from({"BOSCHLTD": rec("BOSCHLTD", anon)})
    assert d["anon"]["ANON_BOSCHLTD_CUSTOMER_A"]["resolved_to"] is None
    assert [n["k"] for n in d["nodes"] if n["id"].startswith("ANON_")] == ["anon"]
    theirs = [{**validate([edge()])[0][0], "name": "Bosch Limited", "direction": "supplier", "wb": "purchases", "w": 0.05}]
    d2 = doc_from({"BOSCHLTD": rec("BOSCHLTD", anon), "TATAMOTORS": rec("TATAMOTORS", theirs)})
    a = d2["anon"]["ANON_BOSCHLTD_CUSTOMER_A"]
    assert a["resolved_to"] == "TATAMOTORS" and a["evidence"] and a["conf"] >= 0.75
    assert not any(n["id"].startswith("ANON_") for n in d2["nodes"])
    assert any(e["kind"] == "resolved" and e["d"] == "TATAMOTORS" for e in d2["edges"])


def test_assembled_graph_passes_the_audit_and_assembly_is_idempotent():
    e, _, _ = validate([edge()])
    d = doc_from({"BOSCHLTD": rec("BOSCHLTD", e)})
    assert cg.audit(d) == []
    d2 = rb.assemble(d, {"BOSCHLTD": rec("BOSCHLTD", e)}, STOCKS, [], 0.75, NOW)
    assert len(d2["edges"]) == len(d["edges"]) == 1 and d["nodes"][0]["house"] in (None, "tata")


# ---------------------------------------------------------------- the audit itself

def good_doc():
    e, _, _ = validate([edge()])
    return doc_from({"BOSCHLTD": rec("BOSCHLTD", e)})


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["edges"][0].update(vq=False), "not verified"),
    (lambda d: d["edges"][0].update(q=""), "missing q"),
    (lambda d: d["edges"][0].update(url=None), "missing url"),
    (lambda d: d["edges"][0].update(w=1.4), "outside"),
    (lambda d: d["edges"][0].update(wb=None), "without a basis"),
    (lambda d: d["edges"][0].update(rel="buys_from"), "unknown relation"),
    (lambda d: d["edges"][0].update(s="NOPE"), "not a node"),
    (lambda d: d["edges"][0].update(kind="sector_io", conf=0.9), "0.3"),
    (lambda d: d["edges"][0].update(rel="target"), "unknown relation"),
])
def test_audit_catches_each_kind_of_bad_edge(mutate, needle):
    d = good_doc()
    mutate(d)
    assert any(needle in p for p in cg.audit(d))


def test_audit_flags_weak_anonymous_resolution_and_unlabelled_coordinates():
    d = good_doc()
    d["anon"]["ANON_X"] = {"resolved_to": "TATAMOTORS", "conf": 0.5, "evidence": []}
    d["fac"]["FAC_1"] = {"co": "BOSCHLTD", "url": "u", "pg": 1, "q": "q", "lat": 18.5, "lon": 73.8, "geo_prec": None, "cap": {"v": None}}
    probs = cg.audit(d)
    assert any("evidence" in p for p in probs) and any("precision" in p for p in probs)


# ---------------------------------------------------------------- driver with a mocked model and a fake NSE

class FakeFetcher:
    def __init__(self, pages):
        self.p = pages

    def pages(self, url):
        return "hash:" + url, self.p


class FakeLLM:
    provider, tag = "groq", "groq:mock"

    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def complete(self, system, user):
        self.calls += 1
        assert "[[PAGE 12]]" in user
        return json.dumps(self.answer)


def test_extract_filing_end_to_end_with_cache_and_pre_filter(tmp_path):
    pages = [(i, "nothing relevant here") for i in range(1, 12)] + [(12, PAGE12 + " Our customers and suppliers: segment revenue 10% of total.")]
    llm = FakeLLM({"edges": [edge(), edge(quote="invented sentence about a 99% customer", w=0.99)], "facilities": []})
    (tmp_path / "llm").mkdir()
    doc = {"kind": "annual", "url": "u", "period": "FY2024-25"}
    e, f, notes, answered = rb.extract_filing(doc, FakeFetcher(pages), llm, SRC, NOW, tmp_path / "llm")
    assert answered == 1 and len(e) == 1 and llm.calls == 1 and notes[0].startswith("annual: 12 pages, 1 relevant")
    rb.extract_filing(doc, FakeFetcher(pages), llm, SRC, NOW, tmp_path / "llm")
    assert llm.calls == 1                                                # second time comes from the cache


def test_discover_reads_annual_report_and_transcripts_and_survives_failures():
    def get(path, params, referer=None):
        if "annual" in path:
            return {"data": [{"fromYr": "2023", "toYr": "2024", "fileName": "https://x/old.pdf"}, {"fromYr": "2024", "toYr": "2025", "fileName": "https://x/new.pdf"}]}
        return [{"desc": "Analysts/Institutional Investor Meet/Con. Call Updates", "attchmntText": "Transcript of earnings call", "attchmntFile": "https://x/t1.pdf", "an_dt": "20-Aug-2026 10:00:00"},
                {"desc": "Credit Rating", "attchmntText": "rating", "attchmntFile": "https://x/r.pdf", "an_dt": "01-Sep-2026 10:00:00"}]
    docs = rb.discover(None, "RELIANCE", SRC, NOW, get=get)
    assert [d["kind"] for d in docs] == ["annual", "transcript"] and docs[0]["url"].endswith("new.pdf") and docs[0]["period"] == "FY2024-25"

    def boom(*a, **k):
        raise RuntimeError("blocked")
    assert rb.discover(None, "X", SRC, NOW, get=boom) == []


def test_run_without_a_key_does_nothing_and_budget_stops_the_run(monkeypatch, capsys):
    import aladin_env
    monkeypatch.setattr(aladin_env, "load_env", lambda *a, **k: None)      # never read the real .env in a test
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert rb.LLM().provider is None and rb.main([]) == 0
    assert "No GROQ_API_KEY" in capsys.readouterr().out
    monkeypatch.setenv("GROQ_API_KEY", "x")
    llm = rb.LLM(max_calls=0)
    with pytest.raises(rb.LLMBudget):
        llm.complete("s", "u")


def test_llm_retries_on_429_then_succeeds(monkeypatch):
    import requests
    seq = [429, 200]

    class R:
        def __init__(self, code):
            self.status_code, self.headers, self.text = code, {"retry-after": "0"}, "slow down"

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R(seq.pop(0)))
    monkeypatch.setenv("GROQ_API_KEY", "x")
    slept = []
    llm = rb.LLM(sleep=slept.append)
    assert llm.complete("s", "u") == "{}" and slept == [0.0]


# ---------------------------------------------------------------- geocoding honesty

def test_geocode_rules():
    hit = {"lat": "18.76", "lon": "73.86", "addresstype": "village", "address": {"country_code": "in"}}
    assert gf.pick([hit]) == (18.76, 73.86, "locality")
    assert gf.pick([{**hit, "address": {"country_code": "us"}}]) is None          # outside India
    assert gf.pick([{**hit, "addresstype": "ocean", "type": "x", "class": "y"}]) is None
    assert gf.pick([{**hit, "addresstype": "building"}])[2] == "exact"
    doc = {"nodes": [{"id": "F1"}], "fac": {"F1": {"addr": "Chakan, Pune", "lat": None, "lon": None, "geo_prec": None},
                                              "F2": {"addr": None, "lat": None, "lon": None, "geo_prec": None}}}
    calls, cache = [], {}
    n = gf.geocode(doc, lambda a: calls.append(a) or (18.76, 73.86, "locality"), cache, sleep=lambda s: None)
    assert n == 1 and doc["fac"]["F1"]["geo_prec"] == "locality" and doc["fac"]["F2"]["lat"] is None and doc["nodes"][0]["lat"] == 18.76
    assert gf.geocode(doc, lambda a: pytest.fail("cached"), cache, sleep=lambda s: None) == 0
    assert gf.geocode({"fac": {"F3": {"addr": "Nowhere", "lat": None}}}, lambda a: None, {}, sleep=lambda s: None) == 1   # no match: stays without coordinates


def test_daily_quota_moves_to_the_next_model_and_ends_the_run_when_all_are_used(monkeypatch):
    import requests
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("GROQ_MODEL", "m-big")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "m-small")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    seen = []

    class R:
        def __init__(self, code, text=""):
            self.status_code, self.headers, self.text = code, {}, text

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 100}}

    def post(url, json=None, **k):
        seen.append(json["model"])
        if json["model"] == "m-big":
            return R(429, "Rate limit reached on tokens per day (TPD): Limit 200000")
        return R(200)
    monkeypatch.setattr(requests, "post", post)
    llm = rb.LLM(sleep=lambda s: None, clock=lambda: 0.0)
    assert llm.complete("s", "u") == "{}" and seen == ["m-big", "m-small"] and llm.tag == "groq:m-small"
    assert llm.complete("s", "u") == "{}" and seen[-1] == "m-small"          # the big model is not tried again today
    monkeypatch.setattr(requests, "post", lambda url, json=None, **k: R(429, "tokens per day (TPD)"))
    with pytest.raises(rb.LLMBudget):
        rb.LLM(sleep=lambda s: None, clock=lambda: 0.0).complete("s", "u")


@pytest.mark.parametrize("label,kept", [("Tata Motors Limited", True), ("Customer A", True), ("a leading semiconductor player", True),
                                         ("key suppliers", False), ("MSMEs / small producers", False), ("supply chain partners", False),
                                         ("large mining OEMs", False), ("North American recreational off-highway vehicle OEM", True)])
def test_groups_of_companies_are_not_counterparties(label, kept):
    q = "Our largest customer, Tata Motors Limited, accounted for 24% of our revenue"
    e, _, dropped = validate([edge(counterparty_name=None if label == "Customer A" else label, counterparty_anon_label="Customer A" if label == "Customer A" else None, quote=q)])
    assert bool(e) == kept, (label, dropped)
