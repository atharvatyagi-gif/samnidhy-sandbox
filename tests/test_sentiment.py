"""Sentiment engine: matching, weighting, the evidence rule, retail/flow/geo parts, transcripts. No network."""
import itertools
import json
import math
import sys
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_sentiment_engine as se  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
ALIASES = json.loads((ROOT / "data" / "config" / "news_aliases.json").read_text(encoding="utf-8"))
STOCKS = [
    {"s": "TCS", "n": "Tata Consultancy Services Limited", "series": "EQ", "board": "Main", "ind": "Information Technology", "val_cr": 900},
    {"s": "TATASTEEL", "n": "Tata Steel Limited", "series": "EQ", "board": "Main", "ind": "Metals & Mining", "val_cr": 500},
    {"s": "INFY", "n": "Infosys Limited", "series": "EQ", "board": "Main", "ind": "Information Technology", "val_cr": 800},
    {"s": "HDFCBANK", "n": "HDFC Bank Limited", "series": "EQ", "board": "Main", "ind": "Financial Services", "val_cr": 700},
    {"s": "LT", "n": "Larsen & Toubro Limited", "series": "EQ", "board": "Main", "ind": "Construction", "val_cr": 300},
    {"s": "OIL", "n": "Oil India Limited", "series": "EQ", "board": "Main", "ind": "Oil Gas & Consumable Fuels", "val_cr": 50},
    {"s": "ADANIENT", "n": "Adani Enterprises Limited", "series": "EQ", "board": "Main", "ind": "Metals & Mining", "val_cr": 100},
    {"s": "ADANIPORTS", "n": "Adani Ports and Special Economic Zone Limited", "series": "EQ", "board": "Main", "ind": "Services", "val_cr": 100},
    {"s": "GOLDBEES", "n": "Nippon Gold ETF", "series": "EQ", "board": "Main", "etf": True, "val_cr": 10},
    {"s": "SMEJUNK", "n": "Sme Junk Limited", "series": "SM", "board": "SME", "val_cr": 1},
]
HOUSES = {"houses": [{"id": "adani", "symbols": ["ADANIENT", "ADANIPORTS"]}, {"id": "tata", "symbols": ["TCS", "TATASTEEL"]}]}
M = se.Matcher(STOCKS, ALIASES, HOUSES)
PUB = ALIASES["indian_publishers"]


def item(title, age_h=1.0, source="Mint", url=None, **kw):
    return se.Item(title, url or f"http://x/{abs(hash((title, age_h)))}", source, NOW - timedelta(hours=age_h), **kw)


def test_levels_at_the_boundaries():
    got = {sc: se.level(sc) for sc in (-100, -60.01, -60, -59.9, -20, -19.9, 19.9, 20, 59.9, 60, 100)}
    assert got == {-100: "BAD", -60.01: "BAD", -60: "BAD", -59.9: "POOR", -20: "POOR", -19.9: "NEUTRAL", 19.9: "NEUTRAL", 20: "GOOD", 59.9: "GOOD", 60: "EXCELLENT", 100: "EXCELLENT"}


# ---------------------------------------------------------------- matching
def test_symbol_name_alias_and_cashtag():
    assert M.match("TCS wins mega deal")[0]["TCS"] == (1.0, "symbol")
    assert M.match("Why $INFY fell today")[0]["INFY"] == (1.0, "symbol")
    assert M.match("Tata Consultancy Services posts profit")[0]["TCS"] == (0.9, "name")
    assert M.match("Larsen and Toubro bags order")[0]["LT"][1] == "name"
    assert M.match("L&T order book swells")[0]["LT"][1] == "name"
    assert M.match("HDFC Bank names new CEO")[0]["HDFCBANK"] == (0.9, "name")


def test_stoplist_short_symbols_and_shouting_headlines_never_match():
    assert "OIL" not in M.match("OIL prices slump on demand worries")[0]            # stoplisted word, not Oil India
    assert "LT" not in M.match("LT says it is hiring")[0]                           # 2 characters: never read as a ticker
    assert M.match("STOCKS TO WATCH: TCS INFY HDFCBANK RESULTS")[0] == {}           # an all-caps headline is not evidence
    assert M.match("Tata Steel and Tata Consultancy Services lead gains")[0].keys() == {"TATASTEEL", "TCS"}


