"""
Builds site_old/ = the current built site (site/) with the four files ALADIN changed put back to how they were before the ALADIN work began
(commit 927ef58, the end of terminal-v2): same data, old page code. Used for the before/after comparison and the performance baseline.

  python tests/e2e/baseline_site.py        then serve it:  python -m http.server 8766 --directory site_old
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BASE_COMMIT = "927ef58"
FILES = ["expert-terminal.html", "terminal.js", "terminal.css", "config.js"]


def main():
    dst = ROOT / "site_old"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / "site", dst)
    for f in FILES:
        (dst / f).write_bytes(subprocess.run(["git", "show", f"{BASE_COMMIT}:{f}"], cwd=ROOT, capture_output=True, check=True).stdout)
    page = (dst / "expert-terminal.html").read_text(encoding="utf-8")
    guard = '<script type="module" src="auth-check.js" data-guard></script>'
    assert guard in page
    page = page.replace(guard, """<script type="module">
  window.expertUser = { email: "developer.preview@learner.manipal.edu" };
  window.__expertSignOut = async () => {};
  document.documentElement.classList.remove("locked");
</script>""").replace('<script src="reload-home.js"></script>', "")
    page = page.replace("<!--TERMINAL-BODY-START-->", '<div style="position:fixed;right:0;bottom:22px;z-index:99;background:#e0a060;color:#061a10;font:700 11px Consolas,monospace;padding:2px 8px">DEV PREVIEW · NO SIGN-IN · NOT PUBLISHED</div>')   # same badge dev_preview.py adds, so the comparison is like for like
    (dst / "expert-dev.html").write_text(page, encoding="utf-8")
    print("built", dst)


if __name__ == "__main__":
    sys.exit(main())
