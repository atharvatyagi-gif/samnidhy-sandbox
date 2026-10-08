import numpy as np

from scripts.aladin2 import drift as DR
from scripts.aladin2 import journal as J


def ev(frm, to, **evd):
    return {"date": "2025-08-04 00:00:00", "sym": "*POOL*", "strategy": "ma_cross_50_200", "from": frm, "to": to, "why": "did not recover within 40 days", "evidence": evd}


def test_journal_text_is_built_only_from_the_evidence_numbers():
    t = J.text_for(ev("Candidate", "Probation", n=3570, mean_bps=655.0, p=0.002, lb_bps=261.7, years_positive="7/8"))
    assert "+655 bps" in t and "3570" in t and "7/8" in t and "0.002" in t and "Moving-average crossover" in t
    assert "CUSUM 5.3" in J.text_for(ev("Active", "Demoted", cusum=5.3, h=5.0)) and "above its limit 5.0" in J.text_for(ev("Active", "Demoted", cusum=5.3, h=5.0))
    assert "-14 bps" in J.text_for(ev("Active", "Demoted", live_trades=200, live_mean_bps=-14.0))
    assert "archived, never deleted" in J.text_for(ev("Demoted", "Retired"))
    assert "PSI 0.31" in J.text_for(ev("Active", "Demoted", reason="feature drift", features={"rsi2": {"psi": 0.31, "ks": 0.2}}))


def test_events_are_written_once_and_published_newest_first(tmp_path):
    a = J.from_lifecycle(ev("Active", "Demoted", cusum=5.3, h=5.0)); b = J.from_lifecycle({**ev("Demoted", "Retired"), "date": "2025-09-01"})
    assert J.append([a, b], tmp_path) == 2 and J.append([a, b], tmp_path) == 0 and len(J.read(tmp_path)) == 2
    assert J.publish(tmp_path) == 2 and [e["date"] for e in __import__("json").loads((tmp_path / "journal.json").read_text())["events"]] == ["2025-09-01", "2025-08-04"]
    assert a["kind"] == "demoted" and b["kind"] == "retired" and a["scope"] == "universe" and a["key"].startswith("2025-08-04|demoted|")


def test_psi_ks_and_volatility_break():
    rng = np.random.default_rng(0); a = rng.normal(0, 1, 5000); same = rng.normal(0, 1, 500); shifted = rng.normal(1.2, 1, 500)
    assert DR.psi(a, same) < 0.1 and DR.psi(a, shifted) > 0.25 and DR.ks(a, same)[1] > 0.01 and DR.ks(a, shifted)[1] < 1e-10
    assert DR.psi(a[:50], same) is None
    assert DR.vol_break(rng.normal(0, 0.01, 1000), rng.normal(0, 0.03, 100))["break"] is True and DR.vol_break(rng.normal(0, 0.01, 1000), rng.normal(0, 0.011, 100))["break"] is False


def test_strategy_drift_raises_an_alarm_only_for_features_it_uses():
    rng = np.random.default_rng(1); ref = {"rsi2": rng.normal(50, 10, 6000), "bb_z": rng.normal(0, 1, 6000)}; cur = {"rsi2": rng.normal(65, 10, 600), "bb_z": rng.normal(0, 1, 600)}
    al = DR.strategy_drift(("rsi2",), ref, cur); assert al and al["reason"] == "feature drift" and "rsi2" in al["features"]
    assert DR.strategy_drift(("bb_z",), ref, cur) is None
    r = rng.normal(0, 0.01, 2000); assert DR.strategy_drift(("bb_z",), ref, cur, ref_ret=r, cur_ret=rng.normal(0, 0.03, 100))["reason"] == "volatility regime break"


def test_events_before_the_forward_clock_are_tagged_as_historical_simulation():
    old = J.from_lifecycle(ev("Active", "Demoted", cusum=5.3, h=5.0))                                  # dated 2025-08-04
    new = J.from_lifecycle({**ev("Active", "Demoted", cusum=5.3, h=5.0), "date": "2026-11-02 00:00:00"})
    assert old["historical"] is True and new["historical"] is False