def test_etfs_and_sme_are_never_matched():
    assert "GOLDBEES" not in M.match("GOLDBEES sees inflows, Nippon Gold ETF up")[0]
    assert "SMEJUNK" not in M.match("SMEJUNK jumps; Sme Junk Limited rallies")[0]


def test_ambiguous_auto_aliases_are_dropped_but_manual_ones_kept():
    twins = [{"s": "AAA", "n": "Bharat Widgets Limited", "series": "EQ", "board": "Main"}, {"s": "BBB", "n": "Bharat Widgets Corporation", "series": "EQ", "board": "Main"}]
    m = se.Matcher(twins, {**ALIASES, "manual": {}}, {})
    assert m.match("Bharat Widgets surges")[0] == {}                                # two companies share the name: no guess


def test_group_story_only_when_no_company_is_named():
    stocks, _, _ = M.match("Adani Group faces fresh scrutiny")
    assert stocks == {"ADANIENT": (0.5, "group"), "ADANIPORTS": (0.5, "group")}
    stocks, _, _ = M.match("Adani Group firm Adani Ports bags contract")
    assert stocks == {"ADANIPORTS": (0.9, "name")}                                  # a specific company is named: no group spill-over


def test_sector_and_market_context_flags():
    st, sectors, market = M.match("Banks rally as Sensex climbs on FII buying")
    assert st == {} and "Financial Services" in sectors and market
    assert M.match("Quiet day")[1:] == (set(), False)


def test_hint_from_a_company_query_needs_the_name_in_the_title():
    assert M.match("Tata Consultancy Services gets order", hint="TCS")[0]["TCS"][1] == "name"
    assert M.match("Weather turns cold in Delhi", hint="TCS")[0] == {}


# ---------------------------------------------------------------- building the document
def build(items_scores, flow=None, geo=None, retail=None):
    return se.build_sentiment(items_scores, M, flow, {}, geo, retail, PUB, NOW)


def test_one_headline_follows_the_formula():
    it = item("Tata Consultancy Services wins deal", age_h=0)
    doc = build([(it, 0.8)])
    w = 0.9 * 1.0 * 1.0                                                              # name match x Indian publisher x no decay
    news = w * 0.8 / (w + 1)
    assert doc["stocks"]["TCS"]["parts"]["news"] == pytest.approx(round(news, 3), abs=1e-3)
    assert doc["stocks"]["TCS"]["sc"] == pytest.approx(round(100 * news, 1), abs=0.1)


def test_decay_and_source_weight():
    fresh = build([(item("Infosys wins deal", 0), 0.9)])["stocks"]["INFY"]["sc"]
    old = build([(item("Infosys wins deal", 48), 0.9)])["stocks"]["INFY"]["sc"]
    foreign = build([(item("Infosys wins deal", 0, source="Reuters", url="http://reuters.com/a"), 0.9)])["stocks"]["INFY"]["sc"]
    assert fresh > foreign > old > 0
    assert se.source_weight("Reuters", "http://reuters.com/x", PUB) == 0.7 and se.source_weight("Mint", "x", PUB) == 1.0


def test_no_specific_evidence_means_no_score_not_neutral():
    doc = build([(item("Banks rally as Sensex climbs", 1), 0.9), (item("Nothing about any company", 1), -0.5)])
    assert doc["stocks"] == {} and doc["scored"] == 0                                # sector + market context never creates a score
    doc = build([(item("Infosys wins deal", 80), 0.9)])                              # older than the 72 h evidence window
    assert "INFY" not in doc["stocks"]


def test_sector_and_market_context_nudges_a_stock_that_has_evidence():
    base = build([(item("Infosys wins deal", 1), 0.4)])["stocks"]["INFY"]["parts"]["news"]
    ctx = build([(item("Infosys wins deal", 1), 0.4), (item("IT stocks rally; Sensex surges", 1), 1.0)])["stocks"]["INFY"]["parts"]["news"]
    assert ctx > base


def test_flow_part_and_weight_renormalisation():
    it = [(item("Infosys wins deal", 0), 0.8)]
    with_flow = build(it, flow=-0.5)["stocks"]["INFY"]
    no_flow = build(it, flow=None)["stocks"]["INFY"]
    assert "flow" in with_flow["parts"] and "flow" not in no_flow["parts"]
    news = no_flow["parts"]["news"]
    assert no_flow["sc"] == pytest.approx(100 * news, abs=0.2)                       # news alone: weight renormalised to 1
    assert with_flow["sc"] == pytest.approx(100 * (0.6 / 0.75 * news + 0.15 / 0.75 * -0.5), abs=0.2)


