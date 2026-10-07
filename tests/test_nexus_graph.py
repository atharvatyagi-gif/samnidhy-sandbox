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


def validate(edges, facs=(), pages=None):
    return rb.validate_answer({"edges": edges, "facilities": list(facs)}, pages or {12: PAGE12}, META, NOW, SRC["schema"])


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
    q = "Our largest customer, Acme Overseas GmbH, accounted for 24% of our revenue"
    e, _, _ = validate([edge(counterparty_name="Acme Overseas GmbH", quote=q)], pages={12: q + " during FY2024-25."})
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
    theirs = [{**validate([edge()])[0][0], "name": "Bosch Limited", "direction": "supplier", "wb": "purchases", "w": 0.05, "q": "Bosch Limited supplies us 5% of our purchases"}]
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
    with pytest.raises(rb.DiscoverError):                              # a blocked NSE is an error to retry, never "no filing"
        rb.discover(None, "X", SRC, NOW, get=boom)


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
    q = f"Our largest customer, {label}, accounted for 24% of our revenue"
    e, _, dropped = validate([edge(counterparty_name=None if label == "Customer A" else label, counterparty_anon_label="Customer A" if label == "Customer A" else None, quote=q)],
                             pages={12: q + " during FY2024-25."})
    assert bool(e) == kept, (label, dropped)


@pytest.mark.parametrize("label", ["parent company", "holding company", "its subsidiaries", "Siemens Group", "promoter group", "associates"])
def test_parents_and_related_groups_are_not_counterparties(label):
    e, _, dropped = validate([edge(counterparty_name=label)])
    assert e == [] and "group" in dropped[0]


# ---------------------------------------------------------------- the 2026-10-05 damage: a run without the stock universe

def test_audit_rejects_a_graph_assembled_without_the_universe_and_reassembly_repairs_it(tmp_path, monkeypatch):
    e, _, _ = validate([edge()])
    results = {"BOSCHLTD": rec("BOSCHLTD", e)}
    damaged = rb.assemble({"cos": {}}, results, [], [], 0.75, NOW)               # what a runner with no data/terminal/universe.json produced
    assert damaged["coverage"]["companies_total"] == 0 and not [n for n in damaged["nodes"] if n["k"] == "co"]
    problems = cg.audit(damaged)
    assert any("companies_total is 0" in p for p in problems) and any("BOSCHLTD" in p and "not a listed-company node" in p for p in problems)
    # repair from the saved edges with the universe present
    monkeypatch.setattr(rb, "OUT", tmp_path / "g.json")
    (tmp_path / "g.json").write_text(json.dumps(damaged), encoding="utf-8")
    monkeypatch.setattr(rb, "load_universe", lambda: STOCKS)
    fixed = rb.reassemble(log=lambda *a: None, now=NOW)
    assert fixed["coverage"]["companies_total"] == len(STOCKS) and cg.audit(fixed) == []
    assert any(n["k"] == "co" and n["id"] == "BOSCHLTD" for n in fixed["nodes"])


def test_the_builder_refuses_to_touch_the_graph_without_a_universe(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "TERM", tmp_path)                                     # no universe.json here
    monkeypatch.setattr(rb, "OUT", tmp_path / "g.json")
    (tmp_path / "g.json").write_text('{"keep": "me"}', encoding="utf-8")
    with pytest.raises(rb.NoUniverse):
        rb.load_universe()
    with pytest.raises(rb.NoUniverse):
        rb.reassemble(log=lambda *a: None)
    assert (tmp_path / "g.json").read_text(encoding="utf-8") == '{"keep": "me"}'
    assert rb.main(["--reassemble"]) == 0                                         # a message, never a crash and never a write
    assert (tmp_path / "g.json").read_text(encoding="utf-8") == '{"keep": "me"}'


def test_the_nexus_workflow_builds_the_universe_before_reading_filings():
    yml = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "nexus.yml").read_text(encoding="utf-8")
    assert yml.index("nse_eod.py") < yml.index("revenue_graph_builder.py")


# ---------------------------------------------------------------- coverage: which pages and which transcript candidates are read

