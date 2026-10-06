"""scripts/run_report.py: the self-reporting step of the workflows. Runs against a fake GitHub API and a temporary repo tree; never fails."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_report as rr  # noqa: E402

ENV = {"GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "42", "GITHUB_TOKEN": "tok-secret", "GITHUB_JOB": "live", "GITHUB_SHA": "abcdef1234"}
JOBS = {"jobs": [{"name": "live", "steps": [
    {"name": "Set up job", "status": "completed", "conclusion": "success", "started_at": "2026-10-06T10:00:00Z", "completed_at": "2026-10-06T10:00:02Z"},
    {"name": "Delayed prices", "status": "completed", "conclusion": "success", "started_at": "2026-10-06T10:00:02Z", "completed_at": "2026-10-06T10:01:32Z"},
    {"name": "Positions", "status": "completed", "conclusion": "failure", "started_at": "2026-10-06T10:01:32Z", "completed_at": "2026-10-06T10:07:32Z"}]},
    {"name": "publish", "steps": []}]}


class R:
    def __init__(self, code, js=None):
        self.status_code, self._js = code, js

    def json(self):
        return self._js


def test_steps_come_from_the_runs_own_job_with_durations():
    steps, note = rr.fetch_steps(ENV, lambda *a, **k: R(200, JOBS))
    assert note is None and [s["name"] for s in steps] == ["Set up job", "Delayed prices", "Positions"]
    assert [s["seconds"] for s in steps] == [2.0, 90.0, 360.0] and steps[2]["conclusion"] == "failure"


def test_every_failure_of_the_api_is_a_stated_reason_not_an_error():
    assert rr.fetch_steps({}, None)[1].startswith("not running inside GitHub Actions")
    assert "actions: read" in rr.fetch_steps(ENV, lambda *a, **k: R(403))[1]
    assert "500" in rr.fetch_steps(ENV, lambda *a, **k: R(500))[1]
    def boom(*a, **k):
        raise ConnectionError("x")
    assert "unreachable" in rr.fetch_steps(ENV, boom)[1]
    assert "not found" in rr.fetch_steps({**ENV, "GITHUB_JOB": "other"}, lambda *a, **k: R(200, JOBS))[1]


def tree(tmp_path, telemetry=None, latest=None):
    (tmp_path / "data" / "live_extra").mkdir(parents=True)
    if telemetry is not None:
        (tmp_path / "data" / "live_extra" / "aladin_telemetry.json").write_text(json.dumps(telemetry), encoding="utf-8")
    if latest is not None:
        (tmp_path / "data" / "aladin").mkdir()
        (tmp_path / "data" / "aladin" / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    return tmp_path


def test_produced_names_the_files_and_every_fallback(tmp_path):
    t = {"flights": [[1]] * 3, "vessels": None, "reason": "add a free AISSTREAM_API_KEY", "cadence_s": 2160, "credits_remaining": 390, "reused": True,
         "sources": {"flights": {"mode": "anonymous", "login_failed": True, "credits_used": 8, "errors": ["gulf: boom"]}}}
    rows, fb = rr.produced("live-prices", tree(tmp_path, t))
    tel = next(r for r in rows if r["file"].endswith("aladin_telemetry.json"))
    assert tel["bytes"] > 0 and "3 flights" in tel["detail"] and "cadence 2160 s" in tel["detail"]
    joined = " | ".join(fb)
    assert "anonymously" in joined and "login was refused" in joined and "no vessel feed: add a free AISSTREAM_API_KEY" in joined and "reused" in joined and "gulf: boom" in joined


def test_missing_outputs_are_reported_as_missing(tmp_path):
    rows, fb = rr.produced("aladin", tree(tmp_path))
    assert all(r["bytes"] is None for r in rows) and any("missing" in (r["detail"] or "") for r in rows)


def test_the_summary_table_has_every_step_the_failure_and_what_to_paste():
    steps, _ = rr.fetch_steps(ENV, lambda *a, **k: R(200, JOBS))
    md = rr.render("live-prices", steps, None, [{"label": "x", "file": "f.json", "bytes": 10, "detail": "d"}], ["OpenSky ran anonymously"], ENV)
    assert "| Delayed prices | ok | 90 s |" in md and "| Positions | FAILED | 6.0 min |" in md and "| **Total** |" in md
    assert "OpenSky ran anonymously" in md and "**Positions** failed" in md and "last 50 log lines" in md and "tok-secret" not in md


def test_main_writes_summary_and_json_and_never_fails(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    out = tmp_path / "run_report.json"
    root = tree(tmp_path / "repo", {"flights": [], "vessels": [], "sources": {"flights": {"mode": "oauth2"}}})
    env = {**ENV, "GITHUB_STEP_SUMMARY": str(summary)}
    assert rr.main(["--workflow", "live-prices", "--out", str(out)], env=env, get=lambda *a, **k: R(200, JOBS), root=root) == 0
    assert "Run report" not in summary.read_text(encoding="utf-8") and "live-prices: run report" in summary.read_text(encoding="utf-8")
    j = json.loads(out.read_text(encoding="utf-8"))
    assert j["failed"] == ["Positions"] and len(j["steps"]) == 3 and j["workflow"] == "live-prices"
    assert rr.main(["--workflow", "nexus", "--out", str(tmp_path)], env={}, root=tmp_path / "nowhere") == 0       # an unwritable output path: one line, exit 0


def test_each_workflow_ends_with_the_report_and_the_artifact_upload_and_can_read_its_own_steps():
    import yaml
    root = Path(__file__).resolve().parent.parent / ".github" / "workflows"
    for name in ("aladin", "live-prices", "nexus"):
        d = yaml.safe_load((root / f"{name}.yml").read_text(encoding="utf-8"))
        assert d["permissions"]["actions"] == "read"
        job = d["jobs"]["live" if name == "live-prices" else name if name == "aladin" else "graph"]
        names = [s.get("name") for s in job["steps"]]
        assert names[-2].startswith("Run report") and names[-1] == "Upload the run report"
        rep = job["steps"][-2]
        assert rep["if"] == "always()" and rep["continue-on-error"] is True and f"--workflow {name}" in rep["run"]
        assert job["steps"][-1]["with"]["path"] == "run_report.json" and job["steps"][-1]["if"] == "always()"