def test_geo_adjustment_signs_and_clip():
    geo = {"regions": [{"score": 100, "exposure": [{"sym": "INFY", "dir": "+"}, {"ind": "Metals & Mining", "dir": "-"}]},
                       {"score": None, "exposure": [{"sym": "TCS", "dir": "-"}]},                       # baseline still building: ignored
                       {"score": 100, "exposure": [{"sym": "INFY", "dir": "+"}]}, {"score": 100, "exposure": [{"sym": "INFY", "dir": "+"}]}]}
    assert se.geo_adjust("INFY", "Information Technology", geo) == 0.2              # 3 x 0.2 clipped
    assert se.geo_adjust("TATASTEEL", "Metals & Mining", geo) == pytest.approx(-0.2)
    assert se.geo_adjust("TCS", "Information Technology", geo) == 0.0
    assert se.geo_adjust("TCS", None, None) == 0.0


def test_score_is_clipped_to_plus_minus_100():
    doc = build([(item(f"Infosys wins deal {i}", 0), 1.0) for i in range(40)], geo={"regions": [{"score": 100, "exposure": [{"sym": "INFY", "dir": "+"}]}]}, flow=1.0)
    assert doc["stocks"]["INFY"]["sc"] <= 100


def test_items_are_capped_at_eight_newest_first():
    doc = build([(item(f"Infosys headline {i}", i * 0.5), 0.1) for i in range(12)])
    its = doc["stocks"]["INFY"]["items"]
    assert len(its) == 8 and [i[3] for i in its] == sorted(i[3] for i in its) and doc["stocks"]["INFY"]["n"] == 12


# ---------------------------------------------------------------- retail
def post(author, title, votes=0, comments=0, age=1.0):
    return se.Item(title, f"http://r/{author}{abs(hash(title))}", "r/IndianStreetBets", NOW - timedelta(hours=age), "reddit", None, author, "", votes, comments)


def test_retail_needs_five_distinct_authors_and_counts_each_once():
    four = [(post(f"a{i}", "TCS looks strong"), 0.8) for i in range(4)]
    assert se.retail_scores(four, M, NOW)["TCS"] == (None, 4)
    spam = four + [(post("a0", "TCS again"), 0.8), (post("a0", "TCS third"), 0.8)]          # same author three times
    assert se.retail_scores(spam, M, NOW)["TCS"] == (None, 4)
    five = four + [(post("a9", "TCS looks strong"), 0.8)]
    sc, n = se.retail_scores(five, M, NOW)["TCS"]
    assert n == 5 and sc == pytest.approx(5 * math.exp(-1 / 8) * 0.8 / (5 * math.exp(-1 / 8) + 3), abs=1e-6)


def test_retail_ignores_old_posts_and_group_or_sector_matches():
    old = [(post(f"a{i}", "TCS looks strong", age=30), 0.9) for i in range(6)]
    assert se.retail_scores(old, M, NOW) == {}
    grp = [(post(f"g{i}", "Adani Group is back"), 0.9) for i in range(6)]
    assert se.retail_scores(grp, M, NOW) == {}


def test_retail_votes_raise_weight():
    hot = [(post(f"h{i}", "INFY rocket", votes=500, comments=200), 1.0) for i in range(5)] + []
    cold = [(post(f"c{i}", "INFY rocket"), 1.0) for i in range(5)]
    assert se.retail_scores(hot, M, NOW)["INFY"][0] > se.retail_scores(cold, M, NOW)["INFY"][0]


def test_retail_flows_into_the_stock_score():
    r = {"INFY": (0.5, 6)}
    doc = build([(item("Infosys wins deal", 0), 0.2)], retail=r)
    assert "retail" in doc["stocks"]["INFY"]["parts"] and doc["stocks"]["INFY"]["rn"] == 6
    only_retail = build([], retail=r)
    assert only_retail["stocks"]["INFY"]["parts"]["retail"] == 0.5 and "news" not in only_retail["stocks"]["INFY"]["parts"]
    assert "INFY" not in build([], retail={"INFY": (None, 3)})["stocks"]               # fewer than 5 authors: nothing to show


