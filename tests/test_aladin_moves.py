"""ALADIN probability movers: the same combiner on both days, honest front attribution, 15 per side, and a clear message when there is too little history."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_model as am  # noqa: E402
import aladin_moves as mv  # noqa: E402

W = {"wF": 0.20, "wS": 0.12, "wSweep": 0.18}


def row(F=None, S=None, T=0.0, p10=0.5, p5=0.5, p20=0.5, I=None):
    r = [F, S, T, p10, p5, p20]
    return r + [I] if I is not None else r


def day(d, **stocks):
    return (d, {"hmm": 0.1, "s": stocks})


def calc(hist):
    return mv.compute(hist, W, am.combine_py)


def test_fewer_than_two_nights_says_how_many_there_are():
    r = calc([day("2026-10-01", A=row())])
    assert r["ok"] is False and r["days"] == 1 and "at least two" in r["reason"]
    assert calc([])["days"] == 0


def test_probability_change_uses_the_same_combiner_for_both_days():
    a = day("2026-10-01", A=row(F=0, S=0, p10=0.55))
    b = day("2026-10-05", A=row(F=40, S=0, p10=0.55))
    r = calc([a, b])
    x = r["h"]["10"]["up"][0]
    now, prev = am.combine_py(0.55, 40, 0, None, W), am.combine_py(0.55, 0, 0, None, W)
    assert x["s"] == "A" and x["p"] == now["p"] and x["prev"] == prev["p"] and x["dp"] == pytest.approx((now["p"] - prev["p"]) * 100, abs=0.06)
    assert r["as_of"] == "2026-10-05" and r["prev_as_of"] == "2026-10-01" and r["h"]["10"]["compared"] == 1


def test_the_front_that_moved_most_is_named_in_log_odds_terms():
    prev = day("d0", TECH=row(p10=0.50), FUND=row(F=0, p10=0.5), SENT=row(S=0, p10=0.5), IMP=row(F=0, p10=0.5, I=0))
    now = day("d1", TECH=row(p10=0.62), FUND=row(F=90, p10=0.5), SENT=row(S=-100, p10=0.5), IMP=row(F=0, p10=0.5, I=100))
    r = calc([prev, now])["h"]["10"]
    byname = {x["s"]: x for x in r["up"] + r["down"]}
    assert byname["TECH"]["front"] == "Technical" and byname["TECH"]["dp"] > 0
    assert byname["FUND"]["front"] == "Fundamental" and byname["FUND"]["dp"] > 0
    assert byname["SENT"]["front"] == "Sentiment" and byname["SENT"]["dp"] < 0
    assert byname["IMP"]["front"] == "Supply-chain impact" and byname["IMP"]["dp"] < 0               # adverse impact lowers P(up)
    w = W["wS"] * (-100) / 100
    assert byname["SENT"]["fronts"]["S"] == pytest.approx(w, abs=1e-3) and byname["SENT"]["fronts"]["T"] == 0


def test_a_front_missing_on_one_day_counts_as_zero_like_the_combiner():
    prev = day("d0", A=row(F=None, p10=0.5))
    now = day("d1", A=row(F=50, p10=0.5))
    x = calc([prev, now])["h"]["10"]["up"][0]
    assert x["fronts"]["F"] == pytest.approx(W["wF"] * 50 / 100, abs=1e-3) and x["front"] == "Fundamental"


def test_old_history_rows_without_an_impact_score_still_work():
    prev = day("d0", A=row(F=10, S=5, p10=0.5, I=20))                    # a new row with I
    now = day("d1", A=row(F=10, S=5, p10=0.5))                           # a row without it: counts as 0
    x = calc([prev, now])["h"]["10"]["up"][0]
    assert x["front"] == "Supply-chain impact" and x["dp"] > 0


def test_fifteen_per_side_sorted_and_stocks_without_both_days_are_skipped():
    prev = {f"S{i:02d}": row(p10=0.5) for i in range(40)}
    now = {f"S{i:02d}": row(p10=0.5 + (i - 20) / 100) for i in range(40)}
    now["NEW"] = row(p10=0.9)                                              # not in the earlier night: not compared
    prev["GONE"] = row(p10=0.5)
    prev["NULL"], now["NULL"] = row(p10=None), row(p10=0.7)                # no probability on one day
    r = calc([("d0", {"s": prev}), ("d1", {"s": now})])["h"]["10"]
    assert r["compared"] == 40 and len(r["up"]) == 15 and len(r["down"]) == 15
    assert [x["s"] for x in r["up"]][:3] == ["S39", "S38", "S37"] and [x["s"] for x in r["down"]][:3] == ["S00", "S01", "S02"]
    assert all(x["dp"] > 0 for x in r["up"]) and all(x["dp"] < 0 for x in r["down"])
    assert not any(x["s"] in ("NEW", "GONE", "NULL") for x in r["up"] + r["down"])
    assert r["up"] == sorted(r["up"], key=lambda x: -x["dp"])


def test_each_horizon_reads_its_own_probability_column():
    prev = day("d0", A=row(p10=0.5, p5=0.5, p20=0.5))
    now = day("d1", A=row(p10=0.5, p5=0.6, p20=0.4))
    r = calc([prev, now])["h"]
    assert r["10"]["up"] == [] and r["10"]["down"] == []
    assert r["5"]["up"][0]["s"] == "A" and r["20"]["down"][0]["s"] == "A"


def test_the_latest_two_nights_are_used_not_the_first_two():
    h = [day("d0", A=row(p10=0.1)), day("d1", A=row(p10=0.5)), day("d2", A=row(p10=0.6))]
    r = calc(h)
    assert r["prev_as_of"] == "d1" and r["as_of"] == "d2" and r["days"] == 3


def test_history_loading_and_the_real_files(tmp_path):
    (tmp_path / "2026-10-05.json").write_text(json.dumps({"s": {"A": row()}}), encoding="utf-8")
    (tmp_path / "2026-10-01.json").write_text("not json", encoding="utf-8")
    (tmp_path / "2026-09-29.json").write_text(json.dumps({"s": {}}), encoding="utf-8")
    assert [d for d, _ in mv.load_history(tmp_path)] == ["2026-09-29", "2026-10-05"]
    real = mv.load_history()
    if len(real) >= 2:
        doc = calc(real)
        assert doc["ok"] and set(doc["h"]) == {"5", "10", "20"}
        for h in doc["h"].values():
            assert len(h["up"]) <= 15 and all(0 <= x["p"] <= 1 and x["front"] in mv.FRONTS.values() for x in h["up"] + h["down"])
        assert len(json.dumps(doc)) < 120_000


def test_history_rows_keep_the_impact_score_and_the_workflow_runs_the_script():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "aladin_model.py").read_text(encoding="utf-8")
    assert '(e.get("x") or {}).get("i")]' in src
    wf = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "aladin.yml").read_text(encoding="utf-8")
    assert "scripts/aladin_moves.py" in wf and wf.index("aladin_moves.py") > wf.index("aladin_model.py")
    assert math.isfinite(mv._logit(0.0)) and math.isfinite(mv._logit(1.0))
