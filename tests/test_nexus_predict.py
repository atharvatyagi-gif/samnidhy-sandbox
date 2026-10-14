import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import company_profiles as CP  # noqa: E402
import filing_mentions as FM  # noqa: E402
import nexus_predict as NP  # noqa: E402

STOCKS = [{"s": "BANKINDIA", "n": "Bank of India", "series": "EQ"}, {"s": "SBIN", "n": "State Bank of India", "series": "EQ"},
          {"s": "PFOCUS", "n": "Prime Focus Limited", "series": "EQ"}, {"s": "POLYCAB", "n": "Polycab India Limited", "series": "EQ"},
          {"s": "ZOMATO", "n": "Eternal Limited", "series": "EQ"}, {"s": "SMEX", "n": "Tiny Widgets Limited", "series": "SM"},
          {"s": "NIFTYBEES", "n": "Nippon Nifty ETF", "series": "EQ", "etf": True}]


# ------------------------------------------------------------------ filing mentions

def test_longest_name_wins_and_institutions_are_not_companies():
    m = FM.Matcher(STOCKS)
    assert m.find("Loans from State Bank of India and Bank of India.") == {"SBIN": 1, "BANKINDIA": 1}
    assert m.find("As directed by the Reserve Bank of India.") == {}


def test_names_must_be_written_as_names_and_one_word_names_need_limited():
    m = FM.Matcher(STOCKS)
    assert m.find("Quality remains a prime focus of ours.") == {}
    assert m.find("We supply Prime Focus with servers.") == {"PFOCUS": 1}
    assert m.find("Eternal growth.") == {} and m.find("Sales to Eternal Limited grew.") == {"ZOMATO": 1}
    assert m.find("Tiny Widgets Limited") == {}                                   # SME names are not matched


def test_scan_skips_board_pages_and_keeps_the_supply_sentence():
    m = FM.Matcher(STOCKS)
    names = {s["s"]: s["n"] for s in STOCKS}
    pages = [(3, "Mr X (DIN: 0001) is also a director of Polycab India Limited."),
             (9, "Polycab India Limited is a vendor. We buy cables from Polycab India Limited under a long-term contract.")]
    out = FM.scan("OWNER", pages, m, names, {"url": "u", "kind": "annual", "per": "FY2025-26"})
    assert list(out) == ["POLYCAB"] and out["POLYCAB"]["pg"] == [9] and out["POLYCAB"]["n"] == 2
    assert out["POLYCAB"]["sup"] == 1 and "Polycab" in out["POLYCAB"]["q"]


def test_owner_comes_from_the_report_url_or_the_cover_letter():
    syms = {"RELIANCE", "BOSCHLTD"}
    assert FM.owner_of("https://x/annual_reports/AR_29285_RELIANCE_2025_2026_A_1.pdf", [], {}, syms) == "RELIANCE"
    assert FM.owner_of("https://x/corporate/abc.pdf", [(1, "NSE Symbol: BOSCHLTD\nDear Sir")], {}, syms) == "BOSCHLTD"
    assert FM.owner_of("https://x/corporate/abc.pdf", [(1, "nothing")], {}, syms) is None


# ------------------------------------------------------------------ company profiles

def test_profiles_fetch_missing_first_and_record_empty_answers():
    today = date(2026, 10, 14)
    old = {"A": {"ind": "x", "at": "2026-10-01"}, "B": {"ind": "y", "at": "2026-01-01"}, "C": {"none": "2026-10-10"}}
    assert CP.due(["A", "B", "C", "D"], old, today, 10) == ["D", "B"]
    assert CP.row_from_info({}, today) == {"none": "2026-10-14"}
    assert CP.row_from_info({"industry": "Steel", "sector": "Basic Materials"}, today)["ind"] == "Steel"


# ------------------------------------------------------------------ model

def test_residual_correlation_finds_a_shared_move_beyond_market_and_industry():
    rng = np.random.default_rng(0)
    W, N = 120, 8
    mkt = rng.normal(0, 0.02, W)
    link = rng.normal(0, 0.02, W)
    R = mkt[:, None] + rng.normal(0, 0.02, (W, N))
    R[:, 0] += link
    R[:, 5] += link                                                # 0 and 5 share a private shock
    corr, lead = NP.corr_matrices(NP.residuals(R, [None] * N))
    assert np.nanargmax(corr[0]) == 5 and corr[0, 5] > 0.3
    assert np.isnan(corr[0, 0])