# ---------------------------------------------------------------- flow
def test_flow_formula_and_scale_switch():
    days = [{"fii": {"net_cr": -4000}, "dii": {"net_cr": 2000}} for _ in range(4)]
    v, info = se.flow_score({"days": days})
    assert v == pytest.approx(math.tanh((0.7 * -4000 + 0.3 * 2000) / 4000), abs=1e-4) and info["scale"] == 4000 and "fixed" in info["scale_kind"]
    many = [{"fii": {"net_cr": -4000 + (i % 5) * 1500}, "dii": {"net_cr": 2000}} for i in range(30)]
    v2, info2 = se.flow_score({"days": many})
    assert info2["scale_kind"] == "60-day std" and info2["scale"] != 4000
    assert se.flow_score({"days": []})[0] is None and se.flow_score({})[0] is None


# ---------------------------------------------------------------- scoring backends
def test_lexicon_fallback_is_signed():
    neg, pos = se._lexicon()
    assert se.lexicon_score("Shares plunge on fraud fears", neg, pos) < 0 < se.lexicon_score("Company wins deal, shares rally on peace talks", neg, pos)
    fb = object.__new__(se.Finbert)
    fb.ok, fb.method, fb.neg, fb.pos, fb.cache = False, "lexicon", neg, pos, {}
    out = fb.score(["Shares plunge on fraud fears", "Shares plunge on fraud fears"])
    assert out[0] == out[1] < 0 and len(fb.cache) == 1                               # cached by text


def test_real_finbert_separates_good_and_bad_news():
    fb = se.Finbert.get()
    if not fb.ok:
        pytest.skip("FinBERT not installed or not cached here")
    good, bad, flat = fb.score(["Reliance posts record quarterly profit, beats estimates", "Adani shares plunge after fraud allegations", "Company announces board meeting date"])
    assert good > 0.5 and bad < -0.5 and abs(flat) < 0.5


# ---------------------------------------------------------------- transcripts
TRANSCRIPT = ("Good morning. " + "We delivered strong growth and margins improved. " * 30 + " Question and Answer session. "
              + "Analyst: why did costs rise? Management: the outlook is uncertain and we cannot say. " * 30)


def fake_scorer(texts):
    return [(-0.5 if "uncertain" in t else 0.5) for t in texts]


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


def groq_ok(payload):
    return Resp(200, {"choices": [{"message": {"content": json.dumps(payload)}}]})


def test_local_transcript_splits_at_qa_and_reports_the_gap():
    r = se.local_transcript(TRANSCRIPT, fake_scorer)
    assert r["prepared_tone"] == 0.5 and r["qa_tone"] == -0.5 and r["qa_gap"] == -1.0 and r["method"] == "local"


def test_no_key_uses_local_path_and_short_text_is_skipped():
    r = se.score_transcript(TRANSCRIPT, "TCS", env={}, scorer=fake_scorer)
    assert r["method"] == "local" and r["symbol"] == "TCS"
    assert se.score_transcript("too short", "TCS", env={}, scorer=fake_scorer) is None


def test_groq_path_truncates_quotes_and_is_cached():
    calls = []
    long_quote = " ".join(f"w{i}" for i in range(60))
    def post(url, **kw):
        calls.append(url)
        return groq_ok({"tone": -0.4, "hedging_ratio": 0.3, "prepared_tone": 0.2, "qa_tone": -0.6, "qa_gap": -0.8, "evidence": [long_quote, "b", "c", "d"], "confidence": 0.7})
    cache = {}
    r = se.score_transcript(TRANSCRIPT, "TCS", cache=cache, key="http://pdf/1", post=post, env={"GROQ_API_KEY": "k"}, scorer=fake_scorer)
    assert r["method"] == "llm" and r["tone"] == -0.4 and len(r["evidence"]) == 3 and len(r["evidence"][0].split()) == 25
    assert "groq.com" in calls[0]
    se.score_transcript(TRANSCRIPT, "TCS", cache=cache, key="http://pdf/1", post=post, env={"GROQ_API_KEY": "k"}, scorer=fake_scorer)
    assert len(calls) == 1                                                                    # second call came from the cache


