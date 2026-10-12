"""Watchdog: keeps the automated jobs running when nobody is looking. Fired every hour by the Market clock heartbeat (watchdog.yml).

What it repairs, and only this (every action is printed and written to the job summary):
  1. A FAILED run of a watched workflow is re-run once (failed jobs only). A second failure is left alone and reported: retrying a real
     bug forever would only hide it.
  2. The nightly chain. "ALADIN nightly" must follow every Daily update whose data job succeeded, and "ALADIN2 nightly" must follow
     ALADIN nightly. If the next link has not started within 45 minutes, it is started by hand (workflow_dispatch).
  3. Jobs that must run at least once a day (NEXUS graph): started if no run began in the last 26 hours. GitHub's own cron is unreliable.

It never touches data, never cancels anything and never re-runs a cancelled run (cancellations here are expected: the 5-minute Live
prices publishes replace each other). Uses only the GitHub REST API with the job's own token.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.github.com"
WATCHED = ["crypto-live.yml", "daily-update.yml", "aladin.yml", "aladin2.yml", "nexus.yml", "globe-data.yml", "aladin-sentiment.yml", "live-prices.yml"]
CHAIN = [("daily-update.yml", "update", "aladin.yml"), ("aladin.yml", "aladin", "aladin2.yml")]     # (upstream, its data job, what must follow it)
DAILY = {"nexus.yml": 26}                                                                          # workflow -> hours allowed without a run
CHAIN_GRACE_MIN = 45
LOOKBACK_H = 24


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def plan(runs, jobs_of, now):
    """runs: {workflow file: [run dicts, newest first]} (GitHub's fields: id, status, conclusion, run_attempt, created_at, event).
    jobs_of(run_id) -> [job dicts with name, conclusion]. Returns a list of (action, workflow, run_id or None, reason)."""
    acts = []
    for wf in WATCHED:
        done = [r for r in runs.get(wf, []) if r["status"] == "completed" and now - ts(r["created_at"]) < timedelta(hours=LOOKBACK_H)]
        if not done or done[0]["conclusion"] != "failure":
            continue
        r = done[0]
        if r.get("run_attempt", 1) >= 2:
            acts.append(("report", wf, r["id"], "failed again after one automatic re-run: needs a fix, not another retry"))
        else:
            acts.append(("rerun", wf, r["id"], "latest run failed: re-running its failed jobs once"))
    for up, job, nxt in CHAIN:
        ups = [r for r in runs.get(up, []) if r["status"] == "completed" and r["conclusion"] in ("success", "cancelled") and now - ts(r["created_at"]) < timedelta(hours=LOOKBACK_H)]
        if not ups:
            continue
        u = ups[0]
        if not any(j["name"] == job and j["conclusion"] == "success" for j in jobs_of(u["id"])):
            continue
        finished = ts(u.get("updated_at") or u["created_at"])
        if now - finished < timedelta(minutes=CHAIN_GRACE_MIN):
            continue
        if any(ts(r["created_at"]) >= ts(u["created_at"]) for r in runs.get(nxt, [])):
            continue
        acts.append(("dispatch", nxt, None, f"{up} data job succeeded (run {u['id']}) but {nxt} has not started since"))
    for wf, hours in DAILY.items():
        rs = runs.get(wf, [])
        if not rs or now - ts(rs[0]["created_at"]) > timedelta(hours=hours):
            acts.append(("dispatch", wf, None, f"no run in the last {hours} hours"))
    return acts


def main():
    repo, tok = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not (repo and tok):
        print("watchdog: GH_REPO and GH_TOKEN are needed"); return 0
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})

    def get(path, **params):
        r = s.get(f"{API}/repos/{repo}/{path}", params=params, timeout=30); r.raise_for_status(); return r.json()
    runs = {}
    for wf in sorted(set(WATCHED) | {n for _, _, n in CHAIN} | set(DAILY)):
        try:
            runs[wf] = get(f"actions/workflows/{wf}/runs", per_page=20)["workflow_runs"]
        except Exception as e:                                                       # noqa: BLE001  one unreadable workflow must not stop the rest
            print(f"watchdog: could not read {wf}: {e}")
    acts = plan(runs, lambda rid: get(f"actions/runs/{rid}/jobs", per_page=50)["jobs"], datetime.now(timezone.utc))
    lines, dry = [], "--dry-run" in sys.argv
    for act, wf, rid, why in acts:
        try:
            if dry:
                pass
            elif act == "rerun":
                s.post(f"{API}/repos/{repo}/actions/runs/{rid}/rerun-failed-jobs", timeout=30).raise_for_status()
            elif act == "dispatch":
                s.post(f"{API}/repos/{repo}/actions/workflows/{wf}/dispatches", json={"ref": "main"}, timeout=30).raise_for_status()
            done = "dry run, not done" if dry else "done"
        except Exception as e:                                                       # noqa: BLE001
            done = f"FAILED ({e})"
        lines.append(f"| {act} | {wf} | {rid or ''} | {why} | {done} |")
        print(f"watchdog: {act} {wf} {rid or ''}: {why} -> {done}")
    if not acts:
        print("watchdog: everything ran as expected")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Watchdog\n\n" + ("| action | workflow | run | why | result |\n|---|---|---|---|---|\n" + "\n".join(lines) if lines else "Everything ran as expected.") + "\n")
    print(json.dumps({"actions": len(acts)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
