"""GitOps tests, run in throwaway repos with a bare 'origin': nothing here can touch the real repository."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gitops  # noqa: E402

MSG = "ALADIN data refresh [skip ci]"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    sh(tmp_path, "git", "init", "--bare", "-b", "main", str(remote))
    sh(tmp_path, "git", "clone", str(remote), str(work))
    sh(work, "git", "config", "user.email", "t@example.com")
    sh(work, "git", "config", "user.name", "t")
    sh(work, "git", "checkout", "-B", "main")
    (work / "data" / "aladin").mkdir(parents=True)
    (work / "data" / "aladin" / "sentiment.json").write_text(json.dumps({"generated_utc": "t0", "v": 1}), encoding="utf-8")
    (work / "README.md").write_text("x", encoding="utf-8")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-m", "base")
    sh(work, "git", "push", "-u", "origin", "main")
    monkeypatch.chdir(work)
    monkeypatch.setenv("ALADIN_GIT_PUSH", "1")
    return work, remote


def head_msg(path):
    return sh(path, "git", "log", "-1", "--format=%s", "main").strip()


def write(work, rel, obj):
    p = work / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_message_must_end_with_skip_ci(repo):
    with pytest.raises(AssertionError):
        gitops.commit_and_push(["data/aladin"], "no marker here", min_interval_s=0)


def test_does_nothing_unless_enabled(repo, monkeypatch):
    work, remote = repo
    monkeypatch.delenv("ALADIN_GIT_PUSH")
    write(work, "data/aladin/sentiment.json", {"generated_utc": "t1", "v": 2})
    assert gitops.commit_and_push(["data/aladin"], MSG, min_interval_s=0) is False
    assert head_msg(work) == "base" and head_msg(remote) == "base"


def test_commits_pushes_and_marks_skip_ci(repo):
    work, remote = repo
    write(work, "data/aladin/sentiment.json", {"generated_utc": "t1", "v": 2})
    assert gitops.commit_and_push(["data/aladin"], MSG, min_interval_s=0) is True
    assert head_msg(work) == MSG and head_msg(remote) == MSG


def test_no_commit_when_only_generated_keys_changed(repo):
    work, remote = repo
    write(work, "data/aladin/sentiment.json", {"generated_utc": "later", "generated_ist": "x", "v": 1})
    assert gitops.commit_and_push(["data/aladin"], MSG, min_interval_s=0) is False
    assert head_msg(work) == "base"


def test_fifteen_minute_throttle(repo):
    work, remote = repo
    write(work, "data/aladin/sentiment.json", {"generated_utc": "t1", "v": 2})
    assert gitops.commit_and_push(["data/aladin"], MSG) is True
    write(work, "data/aladin/sentiment.json", {"generated_utc": "t2", "v": 3})
    assert gitops.commit_and_push(["data/aladin"], MSG) is False                       # inside the default 900 s
    assert gitops.commit_and_push(["data/aladin"], MSG, min_interval_s=0) is True      # floor lifted


def test_only_listed_paths_are_staged(repo):
    work, remote = repo
    write(work, "data/aladin/sentiment.json", {"generated_utc": "t1", "v": 2})
    (work / "README.md").write_text("changed but not listed", encoding="utf-8")
    assert gitops.commit_and_push(["data/aladin"], MSG, min_interval_s=0) is True
    assert "README.md" not in sh(work, "git", "show", "--name-only", "--format=", "HEAD")
    assert " M README.md" in sh(work, "git", "status", "--porcelain")                  # still just a local edit, never committed


def test_secrets_and_live_ticks_are_never_staged(repo):
    work, remote = repo
    (work / ".env").write_text("KEY=1", encoding="utf-8")
    (work / ".env.local").write_text("KEY=2", encoding="utf-8")
    write(work, "data/live_extra/ticks.json", {"q": {}})
    assert gitops.commit_and_push([".env", ".env.local", "data/live_extra/ticks.json"], MSG, min_interval_s=0) is False
    assert head_msg(work) == "base"
    write(work, "data/aladin/sentiment.json", {"generated_utc": "t1", "v": 2})
    assert gitops.commit_and_push(["data/aladin", ".env", "data/live_extra"], MSG, min_interval_s=0) is True
    files = sh(work, "git", "show", "--name-only", "--format=", "HEAD")
    assert ".env" not in files and "live_extra" not in files


def test_failed_push_returns_false_and_never_raises(repo, monkeypatch):
    work, remote = repo
    sh(work, "git", "remote", "set-url", "origin", str(work.parent / "does-not-exist.git"))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    write(work, "data/aladin/sentiment.json", {"generated_utc": "t1", "v": 2})
    assert gitops.commit_and_push(["data/aladin"], MSG, min_interval_s=0) is False