def test_rate_limit_retries_then_falls_back_and_bad_json_falls_back():
    seq = itertools.repeat(Resp(429))                                                          # every model keeps saying "slow down"
    r = se.score_transcript(TRANSCRIPT, "TCS", post=lambda *a, **k: next(seq), env={"GROQ_API_KEY": "k"}, scorer=fake_scorer, sleep=lambda s: None)
    assert r["method"] == "local"
    seq2 = iter([Resp(429), groq_ok({"tone": 0.1, "qa_gap": 0})])
    r2 = se.score_transcript(TRANSCRIPT, "TCS", post=lambda *a, **k: next(seq2), env={"GROQ_API_KEY": "k"}, scorer=fake_scorer, sleep=lambda s: None)
    assert r2["method"] == "llm"
    bad = se.score_transcript(TRANSCRIPT, "TCS", post=lambda *a, **k: Resp(200, {"choices": [{"message": {"content": "not json"}}]}), env={"GROQ_API_KEY": "k"}, scorer=fake_scorer)
    assert bad["method"] == "local"


def test_gemini_used_when_only_that_key_exists():
    seen = []
    def post(url, **kw):
        seen.append(url)
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps({"tone": 0.3, "qa_gap": 0.1, "evidence": []})}]}}]})
    r = se.score_transcript(TRANSCRIPT, "TCS", post=post, env={"GEMINI_API_KEY": "g"}, scorer=fake_scorer)
    assert r["method"] == "llm" and "generativelanguage" in seen[0]


# ---------------------------------------------------------------- choosing Google News symbols, and a whole cycle
def test_symbol_choice_covers_sweeps_top_liquid_and_rotates():
    stocks = [{"s": f"S{i:03d}", "series": "EQ", "board": "Main", "val_cr": 1000 - i} for i in range(200)]
    state = {}
    a = se.choose_symbols(stocks, {"S150"}, state, top_n=10, rotate=25)
    assert a[0] == "S150" and "S000" in a and len(a) == 1 + 10 + 25
    b = se.choose_symbols(stocks, {"S150"}, state, top_n=10, rotate=25)
    assert set(a[11:]).isdisjoint(b[11:])                                                       # the rotating batch moved on


def test_full_cycle_with_fake_network_and_scorer(tmp_path, monkeypatch):
    for name, val in {"UNIVERSE": tmp_path / "u.json", "ALIASES": ROOT / "data/config/news_aliases.json", "HOUSES": tmp_path / "h.json", "WIRE": tmp_path / "w.json",
                      "FIIDII": tmp_path / "f.json", "GEO": tmp_path / "g.json", "CACHE": tmp_path / "cache"}.items():
        monkeypatch.setattr(se, name, val)
    (tmp_path / "u.json").write_text(json.dumps({"stocks": STOCKS}))
    (tmp_path / "h.json").write_text(json.dumps(HOUSES))
    (tmp_path / "w.json").write_text(json.dumps({"groups": [{"id": "india", "sources": [{"name": "Economic Times · Markets", "items": [{"t": "Infosys wins deal", "u": "http://et/1", "age_min": 30}]}]}]}))
    (tmp_path / "f.json").write_text(json.dumps({"days": [{"fii": {"net_cr": 1000}, "dii": {"net_cr": 500}}]}))
    rss = b"<rss><channel><item><title>Tata Consultancy Services shares jump</title><link>http://mint/1</link><pubDate>Fri, 02 Oct 2026 11:00:00 GMT</pubDate></item></channel></rss>"

    class Scorer:
        method = "finbert"
        calls = 0
        def score(self, texts):
            Scorer.calls += len(texts)
            return [0.6 for _ in texts]

    doc = se.run_cycle(Namespace(no_google=True, no_reddit=True), NOW, Scorer(), lambda url, params=None: rss if "livemint" in url else None, lambda s: None)
    assert {"INFY", "TCS"} <= set(doc["stocks"]) and doc["method"] == "finbert" and doc["headlines_scored"] == 2           # Mint\x27s two feeds returned the same story: counted once
    assert any("Per-company Google News" in n for n in doc["notes"])
    first_calls = Scorer.calls
    se.run_cycle(Namespace(no_google=True, no_reddit=True), NOW, Scorer(), lambda url, params=None: rss if "livemint" in url else None, lambda s: None)
    assert Scorer.calls == first_calls                                                           # every headline is scored only once (store)
    assert len(json.loads((tmp_path / "cache" / "news_store.json").read_text())) == 2


# ---------------------------------------------------------------- the free-tier model chain
def gem_ok(payload):
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})


