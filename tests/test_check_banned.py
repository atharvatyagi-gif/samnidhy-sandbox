"""scripts/check_banned.py: it passes on the repository, and it really does catch banned wording, a banned JSON key and a missing disclaimer."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_banned as cb  # noqa: E402


def test_the_repository_passes():
    assert cb.check() == []


def fake_root(tmp_path, **over):
    html = (ROOT / "expert-terminal.html").read_text(encoding="utf-8")
    (tmp_path / "expert-terminal.html").write_text(over.pop("html", html), encoding="utf-8")
    (tmp_path / "README.md").write_text("plain", encoding="utf-8")
    for n in ("desk-aladin.js", "desk-nexus.js", "desk-aladin2.js", "desk-a2views.js", "desk-a2bot.js"):
        (tmp_path / n).write_text(over.pop(n, f"const DISCLAIMER = '{cb.DISCLAIMER}';"), encoding="utf-8")
    (tmp_path / "data" / "aladin").mkdir(parents=True)
    for rel, doc in over.items():
        (tmp_path / "data" / rel).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_a_clean_fake_root_passes(tmp_path):
    assert cb.check(fake_root(tmp_path)) == []


def test_banned_wording_in_a_module_is_caught_but_event_target_and_target_blank_are_not(tmp_path):
    r = fake_root(tmp_path, **{"desk-aladin.js": f"const DISCLAIMER = '{cb.DISCLAIMER}'; const x = 'Buy now'; e.target; '<a target=\"_blank\">'"})
    p = cb.check(r)
    assert any("desk-aladin.js" in x and "buy" in x for x in p) and not any("target" in x for x in p)


def test_a_banned_key_in_served_json_is_caught_at_any_depth_but_symbols_and_quotes_are_not(tmp_path):
    doc = {"stocks": {"BEARDSELL": {"fine": 1}}, "deep": {"list": [{"sell_signal": 1}]}, "heads": [{"title": "Analysts say buy"}]}
    p = cb.check(fake_root(tmp_path, **{"aladin/moves.json": doc}))
    assert any("moves.json keys" in x and "sell_signal" in x for x in p)
    ok = cb.check(fake_root(tmp_path / "b", **{"aladin/moves.json": {"stocks": {"BEARDSELL": {"fine": 1}}, "heads": [{"title": "Analysts say buy"}]}})) if (tmp_path / "b").mkdir() is None else []
    assert ok == []


def test_a_missing_disclaimer_is_caught_on_each_surface(tmp_path):
    p = cb.check(fake_root(tmp_path, **{"desk-nexus.js": "no disclaimer here"}))
    assert any("NEXUS panel" in x for x in p)
    html = (ROOT / "expert-terminal.html").read_text(encoding="utf-8").replace(cb.DISCLAIMER, "removed")
    p2 = cb.check(fake_root(tmp_path / "c", html=html)) if (tmp_path / "c").mkdir() is None else []
    assert any("Globe tab" in x for x in p2)


def test_the_report_of_older_code_lists_lines_without_failing():
    found = cb.existing()
    assert all(len(f) == 4 for f in found)
    assert cb.main([]) == 0
    assert cb.main(["--existing"]) == 0
