"""Sweep evaluation: Wilson interval maths, one outcome per stock-day-direction, only matured events, and the label that is hard to earn."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_sweep_eval as se  # noqa: E402


def ms(date, hh=10, mm=0):                                  # an IST wall-clock time on `date`, as epoch milliseconds
    y, m, d = map(int, date.split("-"))
    return int((datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() - 5.5 * 3600) * 1000)


def ev(sym, date, d=1, close=100.0, lvl="PDL", hh=10):
    return {"sym": sym, "dir": d, "lvl": lvl, "px": close, "close": close, "rvol": 2.0, "wick": 0.6, "score": 40 * d, "ts": ms(date, hh)}


def test_wilson_interval_matches_known_values():
    lo, hi = se.wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    lo, hi = se.wilson(60, 100)
    assert lo == pytest.approx(0.5020, abs=1e-3) and hi == pytest.approx(0.6906, abs=1e-3)
    assert se.wilson(0, 0) == (None, None)
    lo, hi = se.wilson(10, 10)
    assert hi == pytest.approx(1.0) and 0.69 < lo < 0.73                                         # a perfect record on 10 events is still not proof


def test_ist_date_uses_the_indian_calendar_day():
    assert se.ist_date(ms("2026-10-05", 9, 30)) == "2026-10-05"
    late = int(datetime(2026, 10, 5, 19, 0, tzinfo=timezone.utc).timestamp() * 1000)    # 00:30 IST on the 6th
    assert se.ist_date(late) == "2026-10-06"


def test_one_event_per_stock_day_and_direction(tmp_path):
    lines = [ev("A", "2026-10-05"), ev("A", "2026-10-05", hh=11), ev("A", "2026-10-05", d=-1), ev("A", "2026-10-06"), ev("B", "2026-10-05")]
    (tmp_path / "2026-10-05.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n" + json.dumps({"sym": "Z"}) + "\n", encoding="utf-8")
    got = se.load_events(tmp_path)
    assert sorted((e["sym"], e["date"], e["dir"]) for e in got) == [("A", "2026-10-05", -1), ("A", "2026-10-05", 1), ("A", "2026-10-06", 1), ("B", "2026-10-05", 1)]
    assert sum(1 for e in got if e["sym"] == "A" and e["date"] == "2026-10-05" and e["dir"] == 1) == 1


def test_only_matured_events_count_and_a_hit_is_the_side_the_sweep_pointed_to():
    rows = {"UP": [["2026-10-05", 0, 0, 0, 100, 0], ["2026-10-06", 0, 0, 0, 103, 0]], "DOWN": [["2026-10-05", 0, 0, 0, 100, 0], ["2026-10-06", 0, 0, 0, 97, 0]],
            "LATE": [["2026-10-05", 0, 0, 0, 100, 0]], "FLAT": [["2026-10-05", 0, 0, 0, 100, 0], ["2026-10-06", 0, 0, 0, 100, 0]]}
    events = [{**ev("UP", "2026-10-05", 1), "date": "2026-10-05"}, {**ev("DOWN", "2026-10-05", -1), "date": "2026-10-05"}, {**ev("UP", "2026-10-05", -1), "date": "2026-10-05"},
              {**ev("LATE", "2026-10-05", 1), "date": "2026-10-05"}, {**ev("FLAT", "2026-10-05", 1), "date": "2026-10-05"}, {**ev("GONE", "2026-10-05", 1), "date": "2026-10-05"}]
    r = se.evaluate(events, rows.get)
    assert r["events_logged"] == 6 and r["n"] == 4 and r["hits"] == 2                  # UP+1 hit, DOWN-1 hit, UP-1 miss, FLAT miss; LATE and GONE not matured
    assert r["by_level"]["PDL"] == {"n": 4, "hits": 2} and r["validated"] is False
    assert "4 of the 60 outcomes needed have matured" in r["note"]


def test_validated_only_with_enough_events_and_a_lower_bound_above_half():
    def run(hits, n):
        events, rows = [], {}
        for i in range(n):
            s = f"S{i:03d}"
            events.append({**ev(s, "2026-10-05"), "date": "2026-10-05"})
            rows[s] = [["2026-10-05", 0, 0, 0, 100, 0], ["2026-10-06", 0, 0, 0, 101 if i < hits else 99, 0]]
        return se.evaluate(events, rows.get)
    assert run(45, 60)["validated"] is True                                          # 75%: lower bound about 0.62
    assert run(36, 60)["validated"] is False                                         # 60% on 60 events: lower bound 0.47, includes 50%
    assert "includes 50%" in run(36, 60)["note"]
    assert run(59, 59)["validated"] is False                                         # a perfect record on too few events is still "unvalidated"
    assert run(0, 0)["hit_rate"] is None and run(0, 0)["n"] == 0


def test_next_close_skips_the_event_day_and_waits_for_a_later_one():
    rows = [["2026-10-05", 0, 0, 0, 10, 0], ["2026-10-07", 0, 0, 0, 12, 0]]
    assert se.next_close(rows, "2026-10-05") == 12 and se.next_close(rows, "2026-10-07") is None and se.next_close(rows, "2026-10-01") == 10
    assert se.key("M&M") == "M_26M" and se.key("RELIANCE") == "RELIANCE"


def test_main_without_a_log_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(se, "LOG_DIR", tmp_path / "none")
    assert se.main() == 0 and "nothing to evaluate" in capsys.readouterr().out