def test_default_models_are_current_names_not_retired_ones():
    assert "llama-3.3-70b-versatile" not in " ".join(se.DEFAULT_GROQ) and se.DEFAULT_GROQ[0] == "openai/gpt-oss-120b"
    assert all("1.5" not in m and "2.5-flash" != m for m in se.DEFAULT_GEMINI) and se.DEFAULT_GEMINI[0] == "gemini-flash-latest"
    c = se._llm_candidates({"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}, {})
    assert [p for p, _ in c] == ["groq", "groq", "groq", "gemini", "gemini"]
    assert se._llm_candidates({}, {}) == []
    assert se._llm_candidates({"GROQ_API_KEY": "k", "GROQ_MODEL": "m1", "GROQ_FALLBACK_MODELS": "m2,m1"}, {}) == [("groq", "m1"), ("groq", "m2")]
    assert se._llm_candidates({"GEMINI_API_KEY": "g", "GEMINI_MODEL": "gx"}, {}) == [("gemini", "gx")]


def test_a_gone_model_a_used_up_day_and_an_overloaded_model_each_hand_over_to_the_next():
    seen = []

    def post(url, **kw):
        model = (kw.get("json") or {}).get("model") or url.split("/models/")[1].split(":")[0]
        seen.append(model)
        if model == "openai/gpt-oss-120b":
            return Resp(404)                                                                   # gone
        if model == "openai/gpt-oss-20b":
            r = Resp(429)
            r.text = "Rate limit reached on tokens per day (TPD): Limit 200000"
            return r                                                                           # the day's allowance is used up: no retries
        if model == "qwen/qwen3.8-27b":
            return Resp(503)                                                                   # overloaded
        return gem_ok({"tone": 0.2, "qa_gap": 0.0, "evidence": []})
    r = se.score_transcript(TRANSCRIPT, "TCS", post=post, env={"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}, scorer=fake_scorer, sleep=lambda s: None)
    assert seen == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "gemini-flash-latest"] and r["method"] == "llm" and r["tone"] == 0.2


def test_a_plain_429_is_retried_on_the_same_model_before_moving_on():
    seen = []

    def post(url, **kw):
        seen.append(kw["json"]["model"])
        return Resp(429) if len(seen) < 3 else groq_ok({"tone": 0.1, "qa_gap": 0})
    r = se.score_transcript(TRANSCRIPT, "TCS", post=post, env={"GROQ_API_KEY": "k"}, scorer=fake_scorer, sleep=lambda s: None)
    assert seen == ["openai/gpt-oss-120b"] * 3 and r["method"] == "llm"


def test_groq_gets_a_short_excerpt_with_the_qa_part_and_gemini_a_longer_one():
    long = ("Prepared remarks. " * 3000) + "Question-and-Answer Session " + ("Analyst asks. " * 3000)
    sizes = {}

    def post(url, **kw):
        if "groq" in url:
            sizes["groq"] = kw["json"]["messages"][1]["content"]
            return Resp(400)
        sizes["gemini"] = kw["json"]["contents"][0]["parts"][0]["text"]
        return gem_ok({"tone": 0.0, "qa_gap": 0.0, "evidence": []})
    se.call_llm(long, post, {"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}, lambda s: None)
    assert len(sizes["groq"]) <= se.GROQ_CHARS + 20 and "Question-and-Answer Session" in sizes["groq"] and "[...]" in sizes["groq"]
    assert len(sizes["gemini"]) > len(sizes["groq"]) and "Question-and-Answer Session" in sizes["gemini"]
    assert se._excerpt("short", 100) == "short" and se._excerpt("x" * 500, 100) == "x" * 100


def test_gpt_oss_models_are_asked_for_low_reasoning_effort_and_other_models_are_not():
    got = {}

    def post(url, **kw):
        got[kw["json"]["model"]] = kw["json"]
        return Resp(400)
    se.call_llm("t" * 600, post, {"GROQ_API_KEY": "k"}, lambda s: None)
    assert got["openai/gpt-oss-120b"]["reasoning_effort"] == "low" and "reasoning_effort" not in got["qwen/qwen3.8-27b"] and got["openai/gpt-oss-120b"]["max_completion_tokens"] == 1500


def test_a_network_error_moves_to_the_next_model_and_nothing_raises():
    def post(url, **kw):
        raise se.requests.ConnectionError("down")
    assert se.call_llm("t" * 600, post, {"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}, lambda s: None) is None
    assert se.call_llm("t" * 600, post, {}, lambda s: None) is None                        # no keys: nothing is tried
