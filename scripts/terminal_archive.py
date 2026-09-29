"""
Older price history for the Expert terminal chart (everything before the 5 years in data/terminal/daily).

When you scroll a chart back past 5 years, the page fetches this from the repository's "history" branch
(raw.githubusercontent.com allows that). Keeping it out of the website means the site that is republished
every 15 minutes stays small; the old years hardly ever change, so the branch is rebuilt about once a month
by .github/workflows/history-archive.yml.

For each main-board stock: Yahoo Finance daily candles for the whole period Yahoo has ("max"),
split-adjusted like the 5-year files. Kept: every day before the first day of the 5-year file, plus 10
overlapping days so the page can line the two up exactly (it rescales the old part if a split happened
since this archive was made).

  python scripts/terminal_archive.py            -> data/terminal/archive/<key>.json  (+ _index.json)
"""

import json
import sys
from pathlib import Path

from terminal_hist import BATCH, INDICES, OUT as DAILY, TERM, download, key

ARCH = TERM / "archive"
OVERLAP = 10


def main():
    uni = json.loads((TERM / "universe.json").read_text(encoding="utf-8"))
    syms = [s["s"] for s in uni["stocks"] if s.get("board") == "Main" and (DAILY / f"{key(s['s'])}.json").exists()]
    ARCH.mkdir(parents=True, exist_ok=True)
    firsts = {}
    for s in syms:
        firsts[s] = json.loads((DAILY / f"{key(s)}.json").read_text(encoding="utf-8"))["d"][0][0]
    tickers = [s + ".NS" for s in syms] + [t for t, _ in INDICES]
    for t, _ in INDICES:
        p = DAILY / f"{key(t)}.json"
        if p.exists():
            firsts[t] = json.loads(p.read_text(encoding="utf-8"))["d"][0][0]
    print(f"downloading full history for {len(tickers)} tickers in batches of {BATCH}")
    got = download(tickers, "max")
    index, total = {}, 0
    for t in tickers:
        sym = t[:-3] if t.endswith(".NS") else t
        rows = got.get(t)
        first = firsts.get(sym)
        if not rows or not first:
            continue
        old = [r for r in rows if r[0] < first]
        if not old:
            continue
        keep = old + [r for r in rows if r[0] >= first][:OVERLAP]
        (ARCH / f"{key(sym)}.json").write_text(json.dumps({"s": sym, "src": "Yahoo Finance, split-adjusted", "d": keep}, separators=(",", ":")), encoding="utf-8")
        index[sym] = [old[0][0], len(old)]
        total += len(old)
    (ARCH / "_index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    print(f"{len(index)} symbols have history before their 5-year file ({total:,} extra days); oldest starts {min((v[0] for v in index.values()), default='-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
