"""
Audit of data/supply_graph.json. Exit 1 on any problem, so the weekly workflow does not commit a bad graph.

Every edge must carry url, page, quote, period and confidence, and the quote must have been verified against the source text (vq true);
both ends must exist as nodes; a share is in (0, 1] and has a stated basis (revenue or purchases, never both on one edge); no anonymous
customer is linked to a company below the configured confidence; sector-level edges never feed the impact score; our own wording
(relations, kinds) contains none of the banned words. The verbatim `q` quotes and company names come from filings and are not our wording.

Size. The site fetches supply_graph.json only when a NEXUS view opens, and GitHub Pages sends it gzip-compressed (checked on the live site
2026-11-16: 2,922,005 bytes on disk arrived as 443,634 bytes, Content-Encoding: gzip). So the budget is on what a visitor downloads, the
gzip size (DOWNLOAD_LIMIT), plus a ceiling on the raw file so the browser never parses an outsized document (RAW_LIMIT). The first rule,
"raw file under 3,000,000 bytes", was set on day one when the graph held about 200 edges; the graph grows with every company read
(about 2.8 KB a company) and is built to cover the whole universe (~3,565 companies, ~10 MB raw, ~1.4 MB gzip), so that rule began
rejecting every run from 2026-10-24 (1,106 companies, 3,094,157 bytes) and the site kept the 23 Oct graph for three weeks.

When a check fails inside GitHub Actions, every problem is also written as an ::error annotation and into the job summary, so the reason
shows on the run page, not only deep in the log.
"""
import gzip
import json
import os
import re
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "data" / "supply_graph.json"
CFG = ROOT / "data" / "config" / "aladin_config.json"
BANNED = re.compile(r"\b(buy|buys|sell|sells|target|recommendation|guaranteed)\b", re.I)
DOWNLOAD_LIMIT = 2_000_000     # gzip bytes a visitor downloads (the whole universe is projected at ~1.4 MB)
RAW_LIMIT = 15_000_000         # bytes on disk / to parse in the browser (the whole universe is projected at ~10 MB)
RELS = {"supplies", "equipment_for", "raw_material_from", "logistics_for", "related_party", "customer_of"}


def audit_derived(e):
    """A share the filing did not state but its own numbers give: it must say so, show both numbers with their quotes, pages, units and headings, and the division must come out."""
    eid, bad, c = e.get("id", "?"), [], e.get("calc") or {}
    if e.get("wd") != "derived" or not c:
        return [f"{eid}: a calculation without wd=derived (or the reverse)"]
    if e.get("w") is None or e.get("wb") != "revenue":
        bad.append(f"{eid}: a derived share must be a revenue-basis share")
    for k in ("a", "t"):
        x = c.get(k) or {}
        for f in ("v", "u", "h", "pg", "q"):
            if x.get(f) in (None, ""):
                bad.append(f"{eid}: calc.{k} is missing {f}")
    if not bad:
        import related_party_shares as rps
        fa, ft = rps.unit_factor(c["a"]["u"]), rps.unit_factor(c["t"]["u"])
        if not fa or not ft or not c["t"]["v"]:
            bad.append(f"{eid}: calc units cannot be read")
        else:
            r = c["a"]["v"] * fa / (c["t"]["v"] * ft)
            if not 0 < r <= 1 or abs(r - e["w"]) > 0.0006 or abs(r - c.get("r", -1)) > 0.0006:
                bad.append(f"{eid}: the derived share {e['w']} does not equal {c['a']['v']} / {c['t']['v']} = {r:.4f}")
    if e.get("conf", 1) > 0.9:
        bad.append(f"{eid}: a derived share cannot be more confident than 0.9")
    return bad


def gzip_size(raw):
    """Bytes the file takes gzip-compressed, as GitHub Pages serves it."""
    return len(gzip.compress(raw, compresslevel=6))