def test_pages_that_state_a_share_beat_pages_that_only_repeat_topic_words():
    boiler = "Our value chain, plant and manufacturing facility, raw material, supplier and procurement policy, BRSR value chain, capacity and utilisation."
    share = "Our largest customer accounted for 24% of our revenue. Ind AS 108 operating segments. Customer A contributed 12% of revenue."
    pages = [(1, boiler), (2, share), (3, "Nothing relevant here.")]
    kw = SRC["keywords"]
    plain = rb.select_pages(pages, kw, 2, 1)
    weighted = rb.select_pages(pages, kw, 2, 1, bonus=SRC["page_bonus"])
    assert [n for n, _ in plain] == [1] and [n for n, _ in weighted] == [2]          # with one slot, the sustainability page used to win


def test_related_party_tables_are_selected():
    rp = "Name of the related party | Nature of transaction | Purchase of goods | Sale of goods | Holding company | Fellow subsidiary"
    assert [n for n, _ in rb.select_pages([(5, rp)], SRC["keywords"], 2, 5, bonus=SRC["page_bonus"])] == [5]


def test_transcripts_rank_above_scheduling_notices_and_newest_first():
    def row(desc, name, day):
        return {"desc": desc, "attchmntText": "", "attchmntFile": f"https://x/{name}.pdf", "an_dt": f"{day:02d}-Sep-2026 10:00:00"}
    rows = [row("Schedule of earnings call", "notice1", 20), row("Transcript of earnings call", "tr_old", 1), row("Audio recording of earnings call", "audio", 25),
            row("Transcript of earnings call", "tr_new", 10), row("Analyst meet intimation", "notice2", 28)]
    get = lambda path, params, referer=None: [] if "annual" in path else rows
    docs = rb.discover(None, "X", {**SRC, "transcript_candidates": 3}, now=NOW.replace(month=10), get=get)
    urls = [d["url"].rsplit("/", 1)[1] for d in docs if d["kind"] == "transcript"]
    assert urls[:2] == ["tr_new.pdf", "tr_old.pdf"] and len(urls) == 3 and urls[2] in ("notice2.pdf", "notice1.pdf", "audio.pdf")    # notices only fill the remaining slots


def test_a_failed_filing_list_is_an_error_not_an_empty_company():
    def boom(path, params, referer=None):
        raise RuntimeError("NSE paused after 5 failures")
    with pytest.raises(rb.DiscoverError):
        rb.discover(None, "X", SRC, now=NOW, get=boom)
    ok_empty = lambda path, params, referer=None: []                                # NSE answered: there really is nothing
    assert rb.discover(None, "X", SRC, now=NOW, get=ok_empty) == []


