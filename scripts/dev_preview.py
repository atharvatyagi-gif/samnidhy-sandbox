"""
Developer preview of the Expert terminal WITHOUT signing in (local only, never published).

Builds the site, adds expert-dev.html (the terminal with a fake developer user instead of the
Firebase sign-in guard), serves site/ on http://127.0.0.1:8765 and opens it in your browser.
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
shutil.copyfile(ROOT / "expert-dev.html", SITE / "expert-dev.html")
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
