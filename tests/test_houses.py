"""Business-house list and the fundamentals rotation."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_houses  # noqa: E402
import terminal_fund  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def write(tmp, houses, symbols):
    h, u = tmp / "h.json", tmp / "u.json"
    h.write_text(json.dumps({"houses": houses}), encoding="utf-8")
    u.write_text(json.dumps({"stocks": [{"s": s} for s in symbols]}), encoding="utf-8")
    return h, u


def test_real_config_has_32_groups_and_every_symbol_exists():
    uni = ROOT / "data" / "terminal" / "universe.json"
    if not uni.exists():
        return                                              # CI without the terminal cache: check_houses runs in the workflow instead
    houses, problems = check_houses.check()
    assert len(houses) >= 30 and problems == []


def test_checker_flags_missing_duplicate_and_empty(tmp_path):
    h, u = write(tmp_path, [{"id": "a", "symbols": ["X", "NOPE"]}, {"id": "b", "symbols": ["X"]}, {"id": "c", "symbols": []}, {"id": "a", "symbols": ["Y", "Y"]}], ["X", "Y"])
    _, problems = check_houses.check(h, u)
    text = " | ".join(problems)
    assert "NOPE is not in universe" in text and "X is in both a and b" in text
    assert "c: no symbols" in text and "duplicate group id a" in text and "Y listed twice" in text


def test_rotation_covers_whole_main_board_every_five_runs_and_is_stable():
    syms = [f"S{i:04d}" for i in range(2000)]
    day0 = date(2026, 10, 1)
    runs = [set(terminal_fund.pick_symbols([], syms, day0 + timedelta(days=i))) for i in range(5)]
    assert set().union(*runs) == set(syms)
    assert sum(len(r) for r in runs) == len(syms)               # each stock exactly once per cycle
    assert 300 < len(runs[0]) < 500                             # about a fifth
    assert runs[0] == set(terminal_fund.pick_symbols([], syms, day0))


def test_nifty500_and_house_members_are_always_fetched():
    syms = [f"S{i:04d}" for i in range(500)]
    got = set(terminal_fund.pick_symbols(["N1", "N2", "DUMMY1"], syms, date(2026, 10, 1), extra=["HOUSEMEMBER"]))
    assert {"N1", "N2", "HOUSEMEMBER"} <= got and "DUMMY1" not in got
