"""
Runs the whole daily update for Samnidhy Sandbox, in order:

  1. pick the top gainers and losers of the last completed NSE session  (pick_movers.py)
  2. download and check their price history plus the benchmark          (fetch_data.py)
  3. compute every statistic the site shows                             (process_data.py)
  4. save the day, but only if steps 1-3 all worked

Saved on success:
  data/picks/<session>.json   the day's picks          (kept, so past days can be shown)
  data/archive/<session>.json the day's full analysis  (kept, so past days can be shown)
  data/picks/latest.json      copy of the newest picks
  data/picks/index.json       every saved session date, newest first
  data/data.json              the analysis the site currently shows
  data/status.json            ok / error, and when the last attempt and last success were

On any failure only data/status.json changes (ok = false, with the reason). Everything
the site shows stays exactly as it was, so the last good day remains visible. Nothing
is ever invented or substituted.

Usage:
  python scripts/update.py                    # normal daily run
  python scripts/update.py --as-of 2026-09-20 # rebuild the last session on or before a date
"""

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import fetch_history, history_years  # noqa: E402
from pick_movers import IST, compute_picks, load_config, print_picks  # noqa: E402
from process_data import analyse              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PICKS_DIR = DATA / "picks"
ARCHIVE_DIR = DATA / "archive"
STATUS_PATH = DATA / "status.json"


def to_json(obj) -> str:
    # allow_nan=False turns any NaN/Infinity that slipped through into an error instead of a broken site
    return json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)  # atomic: a half-written file is never left behind


def ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def check(picks: dict, analysis: dict, cfg: dict) -> None:
    """Final sanity checks before anything is saved."""
    want_g, want_l = cfg["picks"]["gainers_count"], cfg["picks"]["losers_count"]
    groups = [analysis["stocks"][t]["group"] for t in analysis["order"]]
    if groups.count("gainer") != want_g or groups.count("loser") != want_l:
        raise RuntimeError(f"expected {want_g} gainers and {want_l} losers, got {groups}")
    if len(set(analysis["order"])) != len(analysis["order"]):
        raise RuntimeError("the same stock was picked twice")
    if analysis["session_date"] != picks["session_date"]:
        raise RuntimeError("session dates of picks and analysis do not match")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", help="use the last session on or before this date (YYYY-MM-DD)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    previous = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
    status = {
        "last_attempt_utc": now.isoformat(timespec="seconds"),
        "last_attempt_ist": ist(now),
        "last_success_utc": previous.get("last_success_utc"),
        "last_success_ist": previous.get("last_success_ist"),
        "session_date": previous.get("session_date"),
    }

    try:
        cfg = load_config()
        as_of = date.fromisoformat(args.as_of) if args.as_of else now.astimezone(IST).date()

        print("=== 1. Picking stocks ===")
        picks = compute_picks(cfg, as_of,
                              history_years=lambda t, s: history_years(t, s, cfg["history"]["years"]))
        print_picks(picks)

        print("\n=== 2. Price history ===")
        history, sources, bench_session = fetch_history(picks, cfg)

        print("\n=== 3. Calculations ===")
        analysis = analyse(picks, history, cfg, sources, bench_session)
        check(picks, analysis, cfg)

        picks_record = {**picks, "fetched_at_utc": now.isoformat(timespec="seconds"), "fetched_at_ist": ist(now)}
        picks_text, analysis_text = to_json(picks_record), to_json(analysis)
    except Exception as exc:
        status.update({"ok": False, "error": str(exc)})
        write_text(STATUS_PATH, to_json(status))
        print(f"\nFAILED: {exc}\nNothing the site shows was changed; the last good day stays in place.", file=sys.stderr)
        return 1

    # ---- 4. save (only reached when everything above worked) ----
    session = picks["session_date"]
    write_text(PICKS_DIR / f"{session}.json", picks_text)
    write_text(ARCHIVE_DIR / f"{session}.json", analysis_text)
    newest = json.loads((PICKS_DIR / "latest.json").read_text(encoding="utf-8"))["session_date"] \
        if (PICKS_DIR / "latest.json").exists() else ""
    is_newest = session >= newest
    if is_newest:
        write_text(PICKS_DIR / "latest.json", picks_text)
        write_text(DATA / "data.json", analysis_text)
    sessions = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.json")), reverse=True)
    write_text(PICKS_DIR / "index.json", to_json({"sessions": sessions}))

    status.update({"ok": True, "error": None})
    if is_newest:
        status.update({"last_success_utc": now.isoformat(timespec="seconds"), "last_success_ist": ist(now),
                       "session_date": session})
    write_text(STATUS_PATH, to_json(status))

    w = analysis["analysis_window"]
    print(f"\nSaved session {session}{'' if is_newest else ' (older day; the site still shows ' + newest + ')'}.")
    print(f"Shared analysis window: {w['start']} to {w['end']} ({w['years']} years, {w['trading_days']} trading days)"
          + (f", limited by {', '.join(w['limited_by'])}" if w["limited_by"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
