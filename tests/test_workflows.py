"""Workflow wiring for ALADIN (section 9 of the brief), checked as data: triggers, limits, failure tolerance, commit rules."""
from pathlib import Path

import yaml

W = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name):
    d = yaml.safe_load((W / name).read_text(encoding="utf-8"))
    d["on"] = d.get("on", d.get(True))                              # PyYAML reads the key `on` as boolean True
    return d


def steps(d):
    return list(d["jobs"].values())[0]["steps"]


def test_aladin_nightly_triggers_limits_and_order():
    d = load("aladin.yml")
    on = d["on"]
    assert on["workflow_run"]["workflows"] == ["Daily update"] and on["workflow_run"]["types"] == ["completed"] and "workflow_dispatch" in on
    job = list(d["jobs"].values())[0]
    assert "conclusion == 'success'" in job["if"] and job["timeout-minutes"] == 150
    assert d["permissions"] == {"contents": "write"} and d["concurrency"] == {"group": "aladin", "cancel-in-progress": False}
    runs = [s.get("run", "") for s in steps(d)]
    order = [next(i for i, r in enumerate(runs) if k in r) for k in ("aladin_fund.py", "aladin_filings.py", "aladin_model.py", "paper_trader.py")]
    assert order == sorted(order)
    limits = {s["name"].split(" (")[0]: s.get("timeout-minutes") for s in steps(d) if "name" in s}
    assert limits["Fundamental front"] == 30 and limits["Filings tone and alternative data"] == 20 and limits["Probabilities"] == 90
    uses = " ".join(s.get("uses", "") for s in steps(d))
    assert "actions/cache/restore" in uses and "actions/cache/save" in uses


def test_every_step_except_checkout_and_python_may_fail():
    for name in ("aladin.yml", "aladin-sentiment.yml"):
        for s in steps(load(name)):
            if s.get("uses", "").startswith(("actions/checkout", "actions/setup-python")):
                continue
            assert s.get("continue-on-error") is True, (name, s.get("name"))


def test_commit_step_uses_skip_ci_the_bot_identity_and_the_pull_rebase_push_pattern():
    for name, paths in (("aladin.yml", ("data/aladin", "data/paper_trades")), ("aladin-sentiment.yml", ("data/aladin/sentiment.json",))):
        save = [s for s in steps(load(name)) if "git commit" in s.get("run", "")][0]["run"]
        assert "[skip ci]" in save and "github-actions[bot]" in save and "git pull --rebase" in save and "git push origin HEAD:main" in save
        assert all(p in save for p in paths) and "--force" not in save and ".env" not in save and "live_extra" not in save


def test_nightly_installs_the_aladin_requirements_and_restores_the_terminal_cache_and_history():
    runs = " ".join(s.get("run", "") for s in steps(load("aladin.yml")))
    assert "requirements-aladin.txt" in runs and "origin history" in runs
    caches = [s for s in steps(load("aladin.yml")) if s.get("uses", "").startswith("actions/cache/restore")]
    assert any(s["with"]["key"].startswith("terminal-") or "terminal-" in str(s["with"].get("restore-keys", "")) for s in caches)
    assert any("aladin-cache-" in str(s["with"].get("restore-keys", "")) for s in caches)


def test_heartbeat_fires_the_sentiment_workflow_and_globe_workflow_runs_geo():
    clock = (W / "market-clock.yml").read_text(encoding="utf-8")
    assert "fire aladin-sentiment.yml" in clock and "fire globe-data.yml" in clock and "fire live-prices.yml" in clock
    globe = " ".join(s.get("run", "") for s in steps(load("globe-data.yml")))
    assert "geo_tension.py" in globe and "data/aladin/geo.json" in globe
    daily = " ".join(s.get("run", "") for s in steps(load("daily-update.yml")))
    assert "terminal_fund.py" in daily and "check_houses.py" in daily
