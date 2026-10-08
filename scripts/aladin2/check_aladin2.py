"""
ALADIN 2.0 repository hygiene check (section 12): fails the job when data/aladin2 grows past its limits or a binary that should never be committed appears.

  python scripts/aladin2/check_aladin2.py          exit code 1 on any FAIL, 0 otherwise (WARN lines never fail)
Limits: whole folder FAIL > 250 MB, WARN > 150 MB; one ledger month FAIL > 60 MB, WARN > 30 MB; any state / report / journal shard FAIL > 5 MB; model binaries (.pkl .joblib .bin .npz .h5 .pt) FAIL when
larger than 5 MB; raw history folders (data/terminal) must not be inside data/aladin2.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MB = 1024 * 1024
BIN = {".pkl", ".joblib", ".bin", ".npz", ".h5", ".pt", ".onnx"}


def check(folder=None):
    base = Path(folder or ROOT / "data" / "aladin2"); rows = []; total = 0
    if not base.exists():
        return [("OK", "data/aladin2 does not exist yet", 0)], 0
    for f in sorted(p for p in base.rglob("*") if p.is_file()):
        size = f.stat().st_size; total += size; rel = f.relative_to(base).as_posix()
        if f.suffix in BIN and size > 5 * MB:
            rows.append(("FAIL", f"{rel}: model/binary file of {size / MB:.1f} MB (limit 5 MB, never commit model binaries)", size))
        elif rel.startswith("ledger/"):
            if size > 60 * MB:
                rows.append(("FAIL", f"{rel}: ledger month of {size / MB:.1f} MB (limit 60 MB)", size))
            elif size > 30 * MB:
                rows.append(("WARN", f"{rel}: ledger month of {size / MB:.1f} MB (warn at 30 MB)", size))
        elif f.suffix in (".json", ".jsonl", ".gz") and size > 5 * MB:
            rows.append(("FAIL", f"{rel}: shard of {size / MB:.1f} MB (limit 5 MB)", size))
        if "terminal" in f.parts or "archive" in f.parts and "ledger" not in f.parts:
            rows.append(("FAIL", f"{rel}: raw history must not live in data/aladin2", size))
    if total > 250 * MB:
        rows.append(("FAIL", f"data/aladin2 is {total / MB:.1f} MB (limit 250 MB)", total))
    elif total > 150 * MB:
        rows.append(("WARN", f"data/aladin2 is {total / MB:.1f} MB (warn at 150 MB)", total))
    if not rows:
        rows.append(("OK", f"data/aladin2 is {total / MB:.1f} MB, every file within its limit", total))
    return rows, total


if __name__ == "__main__":
    rows, total = check(sys.argv[1] if len(sys.argv) > 1 else None)
    for lvl, msg, _ in rows:
        print(f"{lvl:<5}{msg}")
    sys.exit(1 if any(r[0] == "FAIL" for r in rows) else 0)
