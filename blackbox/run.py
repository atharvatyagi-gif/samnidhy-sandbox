"""Stress-Test Black Box: one command runs everything, then opens the dashboard.

  python blackbox/run.py --quick          20 seeds a cell, 6 a sweep value (minutes)
  python blackbox/run.py                  200 seeds a cell, 30 a sweep value (the full run)
  options: --no-dashboard   --force (ignore the cache)   --config path/to/config.yaml
Results: blackbox/results/<config hash>[_quick]/ (parquet + CSV + report.html); blackbox/results/latest.txt points the dashboard at the newest run.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from blackbox import inventory  # noqa: E402
from blackbox.analysis import gaps as GA  # noqa: E402
from blackbox.analysis import recommendations as RE  # noqa: E402
from blackbox.analysis import report as RP  # noqa: E402
from blackbox.engine import simulator as SIM  # noqa: E402

log = logging.getLogger("blackbox")


def pipeline(cfg: dict, quick: bool, force: bool) -> Path:
    inventory.write()
    d = SIM.run_main(cfg, quick, force); summary = SIM.summarize(d, cfg)
    d = SIM.run_sweeps(cfg, quick, force); sweeps = pd.read_parquet(d / "sweeps.parquet")
    gaps = GA.analyse(sweeps, cfg); gaps.to_parquet(d / "gaps.parquet", index=False)
    modules = pd.read_parquet(d / "modules.parquet") if (d / "modules.parquet").exists() else None
    recs = RE.build(summary, gaps, modules, inventory.INVENTORY, cfg); recs.to_parquet(d / "recommendations.parquet", index=False)
    f = RP.export(d, summary, gaps, recs, modules)
    (ROOT / cfg["run"]["results_dir"] / "latest.txt").write_text(str(d.resolve()), encoding="utf-8")
    log.info("report: %s", f); log.info("%d recommendations", len(recs))
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true"); ap.add_argument("--no-dashboard", action="store_true"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    cfg = SIM.load_config(a.config)
    pipeline(cfg, a.quick, a.force)
    if not a.no_dashboard:
        subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "blackbox" / "dashboard" / "app.py"), "--theme.base", "dark",
                         "--theme.backgroundColor", "#0d0d0d", "--theme.secondaryBackgroundColor", "#1a1a19", "--theme.textColor", "#f0efec", "--theme.primaryColor", "#3987e5"], cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
