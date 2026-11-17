"""B-Lab Macro division, step 4 (scripts/blab/macro.py), on made-up data. No network; the FRED key is a made-up value."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from blab import core  # noqa: E402
from blab import macro as M  # noqa: E402


def days(n, start=date(2008, 1, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def test_rbi_page_parser():
    page = "<div>Policy Repo Rate : 5.50%</div><p>Standing Deposit Facility Rate : 5.25%</p> Marginal Standing Facility Rate : 5.75% Bank Rate : 5.75% CRR : 3.00% SLR : 18.00% INR / 1 USD : 94.1159"
    assert M.parse_rbi(page) == {"repo": 5.5, "sdf": 5.25, "msf": 5.75, "bank_rate": 5.75, "crr": 3.0, "slr": 18.0, "inr_usd": 94.1159}
    assert M.parse_rbi("<html>redesigned</html>")["repo"] is None


def test_values_count_only_from_publication():
    pub = M.published([["2026-01-01", 7.0], ["2026-02-01", 7.5]], "M")
    assert pub == [["2026-02-15", 7.0], ["2026-03-18", 7.5]]
    known = M.asof_series(pub, ["2026-02-10", "2026-02-15", "2026-03-17", "2026-03-18"])
    assert known == [None, 7.0, 7.0, 7.5]                                              # the January value is unknown until mid-February


def test_factor_levels_follow_the_declared_thresholds():
    d = days(400)
    rup = [[x, 80 + (0.04 * i if i > 200 else 0)] for i, x in enumerate(d)]          # a steady rupee, then a fast fall
    fred = {"DEXINUS": rup, "VIXCLS": [[x, 30.0] for x in d], "DCOILBRENTEU": [[x, 80.0] for x in d]}
    lv = M.levels(d, fred)
    assert lv["rupee"][150] == "stable" and lv["rupee"][-1] == "weakening"
    assert lv["us fear"][-1] == "stressed" and lv["oil"][-1] == "flat"
    assert lv["india rates"][-1] is None and lv["fed"][-1] is None                     # no data: no level, never guessed


def test_outcome_finds_a_real_difference_and_says_so_when_there_is_none():
    d = days(3000)
    lev = ["stressed" if (i // 200) % 2 else "calm" for i in range(len(d))]
    price, p = [], 100.0
    for i in range(len(d)):
        p *= 1.004 if lev[i] == "stressed" else 1.0002
        price.append(p)
    out, allm = M.outcome(d, price, {"us fear": lev, "flat": ["same"] * len(d)}, 21)
    assert out["us fear"]["stressed"]["verdict"] == "measurably better than usual"
    assert out["us fear"]["calm"]["verdict"] == "measurably worse than usual"
    assert out["flat"]["same"]["verdict"] == "no measurable difference" and abs(out["flat"]["same"]["diff_pct"]) < 1e-9


def test_fred_needs_the_key_masks_it_and_merges_new_values(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "STORE", tmp_path)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    ctx = core.Ctx(now=datetime(2026, 11, 17, 10, tzinfo=timezone.utc))
    with pytest.raises(core.NoKey):
        M.fred_series(ctx, ["DEXINUS"])
    monkeypatch.setenv("FRED_API_KEY", "MADEUPKEY123")
    calls = []
    def fetch(url):
        calls.append(url)
        if "DGS10" in url:
            raise OSError("bad request for " + url)
        return {"observations": [{"date": "2026-11-05", "value": "93.5"}, {"date": "2026-11-06", "value": "93.9"}, {"date": "2026-11-07", "value": "."}]}
    ctx.fred_fetch = fetch
    obs, errs = M.fred_series(ctx, ["DEXINUS", "DGS10"])
    assert obs["DEXINUS"] == [["2026-11-05", 93.5], ["2026-11-06", 93.9]]               # "." (no value) is skipped, never zero
    assert errs and all("MADEUPKEY123" not in e for e in errs) and "***" in errs[0]   # the key never appears in a message
    M.fred_series(ctx, ["DEXINUS"])
    assert "observation_start=2026-09-07" in calls[-1]                                 # next run: from 60 days before the last value
    stored = json.loads((tmp_path / "fred.json").read_text())
    assert "MADEUPKEY123" not in json.dumps(stored)
    monkeypatch.delenv("FRED_API_KEY")
    obs2, errs2 = M.fred_series(ctx, ["DEXINUS"])                                      # no key but saved values: shown, and said so
    assert obs2["DEXINUS"] and "no key" in errs2[0]


def test_mospi_reads_the_all_india_combined_general_index():
    ctx = core.Ctx(now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    def fetch(url):
        assert "state_code=99" in url and "sector_code=3" in url and "group_code=0" in url
        if "year=2026" in url:
            return {"data": [], "msg": "No Data Found"}
        return {"data": [{"baseyear": "2012", "year": 2025, "month": "December", "state": "All India", "sector": "Combined", "group": "General", "index": "198.0", "inflation": "1.33"}]}
    ctx.mospi_fetch = fetch
    row, note = M.mospi_cpi(ctx)
    assert row == {"year": 2025, "month": "December", "index": "198.0", "inflation": "1.33", "base": "2012"} and note == ""


def test_strategies_are_grouped_by_each_factors_level():
    lab = {"dates": ["2020-01-01", "2020-01-08", "2020-01-15"], "values": {"momentum": [0.01, 0.03, None], "reversal": [None, -0.01, 0.0]}}
    by_day = {"2020-01-01": {"oil": "flat"}, "2020-01-08": {"oil": "flat"}, "2020-01-15": {"oil": "up sharply"}}
    out = M.strategy_by_factor(lab, by_day)
    assert out["oil"]["flat"]["momentum"]["n"] == 2 and out["oil"]["flat"]["momentum"]["mean_pct"] == 2.0
    assert out["oil"]["up sharply"]["reversal"]["verdict"] == "too few start days"
    assert M.strategy_by_factor(None, by_day) == {}
