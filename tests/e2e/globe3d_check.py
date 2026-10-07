"""
The WebGL globe (V4 8.8, checklist 7): lazy loading, frame rate with 2,500 flights + 1,500 vessels and trails, the governor, memory over 20 open/close cycles, the fallbacks.
Needs `python scripts/dev_preview.py --no-browser` running:      python tests/e2e/globe3d_check.py [all|lazy|fps|governor|memory|fallback|screens]

The headless browser draws WebGL IN SOFTWARE (SwiftShader), which is far slower than a graphics card; the numbers below are therefore a floor, not what a laptop will see.
The 4,000 entities are TEST-ONLY (random positions, written into the served telemetry.json by the test; nothing is written to disk).
"""
import io
import json
import os
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import BASE, GL_ARGS, check, ok  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
SHOTS = ROOT / "docs" / "screens_v4"


def big_snapshot_route(n_fl=2500, n_ve=1500, age=3):
    def handler(route):
        r = route.fetch()
        j = r.json()
        rnd = random.Random(11)
        t = int(time.time()) - age
        j["flights"] = [[f"f{i:05d}", f"XX{i}", rnd.uniform(-45, 60), rnd.uniform(-30, 140), 9000, 220, rnd.randint(0, 359), 0, "Testland", 1 if i % 9 == 0 else 0, t] for i in range(n_fl)]
        j["vessels"] = [[500000 + i, f"V{i}", rnd.uniform(-35, 45), rnd.uniform(-10, 125), 12, rnd.randint(0, 359), rnd.randint(0, 359), 70, None, None, t] for i in range(n_ve)]
        j["reason"] = None
        j["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        route.fulfill(response=r, body=json.dumps(j))
    return handler


def new_page(pw, size=(1440, 900), throttle=None, reduced=False, args=None, routes=None):
    headed = os.environ.get("GL_HEADED") == "1"            # GL_HEADED=1: a visible browser window that uses this PC's real graphics card (the default headless browser draws WebGL in software)
    b = pw.chromium.launch(headless=not headed, args=([] if headed else GL_ARGS) if args is None else args)
    ctx = b.new_context(viewport={"width": size[0], "height": size[1]}, reduced_motion="reduce" if reduced else "no-preference")
    pg = ctx.new_page()
    pg.add_init_script("localStorage.setItem('blab.globe.layers', JSON.stringify({ air: false }))")        # "Other flights" is on by default now; these measurements switch it on themselves, from the load they were written for
    errs, reqs = [], []
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
    pg.on("console", lambda m: errs.append(f"{m.type}: {m.text[:160]}") if m.type in ("error", "warning") and "ERR_NETWORK" not in m.text else None)
    pg.on("request", lambda r: reqs.append(r.url))
    pg.add_init_script("localStorage.setItem('blab-onboarded','true')")
    if throttle:
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
        pg.cdp = cdp                                                   # kept, so a test can end the slowdown on the same session
    for pat, h in (routes or {}).items():
        pg.route(pat, h)
    pg.goto(BASE)
    pg.wait_for_timeout(4500)
    return b, pg, errs, reqs


def open_globe(pg, mode="globe", wait=5000):
    pg.dispatch_event('#tabs [data-go="map"]', "click")
    pg.wait_for_selector("#gd-mode")
    pg.wait_for_timeout(600)
    pg.click(f'#gd-mode [data-m="{mode}"]')
    pg.wait_for_timeout(wait)


def stats(pg):
    return pg.evaluate("() => { const c = document.querySelector('#gd-canvas'); return c && c.__g3 ? c.__g3.stats() : null; }")


def run(which="all"):
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        if which in ("all", "lazy"):
            b, pg, errs, reqs = new_page(pw)
            check("three.js is not requested before the Globe opens", not any("three" in u for u in reqs))
            n0 = len(reqs)
            pg.dispatch_event('#tabs [data-go="map"]', "click")
            pg.wait_for_selector("#gd-mode")
            pg.wait_for_timeout(5000)
            check("the Map tab opens on the 3D globe by default", pg.evaluate("document.querySelector('#gd-canvas').dataset.engine") == "webgl")
            pg.click('#gd-mode [data-m="map"]')
            pg.wait_for_timeout(800)
            check("the standard Map is one click away", pg.evaluate("!document.querySelector('#globe-map').hidden"))
            open_globe(pg, "globe", 6000)
            three = [u for u in reqs if "three" in u]
            check("three.js (pinned, from jsDelivr) is requested when the Globe opens", any("three@0.186.1" in u for u in three), three[:2])
            check("the WebGL engine is the one in use", pg.evaluate("document.querySelector('#gd-canvas').dataset.engine") == "webgl")
            check("lazy-load: no console errors or warnings", not errs, errs[:3])
            b.close()

        if which in ("all", "fps"):
            for thr, want in ((None, 50), (4, 30)):
                b, pg, errs, _ = new_page(pw, throttle=thr, routes={"**/telemetry.json*": big_snapshot_route()})
                open_globe(pg, "globe", 3000)
                pg.check('[data-layer="air"]')
                pg.wait_for_timeout(9000)
                s = stats(pg)
                cvs = pg.evaluate("document.querySelector('#gd-canvas').dataset.items")
                label = "unthrottled" if thr is None else f"{thr}x CPU throttle"
                gpu = "SOFTWARE WebGL" if s["software"] else "graphics card"
                check(f"{label} ({gpu}): {s['entities']} entities with trails: median {s['fps']:.0f} fps ({s['medianMs']:.1f} ms a frame, our code {s['jsMs']:.1f} ms), governor level {s['level']}, {s['drawCalls']} draw calls",
                      s["entities"] >= 3900 and (s["fps"] >= want), f"need >= {want} fps; pickable items {cvs}")
                check(f"{label}: 0 console errors", not errs, errs[:3])
                b.close()

        if which in ("all", "governor"):
            b, pg, errs, _ = new_page(pw, throttle=6, routes={"**/telemetry.json*": big_snapshot_route()})
            open_globe(pg, "globe", 3000)
            pg.check('[data-layer="air"]')
            seen = []
            for _ in range(12):
                pg.wait_for_timeout(2000)
                s = stats(pg)
                seen.append(s["level"])
            check("governor steps down when frames are slow (6x CPU throttle): levels seen " + " > ".join(dict.fromkeys(seen)), seen[-1] != "full" and "no_trails" in seen)
            chip = pg.inner_text("#gd-chips")
            check("the 'Reduced detail' chip appears while it is stepped down", "Reduced detail" in chip, chip[-90:])
            b.close()
            # step-up: a fresh, unthrottled page is forced to the lowest level, then real smooth frames bring it back (removing a CPU-throttle emulation mid-page does not
            # release cleanly in headless Chromium, so the slowdown is not used for this half)
            b, pg, errs, _ = new_page(pw, routes={"**/telemetry.json*": big_snapshot_route(1200, 600)})
            open_globe(pg, "globe", 3000)
            pg.evaluate("() => { const c = document.querySelector('#gd-canvas').__g3; c.gov.level = 3; c.gov.settle = 0; c.gov.calmSince = null; c.resize(); c.hooks.governor && c.hooks.governor(c.gov); }")
            t0 = time.time()
            seen_up = []
            for _ in range(60):
                pg.wait_for_timeout(2000)
                lv = stats(pg)["level"]
                if not seen_up or seen_up[-1][0] != lv:
                    seen_up.append((lv, round(time.time() - t0)))
                if lv == "full":
                    break
            first_up = seen_up[1][1] if len(seen_up) > 1 else None
            check(f"governor steps back up on smooth frames, one level at a time, not before 10 s: {seen_up}", seen_up[-1][0] == "full" and first_up is not None and first_up >= 10, seen_up)


        if which in ("all", "memory"):
            b, pg, errs, _ = new_page(pw, routes={"**/telemetry.json*": big_snapshot_route(800, 400)})
            open_globe(pg, "globe", 3500)
            g0 = stats(pg)
            samples = [(g0["geometries"], g0["textures"])]
            for i in range(20):
                pg.click('#gd-mode [data-m="map"]')
                pg.wait_for_timeout(400)
                pg.click('#gd-mode [data-m="globe"]')
                pg.wait_for_timeout(2200)
                s = stats(pg)
                samples.append((s["geometries"], s["textures"]))
            pg.click('#gd-mode [data-m="map"]')
            pg.wait_for_timeout(600)
            after = pg.evaluate("() => { const c = document.querySelector('#gd-gl'); const g = c && c.__g3; return g ? { geometries: g.renderer.info.memory.geometries, textures: g.renderer.info.memory.textures } : null }")
            check(f"20 open/close cycles: geometries and textures do not grow {samples[0]} -> {samples[-1]} (max seen {max(g for g, _ in samples)}, {max(t for _, t in samples)})",
                  max(g for g, _ in samples) <= samples[1][0] + 2 and max(t for _, t in samples) <= samples[1][1] + 1 and samples[-1][0] <= samples[1][0] and samples[-1][1] <= samples[1][1], samples[:4])
            check(f"after leaving the Globe the renderer holds nothing: {after}", after is not None and after["geometries"] <= 2 and after["textures"] <= 1, after)
            check("memory cycles: 0 console errors", not errs, errs[:3])
            b.close()

        if which in ("all", "fallback"):
            b, pg, errs, _ = new_page(pw, args=["--disable-3d-apis", "--disable-gpu", "--disable-webgl"])
            open_globe(pg, "globe", 4500)
            chip = pg.inner_text("#gd-chips")
            check("no WebGL: the flat 2D map is used and a notice says why", "Flat 2D map" in chip and pg.evaluate("document.querySelector('#gd-canvas').dataset.engine || '2d'") != "webgl", chip[-120:])
            check("no WebGL: the page still draws (2D canvas) and has no console errors", pg.evaluate("!document.querySelector('#gd-canvas').hidden") and not [e for e in errs if "WebGL" not in e and "GPU" not in e], errs[:3])
            b.close()
            b, pg, errs, _ = new_page(pw)
            open_globe(pg, "globe", 5000)
            pg.evaluate("() => { const c = document.querySelector('#gd-canvas'); const gl = c.getContext('webgl2') || c.getContext('webgl'); const e = gl.getExtension('WEBGL_lose_context'); e.loseContext(); }")
            pg.wait_for_timeout(2500)
            chip = pg.inner_text("#gd-chips")
            check("context lost: falls back to the flat 2D map with a notice", "Flat 2D map" in chip and "context" in chip, chip[-120:])
            b.close()
            b, pg, errs, _ = new_page(pw, reduced=True, routes={"**/telemetry.json*": big_snapshot_route(600, 300)})
            open_globe(pg, "globe", 3500)
            pg.wait_for_timeout(5000)
            r = pg.evaluate("() => { const g = document.querySelector('#gd-canvas').__g3; return { reduced: g.reduced, trails: g.trailObj.visible, spinning: g.view.lon }; }")
            lon0 = r["spinning"]
            pg.wait_for_timeout(11000)
            lon1 = pg.evaluate("document.querySelector('#gd-canvas').__g3.view.lon")
            check("prefers-reduced-motion: no trails and no auto-rotation", r["reduced"] and not r["trails"] and abs(lon1 - lon0) < 1e-6, [r, lon0, lon1])
            b.close()

        if which in ("all", "drawer"):
            b, pg, errs, _ = new_page(pw)
            open_globe(pg, "globe", 5000)
            pg.locator("#gd-wrap").scroll_into_view_if_needed()
            pg.wait_for_timeout(800)
            items = pg.evaluate("document.querySelector('#gd-canvas')._items")
            hot = [i for i in items if i["type"] == "hotspot"]
            box = pg.locator("#gd-canvas").bounding_box()
            pg.mouse.click(box["x"] + hot[0]["x"], box["y"] + hot[0]["y"])
            pg.wait_for_timeout(1500)
            t1 = pg.inner_text("#nx-title") if pg.locator("#nx-title").count() else ""
            docked = pg.evaluate("() => { const r = document.querySelector('#nx-root'); return r && r.classList.contains('nx-docked') && !r.hidden; }")
            modal = pg.get_attribute(".nx-drawer", "aria-modal")
            check(f"desktop: a click on the Globe opens the NEXUS drawer docked beside it (aria-modal={modal})", bool(t1) and docked and modal == "false", [t1, docked, modal])
            items2 = pg.evaluate("document.querySelector('#gd-canvas')._items")
            hot2 = [i for i in items2 if i["type"] == "hotspot" and i["id"] != hot[0]["id"] and i["x"] < box["width"] - 760 + 0]
            pg.mouse.click(box["x"] + hot2[0]["x"], box["y"] + hot2[0]["y"]) if hot2 else None
            pg.wait_for_timeout(1500)
            t2 = pg.inner_text("#nx-title")
            check("the Globe stays usable with the drawer open: clicking another point on it switches the drawer to that entity", bool(hot2) and t2 != t1, [t1, t2])
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(500)
            check("Esc closes the drawer", pg.evaluate("() => { const r = document.querySelector('#nx-root'); return !r || r.hidden; }"))
            check("drawer: 0 console errors", not errs, errs[:3])
            b.close()
            b, pg, errs, _ = new_page(pw, size=(390, 844))
            open_globe(pg, "globe", 5000)
            pg.locator("#gd-wrap").scroll_into_view_if_needed()
            pg.wait_for_timeout(800)
            it = [i for i in pg.evaluate("document.querySelector('#gd-canvas')._items") if i["type"] == "hotspot"][0]
            box = pg.locator("#gd-canvas").bounding_box()
            pg.mouse.click(box["x"] + it["x"], box["y"] + it["y"])
            pg.wait_for_timeout(1500)
            r = pg.evaluate("() => { const d = document.querySelector('.nx-drawer').getBoundingClientRect(); return { top: d.top, w: d.width, h: d.height, vh: innerHeight, vw: innerWidth, modal: document.querySelector('.nx-drawer').getAttribute('aria-modal') }; }")
            check("phone: the drawer is a full-width bottom sheet", r["w"] >= r["vw"] - 1 and r["top"] > 40 and abs(r["h"] - 0.88 * r["vh"]) < 8 and r["modal"] == "true", r)
            b.close()

        if which in ("all", "screens"):
            for name, size in (("1440x900", (1440, 900)), ("390x844", (390, 844))):
                for mode in ("globe", "flat"):
                    b, pg, errs, _ = new_page(pw, size=size, routes={"**/telemetry.json*": big_snapshot_route(900, 400)})
                    open_globe(pg, mode, 6000)
                    pg.locator("#gd-wrap").scroll_into_view_if_needed()
                    pg.wait_for_timeout(1500)
                    pg.screenshot(path=str(SHOTS / f"globe_{mode}_{name}.png"))
                    fits = pg.evaluate("document.querySelector('#gd-canvas').getBoundingClientRect().width <= window.innerWidth && document.documentElement.scrollWidth <= window.innerWidth + 1")
                    check(f"{mode} at {name}: fits the screen, screenshot saved to docs/screens_v4/", fits and not errs, errs[:2])
                    b.close()
    print("ALL OK" if all(ok) else f"{ok.count(False)} FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "all"))
