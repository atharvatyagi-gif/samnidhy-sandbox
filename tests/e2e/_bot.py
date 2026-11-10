"""Opening ALADIN BOT in browser checks. The earlier ALADIN models (Tools, Outlook, ALADIN 2.0, the old weekly signal) are shown only
after the bot is unlocked, so checks of those views need the TEST code the local preview was built with:
  ALADIN_BOT_CODE=<any made-up test code> python scripts/dev_preview.py --no-browser
  E2E_BOT_CODE=<the same test code> python tests/e2e/<check>.py
Never use the real access code here. Without E2E_BOT_CODE those checks print SKIP and do not count as passed."""
import os

CODE = os.environ.get("E2E_BOT_CODE")


def unlock(pg, base):
    """Unlock the bot in this page (the code then stays for this browser tab, as for a reader). -> True, or False when no test code is set."""
    if not CODE:
        return False
    pg.goto(base + "#v=a2bot")
    pg.evaluate("localStorage.setItem('blab-onboarded', 'true')")      # the first-visit welcome window would cover the form
    pg.reload()
    pg.wait_for_selector("#botcode", timeout=30000)
    pg.wait_for_function("!/Loading/.test(document.getElementById('a2bot').innerText)", timeout=30000)   # the form is drawn again once the bot's file has loaded
    pg.wait_for_timeout(500)
    pg.fill("#botcode", CODE); pg.click("#a2b-go")
    pg.wait_for_function("document.documentElement.classList.contains('legacy-on')", timeout=30000)
    return True


def skip(name):
    print("SKIP " + name + "  [set E2E_BOT_CODE to the preview's test code]")