def test_run_does_not_record_a_company_whose_filing_list_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "OUT", tmp_path / "g.json")
    monkeypatch.setattr(rb, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(rb, "PACE_S", 0)
    monkeypatch.setattr(rb, "load_universe", lambda: STOCKS)
    monkeypatch.setattr(rb, "discover", lambda *a, **k: (_ for _ in ()).throw(rb.DiscoverError("blocked")))
    doc, report = rb.run(["BOSCHLTD", "TATAMOTORS"], 5, False, False, None, None, None, now=NOW, log=lambda *a: None)
    assert doc["cos"] == {} and all("will be retried" in r[1] or r[1].startswith("stopped") for r in report)


def test_audit_sheet_samples_across_companies_and_shows_the_quote_and_fields():
    import graph_audit_sheet as gs
    e, _, _ = validate([edge()])
    d = doc_from({"BOSCHLTD": rec("BOSCHLTD", e)})
    rows = gs.sample(d, 5, 1)
    text = gs.render(d, rows)
    assert len(rows) == 1 and "Our largest customer, Tata Motors Limited" in text and "share: **24.0%**" in text and "share basis: **revenue**" in text and "page 12" in text
    many = {"edges": [{"id": f"e{i}", "own": "AAA" if i < 30 else "BBB", "s": "AAA", "d": "X", "vq": True} for i in range(40)], "nodes": [], "fac": {}}
    picked = gs.sample(many, 10, 3)
    assert len(picked) == 10 and {p[0] for p in picked} == {"AAA", "BBB"} and sum(p[0] == "BBB" for p in picked) == 5     # round-robin: the small company is not drowned out


def test_the_default_order_reads_the_priority_companies_first(tmp_path, monkeypatch):
    stocks = [{"s": s, "n": s, "board": "Main", "series": "EQ", "n500": i < 2, "avgv20": 1, "c": 1} for i, s in enumerate(["BIG1", "BIG2", "PRIO1", "PRIO2", "DONE1"])]
    monkeypatch.setattr(rb, "OUT", tmp_path / "g.json")
    monkeypatch.setattr(rb, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(rb, "PACE_S", 0)
    monkeypatch.setattr(rb, "load_universe", lambda: stocks)
    (tmp_path / "g.json").write_text(json.dumps({"cos": {"DONE1": {"at": "2026-01-01T00:00:00Z"}}, "edges": [], "nodes": [], "fac": {}}), encoding="utf-8")
    real = rb.load_json
    monkeypatch.setattr(rb, "load_json", lambda p, d=None: {"rows": [{"sym": "PRIO2"}, {"sym": "PRIO1"}, {"sym": "DONE1"}]} if str(p).endswith("nexus_priority.json") else real(p, d))
    seen = []
    monkeypatch.setattr(rb, "discover", lambda sess, sym, src, now=None: seen.append(sym) or [])
    rb.run([], 3, False, True, None, None, None, now=NOW, log=lambda *a: None)
    assert seen == ["PRIO2", "PRIO1", "BIG1"]                    # priority order first, a finished company is not repeated, then the usual n500/liquidity order


def test_a_second_key_adds_its_own_models_after_the_first_keys_and_is_used_for_them(monkeypatch):
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY_1", "GEMINI_API_KEY_1", "GROQ_MODEL", "GEMINI_MODEL", "GROQ_FALLBACK_MODELS", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "g0")
    monkeypatch.setenv("GROQ_API_KEY_1", "g1")
    monkeypatch.setenv("GEMINI_API_KEY_1", "m1")
    llm = rb.LLM()
    assert [c for c in llm.cands if c[0] == "groq"] == [("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b"), ("groq", "qwen/qwen3.8-27b"),
                                                       ("groq", "openai/gpt-oss-120b#1"), ("groq", "openai/gpt-oss-20b#1"), ("groq", "qwen/qwen3.8-27b#1")]
    assert [c for c in llm.cands if c[0] == "gemini"] == [("gemini", "gemini-flash-latest#1"), ("gemini", "gemini-flash-lite-latest#1")]
    seen = []

    class R:
        status_code, headers, text = 200, {}, ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 5}}
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **k: seen.append((k["json"]["model"], k["headers"]["Authorization"])) or R())
    llm.sleep = lambda s: None
    llm.complete("s", "u")
    llm.dead.update(c for c in llm.cands if "#" not in c[1])                       # the first key's day is over
    llm.complete("s", "u")
    assert seen == [("openai/gpt-oss-120b", "Bearer g0"), ("openai/gpt-oss-120b", "Bearer g1")] and llm.tokens


# ---------------------------------------------------------------- the two error types found by the audit sheet

def test_deals_awards_and_things_not_yet_happened_are_not_supply_relationships():
    bad = ["The acquisition of Senn Chemicals AG in Switzerland, completed during the year, marked our entry into the peptide CDMO space",
           "we are expecting now new bids to come from NTPC and others, NHPC, NTPC for pumped hydro",
           "we are in discussions with Tata Steel and other procurers to supply to them",
           "We got a Best Award from Siemens, the Top Supplier Recognition Award, and of course",
           "As you would be aware, during the year, we invested Rs 600 crores in Goldi Solar.",                                   # an investment, not a purchase
           "Freelander is our JLR brand, and it has been licensed to Chery for manufacturing their car.",                       # a licence
           "you will see a huge amount of improvement in Odisha DISCOM",                                                         # no transaction in the sentence at all
           "Neo Pharma Private Limited Other Related Party 7 9",                                                                  # a table row that does not say what the 7 and 9 are
           "In fact, we are going to expand our lines for both Tata Motors as well as Maruti."]                                   # no word of a sale or a purchase
    good = ["we supply parts to Tata Motors and Maruti.", "the biggest buyer is of course NTPC and we do work with them very closely",
            "Our largest customer, Tata Motors Limited, accounted for 24% of our revenue", "The Karcham project has a PPA with PTC India Limited on a long-term basis",
            "We acquired raw material from Acme and purchased components worth 5 crore"]            # "acquired" plus a purchase: a supply sentence
    assert not any(rb.supply_quote_ok(q) for q in bad) and all(rb.supply_quote_ok(q) for q in good)


