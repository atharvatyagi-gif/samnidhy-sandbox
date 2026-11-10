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
    r = legacy.protect(s, CODE, iterations=1000)
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
    legacy.protect(s, CODE, iterations=1000)
    try:
        legacy.open_file(s, "aladin.json", "WRONG")
    except Exception:
        return
    raise AssertionError("a wrong code opened a file")


def test_without_a_code_the_files_are_removed_and_marked_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("ALADIN_BOT_CODE", raising=False)
    s = _site(tmp_path)
    r = legacy.protect(s)
    assert r["encrypted"] is False and r["files"] == 4
    assert legacy.legacy_files(s) == []
    assert json.loads((s / "legacy" / "meta.json").read_text(encoding="utf-8")) == {"v": 1, "missing": True}
