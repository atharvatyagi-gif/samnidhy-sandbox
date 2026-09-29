"""
Turns the student list (Excel) into the allow-list used by Expert access registration. Run on your own
computer only; the Excel file and the output never go to GitHub or the website.

Each student becomes one key:  SHA-256("blab-v1|<ROLL NO>|<YYYY-MM-DD date of birth>")
No names, IDs or dates are stored, only these one-way keys. When someone registers, they type their
roll number and date of birth; the page computes the same key and Firebase's rules check it is on the list.

  python scripts/student_allowlist.py "Student List for ID Card- Batch 2026-29.xlsx"
    -> private/allowlist_keys.json   (the keys)
    -> private/firestore.rules       (firestore.rules.template with the keys filled in: paste it into
                                      Firebase console > Firestore Database > Rules > Publish)
"""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "private" / "allowlist_keys.json"
SALT = "blab-v1"


def norm_roll(v):
    return "".join(str(v).split()).upper()


def norm_dob(v):
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip().split(" ")[0]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def key(roll, dob):
    return hashlib.sha256(f"{SALT}|{roll}|{dob}".encode()).hexdigest()


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "Student List for ID Card- Batch 2026-29.xlsx")
    raw = pd.read_excel(path, header=None)
    hdr = next(i for i in range(min(15, len(raw))) if any("roll" in str(x).lower() for x in raw.iloc[i]))
    df = pd.read_excel(path, header=hdr)
    roll_col = next(c for c in df.columns if "roll" in str(c).lower())
    dob_col = next(c for c in df.columns if "dob" in str(c).lower() or "birth" in str(c).lower())
    keys, bad = [], 0
    for roll, dob in zip(df[roll_col], df[dob_col]):
        if pd.isna(roll) or pd.isna(dob):
            continue
        r, d = norm_roll(roll), norm_dob(dob)
        if not r or not d:
            bad += 1
            continue
        keys.append(key(r, d))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"salt": SALT, "count": len(keys), "keys": sorted(set(keys))}, indent=1), encoding="utf-8")
    print(f"{len(set(keys))} students -> {OUT.relative_to(ROOT)} ({bad} rows skipped: unreadable roll number or date)")
    rules = (ROOT / "firestore.rules.template").read_text(encoding="utf-8")
    assert rules.count("/*STUDENT_KEYS*/") == 1, "firestore.rules.template has no /*STUDENT_KEYS*/ marker"
    listed = ",\n        ".join(f"'{k}'" for k in sorted(set(keys)))
    rules = rules.replace("/*STUDENT_KEYS*/", "\n        " + listed + "\n      ")
    # guest invite codes (people outside TAPMI): made once, kept in private/guest_codes.txt, never published
    codes_file = OUT.parent / "guest_codes.txt"
    if not codes_file.exists():
        import secrets
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        part = lambda: "".join(secrets.choice(alphabet) for _ in range(4))
        codes = [f"BLAB-{part()}-{part()}" for _ in range(10)]
        codes_file.write_text("B-Lab guest invite codes (one account each; keep private)\n" + "\n".join(codes) + "\n", encoding="utf-8")
    codes = [c.strip() for c in codes_file.read_text(encoding="utf-8").splitlines()[1:] if c.strip()]
    gkeys = [hashlib.sha256(f"blab-guest|{c.upper()}".encode()).hexdigest() for c in codes]
    rules = rules.replace("/*GUEST_KEYS*/", "\n        " + ",\n        ".join(f"'{k}'" for k in gkeys) + "\n      ")
    print(f"{len(codes)} guest invite codes -> private/guest_codes.txt")
    rules = rules.replace("// TEMPLATE ONLY (no student data): pasting this into Firebase refuses EVERY student. Do not paste it.",
                          "// PASTE THIS FILE into Firebase > Firestore > Rules. PRIVATE: contains the student keys; never commit or publish it.")
    (OUT.parent / "firestore.rules").write_text(rules, encoding="utf-8")
    print(f"Rules with the student keys -> private/firestore.rules (paste into Firebase > Firestore > Rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