def test_too_little_overlap_is_missing_not_zero():
    R = np.random.default_rng(1).normal(0, 0.02, (60, 3))
    R[:40, 2] = np.nan
    corr, _ = NP.corr_matrices(NP.residuals(R, [None] * 3))
    assert np.isnan(corr[0, 2])


def test_confirmed_pairs_are_undirected_and_listed_only():
    g = {"nodes": [{"id": "A", "sym": "A"}, {"id": "B", "sym": "B"}, {"id": "ANON_X"}],
         "edges": [{"s": "A", "d": "B", "rel": "supplies"}, {"s": "B", "d": "A", "rel": "supplies"}, {"s": "A", "d": "ANON_X", "rel": "supplies"}]}
    assert list(NP.confirmed_pairs(g, {"A": 0, "B": 1})) == [(0, 1)]


def test_test_protocol_finds_a_planted_signal_and_beats_chance():
    rng = np.random.default_rng(3)
    N = 200
    linked = [(2 * i, 2 * i + 1) for i in range(30)]
    corr = rng.normal(0, 0.05, (N, N)).astype(np.float32)
    corr = (corr + corr.T) / 2
    for a, b in linked:
        corr[a, b] = corr[b, a] = 0.6
    z = np.zeros((N, N), np.float32)
    ind = np.full(N, -1)
    F = NP.Features(corr, z, z, z, z, z, ind, ind, ind, np.zeros(N, np.float32))
    readv = np.ones(N, bool)
    res, oof = NP.evaluate(F, linked, readv, N, ind, 0, np.array([0]), np.random.default_rng(0))
    assert res["hit10"] > 0.9 and res["random_hit10"] < 0.06 and len(oof) == res["tests"]


def test_a_damaged_pdf_is_recorded_once_and_a_network_error_is_retried(monkeypatch):
    import revenue_graph_builder as RGB
    monkeypatch.setattr(RGB, "pdf_pages", lambda raw: (_ for _ in ()).throw(ValueError("Invalid object in /Pages")))
    monkeypatch.setattr(FM.time, "sleep", lambda s: None)

    class Sess:
        def get_json(self, *a, **k):
            return {"data": [{"fileName": "https://x/AR_1_AAA_2025_2026_A.pdf", "fromYr": "2025", "toYr": "2026"}]}
    state = {"m": {}, "done": {}}
    m = FM.Matcher(STOCKS)
    FM.download_new(["AAA"], m, {}, state, 5, log=lambda *a: None, session=Sess(), get_pdf=lambda u: b"%PDF")
    assert state["done"]["AAA"]["none"] == "report too large or unreadable"

    def boom(u):
        raise ConnectionError("reset")
    state2 = {"m": {}, "done": {}}
    FM.download_new(["BBB"], m, {}, state2, 5, log=lambda *a: None, session=Sess(), get_pdf=boom)
    assert "BBB" not in state2["done"]


def test_earlier_mentions_survive_a_run_without_the_filings_cache(tmp_path, monkeypatch):
    out = tmp_path / "mentions.json"
    import json as _j
    out.write_text(_j.dumps({"read": ["MARUTI"], "done": {}, "m": {"MARUTI": {"BHARATSE": {"n": 3, "sup": 1, "pg": [9], "q": "q", "url": "u1"}}}}), encoding="utf-8")
    monkeypatch.setattr(FM, "OUT", out)
    monkeypatch.setattr(FM, "load", lambda p, d: _j.loads(p.read_text(encoding="utf-8")) if p == out else ({"stocks": STOCKS} if "universe" in str(p) else d))
    monkeypatch.setattr(FM, "scan_cached", lambda *a, **k: ({}, {}))          # the cache was evicted: nothing cached this run
    FM.main(["--no-download"])
    got = _j.loads(out.read_text(encoding="utf-8"))
    assert "BHARATSE" in got["m"]["MARUTI"] and "MARUTI" in got["read"]
