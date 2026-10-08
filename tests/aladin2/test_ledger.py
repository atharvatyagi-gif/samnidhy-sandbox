import json

import pandas as pd
import pytest

from scripts.aladin2 import forecast as FC
from scripts.aladin2 import ledger as LG

CAL = pd.bdate_range("2026-10-01", periods=40)


def fc(d="2026-10-06", created="2026-10-06T20:00:00+00:00", h=(1, 5)):
    syms = ["A", "B", "C"]; close = [100.0, 200.0, 50.0]
    bands = [[[95, 105, 92, 108, 90, 110] for _ in h], [[190, 210, 185, 215, 180, 220] for _ in h], [[48, 52, 46, 54, 45, 55] for _ in h]]
    p_up = [[0.5 if x == 1 else None for x in h] for _ in syms]
    return LG.forecast_record(d, created, "v1", "abc", h, syms, close, [[0.02, 0.04]] * 3, bands, p_up)


def test_append_only_duplicates_and_conflicts(tmp_path):
    r = fc(); assert LG.append(r, tmp_path) == "written" and LG.append(r, tmp_path) == "duplicate"
    f = tmp_path / "2026-10.jsonl"; before = f.read_bytes()
    with pytest.raises(ValueError):
        LG.append({**r, "v": "v2"}, tmp_path)                                         # a different forecast for the same day: refused
    assert f.read_bytes() == before                                                   # and nothing was written
    LG.append({"t": "corr", "d": "2026-10-06", "note": "data vendor fixed a price"}, tmp_path)
    assert f.read_bytes().startswith(before) and len(LG.read_all(tmp_path)) == 2     # corrections are new lines; old bytes untouched


def test_resolution_marks_inside_and_outside_bands(tmp_path):
    r = fc(); px = {"A": 103.0, "B": 230.0, "C": 49.0}
    o = LG.resolve(r, 1, lambda s, d: px[s], "2026-10-07", CAL)
    assert o["syms"] == ["A", "B", "C"] and o["in50"] == [1, 0, 1] and o["in80"] == [1, 0, 1] and o["in95"] == [1, 0, 1] and o["up"] == [1, 1, 0]
    px2 = {"A": 109.0, "B": 200.0, "C": 50.0}; o2 = LG.resolve(r, 1, lambda s, d: px2[s], "2026-10-07", CAL)
    assert o2["in50"] == [0, 1, 1] and o2["in80"] == [0, 1, 1] and o2["in95"] == [1, 1, 1]


def test_live_statistics_reproduce_from_raw_lines_and_exclude_late_forecasts(tmp_path):
    r = fc(); LG.append(r, tmp_path)
    LG.append(LG.resolve(r, 1, lambda s, d: {"A": 103.0, "B": 230.0, "C": 49.0}[s], "2026-10-07", CAL), tmp_path)
    late = fc(d="2026-10-07", created="2026-10-09T08:00:00+00:00"); LG.append(late, tmp_path)                   # written after its 1-day target date (10-08): not live
    LG.append(LG.resolve(late, 1, lambda s, d: 100.0, "2026-10-08", CAL), tmp_path)
    s = LG.stats(tmp_path, ece_fn=lambda p, y: FC.ece(p, y, bins=1)[0])
    assert s["forecast_batches"] == 2 and s["outcomes"][1]["n"] == 3                      # only the first batch counts
    assert s["outcomes"][1]["coverage"] == {"50": round(2 / 3, 4), "80": round(2 / 3, 4), "95": round(2 / 3, 4)}
    raw = [json.loads(x) for x in (tmp_path / "2026-10.jsonl").read_text().splitlines()]                    # recompute by hand from the raw file
    out = [x for x in raw if x["t"] == "out" and x["d"] == "2026-10-06"][0]
    assert abs(sum(out["in80"]) / len(out["in80"]) - s["outcomes"][1]["coverage"]["80"]) < 1e-3
    assert s["outcomes"][1]["p_up_n"] == 3 and abs(s["outcomes"][1]["ece"] - abs(0.5 - 2 / 3)) < 1e-3          # ECE with one bin = |mean p - hit rate|


def test_unknown_line_type_and_resolved_lines_never_change(tmp_path):
    with pytest.raises(ValueError):
        LG.append({"t": "edit", "d": "2026-10-06"}, tmp_path)
    r = fc(); LG.append(r, tmp_path); o = LG.resolve(r, 5, lambda s, d: 100.0, "2026-10-13", CAL); LG.append(o, tmp_path)
    before = (tmp_path / "2026-10.jsonl").read_text()
    with pytest.raises(ValueError):
        LG.append({**o, "px": [1.0, 1.0, 1.0]}, tmp_path)
    assert (tmp_path / "2026-10.jsonl").read_text() == before
