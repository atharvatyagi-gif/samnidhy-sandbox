"""B-Lab self-evolving strategy desk (scripts/blab/evolve.py, desk.py), on made-up prices. No network, no AI calls."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from blab import core  # noqa: E402
from blab import evolve as V  # noqa: E402

CFG = json.loads((ROOT / "data" / "config" / "aladin_e.json").read_text(encoding="utf-8"))


def market(n_days=800, n_stocks=14, seed=1, drift=None, start=date(2009, 1, 1)):
    rng = np.random.default_rng(seed)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(n_days)]
    mu = np.array(drift if drift is not None else [0.0004] * n_stocks)
    C = (100 * np.exp(np.cumsum(rng.normal(mu, 0.015, (n_days, n_stocks)), 0))).astype(np.float32)
    O = (C * (1 + rng.normal(0, 0.003, C.shape))).astype(np.float32)
    M = V.Market.__new__(V.Market)
    M.dates, M.syms = dates, [f"S{j:02d}" for j in range(n_stocks)]
    M.n50 = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n_days)))
    M.O, M.C, M.TV = O, C, np.full(C.shape, 5e8, np.float32)                 # Rs 50 Cr a day: tradable
    M._cache = {}
    M._prep()
    return M


def test_orders_fill_at_the_next_open_with_costs_and_never_more_than_ten():
    M = market()
    r = V.simulate(M, {"id": "trend_n100", "fam": "trend", "p": {"n": 100}}, CFG)
    enters = [t for t in r["trades"] if t[2] == "enter"]
    assert enters
    pos = {d: i for i, d in enumerate(M.dates)}
    for t in enters[:20]:
        assert t[3] == pytest.approx(float(M.O[pos[t[0]], M.syms.index(t[1])]), abs=0.01)   # the open of the fill day
    assert len(r["positions"]) <= V.SLOTS
    held, mx = set(), 0
    for t in r["trades"]:
        (held.add if t[2] == "enter" else held.discard)(t[1]); mx = max(mx, len(held))
    assert mx <= V.SLOTS
    exits = [t for t in r["trades"] if t[2] == "exit"]
    assert exits and all(t[5] is not None for t in exits)


def test_no_look_ahead():
    M1, M2 = market(seed=3), market(seed=3)
    cut = 600
    M2.C[cut:] *= 3; M2.O[cut:] *= 3; M2._cache = {}; M2._prep()                # change only the future
    c = {"id": "breakout", "fam": "breakout", "p": {"inn": 50, "out": 20}}
    a, b = V.simulate(M1, c, CFG), V.simulate(M2, c, CFG)
    day = M1.dates[cut]                                                               # prices change from this day's open on
    before = [t for t in a["trades"] if t[0] < day]
    assert before and before == [t for t in b["trades"] if t[0] < day]


def test_ranking_rebalances_monthly_to_the_top_ten():
    drift = [0.002 if j < 4 else -0.0005 for j in range(14)]
    M = market(drift=drift, seed=5)
    r = V.simulate(M, {"id": "mad", "fam": "mad", "p": {"s": 21, "l": 200}}, CFG)
    days = sorted({t[0] for t in r["trades"] if t[2] == "enter"})
    assert len(days) >= 2 and len(r["positions"]) <= 10
    assert {"S00", "S01", "S02", "S03"} <= {p[0] for p in r["positions"]}          # the strongest trends are held


def test_the_luck_penalty_grows_with_the_number_tried():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 252)
    srs = list(rng.normal(0.02, 0.03, 40))
    assert V.deflated_p(r, srs, 2) > V.deflated_p(r, srs, 200) > 0
    assert V.deflated_p([0.0] * 100, srs, 10) == 0.0


def test_breeding_steps_on_the_grid_and_never_pairs_a_family_with_itself():
    live = [{"id": "trend_n200", "fam": "trend", "p": {"n": 200}, "filt": None}, {"id": "cross_l200_s50", "fam": "cross", "p": {"s": 50, "l": 200}, "filt": None}]
    new = V.breed(live, {"trend_n200", "cross_l200_s50"})
    assert 0 < len(new) <= V.BREED
    assert all(not (c.get("filt") and c["filt"][0] == c["fam"]) for c in new)
    assert {c["id"] for c in new} >= {"trend_n150", "trend_n250"} or any(c["id"].startswith("trend_n") for c in new)
    n = V.neighbours({"id": "x", "fam": "trend", "p": {"n": 200}, "filt": ("trend", {"n": 250})})
    assert n == []                                                                    # a same-family pair has no offspring


def test_the_selector_finds_a_planted_edge_and_the_pool_survives(monkeypatch):
    monkeypatch.setattr(V, "GRID", {"trend": {"n": [50, 100]}, "mad": {"s": [10, 21], "l": [100, 150]}})
    monkeypatch.setattr(V, "MIN_POOL", 3)
    drift = [0.0025 if j < 5 else -0.0008 for j in range(14)]
    M = market(n_days=1100, drift=drift, seed=7)
    R = V.replay(M, CFG, log=lambda *a: None)
    assert R["picks"] and R["picks"][0]["date"] >= M.dates[V.MIN_RECORD]          # nothing chosen before 126 sessions of record
    assert sum(1 for s in R["status"].values() if not s["retired"]) >= 3
    ever = {k for p in R["picks"] for k in p["live"]}
    assert ever and all(k.startswith("mad") or k.startswith("trend") for k in ever)
    for name in ("selector", "blend", "nifty50"):
        assert R["result"][name]["whole"] is not None


def test_scout_proposals_are_checked_by_code():
    paper = {"id": "http://arxiv.org/abs/1", "title": "T", "summary": "s", "date": "2026-11-17"}
    ok = V.to_candidate({"family": "trend", "params": {"n": 120}}, paper, "2026-11-17")
    assert ok["id"] == "trend_n120" and ok["born"] == "2026-11-17" and ok["origin"].startswith("AI scout")
    for bad in ({"family": "macd", "params": {}}, {"family": "trend", "params": {"n": 5000}}, {"family": "cross", "params": {"s": 200, "l": 50}},
                {"family": "rsi", "params": {"lo": 60, "hi": 50, "k": 5}}, {"family": "trend", "params": {"n": "soon"}}, "trend"):
        assert V.to_candidate(bad, paper, "2026-11-17") is None, bad


def test_scout_reads_arxiv_and_adds_only_new_valid_rules():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2611.1</id><title>A moving average
    rule</title><summary>We test a 120-day moving average filter.</summary><published>2026-11-16T00:00:00Z</published></entry>
    <entry><id>http://arxiv.org/abs/2611.2</id><title>Deep options</title><summary>Neural nets.</summary><published>2026-11-15T00:00:00Z</published></entry></feed>"""
    class Fake:
        def complete(self, system, user):
            assert "SIMPLE trading rules" in system and "A moving average rule" in user
            return json.dumps({"items": [{"i": 1, "rule": {"family": "trend", "params": {"n": 120}}, "why": "tests a 120-day filter"}, {"i": 2, "rule": None}]})
    new, notes = V.scout(core.Ctx(), {"trend_n200"}, "2026-11-17", llm=Fake(), fetch=lambda u: feed)
    assert [c["id"] for c in new] == ["trend_n120"] and notes["read"] == 2 and notes["proposed"][0]["paper"].endswith("2611.1")
    new2, _ = V.scout(core.Ctx(), {"trend_n120"}, "2026-11-17", llm=Fake(), fetch=lambda u: feed)
    assert new2 == []
