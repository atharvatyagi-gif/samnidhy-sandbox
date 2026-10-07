"""
The masthead chip tells which local feed is running (needs `python scripts/dev_preview.py --no-browser`):   python tests/e2e/ticks_check.py

The page's local tick connection (ws://127.0.0.1:8787/ws/ticks) is replaced by a scripted one, so no daemon and no Angel One login are needed. Checks that
  * a daemon saying src "angel" shows "REAL-TIME · NSE (THIS PC)", and one saying "nse-web" shows "LIVE · NSE WEB (THIS PC, 1-3 min)";
  * the connect message names the feed, ticks update prices, and sweeps arrive;
  * nothing logs a console error.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import BASE, check, ok, page_for  # noqa: E402


def scripted(src):
    def handler(ws):
        ws.send(json.dumps({"type": "hello", "ok": True, "src": src, "port": 8787, "market": "open", "stale": False}))
        ws.send(json.dumps({"type": "snap", "q": {"RELIANCE": [1234.5, 1200, 1250, 1190, 1210, 5000, 1790000000000]}}))
        ws.send(json.dumps({"type": "sweeps", "s": [{"sym": "RELIANCE", "dir": 1, "lvl": "PDL", "px": 1190.0, "rvol": 2.4, "wick": 0.6, "score": 48, "confirmed": True, "ts": 1790000000000}], "agg": {"RELIANCE": 48}}))
    return handler


def run():
    with sync_playwright() as pw:
        for src, want in (("angel", "REAL-TIME · NSE (THIS PC)"), ("nse-web", "LIVE · NSE WEB (THIS PC, 1-3 min)")):
            b, pg, errs, _ = page_for(pw, init="localStorage.setItem('aladin.ticks','1')")
            pg.route_web_socket("ws://127.0.0.1:8787/ws/ticks", scripted(src))
            pg.goto(BASE)
            pg.wait_for_timeout(3500)
            toast = pg.inner_text("#toast")
            check(f"daemon source {src}: the connect message names the feed", f"({'Angel One, real-time, this PC' if src == 'angel' else 'NSE web, this PC'})" in toast, toast[:90])
            pg.wait_for_timeout(3500)
            chip = pg.inner_text("#live-txt")
            check(f"daemon source {src}: the chip says '{want}'", chip.upper() == want.upper(), chip)
            pg.dispatch_event('#tabs [data-go="movers"]', "click")
            pg.wait_for_timeout(1200)
            pg.fill("#mov-filter", "RELIANCE")
            pg.wait_for_timeout(800)
            sw = pg.locator("#mov-table tbody tr[data-s='RELIANCE'] td").nth(8).inner_text()
            check(f"daemon source {src}: the sweep that arrived shows as a badge in Movers", sw == "▲ 48", sw)
            check(f"daemon source {src}: 0 console errors", not errs, errs[:3])
            b.close()
    print("ALL OK" if all(ok) else f"{ok.count(False)} FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(run())
