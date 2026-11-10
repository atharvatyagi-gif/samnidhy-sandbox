"""
The earlier ALADIN models behind the ALADIN BOT access code (owner, 2026-11-10: "hide them from the main site, keep them in the
backend, inside ALADIN BOT with the same password"). They keep running and learning every night; only their PUBLISHED files change.

Called by scripts/build_site.py after everything is copied into site/:
  every legacy file (aladin.json, predict.json, aladin_moves.json, aladin_movers.json, paper.json, aladin_method.json, aladin2/**
  except the bot's own bot.enc.json) is encrypted to site/legacy/<path>.enc and its readable copy is DELETED.
  Encryption: AES-256-GCM, one key derived from the access code with PBKDF2-SHA256 (600,000 rounds, one random salt per build,
  stored in site/legacy/meta.json); each file has its own random IV. The browser derives the key once when the bot is unlocked.
Without ALADIN_BOT_CODE in the environment the readable copies are still deleted (nothing leaks); the bot says they are not published.
The code is never written, logged or committed.
"""
import base64
import json
import os
import re
import shutil
from pathlib import Path

from . import bot

LEGACY = re.compile(r"^(aladin\.json|predict\.json|aladin_moves\.json|aladin_movers\.json|paper\.json|aladin_method\.json|aladin2/(?!bot\.enc\.json$).+)$")
AAD = b"aladin-legacy-v1"


def legacy_files(site):
    site = Path(site)
    return sorted(p for p in site.rglob("*.json") if LEGACY.match(p.relative_to(site).as_posix()))


def protect(site, code=None, iterations=bot.ITER):
    """-> dict(files, bytes, encrypted). Deletes every readable legacy file in `site`."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    site = Path(site)
    files = legacy_files(site)
    out = site / "legacy"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    code = code if code is not None else os.environ.get("ALADIN_BOT_CODE")
    b = lambda x: base64.b64encode(x).decode()
    total = 0
    if code:
        salt = os.urandom(16)
        key = bot._key(code, salt, iterations)
        g = AESGCM(key)
        iv = os.urandom(12)
        meta = {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iterations, "salt": b(salt), "aad": AAD.decode(),
                "check": {"iv": b(iv), "ct": b(g.encrypt(iv, b"legacy-ok", AAD))}}
        for p in files:
            rel = p.relative_to(site).as_posix()
            iv = os.urandom(12)
            raw = p.read_bytes()
            total += len(raw)
            dst = out / (rel + ".enc")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps({"iv": b(iv), "ct": b(g.encrypt(iv, raw, AAD))}, separators=(",", ":")), encoding="utf-8")
    else:
        meta = {"v": 1, "missing": True}
    for p in files:
        p.unlink()
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return {"files": len(files), "bytes": total, "encrypted": bool(code)}


def open_file(site, rel, code):
    """Decrypt one protected file (tests and checks only)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    site = Path(site)
    meta = json.loads((site / "legacy" / "meta.json").read_text(encoding="utf-8"))
    d = lambda x: base64.b64decode(x)
    key = bot._key(code, d(meta["salt"]), meta["iter"])
    blob = json.loads((site / "legacy" / (rel + ".enc")).read_text(encoding="utf-8"))
    return json.loads(AESGCM(key).decrypt(d(blob["iv"]), d(blob["ct"]), meta["aad"].encode()))