def test_a_descriptor_is_an_anonymous_customer_never_a_company_called_that():
    for n in ("a major customer based in USA", "Customer A", "our largest supplier", "The single largest customer"):
        assert rb.is_generic_name(n), n
    for n in ("Tata Motors Limited", "Siemens AG", "Reliance Industries", "Customer Support Services Limited", "Largest Customer Care Pvt Ltd"):
        assert not rb.is_generic_name(n), n
    quote = "Revenue from the major customer based in USA represented 29,477.8 million of the Group's total revenues"
    pages = {3: quote + " in the Pharmaceuticals segment."}
    e = {"counterparty_name": "major customer based in USA", "counterparty_anon_label": None, "direction": "customer", "rel": "supplies", "w": None, "w_basis": None,
         "period": "FY2025-26", "component": None, "page": 3, "quote": quote}
    good, _, dropped = rb.validate_answer({"edges": [e], "facilities": []}, pages, META, NOW, SRC["schema"])
    assert good and good[0]["name"] is None and good[0]["anon"] == "major customer based in USA" and not dropped


def test_saved_edges_are_cleaned_by_the_same_rules_when_the_graph_is_reassembled():
    ix = rb.NameIndex(STOCKS)
    bad_q = "The acquisition of Senn Chemicals AG in Switzerland, completed during the year, marked our entry into peptides"
    e1 = {"own": "BOSCHLTD", "s": "BOSCHLTD", "d": "EXT_SENN", "rel": "supplies", "w": None, "wb": None, "per": "FY2025-26", "tier": 1, "comp": None, "conf": 0.8, "kind": "disclosed",
          "url": "u", "pg": 1, "q": bad_q, "vq": True, "doc": "annual", "cpn": "Senn Chemicals AG"}
    e2 = {**e1, "d": "EXT_MAJOR_CUSTOMER_BASED_IN_USA", "q": "Revenue from the major customer based in USA represented 29,477.8 million", "cpn": "major customer based in USA"}
    d = rb.assemble({"cos": {}, "edges": [e1, e2]}, {}, STOCKS, [], 0.75, NOW)
    assert len(d["edges"]) == 1 and d["edges"][0]["d"] == "ANON_BOSCHLTD_MAJOR_CUSTOMER_BASED_IN_USA"
    assert [n["k"] for n in d["nodes"] if n["id"].startswith("ANON_")] == ["anon"] and cg.audit(d) == []


def test_an_edge_whose_quote_does_not_name_the_counterparty_is_not_kept():
    assert rb.names_the_counterparty("Maharashtra Scooters Ltd.", "Maharashtra Scooters Limited Purchases 0.18") is True
    assert rb.names_the_counterparty("GE", "these are all commercial activities as per the purchase order with GE, what") is True
    assert rb.names_the_counterparty("Maharashtra Scooters Ltd.", "Purchases - - 0.18 -") is False                       # a table row with no name in it
    assert rb.names_the_counterparty("", "anything") is False
    pages = {12: "Purchases 0.18 0.2 and later Maharashtra Scooters Limited is a related party."}
    e = edge(counterparty_name="Maharashtra Scooters Ltd.", w=None, w_basis=None, quote="Purchases 0.18 0.2", direction="supplier", period="FY2024-25")
    good, _, dropped = rb.validate_answer({"edges": [e], "facilities": []}, pages, META, NOW, SRC["schema"])
    assert good == [] and any("does not name the counterparty" in d for d in dropped)
    pages = {12: "We make purchases from Maharashtra Scooters Limited, a related party, every year."}
    ok_e = edge(counterparty_name="Maharashtra Scooters Ltd.", w=None, w_basis=None, quote="We make purchases from Maharashtra Scooters Limited", direction="supplier")
    good, _, dropped = rb.validate_answer({"edges": [ok_e], "facilities": []}, pages, META, NOW, SRC["schema"])
    assert len(good) == 1 and not dropped
    saved = {"own": "BOSCHLTD", "s": "EXT_X", "d": "BOSCHLTD", "rel": "supplies", "w": None, "wb": None, "per": "FY2025-26", "tier": 1, "comp": None, "conf": 0.8, "kind": "disclosed",
             "url": "u", "pg": 1, "q": "Purchases 0.03 - 0.65 -", "vq": True, "doc": "annual", "cpn": "Bajaj Auto Technology Ltd."}
    assert rb.clean_saved_edge(saved) is None and rb.clean_saved_edge({**saved, "q": "Purchases from Bajaj Auto Technology Ltd. 0.03"}) is not None


