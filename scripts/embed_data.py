"""
Copies the latest data into dashboard.html, so the page works when opened straight from
disk (file://) with no server and no network.

Four JSON blocks inside dashboard.html are replaced:
  dashboard-data      data/data.json      the analysis of the latest successful session
  dashboard-status    data/status.json    did the last update work? (drives "Data not updated")
  dashboard-sessions  data/picks/*.json   every saved session's picks, for the "Past sessions" list
  dashboard-meta      how this copy of the page links to past sessions

Run this after scripts/update.py, whether or not the update succeeded: on a failed day it
still refreshes the status block, so the page shows the "Data not updated" notice.
scripts/build_site.py uses the same functions to build the public site.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HTML_PATH = ROOT / "dashboard.html"
BLOCK_IDS = ("dashboard-data", "dashboard-status", "dashboard-sessions", "dashboard-meta")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sessions_summary() -> list[dict]:
    """Newest first: date and the picks (symbol, label, % change) of every saved session."""
    out = []
    for f in sorted((DATA / "picks").glob("????-??-??.json"), reverse=True):
        p = read_json(f)
        slim = lambda s: {"symbol": s["symbol"], "label": s["label"], "group": s["group"], "pct_change": s["pct_change"]}  # noqa: E731
        out.append({
            "session_date": p["session_date"],
            "gainers": [slim(s) for s in p["gainers"]],
            "losers": [slim(s) for s in p["losers"]],
            "skipped": [{"symbol": s["symbol"], "would_have_been": s["would_have_been"]} for s in p.get("skipped", [])],
        })
    return out


def embed(html: str, blocks: dict) -> str:
    for block_id, obj in blocks.items():
        pattern = re.compile(rf'(<script type="application/json" id="{block_id}">)(.*?)(</script>)', re.DOTALL)
        if len(pattern.findall(html)) != 1:
            sys.exit(f"ERROR: expected exactly one {block_id} <script> block in the page")
        # "</" is escaped so no string inside the data can ever close the script tag early.
        payload = json.dumps(obj, indent=1, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
        html = pattern.sub(lambda m: f"{m.group(1)}\n{payload}\n{m.group(3)}", html)
    return html


def main() -> None:
    data = read_json(DATA / "data.json")
    status = read_json(DATA / "status.json")
    blocks = {
        "dashboard-data": data,
        "dashboard-status": status,
        "dashboard-sessions": sessions_summary(),
        # Opened from the project folder, past sessions live in site/days/ (made by build_site.py).
        "dashboard-meta": {"view": "latest", "days_prefix": "site/days/", "home": "dashboard.html"},
    }
    HTML_PATH.write_text(embed(HTML_PATH.read_text(encoding="utf-8"), blocks), encoding="utf-8")
    print(f"Embedded session {data['session_date']} (last update ok: {status.get('ok')}) into {HTML_PATH.name}")


if __name__ == "__main__":
    main()
