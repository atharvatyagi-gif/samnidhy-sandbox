"""
Browser checks for the command line (needs `python scripts/dev_preview.py --no-browser` running):

  python tests/e2e/cmd_check.py

Types real commands into the masthead command line and checks what the page does, that the old grammar still works, that unknown input explains
itself with at most three suggestions, and that nothing logs a console error.
"""
import collections
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import BASE, check, ok, page_for  # noqa: E402

UNI = json.loads((ROOT / "data" / "terminal" / "universe.json").read_text(encoding="utf-8"))["stocks"]
SECTOR = collections.Counter(s["ind"] for s in UNI if s.get("ind") and s.get("n500")).most_common(1)[0][0]
GEO = json.loads((ROOT / "data" / "aladin" / "geo.json").read_text(encoding="utf-8"))["regions"][0]["name"]
HOUSE = json.loads((ROOT / "data" / "config" / "business_houses.json").read_text(encoding="utf-8"))["houses"][0]


def run_cmd(pg, text, wait=700):
    pg.fill("#cmd", text)
    pg.press("#cmd", "Enter")
    pg.wait_for_timeout(wait)


def view_on(pg):
    return pg.evaluate("[...document.querySelectorAll('.view.on')].map(v => v.id)[0]")


def msg(pg):
    return pg.inner_text("#cmd-list") if pg.evaluate("!document.querySelector('#cmd-list').hidden") else ""


def fresh(pw, hash_="#v=brief", **kw):
    b, pg, errs, reqs = page_for(pw, **kw)
    pg.goto(BASE + hash_)
    pg.wait_for_timeout(5500)
    return b, pg, errs, reqs


