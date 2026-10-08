import json
import re
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from scripts.aladin2 import bot as BT
from scripts.aladin2 import costs as C
from scripts.aladin2 import weekly as W

ROOT = Path(__file__).resolve().parents[2]
CODE = "ALADIN-TEST-TEST-TEST-TEST-TEST"


def test_roundtrip_wrong_code_and_tampering():
    blob = BT.encrypt({"secret": "LUPIN", "n": [1, 2]}, CODE, iterations=1000)
    assert BT.decrypt(blob, CODE) == {"secret": "LUPIN", "n": [1, 2]}
    assert BT.decrypt(blob, "aladin test test test test test") == {"secret": "LUPIN", "n": [1, 2]}                          # case, spaces and dashes do not matter
    with pytest.raises(InvalidTag):
        BT.decrypt(blob, "ALADIN-WRONG-WRONG-WRONG-WRONG-WRONG")
    bad = dict(blob); import base64; ct = bytearray(base64.b64decode(blob["ct"])); ct[5] ^= 1; bad["ct"] = base64.b64encode(bytes(ct)).decode()
    with pytest.raises(InvalidTag):
        BT.decrypt(bad, CODE)                                                                                                # a changed file fails the GCM check
    with pytest.raises(InvalidTag):
        BT.decrypt({**blob, "aad": "something-else"}, CODE)


def test_the_encrypted_file_contains_no_readable_data_and_each_encryption_is_different():
    text = json.dumps(BT.encrypt({"symbols": ["LUPIN", "SANOFI"], "note": "ALADIN BOT"}, CODE, iterations=1000))
    assert not re.search(r"LUPIN|SANOFI|ALADIN BOT|TEST-TEST", text)
    a, b = BT.encrypt({"x": 1}, CODE, iterations=1000), BT.encrypt({"x": 1}, CODE, iterations=1000); assert a["ct"] != b["ct"] and a["salt"] != b["salt"] and a["iv"] != b["iv"]


def test_generated_codes_are_long_random_and_unambiguous():
    cs = {BT.new_code() for _ in range(200)}; assert len(cs) == 200
    c = next(iter(cs)); assert re.fullmatch(r"ALADIN(-[A-HJKMNP-Z2-9]{4}){5}", c) and len(BT.normalise(c)) == 26 and BT.normalise(c.lower().replace("-", " ")) == BT.normalise(c)


def test_the_fixture_the_browser_test_opens_is_decryptable_here_too():
    blob = json.loads((ROOT / "tests" / "fixtures" / "bot_fixture.enc.json").read_text()); assert BT.decrypt(blob, CODE)["unicode"] == "₹ 100" and blob["iter"] == 2000 and blob["kdf"] == "PBKDF2-SHA256"


def test_the_published_iteration_count_is_high_and_the_code_is_never_written_by_the_builder(tmp_path, monkeypatch):
    assert BT.ITER >= 600_000
    src = (ROOT / "scripts" / "aladin2" / "bot.py").read_text(encoding="utf-8")
    assert "write_text(code" not in src and "print(code" not in src and '".env"' not in src and "dotenv" not in src


def test_payload_has_the_pages_data_and_only_what_the_files_say():
    book = {"as_of": "2026-10-07", "universe": 100, "counts": {"bull": 1, "bear": 1, "hold": 98}, "rules": {"bull": "best 1%", "bear": "worst 5%"}, "ranks": {"A": [0.995, 0.55, 0.52], "B": [0.03, 0.43, 0.38]},
            "bull": [{"sym": "A", "name": "A Ltd", "sector": "IT", "close": 100.0, "rank_pct": 0.995, "p5": 0.62, "chance": {"closes_higher": 0.55}, "round_trip_cost_bps": 36.0, "entry_zone": [99.5, 100.5], "invalidation": 96.0, "exit": "x", "what_to_do": "Enter", "fno": True, "evidence": {"range_5d_80pct": [95, 105]}, "size_for_capital": None, "record": None}],
            "bear": [{"sym": "B", "name": "B Ltd", "sector": "IT", "close": 50.0, "rank_pct": 0.03, "p5": 0.4, "chance": None, "round_trip_cost_bps": 44.0, "exit": "x", "what_to_do": "Exit", "fno": False, "evidence": {}, "record": None}]}
    study = {"weeks": 655, "rows": 310816, "record": {"buy": {"share_closing_up": 0.5548, "net_bps": 27.0}, "sell": {"share_closing_up": 0.4159, "gross_excess_bps": -71.9}},
             "charts": {"by_decile": [], "by_year": [], "weekly_curves": {"dates": ["2013-01-04", "2013-01-11"], "bull_cumulative_net_excess": [0.0, 0.01], "bear_cumulative_underperformance": [0.0, 0.01]}}, "probability_curve": [], "probability_check": None}
    aladin = {"stocks": {"A": {"t": {"p": {"5": 0.62}}}, "B": {"t": {"p": {"5": 0.4}}}}}
    p = BT.build_payload({"book": book, "labels": {"bull": "BUY", "bear": "SELL", "none": "HOLD"}, "mode": "directional", "disclaimer": "d", "live_record": {}}, study, None, [], {"events": []}, {"stocks_forecast": 500, "horizons": [1, 5], "timings_s": []}, None, {"strategies": {}}, {"A": {"d": ["x"], "c": [1.0]}}, aladin, {"price_files": 10})
    assert p["as_of"] == "2026-10-07" and [t["sym"] for t in p["traces"]] == ["A", "B"] and len(p["stages"]) == 7 and p["kpis"]["signals_today"] == {"bull": 1, "bear": 1, "hold": 98} and "paper_end_inr" not in p["kpis"]["history"] and p["kpis"]["history"]["bull_net_bps_per_week"] == 27.0
    assert p["charts"]["score_hist"]["n"] == 2 and p["kpis"]["forecasts_made"] == 0 and p["traces"][0]["series"]["c"] == [1.0] and len(p["decision_steps"]) == 6


def test_chance_lookup_follows_the_rank_bucket():
    st = W.study(); curve = st["probability_curve"]
    best = W.chance(0.995, curve); worst = W.chance(0.003, curve); mid = W.chance(0.5, curve)
    assert best["closes_higher"] > mid["closes_higher"] > worst["closes_higher"] and best["beats_market"] > worst["beats_market"] and best["closes_higher_ci95"][0] < best["closes_higher"] < best["closes_higher_ci95"][1]
    assert W.chance(1.0, curve)["bucket"][1] == 1.0 and W.chance(0.5, None) is None
    assert st["probability_check"]["closes_higher"]["ece"] < 0.03 and st["probability_check"]["closes_higher"]["brier"] < st["probability_check"]["closes_higher"]["brier_base_rate"]        # checked out of sample, and better than the base rate


def test_signal_rows_carry_their_chance():
    from tests.aladin2.test_weekly import world
    stocks, al = world(400); b = W.build("2026-10-09", al, stocks, C.load_cfg())
    assert b["bull"][0]["chance"]["closes_higher"] > b["bear"][0]["chance"]["closes_higher"] and b["ranks"]["S000"][1] == b["bull"][0]["chance"]["closes_higher"] and len(b["ranks"]) == 400
