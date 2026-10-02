"""
Asset stamping order (scripts/build_site.py): every file must be stamped AFTER the files it imports, otherwise the import keeps its plain address while the
page loads the hashed address, and the browser creates two separate copies of the module (one never initialised). Found when the Globe's ALADIN columns
stayed empty: desk-map.js had its own, never-initialised copy of desk-aladin.js.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402

IMPORT = re.compile(r'(?:import|export)\s[^;]*?from\s+"\./([A-Za-z0-9_.\-]+\.js)"')


def test_every_file_comes_after_the_files_it_imports():
    order = {name: i for i, name in enumerate(build_site.ASSETS)}
    bad = []
    for name in build_site.ASSETS:
        if not name.endswith(".js") or not (ROOT / name).exists():
            continue
        for dep in IMPORT.findall((ROOT / name).read_text(encoding="utf-8")):
            if dep in order and order[dep] > order[name]:
                bad.append(f"{name} imports {dep}, which is stamped later")
    assert bad == [], bad


def test_every_imported_script_is_an_asset_so_it_gets_a_version():
    missing = []
    for name in build_site.ASSETS:
        if not name.endswith(".js") or not (ROOT / name).exists():
            continue
        for dep in IMPORT.findall((ROOT / name).read_text(encoding="utf-8")):
            if dep not in build_site.ASSETS:
                missing.append(f"{name} imports {dep}, which is not in ASSETS")
    assert missing == [], missing


def test_built_site_has_no_plain_import_of_a_versioned_module():
    site = ROOT / "site"
    if not (site / "terminal.js").exists():
        return                                                               # not built here
    stamped = {n for n in build_site.ASSETS if n.endswith(".js")}
    for name in stamped:
        f = site / name
        if not f.exists():
            continue
        for dep in IMPORT.findall(f.read_text(encoding="utf-8")):
            pass
        text = f.read_text(encoding="utf-8")
        plain = [m for m in re.findall(r'from\s+"\./([A-Za-z0-9_.\-]+\.js)"', text) if m in stamped]
        assert plain == [], f"{name} still has plain imports of {plain}"
