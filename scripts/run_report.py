"""
A workflow that reports on itself.   python scripts/run_report.py --workflow aladin|live-prices|nexus   (the last step of each job, `if: always()`)

Nobody can read the Actions logs from outside, so every run writes what a person would look for:
  * a table in the job summary ($GITHUB_STEP_SUMMARY): every step with its result and how long it took (read from GitHub's own API for this run, using the job's token),
  * what the run produced (files, sizes, row counts, data dates) and which sources fell back (anonymous OpenSky, no vessel feed, lexicon instead of FinBERT, prior weights...),
  * the steps that failed, and a run_report.json with the same facts, uploaded as an artifact.
It never fails the job: any problem here is printed as one line and the exit code stays 0.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def fetch_steps(env, get=None):
    """-> (steps [{name, status, conclusion, seconds}], note). The job is the one named like GITHUB_JOB (or the only one)."""
    repo, run, tok = env.get("GITHUB_REPOSITORY"), env.get("GITHUB_RUN_ID"), env.get("GITHUB_TOKEN")
    if not (repo and run):
        return [], "not running inside GitHub Actions: no step list"
    if get is None:
        import requests
        get = requests.get
    try:
        r = get(f"{API}/repos/{repo}/actions/runs/{run}/jobs", headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"} if tok else {"Accept": "application/vnd.github+json"}, timeout=20)
    except Exception as e:  # noqa: BLE001
        return [], f"GitHub API unreachable ({type(e).__name__})"
    if r.status_code == 403:
        return [], "GitHub API said 403: the job needs `permissions: actions: read` to list its own steps"
    if r.status_code != 200:
        return [], f"GitHub API answered {r.status_code}"
    jobs = r.json().get("jobs", [])
    mine = [j for j in jobs if j.get("name") == env.get("GITHUB_JOB")] or (jobs if len(jobs) == 1 else [])
    if not mine:
        return [], "this job was not found in the run's job list"
    out = []
    for s in mine[0].get("steps", []):
        a, b = parse_ts(s.get("started_at")), parse_ts(s.get("completed_at"))
        out.append({"name": s.get("name"), "status": s.get("status"), "conclusion": s.get("conclusion"), "seconds": round((b - a).total_seconds(), 1) if a and b else None})
    return out, None


# ------------------------------------------------------------------ what each workflow produces

def jload(rel, root=ROOT):
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def size(rel, root=ROOT):
    p = root / rel
    return p.stat().st_size if p.exists() else None


def produced(workflow, root=ROOT):
    """-> ([{label, file, bytes, detail}], [fallback sentences])."""
    rows, fb = [], []

    def add(label, rel, detail=None):
        rows.append({"label": label, "file": rel, "bytes": size(rel, root), "detail": detail})
    if workflow == "aladin":
        d = jload("data/aladin/latest.json", root)
        add("ALADIN probabilities", "data/aladin/latest.json", f"{len(d['stocks'])} stocks, data as of {d['as_of']}, weights {d['weights'].get('mode')}" if d else "missing")
        if d and d["weights"].get("mode") == "prior":
            fb.append("combiner weights are the prior (the fitted stacker needs matured days)")
        i = jload("data/aladin/impact.json", root)
        add("NEXUS impact scores", "data/aladin/impact.json", f"{len(i['stocks'])} stocks, as of {i['as_of']}; {i['validation'].get('note')}" if i else "missing")
        if i and not i["stocks"]:
            fb.append("no impact scores: no disclosed dependency between two listed companies with a stated share yet")
        s = jload("data/aladin/sentiment.json", root)
        add("Sentiment", "data/aladin/sentiment.json", f"{len(s.get('stocks', {}))} stocks, method {s.get('method')}" if s else "missing")
        if s and s.get("method") not in (None, "finbert"):
            fb.append(f"sentiment used {s.get('method')} instead of FinBERT")
        add("Probability movers", "data/aladin/moves.json")
        add("Paper portfolio", "data/paper_trades/portfolio.json")
    elif workflow == "live-prices":
        t = jload("data/live_extra/aladin_telemetry.json", root)
        if t:
            fl = (t.get("sources") or {}).get("flights") or {}
            add("Flight and vessel telemetry", "data/live_extra/aladin_telemetry.json",
                f"{len(t['flights'])} flights, {len(t['vessels']) if t['vessels'] is not None else 'no'} vessels, cadence {t.get('cadence_s')} s, OpenSky {fl.get('mode')}, {fl.get('credits_used')} credits, remaining {t.get('credits_remaining')}")
            if fl.get("mode") == "anonymous":
                fb.append("OpenSky ran anonymously" + (" (the login was refused)" if fl.get("login_failed") else ""))
            if t.get("vessels") is None:
                fb.append("no vessel feed: " + str(t.get("reason")))
            if t.get("reused"):
                fb.append("reused the last published telemetry snapshot (inside its cadence)")
            for e in fl.get("errors") or []:
                fb.append("OpenSky: " + e)
        else:
            add("Flight and vessel telemetry", "data/live_extra/aladin_telemetry.json", "missing")
        add("Live quotes", "data/screener/live.json")
        add("Screen", "data/screener/latest.json")
    elif workflow == "nexus":
        g = jload("data/supply_graph.json", root)
        add("Supply-chain graph", "data/supply_graph.json", f"{g['coverage']['companies_done']} companies read, {g['coverage']['edges']} edges, {g['coverage']['facilities']} facilities" if g else "missing")
        if g and not g["coverage"].get("companies_total"):
            fb.append("the graph was assembled without the stock universe (the audit should have refused it)")
        n = len(list((root / "data" / "nexus_cache" / "llm").glob("*.json"))) if (root / "data" / "nexus_cache" / "llm").exists() else 0
        add("Model answers cached", "data/nexus_cache/llm", f"{n} answers")
    return rows, fb


def render(workflow, steps, note, rows, fallbacks, env):
    fmt = lambda s: "—" if s is None else (f"{s:.0f} s" if s < 100 else f"{s / 60:.1f} min")      # noqa: E731
    mark = {"success": "ok", "failure": "FAILED", "skipped": "skipped", "cancelled": "cancelled", None: "?"}
    L = [f"## {workflow}: run report", f"Run {env.get('GITHUB_RUN_ID', '(local)')} · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · {env.get('GITHUB_SHA', '')[:7]}", ""]
    if steps:
        L += ["| Step | Result | Time |", "|---|---|---|"] + [f"| {s['name']} | {mark.get(s['conclusion'], s['conclusion'] or s['status'])} | {fmt(s['seconds'])} |" for s in steps]
        L.append(f"| **Total** | | **{fmt(sum(s['seconds'] or 0 for s in steps))}** |")
    else:
        L.append(f"Steps: not available ({note}).")
    L += ["", "### Produced", "| What | File | Size | Detail |", "|---|---|---|---|"]
    L += [f"| {r['label']} | `{r['file']}` | {'missing' if r['bytes'] is None else format(r['bytes'], ',') + ' B'} | {r['detail'] or ''} |" for r in rows]
    L += ["", "### Fell back", *([f"- {f}" for f in fallbacks] or ["- nothing fell back"])]
    bad = [s for s in steps if s["conclusion"] == "failure"]
    L += ["", "### Errors", *([f"- **{s['name']}** failed (ran {fmt(s['seconds'])}). Paste this table and that step's last 50 log lines." for s in bad] or ["- no step failed"])]
    return "\n".join(L) + "\n"


def main(argv=None, env=None, get=None, root=ROOT):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True, choices=["aladin", "live-prices", "nexus"])
    ap.add_argument("--out", default="run_report.json")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env
    try:
        steps, note = fetch_steps(env, get)
        rows, fb = produced(a.workflow, root)
        md = render(a.workflow, steps, note, rows, fb, env)
        summ = env.get("GITHUB_STEP_SUMMARY")
        if summ:
            with open(summ, "a", encoding="utf-8") as f:
                f.write(md)
        else:
            print(md)
        Path(a.out).write_text(json.dumps({"workflow": a.workflow, "run_id": env.get("GITHUB_RUN_ID"), "steps": steps, "steps_note": note, "produced": rows, "fell_back": fb,
                                           "failed": [s["name"] for s in steps if s["conclusion"] == "failure"]}, indent=1), encoding="utf-8")
        print(f"run report written ({len(steps)} steps, {len(rows)} outputs, {len(fb)} fallbacks)")
    except Exception as e:  # noqa: BLE001 - a report must never fail the job
        print("run report could not be written:", str(e)[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
