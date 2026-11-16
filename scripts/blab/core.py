"""B-Lab research desk: the framework every bot runs in (docs/blab/PLAN.md). Standard library only.

A bot is a function `fn(ctx) -> {"items": int, "as_of": "YYYY-MM-DD[THH:MM...]", "detail": str, "findings": [...]}` with
metadata (division, role, freshness limit). The framework runs a division's bots IN PARALLEL, times each one, isolates its
errors (one failing bot never stops the others), judges freshness from the source's own date, and keeps one ledger of
findings with a forward scorecard. Nothing here blends divisions into one score.

States: ok, stale (the source is older than the bot's limit), error, planned (arrives in a later step), no_key (a free key
the owner has not added yet), limit (a free quota ran out).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = DATA / "blab"
SITE_URL = "https://atharvatyagi-gif.github.io/samnidhy-sandbox/"
DIVISIONS = {
    "fundamental": {"name": "Fundamental", "source": "what the company or a regulator files about the company"},
    "technical": {"name": "Technical", "source": "what trading produces"},
    "macro": {"name": "Macro", "source": "official economic statistics and market-priced macro"},
    "sentiment": {"name": "Sentiment", "source": "what other people write or say"},
}
HORIZONS = (5, 20, 63)            # trading sessions after a finding at which it is scored
MIN_SCORED = 20                   # fewer scored findings than this: "too few so far", no verdict
REPEAT_DAYS = 7                   # the same bot, stock and direction is one finding until 7 days have passed


class NoKey(Exception):
    """A free key the owner has not added yet."""


class Limit(Exception):
    """A free quota ran out."""


@dataclass
class Bot:
    id: str
    division: str
    name: str
    role: str                     # scout or analyst
    does: str                     # one plain sentence
    sources: list
    fresh_h: float = 100.0        # hours; session data: 100 covers a weekend plus a holiday
    fn: Optional[Callable] = None # None: planned
    step: int = 1                 # the plan step that builds (or built) it
    wraps: str = ""               # the existing job it reports on, if any


@dataclass
class Ctx:
    """What a bot may use: repository files first, the published site second. `fetch` is replaceable in tests."""
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fetch: Callable = None
    used: list = field(default_factory=list)
    shared: dict = field(default_factory=dict)   # what a division's scouts collected this run, for its analysts

    def read(self, repo_path: str = None, site_path: str = None):
        """-> (document, where). The repository copy if it exists, else the live site's copy."""
        if repo_path and (ROOT / repo_path).exists():
            self.used.append(repo_path)
            return json.loads((ROOT / repo_path).read_text(encoding="utf-8")), repo_path
        if site_path:
            self.used.append(site_path)
            return (self.fetch or fetch_json)(SITE_URL + site_path), "site:" + site_path
        raise FileNotFoundError(repo_path or site_path)


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "B-Lab research desk (educational)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_when(s):
    """'2026-11-13', '2026-11-15T16:02:24+00:00', '...Z', '15 Nov 2026, 09:02 PM IST' -> aware UTC datetime, or None."""
    if not s:
        return None
    s = str(s).strip()
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(hour=10, tzinfo=timezone.utc)      # a session date: its 15:30 IST close
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.strptime(s.replace(" IST", ""), "%d %b %Y, %I:%M %p").replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
    except ValueError:
        return None


def run_bot(bot: Bot, ctx: Ctx) -> dict:
    base = {"id": bot.id, "division": bot.division, "name": bot.name, "role": bot.role, "does": bot.does, "sources": bot.sources,
            "wraps": bot.wraps, "step": bot.step, "fresh_h": bot.fresh_h, "findings": []}
    if bot.fn is None:
        return {**base, "state": "planned", "detail": f"Arrives in step {bot.step} of the plan.", "items": None, "as_of": None, "age_h": None, "took_s": None, "errors": []}
    t0 = time.perf_counter()
    try:
        r = bot.fn(ctx) or {}
    except NoKey as e:
        return {**base, "state": "no_key", "detail": str(e), "items": None, "as_of": None, "age_h": None, "took_s": round(time.perf_counter() - t0, 2), "errors": []}
    except Limit as e:
        return {**base, "state": "limit", "detail": str(e), "items": None, "as_of": None, "age_h": None, "took_s": round(time.perf_counter() - t0, 2), "errors": []}
    except Exception as e:  # noqa: BLE001  one bot's failure is reported, never spread
        return {**base, "state": "error", "detail": "The run failed; see errors.", "items": None, "as_of": None, "age_h": None,
                "took_s": round(time.perf_counter() - t0, 2), "errors": [f"{type(e).__name__}: {str(e)[:300]}"]}
    when = parse_when(r.get("as_of"))
    age = None if when is None else round((ctx.now - when).total_seconds() / 3600, 1)
    state = "error" if when is None else "stale" if age > bot.fresh_h else "ok"
    detail = r.get("detail", "")
    if when is None:
        detail = (detail + " " if detail else "") + "The source has no date, so its freshness cannot be checked."
    for f in r.get("findings", []):
        f.setdefault("bot", bot.id); f.setdefault("division", bot.division); f.setdefault("source_as_of", r.get("as_of"))
    return {**base, "state": state, "detail": detail, "items": r.get("items"), "as_of": r.get("as_of"), "age_h": age,
            "took_s": round(time.perf_counter() - t0, 2), "errors": r.get("errors", []), "findings": r.get("findings", [])}


