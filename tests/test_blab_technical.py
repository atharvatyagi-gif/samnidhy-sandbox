"""B-Lab Technical division, step 3 (scripts/blab/technical.py), on made-up prices. No network."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from blab import core  # noqa: E402
from blab import technical as T  # noqa: E402


def days(n, start=date(2010, 1, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def test_states_trend_and_volatility_without_look_ahead():
    rng = np.random.default_rng(1)
    calm = rng.normal(0.0005, 0.005, 900)
    wild = rng.normal(0.0005, 0.03, 100)
    m = 100 * np.exp(np.cumsum(np.concatenate([calm, wild])))
    st, vol, ma = T.states(m)
    assert st[150] is None                                         # under 200 days of history: no state
    assert st[-1] == "up trend, high volatility" or st[-1] == "down trend, high volatility"
    assert st[880].endswith("volatility")
    before = T.states(m[:950])[0]
    assert before == st[:950]                                      # adding later days never changes an earlier state


def test_joined_history_rescales_at_the_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "TERM", tmp_path)
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "X.json").write_text(json.dumps({"d": [["2021-01-01", 0, 0, 0, 50, 0], ["2021-01-02", 0, 0, 0, 55, 0]]}))
    cur = [["2021-01-02", 0, 0, 0, 110, 0], ["2021-01-03", 0, 0, 0, 120, 0]]               # current file on a 2x basis (a split)
    j = T.joined("X.json", cur)
    assert j == {"2021-01-01": 100.0, "2021-01-02": 110, "2021-01-03": 120}


def test_strategies_pick_by_their_signal_and_eligibility():
    n, k = 300, 60
    P = np.ones((n, k)) * 100.0
    rng = np.random.default_rng(5)
    for j in range(k):
        P[:, j] = 100 * np.exp(np.linspace(0, 0.002 * j * n / 100, n) + rng.normal(0, 0.005, n))   # stock j trends up faster as j grows
    P[:, 58] = 100.0                                                                          # a stuck (suspended) price
    P[:, 0] = 5.0                                                                             # under Rs 10: never eligible
    P[:100, 1] = np.nan                                                                       # too short a history
    s = T.signals(P, n - 1)
    assert not s["_eligible"][0] and not s["_eligible"][1] and s["_eligible"][59]
    assert np.nanargmax(s["momentum"]) == 59 and np.nanargmax(s["quality trend"]) == 59
    assert np.isnan(s["momentum"][0])
    assert np.isnan(s["low volatility"][58]) and np.isnan(s["quality trend"][58])              # never "lowest volatility" or divided by ~0


def test_lab_measures_a_real_edge_and_uses_only_later_prices():
    rng = np.random.default_rng(7)
    n, k = 1400, 80
    mom = rng.normal(0, 0.01, (n, k))
    P = 100 * np.exp(np.cumsum(mom, 0))
    for t in range(270, n - 30, 5):                                                          # winners keep winning for the next 21 sessions
        r = P[t - 21] / P[t - 252] - 1
        top = r >= np.quantile(r, 0.9)
        P[t + 1:, top] *= 1.004
    dates = days(n)
    st = ["up trend, low volatility"] * n
    rec = T.lab(dates, P, st, st[-1])["up trend, low volatility"]
    assert rec["momentum"]["mean_pct"] > 0 and rec["momentum"]["verdict"].startswith("measurably better")
    assert rec["momentum"]["n"] >= 30


def test_analogs_find_the_closest_days_with_gaps_and_report_what_followed():
    rng = np.random.default_rng(3)
    n = 1500
    m = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n)))
    dates = days(n)
    st, vol, ma = T.states(m)
    br = np.full(n, np.nan)
    a = T.analogs(dates, m, {d: v for d, v in zip(dates, m)}, br, vol, ma)
    idx = sorted(dates.index(x["date"]) for x in a["days"])
    assert len(idx) == 10 and all(b - a_ >= 21 for a_, b in zip(idx, idx[1:])) and max(idx) <= n - 63
    assert "breadth" not in a["features"]                                                    # no breadth today: left out, not guessed
    assert a["lean"] in (-1, 0, 1) and a["h21"]["analogs"] == 10


def test_market_findings_are_scored_on_the_index_itself():
    d = days(80)
    n50 = {x: 100 * (1.01 ** i) for i, x in enumerate(d)}
    led = [{"bot": "T5", "scope": "NIFTY 50", "direction": 1, "seen": d[i]} for i in range(25)]
    card = core.scorecard(led, {}, {}, {"NIFTY 50": n50})["T5"]
    assert card["directional"] == 25 and card["5"]["n"] == 25 and card["5"]["right_pct"] == 100.0
    assert abs(card["5"]["mean_pct"] - (1.01 ** 5 - 1) * 100) < 0.01                       # reported to 2 decimals
    assert core.scorecard(led, {}, {}, {})["T5"]["directional"] == 0                         # no index series: not scored, never guessed


def test_flows_keep_deals_once_and_survive_an_nse_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "STORE", tmp_path)
    class Nse:
        def __init__(self, ans): self.ans = ans
        def get_json(self, *a, **k):
            if isinstance(self.ans, Exception): raise self.ans
            return self.ans
    ans = {"BULK_DEALS_DATA": [{"buySell": "BUY", "clientName": "A FUND", "date": "13-Nov-2026", "qty": "100", "symbol": "X", "watp": "50"}],
           "BLOCK_DEALS_DATA": [], "SHORT_DEALS_DATA": [{"date": "13-Nov-2026", "qty": "1", "symbol": "Y"}]}
    ctx = core.Ctx(now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
    ctx.read = lambda repo_path=None, site_path=None: ({"days": [{"date": "2026-11-13", "fii": {"net_cr": 1}, "dii": {"net_cr": -1}}]}, "x")
    ctx.nse = Nse(ans)
    r1 = T.t2_flows(ctx); r2 = T.t2_flows(ctx)
    assert json.loads((tmp_path / "deals.json").read_text())["rows"].__len__() == 2 and "1 bulk" in r2["detail"]
    ctx.nse = Nse(ConnectionError("down"))
    r3 = T.t2_flows(ctx)
    assert r3["errors"] and r3["as_of"] == "2026-11-13" and r1["items"] == 3
