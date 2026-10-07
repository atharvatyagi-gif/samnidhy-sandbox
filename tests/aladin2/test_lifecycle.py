import numpy as np

from scripts.aladin2 import costs as C
from scripts.aladin2 import lifecycle as LC

CFG = C.load_cfg()


def rec(state="Candidate", **k):
    r = LC.Record("TCS", "donchian_55", state=state, since="2024-01-01"); r.__dict__.update(k); return r


def good_live(n=30):
    return list(np.random.default_rng(0).normal(0.02, 0.02, n))


def test_candidate_to_probation_only_when_eligible_and_logs_evidence():
    r = rec(); assert LC.step(r, "2024-03-01", False, cfg=CFG) == [] and r.state == "Candidate"
    ev = LC.step(r, "2024-03-01", True, cfg=CFG, evidence={"n": 40, "mean_bps": 55})
    assert r.state == "Probation" and ev[0]["from"] == "Candidate" and ev[0]["to"] == "Probation" and ev[0]["evidence"]["n"] == 40 and r.history == ev


def test_probation_promotion_needs_time_trades_and_psr():
    r = rec("Probation", live_returns=good_live(30), live_n=30)
    assert LC.step(r, "2024-04-01", True, cfg=CFG, days_since=30) == [] and r.state == "Probation"                  # too early
    r.live_returns, r.live_n = good_live(5), 5
    assert LC.step(r, "2024-04-01", True, cfg=CFG, days_since=70) == [] and r.state == "Probation"                  # too few trades
    r.live_returns, r.live_n = list(np.random.default_rng(1).normal(0.0, 0.05, 30)), 30
    assert LC.step(r, "2024-04-01", True, cfg=CFG, days_since=70) == []                                           # PSR too low
    r.live_returns, r.live_n = good_live(30), 30
    ev = LC.step(r, "2024-04-01", True, cfg=CFG, days_since=70); assert r.state == "Active" and ev[0]["evidence"]["live_psr"] >= 0.95


def test_active_demoted_by_alarm_or_loss_of_eligibility_then_retired_or_recovered():
    r = rec("Active"); ev = LC.step(r, "2024-05-01", True, alarm={"cusum": 5.3, "h": 5.0}, cfg=CFG)
    assert r.state == "Demoted" and ev[0]["evidence"]["cusum"] == 5.3
    LC.step(r, "2024-05-20", False, cfg=CFG, days_since=19); assert r.state == "Demoted"                          # not long enough yet
    ev = LC.step(r, "2024-06-15", False, cfg=CFG, days_since=45); assert r.state == "Retired" and r.retired_on == "2024-06-15" and ev[0]["to"] == "Retired"
    r2 = rec("Demoted"); LC.step(r2, "2024-05-20", True, cfg=CFG, days_since=19); assert r2.state == "Active"       # recovery before retirement
    r3 = rec("Active"); LC.step(r3, "2024-05-01", False, cfg=CFG); assert r3.state == "Demoted"


def test_retired_reenters_only_with_fresh_evidence():
    r = rec("Retired", retired_on="2024-06-15")
    assert LC.step(r, "2024-09-01", True, fresh=False, cfg=CFG) == [] and r.state == "Retired"
    ev = LC.step(r, "2024-09-01", True, fresh=True, cfg=CFG); assert r.state == "Probation" and r.live_n == 0 and "fresh" in ev[0]["why"]


def test_cap_on_active_strategies_per_stock():
    rs = [LC.Record("TCS", f"s{i}", state="Active", since="2024-01-01") for i in range(6)]
    ev = LC.enforce_cap(rs, {f"s{i}": i for i in range(6)}, "2024-07-01", CFG)
    assert sum(r.state == "Active" for r in rs) == 4 and {e["strategy"] for e in ev} == {"s0", "s1"} and all(e["to"] == "Probation" for e in ev)


def test_full_path_candidate_to_reentry_writes_an_event_per_transition():
    r = rec(); log = []
    log += LC.step(r, "2024-01-10", True, cfg=CFG)                                                   # -> Probation
    r.live_returns, r.live_n = good_live(30), 30
    log += LC.step(r, "2024-04-01", True, cfg=CFG, days_since=80)                                    # -> Active
    log += LC.step(r, "2024-05-01", True, alarm={"cusum": 5.1}, cfg=CFG)                             # -> Demoted
    log += LC.step(r, "2024-06-20", False, cfg=CFG, days_since=50)                                   # -> Retired
    log += LC.step(r, "2024-12-01", True, fresh=True, cfg=CFG)                                       # -> Probation again
    assert [e["to"] for e in log] == ["Probation", "Active", "Demoted", "Retired", "Probation"] and len(r.history) == 5
