"""The earlier ALADIN models are published only encrypted (scripts/aladin2/legacy.py). Tests use a made-up code, never the real one."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.aladin2 import legacy  # noqa: E402

CODE = "TEST-ONLY-CODE"


def _site(tmp_path):
    s = tmp_path / "site"
    for rel, body in {"aladin.json": {"a": 1}, "predict.json": {"p": 2}, "aladin2/weekly.json": {"w": 3}, "aladin2/stock/TCS.json": {"t": 4},
                      "aladin2/bot.enc.json": {"bot": 1}, "aladin_e.json": {"e": 5}, "desk_data.json": {"d": 6}}.items():
        (s / rel).parent.mkdir(parents=True, exist_ok=True)
        (s / rel).write_text(json.dumps(body), encoding="utf-8")
    return s


def test_protect_encrypts_every_legacy_file_and_leaves_no_readable_copy(tmp_path):
    s = _site(tmp_path)
    r = legacy.protect(s, CODE, iterations=1000, open_mode=False)
    assert r == {"files": 4, "bytes": r["bytes"], "encrypted": True}
    assert legacy.legacy_files(s) == []
    for rel in ("aladin.json", "predict.json", "aladin2/weekly.json", "aladin2/stock/TCS.json"):
        assert not (s / rel).exists()
        assert CODE not in (s / "legacy" / (rel + ".enc")).read_text(encoding="utf-8")
    assert legacy.open_file(s, "aladin2/weekly.json", CODE) == {"w": 3}
    assert legacy.open_file(s, "aladin.json", CODE) == {"a": 1}
    for rel in ("aladin2/bot.enc.json", "aladin_e.json", "desk_data.json"):
        assert (s / rel).exists()
    meta = (s / "legacy" / "meta.json").read_text(encoding="utf-8")
    assert CODE not in meta and json.loads(meta)["iter"] == 1000


def test_a_wrong_code_cannot_open_the_files(tmp_path):
    s = _site(tmp_path)
    legacy.protect(s, CODE, iterations=1000, open_mode=False)
    try:
        legacy.open_file(s, "aladin.json", "WRONG")
    except Exception:
        return
    raise AssertionError("a wrong code opened a file")


def test_without_a_code_the_files_are_removed_and_marked_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("ALADIN_BOT_CODE", raising=False)
    s = _site(tmp_path)
    r = legacy.protect(s, open_mode=False)
    assert r["encrypted"] is False and r["files"] == 4
    assert legacy.legacy_files(s) == []
    assert json.loads((s / "legacy" / "meta.json").read_text(encoding="utf-8")) == {"v": 1, "missing": True}


def test_open_mode_keeps_the_files_readable_and_says_so(tmp_path):
    """Owner, 2026-11-13: 'make the aladin bot accessible without any code' (data/config/aladin_bot.json "open": true)."""
    import json as _j
    from scripts.aladin2 import legacy as LG
    (tmp_path / "aladin2").mkdir()
    (tmp_path / "aladin.json").write_text('{"a": 1}', encoding="utf-8"); (tmp_path / "aladin2" / "weekly.json").write_text('{"w": 2}', encoding="utf-8")
    r = LG.protect(tmp_path, code="ignored-in-open-mode", open_mode=True)
    assert r["open"] and not r["encrypted"]
    assert _j.loads((tmp_path / "aladin.json").read_text(encoding="utf-8")) == {"a": 1} and (tmp_path / "aladin2" / "weekly.json").exists()
    assert _j.loads((tmp_path / "legacy" / "meta.json").read_text(encoding="utf-8")) == {"v": 1, "open": True}
    assert not list((tmp_path / "legacy").rglob("*.enc"))


def test_the_owner_setting_is_open():
    from scripts.aladin2 import bot as BT
    assert BT.is_open() is True


def test_open_mode_needs_no_cryptography_library(tmp_path, monkeypatch):
    """The live-prices build had no `cryptography` (2026-11-13): open mode must not need it."""
    import sys as _s
    for k in [k for k in _s.modules if k == "cryptography" or k.startswith("cryptography.")]:
        monkeypatch.delitem(_s.modules, k)
    monkeypatch.setitem(_s.modules, "cryptography", None)                  # any import of it now fails
    (tmp_path / "aladin.json").write_text('{"a": 1}', encoding="utf-8")
    r = legacy.protect(tmp_path, open_mode=True)
    assert r["open"] and (tmp_path / "aladin.json").exists()
