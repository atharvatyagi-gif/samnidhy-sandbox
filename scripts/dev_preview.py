"""
Developer preview of the Expert terminal WITHOUT signing in (local only, never published).

Builds the site, adds two local-only pages, serves site/ on http://127.0.0.1:8765 and opens the preview:
  expert-dev.html        the real expert-terminal.html with a fake developer user instead of the sign-in guard
Press Ctrl+C to stop.

  python scripts/dev_preview.py
"""
import functools
import http.server
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PORT = 8765

subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True)
page = (ROOT / "expert-terminal.html").read_text(encoding="utf-8")
guard = '<script type="module" src="auth-check.js" data-guard></script>'
assert guard in page, "expert-terminal.html no longer has the auth guard line"
page = page.replace(guard, """<script type="module">
  // DEVELOPER PREVIEW: fake signed-in user, no Firebase. Local only, never published.
  window.expertUser = { email: "developer.preview@tapmi.edu.in" };
  window.__expertSignOut = async () => {};
  document.documentElement.classList.remove("locked");
</script>""")
page = page.replace('<script src="reload-home.js"></script>', "")
page = page.replace("<title>B-LAB TERMINAL", "<title>DEV PREVIEW · B-LAB TERMINAL")
page = page.replace("<!--TERMINAL-BODY-START-->", '<div style="position:fixed;right:0;bottom:22px;z-index:99;background:#e0a060;color:#061a10;font:700 11px Consolas,monospace;padding:2px 8px">DEV PREVIEW · NO SIGN-IN · NOT PUBLISHED</div>')
(SITE / "expert-dev.html").write_text(page, encoding="utf-8")
url = f"http://127.0.0.1:{PORT}/expert-dev.html"
print(f"Developer preview: {url}   (Ctrl+C to stop)")
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as srv:
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
