import json
import re

import pandas as pd

from scripts.aladin2 import forecast as FC
from scripts.aladin2 import ledger as LG
from scripts.aladin2 import publish as PB


def make_ledger(tmp_path, n=12):
    syms = [f"S{i}" for i in range(n)]; Hs = [1, 5, 10, 20, 60]
    bands = [[[95, 105, 92, 108, 90, 110] for _ in Hs] for _ in syms]
    rec = LG.forecast_record("2026-10-06", "2026-10-08T05:45:00+00:00", "v1", "h", Hs, syms, [100.0] * n, [[0.02] * 5] * n, bands, [[0.5, 0.5, None, None, None]] * n)
    LG.append(rec, tmp_path / "ledger"); return syms


def test_shards_have_the_published_shape_sizes_and_neutral_wording(tmp_path):
    syms = make_ledger(tmp_path); out = tmp_path / "site" / "aladin2"
    r = PB.build(out, ledger_dir=tmp_path / "ledger", state_dir=tmp_path / "state", journal_dir=tmp_path, mode="neutral", weekly_path=tmp_path / "none.json", paper_dir=tmp_path / "no_paper")
    assert r["built"] and r["stocks"] == 12 and r["biggest_stock_shard_bytes"] < 80_000 and r["index_bytes"] < 200 * 12 + 2000
    idx = json.loads((out / "index.json").read_text()); assert idx["mode"] == "neutral" and idx["labels"]["none"] == "NO EDGE" and len(idx["rows"]) == 12 and idx["rows"][0][1] == "L"
    d = json.loads((out / "stock" / "S0.json").read_text())
    assert d["state"] == "Learning" and d["signal"] == "none" and d["plan"] is None and "Validated" in d["plan_why"] and [b["H"] for b in d["bands"]] == [1, 5, 10, 20, 60] and d["bands"][0]["p_up"] == 0.5 and d["bands"][2]["p_up"] is None
    assert d["disclaimer"].startswith("ALADIN is a statistical model built by students. It is often wrong.")
    text = " ".join(p.read_text() for p in out.rglob("*.json")); assert not re.search(r"\b(buy|sell|target|recommendation|guaranteed)\b", text, re.I)
    sb = json.loads((out / "scoreboard.json").read_text()); assert sb["state_shares"] == {"L": 1.0} and "HISTORICAL SIMULATION" in sb["historical_simulation"]["label"]


def test_nothing_is_built_without_a_forecast(tmp_path):
    assert PB.build(tmp_path / "x", ledger_dir=tmp_path / "ledger", state_dir=tmp_path / "state")["built"] is False
