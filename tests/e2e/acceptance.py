"""
Browser acceptance checks for the ALADIN desk (checks 1, 7, 12 of the brief). Not collected by pytest (it needs a running dev server and Chromium):

  python scripts/dev_preview.py --no-browser        (in another window; serves http://127.0.0.1:8765/expert-dev.html)
  python tests/e2e/acceptance.py [console|perf|degrade|a11y|all]

console  every tab (Brief ... Tools) with the local tick daemon on and off: 0 console errors / warnings
perf     desk opens fast with the CPU throttled 4x; houses.json, geo.json and the map libraries are not requested until their tabs open; file sizes
degrade  sentiment.json, geo.json, aladin.json missing, daemon stopped: honest "not available" states, no errors
a11y     axe-core accessibility audit of the page and the ALADIN tab, keyboard reach of dropdowns / sortable headers / tabs
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = "http://127.0.0.1:8765/expert-dev.html"
TABS = ["brief", "terminal", "movers", "sectors", "houses", "world", "outlook", "news", "globe", "lab"]
ok = []
GL_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"]      # software WebGL, so the headless browser can run the 3D globe


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra != "" else ""))
    ok.append(bool(cond))


def page_for(pw, size=(1440, 900), init=None, throttle=None, routes=None):
    b = pw.chromium.launch(args=GL_ARGS)
    ctx = b.new_context(viewport={"width": size[0], "height": size[1]})
    pg = ctx.new_page()
    errs, reqs = [], []
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
    pg.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("request", lambda r: reqs.append((r.url, time.time())))
    pg.add_init_script("localStorage.setItem('blab-onboarded','true')")
    if init:
        pg.add_init_script(init)
    for pat, handler in (routes or {}).items():
        pg.route(pat, handler)
    if throttle:
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
    return b, pg, errs, reqs


def visit_all(pg):
    for t in TABS:
        pg.dispatch_event(f'#tabs [data-go="{t}"]', "click")
        pg.wait_for_timeout(1500 if t in ("globe", "lab", "houses") else 600)


def run_console():
    daemon = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "aladin_ticker_daemon.py")], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    try:
        with sync_playwright() as pw:
            for label, init in (("daemon on (TICKS ON)", "localStorage.setItem('aladin.ticks','1')"), ("daemon feature off", None)):
                b, pg, errs, _ = page_for(pw, init=init)
                pg.goto(BASE)
                pg.wait_for_timeout(7000)
                visit_all(pg)
                chip = pg.inner_text("#live-txt")
                check(f"console [{label}]: 0 errors or warnings across all 10 tabs", not errs, errs[:3])
                if init:
                    check("console [daemon on]: the chip shows the local feed", "NSE WEB (THIS PC" in chip, chip)
                b.close()
    finally:
        daemon.terminate()


MARK = """
window.__marks = {};
new MutationObserver(() => { const e = document.querySelector('#brief-cards'); if (e && e.children.length && !window.__marks.brief) window.__marks.brief = performance.now(); }).observe(document, { childList: true, subtree: true });
"""


def run_perf():
    import statistics
    times = []
    with sync_playwright() as pw:
        for _ in range(3):                                                       # the Brief's cards exist in the page (measured with a MutationObserver: no dependence on paint or web-font timing)
            b, pg, errs, reqs = page_for(pw, throttle=4, init=MARK)
            pg.goto(BASE, wait_until="commit")
            pg.wait_for_function("window.__marks && window.__marks.brief", timeout=60000)
            times.append(pg.evaluate("window.__marks.brief") / 1000)
            pg.wait_for_timeout(1500)
            if _ < 2:
                b.close()
        t = statistics.median(times)
        check("perf: Brief content exists in under 2 s with the CPU throttled 4x (median of 3)", t < 2.0, f"median {t:.2f} s, runs {[round(x, 2) for x in times]}")
        pg.wait_for_timeout(2500)
        names = [u.split("?")[0].split("/")[-1] for u, _ in reqs]
        urls = " ".join(u for u, _ in reqs)
        check("perf: houses.json is not requested before the Houses tab opens", "houses.json" not in names)
        check("perf: geo.json is not requested before the Globe tab opens", "geo.json" not in names)
        check("perf: the tiny geo_summary.json is what the Brief reads instead", "geo_summary.json" in names)
        check("perf: no map libraries (Leaflet / d3 / topojson) before the Globe tab opens", not re.search(r"leaflet|d3-geo|topojson", urls))
        tq = next((t0 for u, t0 in reqs if u.split("?")[0].endswith("quotes.json")), None)
        for f in ("aladin.json", "sentiment.json", "paper.json", "aladin_method.json"):
            ta = next((t0 for u, t0 in reqs if u.split("?")[0].endswith("/" + f)), None)
            check(f"perf: {f} is not requested during start-up (never before 4 s after the desk's own data)", ta is None or (tq is not None and ta - tq >= 4), None if ta is None else round(ta - tq, 1))
        n0 = len(reqs)
        pg.dispatch_event('#tabs [data-go="houses"]', "click"); pg.wait_for_timeout(1500)
        check("perf: houses.json is requested when Houses opens", "houses.json" in [u.split("?")[0].split("/")[-1] for u, _ in reqs[n0:]])
        pg.dispatch_event('#tabs [data-go="globe"]', "click"); pg.wait_for_timeout(3000)
        urls2 = " ".join(u for u, _ in reqs[n0:])
        check("perf: the map libraries are requested when Globe opens", "leaflet" in urls2)
        b.close()
    sizes = {f: (ROOT / "site" / f).stat().st_size for f in ("aladin.json", "sentiment.json", "geo.json", "houses.json", "paper.json", "aladin_method.json", "geo_summary.json") if (ROOT / "site" / f).exists()}
    check("size: aladin.json under 3 MB", sizes.get("aladin.json", 0) < 3_000_000, {k: f"{v / 1e3:.0f} KB" for k, v in sizes.items()})

def run_degrade():
    def body(obj):
        return lambda route: route.fulfill(status=200, body=json.dumps(obj), headers={"content-type": "application/json"})
    man = json.loads((ROOT / "site" / "desk_data.json").read_text(encoding="utf-8"))
    cases = {
        "sentiment.json missing": ({"sentiment": False}, None),
        "geo.json missing": ({"geo": False, "geo_summary": False}, None),
        "aladin.json missing": ({"aladin": False}, None),
        "all three missing": ({"sentiment": False, "geo": False, "geo_summary": False, "aladin": False}, None),
    }
    with sync_playwright() as pw:
        for name, (off, _) in cases.items():
            m = {**man, **off}
            b, pg, errs, reqs = page_for(pw, routes={"**/desk_data.json*": body(m)})
            pg.goto(BASE)
            pg.wait_for_timeout(7000)
            visit_all(pg)
            lab = pg.inner_text("#aladin")
            if off.get("aladin") is False:
                check(f"degrade [{name}]: ALADIN says it is not available", "not available" in lab.lower(), lab[:70])
            else:
                check(f"degrade [{name}]: ALADIN table still works", pg.eval_on_selector_all("#al-table tr.al-r", "e => e.length") > 0)
            if off.get("sentiment") is False:
                check(f"degrade [{name}]: sentiment shows NO NEWS, P(up) falls back to the remaining views", pg.eval_on_selector_all("#al-table .sent[data-lvl='NO NEWS']", "e => e.length") > 0 if off.get("aladin") is not False else True)
            if off.get("geo") is False:
                check(f"degrade [{name}]: the Globe's news-attention section says it has not been published", "not been published" in pg.inner_text("#geo-desk"))
            check(f"degrade [{name}]: zero console errors or warnings", not errs, errs[:3])
            b.close()
        # the local tick daemon is not running and the user has NOT opted in: nothing is attempted, nothing is logged
        b, pg, errs, reqs = page_for(pw)
        pg.goto(BASE); pg.wait_for_timeout(7000); visit_all(pg)
        check("degrade [daemon not running, feature off]: no websocket attempt, no console messages", not errs and not any(u.startswith("ws://") for u, _ in reqs), errs[:2])
        b.close()
        # opted in but the daemon is down: count what the browser itself logs (it cannot be silenced from JavaScript) and make sure it stops after 3 tries
        b, pg, errs, reqs = page_for(pw, init="localStorage.setItem('aladin.ticks','1')")
        pg.goto(BASE); pg.wait_for_timeout(9000); visit_all(pg)
        ws = [e for e in errs if "WebSocket" in e]
        other = [e for e in errs if "WebSocket" not in e]
        check("degrade [opted in, daemon down]: only the browser's own connection notice(s), at most 3, nothing else", len(ws) <= 3 and not other, f"{len(ws)} websocket notice(s); other: {other[:2]}")
        b.close()


AXE = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"


def run_a11y():
    with sync_playwright() as pw:
        b, pg, errs, _ = page_for(pw)
        pg.goto(BASE); pg.wait_for_timeout(7000)
        pg.add_script_tag(url=AXE)
        for label, tab in (("Brief", "brief"), ("Houses", "houses"), ("Tools (ALADIN)", "lab")):
            pg.dispatch_event(f'#tabs [data-go="{tab}"]', "click"); pg.wait_for_timeout(2500)
            res = pg.evaluate("async () => { const r = await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'best-practice'] }); return r.violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length, help: v.help })); }")
            serious = [v for v in res if v["impact"] in ("serious", "critical")]
            print("   axe", label, [(v["id"], v["impact"], v["n"]) for v in res])
            check(f"a11y [{label}]: no serious or critical axe violations", not serious, [(v["id"], v["n"]) for v in serious])
        # keyboard: tabs, dropdowns, sortable headers, sentiment details
        pg.dispatch_event('#tabs [data-go="lab"]', "click"); pg.wait_for_timeout(1500)
        check("a11y: tab buttons are keyboard focusable", pg.evaluate("() => [...document.querySelectorAll('#tabs button')].every(b => b.tabIndex >= 0)"))
        check("a11y: sortable headers are focusable and carry aria-sort", pg.evaluate("() => [...document.querySelectorAll('#al-table th[data-sort]')].every(t => t.tabIndex === 0 && t.hasAttribute('aria-sort'))"))
        check("a11y: filter controls have accessible names", pg.evaluate("() => [...document.querySelectorAll('.al-controls select, .al-controls input')].every(e => e.getAttribute('aria-label'))"))
        check("a11y: sentiment dropdowns are native <details>/<summary> (keyboard operable)", pg.eval_on_selector_all("#al-table details.sent > summary", "e => e.length") > 0)
        b.close()


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, fn in (("console", run_console), ("perf", run_perf), ("degrade", run_degrade), ("a11y", run_a11y)):
        if which in (name, "all"):
            print(f"== {name}")
            fn()
    print("ALL OK" if all(ok) else "SOME FAILED")
