"""GitHub suspended the account on 18 Nov 2026 after ~515 Actions runs a day (a self-restarting "market clock" loop firing the live
workflows every 5 minutes, day and night, weekends included). These tests keep the workflow files within a budget so that cannot
come back: GitHub only runs the heavy night jobs; the live lane stays on the Azure server."""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
BUDGET_RUNS_PER_DAY = 30
MAX_TIMEOUT_MIN = 360
HEAVY_NIGHT = {"daily-update.yml", "aladin.yml", "aladin2.yml", "nexus.yml", "nexus-predict.yml", "blab.yml", "history-archive.yml"}


def _field(text, lo, hi):
    """One cron field -> the set of values it matches (supports *, lists, ranges, steps)."""
    out = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/"); step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
            if step != 1:
                b = hi
        out.update(range(a, b + 1, step))
    return out


def runs_per_day(cron):
    """Average runs per calendar day for a 5-field cron (day-of-month, month and weekday limits count as the share of days they allow)."""
    m, h, dom, mon, dow = cron.split()
    n = len(_field(m, 0, 59)) * len(_field(h, 0, 23))
    if dom != "*":
        n *= len(_field(dom, 1, 31)) / 30.44
    if mon != "*":
        n *= len(_field(mon, 1, 12)) / 12
    if dow != "*":
        n *= len({d % 7 for d in _field(dow, 0, 7)}) / 7
    return n


def load_workflows(directory=WORKFLOWS):
    out = {}
    for f in sorted(Path(directory).glob("*.yml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        d["__text__"] = f.read_text(encoding="utf-8")
        d["__on__"] = d.get("on", d.get(True)) or {}          # PyYAML reads the key `on` as the boolean True
        out[f.name] = d
    return out


def schedule_runs(wf):
    sched = (wf["__on__"] or {}).get("schedule") or []
    return sum(runs_per_day(s["cron"]) for s in sched)


def chain_calls(text):
    return re.findall(r"gh workflow run ([\w.-]+\.yml)", text)


def test_runs_per_day_examples():
    assert runs_per_day("*/5 * * * *") == 288
    assert runs_per_day("30 13 * * *") == 1
    assert abs(runs_per_day("*/5 * * * 1-5") - 288 * 5 / 7) < 1e-9
    assert abs(runs_per_day("30 20 1 * *") - 1 / 30.44) < 1e-9
    assert runs_per_day("0 2,14 * * *") == 2


def test_total_runs_per_day_within_budget():
    wfs = load_workflows()
    own = {name: schedule_runs(w) for name, w in wfs.items()}
    total = sum(own.values())
    for name, w in wfs.items():                                   # a chained run happens once per run of its caller
        for target in chain_calls(w["__text__"]):
            total += own.get(name, 0) if own.get(name, 0) else 1
    assert total <= BUDGET_RUNS_PER_DAY, f"{total:.0f} runs/day (budget {BUDGET_RUNS_PER_DAY}); by workflow: { {k: round(v, 1) for k, v in own.items() if v} }"


def test_no_workflow_outside_the_night_set_has_a_schedule():
    offenders = {n: schedule_runs(w) for n, w in load_workflows().items() if n not in HEAVY_NIGHT and schedule_runs(w)}
    assert not offenders, f"live-lane workflows must not run on GitHub (Azure runs them): {offenders}"


def test_no_self_restarting_workflow():
    for name, w in load_workflows().items():
        assert name not in chain_calls(w["__text__"]), f"{name} starts itself"


def test_no_long_loops_or_long_timeouts():
    for name, w in load_workflows().items():
        t = w["__text__"]
        assert not re.search(r"while\s+(:|true)\b", t), f"{name} has an endless loop"
        assert not re.search(r"^\s*sleep\s+(60|[6-9]\d|\d{3,})\b", t, re.M), f"{name} sleeps in a loop"
        for m in re.finditer(r"timeout-minutes:\s*(\d+)", t):
            assert int(m.group(1)) <= MAX_TIMEOUT_MIN, f"{name} timeout {m.group(1)} min"


def test_no_workflow_runs_when_its_own_file_is_pushed():
    for name, w in load_workflows().items():
        push = (w["__on__"] or {}).get("push") or {}
        paths = push.get("paths", []) if isinstance(push, dict) else []
        assert not any(p.startswith(".github/workflows/") for p in paths), f"{name} runs itself when edited"


def test_market_clock_is_gone():
    assert "market-clock.yml" not in load_workflows()


@pytest.mark.parametrize("name", sorted(HEAVY_NIGHT))
def test_night_workflows_exist(name):
    assert name in load_workflows()
