"""
GitOps helper for ALADIN's automated commits.

Every automated commit must end with "[skip ci]", never force-pushes, never raises (a failed push is just
False), stages only the paths it was given, and never stages secrets or the operator's live-tick files. It
does nothing at all unless ALADIN_GIT_PUSH=1, so development runs can never push by accident.

Why "[skip ci]" and a 15-minute floor: GitHub Pages only redeploys when a workflow runs (live-prices.yml does,
every 5 minutes), and the scheduled workflows publish whatever is committed - a commit every few minutes adds
repository bloat with no visible benefit. "[skip ci]" only suppresses push-triggered runs, not scheduled ones.
"""

import json
import os
import subprocess
import time
from pathlib import Path

FORBIDDEN_PREFIXES = ("data/live_extra/",)


def _forbidden(path: str) -> bool:
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    name = p.rsplit("/", 1)[-1]
    return name == ".env" or name.startswith(".env.") or any(p.startswith(f) or p + "/" == f for f in FORBIDDEN_PREFIXES)


def _git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def _semantic(text):
    """JSON with every generated_* key (at any depth) removed, so a refresh that only changed the timestamps
    compares equal. Non-JSON files compare as plain text."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not k.startswith("generated_")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    try:
        return strip(json.loads(text))
    except ValueError:
        return text


def _really_changed(paths):
    """True if any listed file differs from HEAD in more than its generated_* keys (new/deleted files count)."""
    out = _git("status", "--porcelain=v1", "-uall", "--", *paths).stdout
    for line in out.splitlines():
        status, f = line[:2], line[3:].strip().strip('"')
        if "?" in status or "A" in status or "D" in status:
            return True
        head = _git("show", f"HEAD:{f}", check=False)
        if head.returncode != 0:
            return True
        try:
            now = Path(f).read_text(encoding="utf-8")
        except OSError:
            return True
        if _semantic(head.stdout) != _semantic(now):
            return True
    return False


def commit_and_push(paths: list[str], message: str, *, min_interval_s: int = 900,
                    state_file: str = "data/aladin_cache/gitops_state.json", branch: str = "main") -> bool:
    assert message.endswith("[skip ci]"), 'automated commit messages must end with "[skip ci]"'
    try:
        if os.environ.get("ALADIN_GIT_PUSH") != "1":
            return False
        paths = [p for p in paths if not _forbidden(p)]
        if not paths:
            return False
        state = Path(state_file)
        try:
            last = json.loads(state.read_text(encoding="utf-8")).get("last_push_epoch", 0)
        except (OSError, ValueError):
            last = 0
        if time.time() - last < min_interval_s:
            return False
        if not _really_changed(paths):
            return False
        _git("add", "--", *paths)
        if _git("diff", "--cached", "--quiet", "--", *paths, check=False).returncode == 0:
            return False
        _git("commit", "-m", message, "--", *paths)
        for attempt in range(3):
            pulled = _git("pull", "--rebase", "--autostash", "origin", branch, check=False)
            if pulled.returncode == 0 and _git("push", "origin", f"HEAD:{branch}", check=False).returncode == 0:
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text(json.dumps({"last_push_epoch": time.time()}), encoding="utf-8")
                return True
            time.sleep(2 ** attempt)
        return False
    except AssertionError:
        raise
    except Exception:
        return False