def run_division(bots, division, ctx=None, workers=8) -> dict:
    """A division's scouts all at the same time, then its analysts all at the same time (they read what the scouts put in ctx.shared)."""
    ctx = ctx or Ctx()
    mine = [b for b in bots if b.division == division]
    res = {}
    for phase in ("scout", "analyst"):
        group = [b for b in mine if b.role == phase]
        if group:
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(group)))) as ex:
                for b, r in zip(group, ex.map(lambda b: run_bot(b, ctx), group)):
                    res[b.id] = r
    return {"division": division, "ran_utc": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"), "bots": [res[b.id] for b in mine]}


def finding_id(f):
    if f.get("event"):                            # tied to one filing or disclosure: the same event is one finding, ever
        k = f"{f['bot']}|{f.get('sym') or f.get('scope')}|{f.get('kind')}|{f['event']}"
    else:
        k = f"{f['bot']}|{f.get('sym') or f.get('scope')}|{f.get('kind')}|{f.get('direction')}|{f.get('seen')}"
    return hashlib.sha1(k.encode()).hexdigest()[:12]


def add_findings(ledger, new, today: date):
    """Append findings. One tied to an event (a filing, a disclosure) is added once, ever. Otherwise one per bot + stock + kind +
    direction within REPEAT_DAYS (a mood that lasts a week is one finding, not seven: repeats would inflate the scorecard with
    overlapping copies). -> number added."""
    ids = {f["id"] for f in ledger}
    last = {}
    for f in ledger:
        k = (f["bot"], f.get("sym") or f.get("scope"), f.get("kind"), f.get("direction"))
        last[k] = max(last.get(k, ""), f["seen"])
    added = 0
    for f in new:
        f = {**f, "seen": f.get("seen") or today.isoformat()}
        if f.get("event"):
            f["id"] = finding_id(f)
            if f["id"] not in ids:
                ledger.append(f); ids.add(f["id"]); added += 1
            continue
        k = (f["bot"], f.get("sym") or f.get("scope"), f.get("kind"), f.get("direction"))
        if k in last and (today - date.fromisoformat(last[k])).days < REPEAT_DAYS:
            continue
        f["id"] = finding_id(f)
        ledger.append(f); last[k] = f["seen"]; added += 1
    return added


def forward(closes, index, seen, h):
    """Signed-later excess return of one finding. closes/index: {date_str: close}. Entry: the first close AFTER the day it was
    seen (never the same day: no look-ahead); exit h sessions of the INDEX calendar later. -> (excess, entry_day) or None."""
    days = sorted(d for d in index if d > seen)
    if len(days) <= h:
        return None
    d0, d1 = days[0], days[h]
    if d0 not in closes or d1 not in closes or not closes[d0] or not index[d0]:
        return None
    return (closes[d1] / closes[d0] - 1) - (index[d1] / index[d0] - 1), d0


def scorecard(ledger, prices, index):
    """Per bot and horizon: findings scored, mean of (direction x excess return vs NIFTY 500) in %, 95% range, share right, verdict."""
    out = {}
    for bot in sorted({f["bot"] for f in ledger}):
        rows = [f for f in ledger if f["bot"] == bot and f.get("direction") in (1, -1) and f.get("sym")]
        out[bot] = {"directional": len(rows)}
        for h in HORIZONS:
            xs = []
            for f in rows:
                r = forward(prices.get(f["sym"], {}), index, f["seen"], h)
                if r is not None:
                    xs.append(f["direction"] * r[0] * 100)
            n = len(xs)
            m = sum(xs) / n if n else None
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else None
            lo, hi = (None, None) if sd is None else (m - 1.96 * sd / math.sqrt(n), m + 1.96 * sd / math.sqrt(n))
            if n < MIN_SCORED:
                v = f"too few so far ({n} of {MIN_SCORED})"
            elif lo > 0:
                v = "measurably right so far"
            elif hi < 0:
                v = "measurably wrong so far"
            else:
                v = "no measurable edge so far"
            r2 = lambda x: None if x is None else round(x, 2)
            out[bot][str(h)] = {"n": n, "mean_pct": r2(m), "ci95_pct": None if lo is None else [r2(lo), r2(hi)],
                                "right_pct": None if not n else round(100 * sum(x > 0 for x in xs) / n, 1), "verdict": v}
    return out


def status_doc(parts, bots_meta, ledger, card, now):
    bots = [b for p in parts for b in p["bots"]]
    for b in bots:
        b["findings_new"] = len(b.pop("findings", []))
        b["findings_total"] = sum(1 for f in ledger if f["bot"] == b["id"])
    divs = []
    for k, d in DIVISIONS.items():
        mine = [b for b in bots if b["division"] == k]
        count = lambda s: sum(1 for b in mine if b["state"] == s)
        divs.append({"id": k, **d, "bots": len(mine), "ok": count("ok"), "stale": count("stale"), "error": count("error"),
                     "planned": count("planned"), "no_key": count("no_key"), "limit": count("limit"),
                     "ran_utc": next((p["ran_utc"] for p in parts if p["division"] == k), None)})
    cut = (now.date() - timedelta(days=45)).isoformat()
    return {"version": "blab-1", "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "divisions": divs, "bots": bots,
            "findings_recent": sorted([f for f in ledger if f["seen"] >= cut], key=lambda f: (f["seen"], f["bot"]), reverse=True)[:600],
            "findings_total": len(ledger), "scorecard": card, "horizons": list(HORIZONS), "min_scored": MIN_SCORED, "repeat_days": REPEAT_DAYS,
            "note": "Experimental research desk. Each division reports its own evidence; nothing is blended into one score. Educational analysis, not investment advice."}