def test_who_a_counterparty_may_not_be_and_what_a_label_must_be():
    for n in ("Indonesia", "India", "Saudi Arabia", "United States"[:0] or "USA", "London Bullion Market Association (LBMA)", "local enterprises", "third-party consumers", "government shipyards",
              "Steel Melt Shops at TSJ, TSK", "Dealers", "tier 1 suppliers"):
        assert rb.bad_counterparty(n), n
    for n in ("Tata Motors Limited", "Pawan Hans", "Chemours", "Maharashtra DISCOM", "Liebherr Aerospace", "INOX Clean"):
        assert not rb.bad_counterparty(n), n
    assert rb.label_in_quote("Customer A", "Customer A contributed 31% of revenue") and not rb.label_in_quote("Customer A", "the respective C&I customers that will finally be contracted")
    assert rb.label_in_quote("single customer based out of Japan", "overseas sales are made to a single customer based out of Japan")


def test_a_share_needs_wording_that_matches_its_basis_and_a_period_cannot_be_in_the_future():
    assert rb.basis_in_quote("revenue", "accounted for 24% of our revenue") and not rb.basis_in_quote("revenue", "around 80% of total transactions with Siemens AG")
    assert rb.basis_in_quote("purchases", "89% of procurement is sourced locally") and not rb.basis_in_quote("purchases", "around 80% of total transactions with Siemens AG")
    q = "We bought equipment from Siemens AG; these constitute around 80% of total transactions with Siemens AG in past years."
    good, _, dropped = validate([edge(counterparty_name="Siemens AG", w=0.8, w_basis="purchases", quote=q, direction="supplier", period="past years")], pages={12: q})
    assert good and good[0]["w"] is None and good[0]["wb"] is None                                  # kept as a link, but the 80% is not a purchases share
    none_q = "Overall, these transactions constitute around 80% of total transactions with Siemens AG in past years."
    assert validate([edge(counterparty_name="Siemens AG", w=0.8, w_basis="purchases", quote=none_q, direction="supplier", period="past years")], pages={12: none_q})[0] == []      # and with no word of a sale or purchase it is no link at all
    qf = "Software services provided by JPL to RRL for the period FY 2027-28 to FY 2031-32 are supplied as agreed."
    good, _, dropped = validate([edge(counterparty_name="JPL", w=None, w_basis=None, quote=qf, direction="supplier", period="FY 2027-28 to FY 2031-32")], pages={12: qf})
    assert good == [] and any("future" in d for d in dropped)
    ql = "Customer A has not been named; the largest customer takes 31% of revenue."
    good, _, dropped = validate([edge(counterparty_name=None, counterparty_anon_label="Customer B", w=None, w_basis=None, quote=ql)], pages={12: ql})
    assert good == [] and any("anonymous label" in d for d in dropped)


def test_unnamed_counterparties_get_the_same_scrutiny_as_named_ones():
    for label, q in (("Indonesia", "the Indonesia order and the advance that we received from Indonesia helped cash flow"), ("local enterprises", "89% of procurement is sourced from local enterprises"),
                     ("Supplier", "representing 80% of our total tier 1 supplier expenditure, we purchase from them")):
        e = edge(counterparty_name=None, counterparty_anon_label=label, w=None, w_basis=None, quote=q, direction="supplier")
        good, _, dropped = validate([e], pages={12: q})
        assert good == [] and dropped, label
    ok_q = "The Company has one customer whose revenue represents 37% of the Company's total revenue"
    good, _, _ = validate([edge(counterparty_name=None, counterparty_anon_label="one customer", w=0.37, w_basis="revenue", quote=ok_q)], pages={12: ok_q})
    assert len(good) == 1 and good[0]["anon"] == "one customer" and good[0]["w"] == 0.37


def test_a_quota_reply_without_the_word_day_does_not_stall_the_run(monkeypatch):
    import requests
    monkeypatch.setenv("GROQ_API_KEY", "x")
    slept = []

    class R:
        status_code, headers, text = 429, {}, "Resource has been exhausted (e.g. check quota)."

        def raise_for_status(self):
            pass
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    llm = rb.LLM(sleep=slept.append, clock=lambda: 0.0)
    with pytest.raises(rb.LLMBudget):
        llm.complete("s", "u")
    assert len(slept) <= 2 * len(llm.cands), "each model is given up after three rate-limit replies, not retried for minutes"
