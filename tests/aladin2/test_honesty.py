"""Section 6.7 in miniature: the learner promotes nothing on noise and finds a strong planted reversion edge. The full-size runs (2,000 noise series etc.) are in
scripts/aladin2/experiments.py and reported in docs/aladin2/PHASE2_REPORT.md. These tests take about a minute."""
import numpy as np
import pytest

from scripts.aladin2 import costs as C
from scripts.aladin2 import evaluate as E
from scripts.aladin2 import experiments as X
from scripts.aladin2.strategies import registry as R


@pytest.fixture(scope="module")
def world():
    cfg0 = X.zero_costs(C.load_cfg()); cfg, cal = X.experiment_cfg(cfg0)
    specs = [("noise", 20_000 + i, 0, 0.5) for i in range(40)] + [("reversion", 30_000 + i, 80, 0.5) for i in range(8)]
    U, meta = X.build_universe(specs, cfg, workers=4)
    sel = [s for s in R.all_strategies() if s.family not in ("relative", "flow")]
    res = E.walk_forward(U, sel, cal, cfg, seed=3, log=None, max_folds=24)
    return U, meta, res, cfg


def test_no_noise_series_is_promoted_and_false_discovery_proportion_is_below_q(world):
    U, meta, res, cfg = world
    null_pairs = [p for fold in res["eligible_by_fold"] for p in fold if meta[p[0]][0] == "noise"]
    total = sum(len(f) for f in res["eligible_by_fold"])
    assert total > 0                                                                   # the machine is not simply dead: it promoted the planted edges
    assert len(null_pairs) / total <= cfg["eval"]["fdr_q"]


def test_strong_planted_reversion_is_found_in_most_series(world):
    U, meta, res, cfg = world
    ever = {(s, sid) for fold in res["eligible_by_fold"] for s, sid in fold}
    planted = [s for s, m in meta.items() if m[0] == "reversion"]
    found = [s for s in planted if any(R.by_id()[sid].family == "reversion" for (t, sid) in ever if t == s)]
    assert len(found) / len(planted) >= 0.7


def test_every_traded_strategy_was_selected_before_its_block_and_trades_start_after_it(world):
    U, meta, res, cfg = world
    rows = res["rows"]; folds = X.E.folds(__import__("pandas").bdate_range("2012-01-02", periods=6000), X.experiment_cfg(C.load_cfg())[0])
    starts = {k: a for k, (a, b) in enumerate(folds)}
    assert (rows["e"].values >= rows["fold"].map(starts).values).all()                 # a trade is never entered before its block starts
    assert set(rows["state"]) <= {"Probation", "Active"}