def audit(doc, anon_min=0.75, size_bytes=None, gzip_bytes=None):
    bad = []
    nodes = {n["id"]: n for n in doc.get("nodes", [])}
    seen = set()
    for e in doc.get("edges", []):
        eid = e.get("id", "?")
        for k in ("url", "pg", "q", "per", "conf"):
            if e.get(k) in (None, ""):
                bad.append(f"{eid}: missing {k}")
        if e.get("vq") is not True:
            bad.append(f"{eid}: quote not verified (vq != true)")
        if e.get("s") not in nodes or e.get("d") not in nodes:
            bad.append(f"{eid}: an end is not a node")
        w = e.get("w")
        if w is not None:
            if not (0 < w <= 1):
                bad.append(f"{eid}: share {w} outside (0, 1]")
            if e.get("wb") not in ("revenue", "purchases"):
                bad.append(f"{eid}: share without a basis")
        elif e.get("wb") is not None:
            bad.append(f"{eid}: basis without a share")
        if e.get("rel") not in RELS:
            bad.append(f"{eid}: unknown relation {e.get('rel')!r}")
        if e.get("kind") not in ("disclosed", "resolved", "sector_io"):
            bad.append(f"{eid}: unknown kind")
        if e.get("wd") is not None or e.get("calc") is not None:
            bad += audit_derived(e)
        if e.get("kind") == "sector_io" and e.get("conf") != 0.3:
            bad.append(f"{eid}: sector_io confidence must be 0.3")
        for f in ("rel", "kind", "wb"):
            if e.get(f) and BANNED.search(str(e[f])):
                bad.append(f"{eid}: banned word in {f}")
        k = (e.get("s"), e.get("d"), e.get("rel"), e.get("per"), e.get("comp"), e.get("own"))
        if k in seen:
            bad.append(f"{eid}: duplicate edge")
        seen.add(k)
    cov = doc.get("coverage") or {}
    if doc.get("edges") and not cov.get("companies_total"):
        bad.append("coverage.companies_total is 0: the graph was assembled without the stock universe")
    for own in sorted({e.get("own") for e in doc.get("edges", [])}):
        if (nodes.get(own) or {}).get("k") != "co":
            bad.append(f"{own}: owns edges but is not a listed-company node (the graph lost its company nodes)")
    for aid, a in doc.get("anon", {}).items():
        if a.get("resolved_to") and (a.get("conf", 0) < anon_min or not a.get("evidence")):
            bad.append(f"{aid}: resolved without enough evidence")
    for fid, f in doc.get("fac", {}).items():
        for k in ("url", "pg", "q"):
            if f.get(k) in (None, ""):
                bad.append(f"{fid}: missing {k}")
        if f.get("lat") is not None and f.get("geo_prec") not in ("exact", "locality", "district", "city"):
            bad.append(f"{fid}: coordinates without a precision label")
        if (f.get("cap") or {}).get("v") is not None and not f["cap"].get("q"):
            bad.append(f"{fid}: capacity without a quote")
    if size_bytes is not None and size_bytes > RAW_LIMIT:
        bad.append(f"size: the file is {size_bytes:,} bytes on disk (limit {RAW_LIMIT:,})")
    if gzip_bytes is not None and gzip_bytes > DOWNLOAD_LIMIT:
        bad.append(f"size: a visitor would download {gzip_bytes:,} bytes gzip-compressed (limit {DOWNLOAD_LIMIT:,})")
    return bad


def report_to_actions(bad, name, env=None):
    """Inside GitHub Actions: one ::error annotation per problem (the first 10) and a section in the job summary. Never raises."""
    env = os.environ if env is None else env
    if not bad or env.get("GITHUB_ACTIONS") != "true":
        return
    for b in bad[:10]:
        print(f"::error title=NEXUS graph audit failed ({name} not saved)::{b}")
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                lines = [f"### NEXUS graph audit FAILED: {len(bad)} problem(s); the repository keeps its previous {name}", ""]
                lines += [f"- {b}" for b in bad[:40]] + ([f"- ...and {len(bad) - 40} more"] if len(bad) > 40 else [])
                f.write("\n".join(lines) + "\n\n")
        except OSError as e:
            print(f"job summary not written ({type(e).__name__})")


def main(argv=None):
    p = Path(argv[0]) if argv else GRAPH
    if not p.exists():
        print(f"{p.name}: not built yet (nothing to check)")
        return 0
    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8")).get("nexus", {})
    except (OSError, ValueError):
        cfg = {}
    raw = p.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    gz = gzip_size(raw)
    bad = audit(doc, cfg.get("anon_resolve_min_conf", 0.75), len(raw), gz)
    print(f"{p.name}: {len(doc.get('edges', []))} edges, {len(doc.get('fac', {}))} facilities, generated {doc.get('generated_utc', '?')}; "
          f"{len(raw):,} bytes on disk ({len(raw) / RAW_LIMIT:.0%} of {RAW_LIMIT:,}), {gz:,} bytes to download ({gz / DOWNLOAD_LIMIT:.0%} of {DOWNLOAD_LIMIT:,})")
    for b in bad[:40]:
        print("  PROBLEM", b)
    if len(bad) > 40:
        print(f"  ...and {len(bad) - 40} more problems")
    report_to_actions(bad, p.name)
    print("graph check:", f"FAILED ({len(bad)} problem(s)); {p.name} is NOT saved" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