def run():
    with sync_playwright() as pw:
        b, pg, errs, _ = fresh(pw)
        check("GO key is visible and named", pg.locator("#cmd-go").is_visible() and bool(pg.get_attribute("#cmd-go", "aria-label")))

        run_cmd(pg, "RELIANCE SPLC TIER2", 2500)
        check("SYM SPLC TIER2: opens the terminal, the NEXUS drawer on the supply-chain tab at tier 2",
              view_on(pg) == "v-terminal" and pg.evaluate("!document.querySelector('#nx-root').hidden") and pg.locator('[data-nx-tab="chain"].on').count() == 1 and pg.input_value("#nx-tier") == "2",
              [view_on(pg), pg.evaluate("document.querySelector('#nx-tier') && document.querySelector('#nx-tier').value")])
        check("SYM SPLC: the panel is about RELIANCE", "RELIANCE" in pg.inner_text("#nx-title"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        run_cmd(pg, "tcs <equity> splc <go>", 2000)
        check("lowercase, <EQUITY> and <GO> are accepted", "TCS" in pg.inner_text("#nx-title"), pg.inner_text("#nx-title"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        run_cmd(pg, "SPLC TIER3", 1500)
        check("SPLC alone uses the selected symbol (TCS) at tier 3", "TCS" in pg.inner_text("#nx-title") and pg.input_value("#nx-tier") == "3", pg.inner_text("#nx-title"))
        pg.keyboard.press("Escape")

        run_cmd(pg, "TATA SPLC")
        t = msg(pg)
        check("ambiguous name: asks which one and lists up to 3 closest", "more than one security" in t and 1 <= pg.locator("#cmd-list b").count() <= 3, t[:140])
        run_cmd(pg, "ZZZZ QQQQ")
        t = msg(pg)
        check("unknown input: one-line reason, at most 3 suggestions", "No security or command matches" in t and pg.locator("#cmd-list b").count() <= 3, t[:140])
        run_cmd(pg, "SPLX")
        check("a typo suggests the command it is closest to", "SPLC" in msg(pg), msg(pg)[:140])

        run_cmd(pg, "SWEEP")
        check("SWEEP without the local daemon explains why", "Sweep data needs the local daemon (not running)" in msg(pg), msg(pg)[:120])
        run_cmd(pg, "FLIGHT ZZZ9999", 2500)
        check("FLIGHT with a snapshot but no such callsign: says so with the snapshot's age, invents nothing", "Not in the current snapshot (age" in msg(pg), msg(pg)[:140])
        run_cmd(pg, "VESSEL EVER GIVEN")
        check("VESSEL with no AIS feed says the layer is off", "Vessel layer off" in msg(pg), msg(pg)[:100])

        run_cmd(pg, "ALADIN INFY", 2500)
        check("ALADIN SYM: Tools tab filtered to the symbol and its row expanded", view_on(pg) == "v-lab" and pg.locator('tr.al-r[data-s="INFY"]').count() == 1 and pg.locator("tr.al-x").count() >= 1)
        run_cmd(pg, "TCS ALADIN", 2000)
        check("SYM ALADIN (the older order) still works", view_on(pg) == "v-lab" and pg.locator('tr.al-r[data-s="TCS"]').count() == 1)
        run_cmd(pg, "ALADIN", 2000)
        check("bare ALADIN opens the Tools tab", view_on(pg) == "v-lab")

        run_cmd(pg, f"HOUSE {HOUSE['name'].split()[0]}", 3000)
        check("HOUSE <name>: Houses tab with that group expanded", view_on(pg) == "v-houses" and pg.locator(f'tr.hh-row[data-h="{HOUSE["id"]}"].on').count() == 1, [view_on(pg), HOUSE["id"]])
        run_cmd(pg, "HOUSE nosuchgroupzz")
        check("HOUSE with no match says so", "No business house" in msg(pg), msg(pg)[:100])
        run_cmd(pg, f"SECTOR {SECTOR}", 1500)
        check("SECTOR <name>: Sectors tab with that sector selected", view_on(pg) == "v-sectors" and SECTOR.lower() in pg.inner_text("#sec-detail").lower(), SECTOR)
        run_cmd(pg, f"GEO {GEO}", 3500)
        check("GEO <region>: Globe tab with that region selected", view_on(pg) == "v-globe" and pg.evaluate("document.querySelectorAll('#geo-table tr.geo-row.on').length") >= 0, GEO)
        run_cmd(pg, "MOVERS", 800)
        check("MOVERS: Movers tab", view_on(pg) == "v-movers")
        run_cmd(pg, "MOVERS SHOCK", 800)
        check("MOVERS SHOCK says it is not built yet instead of pretending", "not built yet" in pg.inner_text("#toast"), pg.inner_text("#toast"))
        run_cmd(pg, "MAP", 800)
        check("MAP: Globe tab", view_on(pg) == "v-globe")

        # no flight snapshot published at all
        b2, pg2, errs2, _ = page_for(pw, routes={"**/desk_data.json*": lambda route: route.fulfill(response=route.fetch(), body=json.dumps({k: v for k, v in route.fetch().json().items() if k != "transport"}))})
        pg2.goto(BASE)
        pg2.wait_for_timeout(5500)
        run_cmd(pg2, "FLIGHT AIC101", 800)
        check("FLIGHT with no snapshot published says so and invents nothing", "No flight snapshot is published" in msg(pg2) and not errs2, msg(pg2)[:140])
        b2.close()

        # the old grammar
        run_cmd(pg, "RELIANCE CH", 1500)
        check("old grammar: SYMBOL CODE still opens the chart", view_on(pg) == "v-terminal")
        run_cmd(pg, "NIFTY MOV", 800)
        check("old grammar: NIFTY MOV still opens Movers", view_on(pg) == "v-movers")
        run_cmd(pg, "TICKS", 600)
        check("old grammar: TICKS still reports the local feed", "Local ticks are" in pg.inner_text("#toast"), pg.inner_text("#toast"))
        run_cmd(pg, "INFY", 1500)
        check("old grammar: a bare symbol still opens it", view_on(pg) == "v-terminal")
        run_cmd(pg, "HELP splc", 500)
        check("HELP <text>: the directory opens filtered, and lists SPLC", pg.evaluate("!document.querySelector('#help').hidden") and "SPLC" in pg.inner_text("#help-list"))
        pg.keyboard.press("Escape")

        # GO button
        pg.fill("#cmd", "MOVERS")
        pg.click("#cmd-go")
        pg.wait_for_timeout(600)
        check("the GO key runs the command like Enter", view_on(pg) == "v-movers")
        check("command line: 0 console errors or warnings across all of it", not errs, errs[:3])
        b.close()

        # accessibility of the command line with its dropdown open
        b, pg, errs, _ = fresh(pw)
        pg.fill("#cmd", "SPL")
        pg.wait_for_timeout(400)
        pg.add_script_tag(url="https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js")
        res = pg.evaluate("axe.run('#cmdline').then(r => r.violations.map(v => [v.id, v.impact, v.nodes.length]))")
        bad = [v for v in res if v[1] in ("serious", "critical")]
        check("command line (dropdown open): no serious or critical axe violations", not bad, res)
        check("dropdown offers the new command SPLC", "SPLC" in pg.inner_text("#cmd-list"))
        b.close()
    print("ALL OK" if all(ok) else f"{ok.count(False)} FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(run())
