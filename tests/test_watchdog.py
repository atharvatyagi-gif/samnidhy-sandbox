import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import watchdog as W  # noqa: E402

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def run(i, ago_min, conclusion="success", status="completed", attempt=1, took_min=10):
    c = NOW - timedelta(minutes=ago_min)
    return {"id": i, "status": status, "conclusion": conclusion, "run_attempt": attempt, "created_at": c.isoformat(), "updated_at": (c + timedelta(minutes=took_min)).isoformat()}


def fresh_nexus():
    return {"nexus.yml": [run(99, 60)], "nexus-predict.yml": [run(98, 60)]}


def test_a_failed_run_is_rerun_once_then_only_reported():
    acts = W.plan({**fresh_nexus(), "crypto-live.yml": [run(1, 5, "failure")]}, lambda i: [], NOW)
    assert ("rerun", "crypto-live.yml", 1) == acts[0][:3]
    acts = W.plan({**fresh_nexus(), "crypto-live.yml": [run(1, 5, "failure", attempt=2)]}, lambda i: [], NOW)
    assert acts[0][0] == "report"


def test_cancelled_and_old_runs_are_left_alone():
    acts = W.plan({**fresh_nexus(), "live-prices.yml": [run(1, 5, "cancelled")], "crypto-live.yml": [run(2, 60 * 30, "failure")]}, lambda i: [], NOW)
    assert acts == []


def test_the_chain_is_restarted_when_the_data_job_succeeded_but_the_run_shows_cancelled():
    runs = {**fresh_nexus(), "daily-update.yml": [run(10, 120, "cancelled")], "aladin.yml": [run(11, 60 * 20)]}
    jobs = {10: [{"name": "update", "conclusion": "success"}, {"name": "publish", "conclusion": "cancelled"}]}
    acts = W.plan(runs, lambda i: jobs.get(i, []), NOW)
    assert ("dispatch", "aladin.yml") == acts[0][:2]


def test_no_dispatch_when_the_next_link_already_started_or_the_data_job_failed_or_too_soon():
    jobs = {10: [{"name": "update", "conclusion": "success"}]}
    started = {**fresh_nexus(), "daily-update.yml": [run(10, 120, "cancelled")], "aladin.yml": [run(11, 60)]}
    assert W.plan(started, lambda i: jobs.get(i, []), NOW) == []
    failed = {**fresh_nexus(), "daily-update.yml": [run(10, 120, "cancelled")], "aladin.yml": []}
    assert W.plan(failed, lambda i: [{"name": "update", "conclusion": "failure"}], NOW) == []
    soon = {**fresh_nexus(), "daily-update.yml": [run(10, 30, "success", took_min=5)], "aladin.yml": []}
    assert W.plan(soon, lambda i: jobs.get(i, []), NOW) == []


def test_nexus_is_started_when_it_has_not_run_for_a_day():
    assert ("dispatch", "nexus.yml") in [a[:2] for a in W.plan({**fresh_nexus(), "nexus.yml": [run(1, 60 * 30)]}, lambda i: [], NOW)]
    assert W.plan({**fresh_nexus(), "nexus.yml": [run(1, 60 * 3)]}, lambda i: [], NOW) == []


def test_a_run_stuck_far_past_its_time_limit_is_cancelled():
    runs = {**fresh_nexus(), "live-prices.yml": [run(5, 60 * 34, status="in_progress", conclusion=None), run(6, 3, status="in_progress", conclusion=None)]}
    acts = W.plan(runs, lambda i: [], NOW)
    assert [a[:3] for a in acts] == [("cancel", "live-prices.yml", 5)]


def test_only_the_two_newest_copies_of_each_cache_are_kept():
    c = lambda i, key, t, ref="refs/heads/main": {"id": i, "key": key, "ref": ref, "created_at": t, "size_in_bytes": 100}
    caches = [c(1, "aladin-sentiment-38603507907", "2026-10-14T17:00:00Z"), c(2, "aladin-sentiment-38594841473", "2026-10-14T16:00:00Z"),
              c(3, "aladin-sentiment-38585949922", "2026-10-14T15:00:00Z"), c(4, "nexus-38538617353", "2026-10-14T12:00:00Z"),
              c(5, "setup-python-Linux-x64-24.04-Ubuntu-python-3.12.15-pip-aaf04e0089d767", "2026-10-01T00:00:00Z"),
              c(6, "terminal-38506642564", "2026-10-14T03:00:00Z"), c(7, "terminal-38525879935", "2026-10-14T07:00:00Z"), c(8, "terminal-38538932572", "2026-10-14T09:00:00Z"),
              c(9, "terminal-38500000000", "2026-10-13T09:00:00Z", ref="refs/heads/feature")]
    assert sorted(i for i, _, _ in W.prune_plan(caches)) == [3, 6]          # the nexus cache, pip's cache and another branch's copy stay
