"""
Browser checks for the Globe's D3 views and the flight / vessel / hotspot / chokepoint panels (needs `python scripts/dev_preview.py --no-browser` running):

  python tests/e2e/globe_check.py

Uses the real local telemetry snapshot (python scripts/aladin_telemetry.py --once --force) for flights. The vessel feed needs a key, so vessel tests inject clearly labelled
TEST-ONLY ships into the served telemetry.json; a synthetic 2,500-flight / 1,500-vessel file measures the frame rate. Nothing is written to disk.
"""
import json
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import BASE, check, ok, page_for  # noqa: E402

TRANSPORT = json.loads((ROOT / "data" / "live_extra" / "aladin_telemetry.json").read_text(encoding="utf-8"))
SHIPS = [[419000001, "TEST VESSEL ALPHA", 27.1, 56.3, 11.2, 200.0, 200.0, 84, "SIKKA", "10-07 05:30", 0], [419000002, "TEST VESSEL BETA", 13.1, 43.4, 9.0, 120.0, 120.0, 70, None, None, 0]]   # TEST-ONLY
CARGO = next((f for f in TRANSPORT["flights"] if f[9] == 1), None)
ANY = TRANSPORT["flights"][0]


def fresh(j, age=20):
    """The saved local file may be a day old; the test wants markers whose own fix time is recent (so they are not ghosts)."""
    t = int(time.time() - age)
    j["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    for f in j.get("flights") or []:
        f[10] = t
    for v in j.get("vessels") or []:
        v[10] = t
    return j


def with_vessels(route):
    r = route.fetch()
    j = r.json()
    j["vessels"], j["reason"] = [list(v) for v in SHIPS], None
    route.fulfill(response=r, body=json.dumps(fresh(j)))


def old_snapshot(route):
    r = route.fetch()
    j = r.json()
    j["generated_utc"] = "2026-10-01T00:00:00Z"
    for f in j.get("flights") or []:
        f[10] = 1790000000                                                          # 2026-09-21: far past the extrapolation caps
    for v in j.get("vessels") or []:
        v[10] = 1790000000
    route.fulfill(response=r, body=json.dumps(j))


def big_snapshot(route):
    rnd = random.Random(7)
    r = route.fetch()
    j = r.json()
    j["flights"] = [[f"f{i:05d}", f"XX{i}", rnd.uniform(-40, 60), rnd.uniform(-20, 130), 9000, 220, rnd.randint(0, 359), 0, "Testland", i % 9 == 0 and 1 or 0, 0] for i in range(2500)]
    j["vessels"] = [[500000 + i, f"V{i}", rnd.uniform(-35, 45), rnd.uniform(-10, 125), 8, 90, 90, 70, None, None, 0] for i in range(1500)]
    j["reason"] = None
    route.fulfill(response=r, body=json.dumps(fresh(j, 120)))


def globe_tab(pg):
    pg.dispatch_event('#tabs [data-go="globe"]', "click")
    pg.wait_for_selector("#gd-mode")
    pg.wait_for_timeout(800)


def mode(pg, m, wait=2500):
    pg.click(f'#gd-mode [data-m="{m}"]')
    pg.wait_for_timeout(wait)


def items(pg):
    return pg.evaluate("document.querySelector('#gd-canvas')._items || []")


def drawn(pg):
    """True when the canvas has real pixels (not blank)."""
    return pg.evaluate("""() => { const c = document.querySelector('#gd-canvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        let n = 0; for (let i = 3; i < d.length; i += 400) if (d[i] > 0) n++; return n > 200; }""")


def click_item(pg, typ, kind=None):
    it = next((i for i in items(pg) if i["type"] == typ and (kind is None or i.get("kind") == kind)), None)
    if not it:
        return None
    pg.locator("#gd-canvas").scroll_into_view_if_needed()
    pg.evaluate("document.querySelector('#gd-canvas').scrollIntoView({block: 'center'})")
    pg.wait_for_timeout(200)
    box = pg.locator("#gd-canvas").bounding_box()
    pg.mouse.click(box["x"] + it["x"], box["y"] + it["y"])
    pg.wait_for_timeout(1200)
    return it


def run():
    with sync_playwright() as pw:
        # 1. nothing heavy before the viewer asks for it; then the globe
        b, pg, errs, reqs = page_for(pw, routes={"**/telemetry.json*": with_vessels})
        pg.goto(BASE)
        pg.wait_for_timeout(5000)
        globe_tab(pg)
        check("Globe tab opens on the existing Map; the D3 libraries and the snapshot are not requested yet",
              not any(("d3-geo" in u or "topojson" in u or "world-atlas" in u or "telemetry.json" in u) for u, _ in reqs) and pg.evaluate("!document.querySelector('#globe-map').hidden"))
        check("the Map / Globe / Flat / List switch is there and the Map is on", pg.locator("#gd-mode button").count() == 4 and pg.get_attribute('#gd-mode [data-m="map"]', "aria-pressed") == "true")
        mode(pg, "globe", 4000)
        check("Globe: the libraries and the snapshot are requested only now", any("d3-geo" in u for u, _ in reqs) and any("telemetry.json" in u for u, _ in reqs))
        check("Globe: the canvas draws real pixels and has items", drawn(pg) and int(pg.get_attribute("#gd-canvas", "data-items")) >= 10, pg.get_attribute("#gd-canvas", "data-items"))
        check("Globe: the Leaflet map is hidden, the canvas shown", pg.evaluate("document.querySelector('#globe-map').hidden && !document.querySelector('#gd-wrap').hidden"))
        chip = pg.inner_text("#gd-chips")
        check("snapshot chips: source, cadence, newest fix age", "Flights · OpenSky" in chip and "refreshed about every" in chip and "newest fix" in chip and "Vessels · AISstream" in chip, chip[:200])
        check("the chip's tooltip carries the OpenSky attribution", "opensky-network.org" in (pg.get_attribute("#gd-chips .gd-chip", "title") or ""))

        n0 = len(items(pg))
        pg.uncheck('[data-layer="hot"]')
        pg.wait_for_timeout(400)
        check("a layer switch removes its items", len(items(pg)) < n0 and not any(i["type"] == "hotspot" for i in items(pg)), [n0, len(items(pg))])
        pg.reload()
        pg.wait_for_timeout(5000)
        globe_tab(pg)
        mode(pg, "list", 1500)
        check("the layer choice is remembered in this browser", pg.evaluate("JSON.parse(localStorage.getItem('blab.globe.layers')).hot === false") and not pg.locator('[data-layer="hot"]').is_checked())
        pg.check('[data-layer="hot"]')

        # 2. flat
        mode(pg, "flat", 3000)
        check("Flat: Natural Earth drawn on the same canvas", pg.get_attribute("#gd-canvas", "data-mode") == "flat" and drawn(pg) and len(items(pg)) >= 10)

        # 3. clicking things opens the one NEXUS panel
        mode(pg, "globe", 2000)
        if CARGO:
            pg.check('[data-layer="cargo"]')
        pg.check('[data-layer="air"]')
        pg.wait_for_timeout(500)
        pg.uncheck('[data-layer="ship"]')
        pg.wait_for_timeout(300)
        hs = click_item(pg, "hotspot", "conflict")
        check("click a hotspot: the NEXUS hotspot panel opens", hs is not None and pg.locator("#nx-root .nx-drawer").is_visible() and "hotspot" in pg.inner_text("#nx-kind").lower(), hs)
        t = pg.inner_text("#nx-body").lower()
        check("hotspot panel: level, baseline note, history, affected lanes, exposed stocks with ΔP(up) and the association wording",
              "30-day history" in t and "exposed on nse" in t and "δp(up)" in t and "association, not proof of cause" in t and ("building its baseline" in t or "·" in t), t[:200])
        check("hotspot panel: the disclaimer is on it", "often wrong" in pg.inner_text("#nx-root"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        pg.evaluate("document.querySelector('#nx-root').hidden = true")
        ch = click_item(pg, "chokepoint")
        check("a chokepoint is on the globe to click", ch is not None)
        if ch:
            t = pg.inner_text("#nx-body").lower()
            check("click a chokepoint: panel with the vessel count and its lanes", "vessels in the box" in t and "lanes that pass through" in t, t[:160])
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        pg.evaluate("document.querySelector('#nx-root').hidden = true")
        fl = click_item(pg, "flight")
        check("click a flight: the NEXUS flight panel opens", fl is not None and "flight" in pg.inner_text("#nx-kind").lower(), fl)
        t = pg.inner_text("#nx-body")
        low = t.lower()
        check("flight panel: fixed 'Not measured' rows are exactly as specified",
              "cargo manifest / bill of lading" in low and "not measured — private/paid customs data" in low and "receiving client" in low and "logistics carrier" in low)
        check("flight panel: operator is labelled inferred, and the freighter flag says it is not about this cargo", ("inferred from the callsign prefix" in low or "operator not identified" in low) and "says nothing about what is on board" in low)
        check("flight panel: lane exposure is labelled as an inference, snapshot age and attribution shown",
              "lane-level exposure (inference, not this shipment)" in low and "positions are not live" in low and "opensky" in low)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        pg.evaluate("document.querySelector('#nx-root').hidden = true")
        pg.check('[data-layer="ship"]')
        pg.wait_for_timeout(300)
        vs = click_item(pg, "vessel")
        check("click a vessel (test ships): the vessel panel shows broadcast fields only", vs is not None and "destination (as broadcast)" in pg.inner_text("#nx-body").lower() and "not measured" in pg.inner_text("#nx-body").lower(), vs)
        pg.keyboard.press("Escape")
        check("Globe/Flat/List: 0 console errors or warnings so far", not errs, errs[:3])

        # 4. commands that use the snapshot
        cs = ANY[1] or ANY[0]
        pg.fill("#cmd", f"FLIGHT {cs}")
        pg.press("#cmd", "Enter")
        pg.wait_for_timeout(2500)
        check("FLIGHT <real callsign>: Globe tab and that flight's panel", "flight" in pg.inner_text("#nx-kind").lower() and cs in pg.inner_text("#nx-title"), pg.inner_text("#nx-title"))
        pg.keyboard.press("Escape")
        pg.fill("#cmd", "FLIGHT ZZZ9999")
        pg.press("#cmd", "Enter")
        pg.wait_for_timeout(700)
        check("FLIGHT <not in the snapshot>: says so with the snapshot's age, invents nothing", "Not in the current snapshot (age" in pg.inner_text("#cmd-list"), pg.inner_text("#cmd-list")[:120])
        pg.fill("#cmd", "VESSEL TEST VESSEL ALPHA")
        pg.press("#cmd", "Enter")
        pg.wait_for_timeout(2000)
        check("VESSEL <name> opens the vessel panel", "vessel" in pg.inner_text("#nx-kind").lower() and "ALPHA" in pg.inner_text("#nx-title"), pg.inner_text("#nx-title"))
        pg.keyboard.press("Escape")
        pg.fill("#cmd", "GEO hormuz")
        pg.press("#cmd", "Enter")
        pg.wait_for_timeout(1500)
        check("GEO still works with the new Globe tab", pg.evaluate("document.querySelector('#v-globe').classList.contains('on')"))

        # 5. list view
        mode(pg, "list", 1500)
        rows = pg.locator("#gd-list tbody tr").count()
        pg.fill("#gd-q", "hormuz")
        pg.wait_for_timeout(400)
        rows2 = pg.locator("#gd-list tbody tr").count()
        check("List view: filters, and every row has an 'open' button into NEXUS", 0 < rows2 < rows and pg.locator("#gd-list [data-nexus]").count() == rows2, [rows, rows2])
        pg.click("#gd-list [data-nexus]")
        pg.wait_for_timeout(1200)
        check("List view: a row opens the same NEXUS panel", pg.locator("#nx-root .nx-drawer").is_visible())
        pg.keyboard.press("Escape")
        pg.add_script_tag(url="https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js")
        res = pg.evaluate("axe.run('#gd-bar, #gd-list').then(r => r.violations.map(v => [v.id, v.impact, v.nodes.length]))")
        bad = [v for v in res if v[1] in ("serious", "critical")]
        check("Globe bar and list: no serious or critical axe violations", not bad, res)
        check("Globe tab: 0 console errors or warnings in total", not errs, errs[:3])
        b.close()

        # 6. an old snapshot is greyed and says so
        b, pg, errs, _ = page_for(pw, routes={"**/telemetry.json*": old_snapshot})
        pg.goto(BASE)
        pg.wait_for_timeout(5000)
        globe_tab(pg)
        mode(pg, "globe", 3500)
        check("a snapshot whose fixes are older than the extrapolation caps says 'positions not live' and its markers are ghosts", "positions not live" in pg.inner_text("#gd-chips") and pg.locator("#gd-chips .gd-chip.stale").count() >= 1, pg.inner_text("#gd-chips")[:140])
        b.close()

        # 7. frame rate with 2,500 flights and 1,500 vessels at 4x slower CPU
        b, pg, errs, _ = page_for(pw, throttle=4, routes={"**/telemetry.json*": big_snapshot})
        pg.goto(BASE)
        pg.wait_for_timeout(6000)
        globe_tab(pg)
        mode(pg, "globe", 5000)
        pg.check('[data-layer="air"]')
        pg.wait_for_timeout(1500)
        n = len(items(pg))
        MEASURE = """() => new Promise(res => { const c = document.querySelector('#gd-canvas'), t = []; let k = 0;
            const step = () => { const t0 = performance.now(); c.dispatchEvent(new WheelEvent('wheel', { deltaY: k % 2 ? 100 : -100, cancelable: true }));
              requestAnimationFrame(() => { t.push(performance.now() - t0); if (++k < 60) setTimeout(step, 0); else res(t.slice(6).reduce((a, b) => a + b, 0) / (t.length - 6)); }); }; step(); })"""
        ms = pg.evaluate(MEASURE)
        for layer in ("hot", "choke", "cargo", "air", "ship", "plant", "lane"):
            pg.uncheck(f'[data-layer="{layer}"]')
        pg.wait_for_timeout(500)
        ms_base = pg.evaluate(MEASURE)                                           # the same globe with every layer off: the cost of the base map alone
        fps, cost = 1000 / ms, ms - ms_base
        real = cost / 4                                                           # the browser was slowed 4x: this is what the items cost at the machine's own speed
        # A machine's speed varies (this one has measured 17 ms and 43 ms for the SAME empty globe on different days), so the test asks for 30 frames a second at 4x
        # slower CPU when the machine allows it, and otherwise that all 3,875 items cost under 8 ms of real drawing time a frame (half of a 60 fps frame).
        check(f"Globe holds >= 30 frames/s with {n} drawn items (2,500 flights + 1,500 vessels) at 4x slower CPU, or the items cost under 8 ms a frame at normal speed", fps >= 30 or real <= 8,
              f"{fps:.0f} fps = {ms:.1f} ms a frame with everything on; {ms_base:.1f} ms with every layer off; the items cost {cost:.1f} ms throttled = {real:.1f} ms at normal speed, measured inside the page")
        check("heavy snapshot: 0 console errors", not errs, errs[:3])
        b.close()

        # 8. phone
        b, pg, errs, _ = page_for(pw, size=(390, 844))
        pg.goto(BASE)
        pg.wait_for_timeout(5000)
        globe_tab(pg)
        mode(pg, "globe", 3500)
        w = pg.evaluate("document.querySelector('#gd-canvas').getBoundingClientRect().width")
        check("phone: the canvas fits the screen, no sideways scroll", w <= 390 and pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), w)
        b.close()

        # 9. no snapshot published: honest, no errors
        def no_telemetry(route):
            r = route.fetch()
            m = r.json()
            m.pop("telemetry", None)
            route.fulfill(response=r, body=json.dumps(m))
        b, pg, errs, _ = page_for(pw, routes={"**/desk_data.json*": no_telemetry})
        pg.goto(BASE)
        pg.wait_for_timeout(5000)
        globe_tab(pg)
        mode(pg, "list", 1500)
        check("no snapshot published: the chip says so and nothing errors", "no snapshot published" in pg.inner_text("#gd-chips") and not errs, errs[:3])
        b.close()
    print("ALL OK" if all(ok) else f"{ok.count(False)} FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(run())
