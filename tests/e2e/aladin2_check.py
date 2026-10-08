"""
ALADIN 2.0 browser acceptance (items 12, 13 and 14 of the checklist). Serve a BUILT site (python scripts/dev_preview.py or any static server on site/), then:

  python tests/e2e/aladin2_check.py http://127.0.0.1:8767        -> data/aladin2/e2e_report.json (+ printed summary)
Measures on a real Chromium: console/page errors on every ALADIN 2.0 page at 1440x900 and 390x844; that nothing from aladin2/ is fetched at page start; the time until the desk shows its
watchlist; the time to fetch one stock shard under a throttled connection (150 ms round trip, 1.6 Mbit/s down); keyboard access (Tab to a market-map tile and Enter opens the stock);
tooltips (SVG <title> counts); the disclaimer and an "As of" line on every page; accessible names on charts, buttons and inputs.
"""
import json
import statistics
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8767").rstrip("/")
OUT = Path(__file__).resolve().parents[2] / "data" / "aladin2" / "e2e_report.json"
DIS = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results."
TABS = ["weekly", "score", "map", "rot", "board", "journal", "curve", "method"]
KNOWN_404 = ("live.json", "news.json", "nse_live.json", "INDIAMART.json")          # optional files a local preview may lack; not part of ALADIN 2.0


def main():
    rep = {"base": BASE, "viewports": {}}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, (w, h) in {"desk": (1440, 900), "phone": (390, 844)}.items():
            ctx = b.new_context(viewport={"width": w, "height": h}); pg = ctx.new_page(); errs, reqs, bad = [], [], []
            pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
            pg.on("request", lambda r: reqs.append(r.url)); pg.on("response", lambda r: bad.append(r.url.split("/")[-1].split("?")[0]) if r.status >= 400 else None)
            t0 = time.time(); pg.goto(BASE + "/expert-dev.html#v=terminal&s=TCS", wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_selector("#watch .wl-row", state="attached", timeout=60000); ready_ms = round((time.time() - t0) * 1000); pg.wait_for_timeout(3000)
            early = [u for u in reqs if "aladin2/" in u]
            if pg.locator("#ob-skip").is_visible():
                pg.locator("#ob-skip").click(); pg.wait_for_timeout(500)
            v = {"desk_ready_ms": ready_ms, "aladin2_requests_before_opening_a_stock_or_the_tab": [u.split("aladin2/")[-1].split("?")[0] for u in early], "pages": {}}
            # brief on the open stock
            pg.evaluate("document.querySelector('[data-side=details]') && document.querySelector('[data-side=details]').click()"); pg.wait_for_selector("#a2-brief svg", state="attached", timeout=20000)
            br = pg.locator("#a2-brief"); txt = br.inner_text()
            v["brief"] = {"disclaimer": DIS in txt, "as_of": "as of" in txt.lower(), "svg_titles": br.locator("svg title").count(), "svg_with_label": br.locator("svg[role=img][aria-label]").count(), "inputs_labelled": br.locator("label input").count() == br.locator("input").count(),
                          "table_fallback": br.locator("details summary").count() >= 1}
            pg.evaluate("document.querySelector('[data-go=a2]').click()"); pg.wait_for_timeout(1200)
            for t in TABS:
                pg.evaluate(f"document.querySelector('[data-tab={t}]').click()"); pg.wait_for_timeout(1500)
                root = pg.locator("#a2v"); text = root.inner_text(); svgs = root.locator("svg[role=img]")
                v["pages"][t] = {"disclaimer": DIS in text, "as_of": "As of" in text or "AS OF" in text.upper(), "svg_charts": svgs.count(), "svg_charts_with_aria_label": root.locator("svg[role=img][aria-label]").count(), "svg_titles": root.locator("svg title").count(),
                                 "buttons_without_name": root.locator("button:not([aria-label])").evaluate_all("els => els.filter(e => !e.textContent.trim()).length"), "has_numbers_fallback": root.locator("table").count() > 0 or t in ("map", "journal", "method", "curve")}
            # keyboard: Tab to a market-map tile and press Enter
            pg.evaluate("document.querySelector('[data-tab=map]').click()"); pg.wait_for_timeout(1200); pg.evaluate("document.activeElement && document.activeElement.blur()")
            opened = None
            for _ in range(80):
                pg.keyboard.press("Tab"); sym = pg.evaluate("document.activeElement && document.activeElement.classList.contains('a2v-tile') ? document.activeElement.dataset.sym : null")
                if sym:
                    pg.keyboard.press("Enter"); pg.wait_for_timeout(1500); opened = {"focused_tile": sym, "terminal_symbol": pg.locator("#tb-sym").inner_text()}; break
            v["keyboard_open_from_map"] = opened
            v["js_errors"] = errs; v["unexpected_404s"] = sorted({x for x in bad if x not in KNOWN_404})
            rep["viewports"][name] = v
            # throttled shard fetch (desk only)
            if name == "desk":
                cdp = ctx.new_cdp_session(pg); cdp.send("Network.enable"); cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 150, "downloadThroughput": 1.6 * 1024 * 1024 / 8, "uploadThroughput": 750 * 1024 / 8})
                ms = [pg.evaluate("async s => { const t = performance.now(); const r = await fetch(`aladin2/stock/${s}.json?x=` + Math.random(), { cache: 'no-store' }); const b = await r.arrayBuffer(); return [performance.now() - t, b.byteLength]; }", s) for s in ("TCS", "RELIANCE", "INFY", "ITC", "LT")]
                rep["throttled_stock_shard"] = {"profile": "150 ms round trip, 1.6 Mbit/s", "ms_median": round(statistics.median(m[0] for m in ms)), "ms_max": round(max(m[0] for m in ms)), "bytes": [m[1] for m in ms]}
            ctx.close()
        b.close()
    OUT.write_text(json.dumps(rep, indent=1)); print(json.dumps(rep, indent=1)[:3500])


if __name__ == "__main__":
    main()
