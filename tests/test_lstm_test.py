"""The LSTM experiment: no look-ahead in its inputs, the decision rule exactly as pre-registered, and a learnable synthetic problem it can actually learn."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_lstm_test as lt  # noqa: E402


def bars(n=200, seed=3):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.01, n)))
    h, l = c * (1 + np.abs(r.normal(0, 0.005, n))), c * (1 - np.abs(r.normal(0, 0.005, n)))
    return pd.DataFrame({"c": c, "h": h, "l": l, "v": r.integers(1000, 5000, n).astype(float)}, index=pd.bdate_range("2024-01-01", periods=n))


def test_features_have_four_bounded_inputs_and_use_only_the_past():
    df = bars()
    X = lt.make_features(df)
    assert X.shape == (200, 4) and X.dtype == np.float32 and np.abs(X).max() <= 8 and np.isfinite(X).all()
    assert (X[:, 3] >= -0.5 - 1e-6).all() and (X[:, 3] <= 0.5 + 1e-6).all()                       # the close's place in the day's range
    cut = 120
    df2 = df.copy()
    df2.iloc[cut + 1:] = df2.iloc[cut + 1:] * 1.7                                                      # the future is rewritten
    X2 = lt.make_features(df2)
    assert np.allclose(X[:cut + 1], X2[:cut + 1])                                                      # every input up to the cut is unchanged
    flat = df.copy()
    flat.loc[flat.index[50], ["h", "l"]] = flat.iloc[50]["c"]                                          # a zero-range day: no division blow-up
    assert np.isfinite(lt.make_features(flat)).all()


def test_sequences_end_on_the_rows_own_date_and_skip_rows_without_enough_history():
    df = bars()
    feats = {"AAA": lt.make_features(df)}
    index_of = {"AAA": {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}}
    rows = pd.DataFrame({"date": [df.index[10], df.index[59], df.index[60], df.index[150], pd.Timestamp("2030-01-01")], "sym": ["AAA"] * 4 + ["AAA"], "y": [1, 0, 1, 0, 1]})
    X, keep = lt.build_sequences(rows, feats, index_of)
    assert keep.tolist() == [1, 2, 3] and X.shape == (3, 60, 4)                                         # row 0 (10 days of history) and the unknown date are skipped
    assert np.allclose(X[2], feats["AAA"][91:151]) and np.allclose(X[0], feats["AAA"][0:60])
    X0, k0 = lt.build_sequences(rows, {}, {})
    assert X0.shape == (0, 60, 4) and len(k0) == 0


def test_the_decision_rule_is_exactly_the_pre_registered_one():
    f = lambda gains: [{"year": 2018 + i, "auc_lgb": 0.55, "auc_blend": 0.55 + g} for i, g in enumerate(gains)]       # noqa: E731
    assert lt.decide(f([0.005, 0.004, 0.004]))["used"] is True
    assert lt.decide(f([0.002, 0.002, 0.002]))["used"] is False                                          # better every year but below 0.003 on average
    assert lt.decide(f([0.02, -0.001, -0.001]))["used"] is False                                         # a big average gain from one year: not at least two thirds
    assert lt.decide(f([0.01, 0.01, -0.005]))["used"] is True and lt.decide(f([0.01, 0.01, -0.005]))["years_better"] == "2 of 3"
    d = lt.decide([{"year": 2018, "auc_lgb": None, "auc_blend": None}] + f([0.01]))
    assert d["years_better"] == "1 of 1" and d["used"] is True                                             # a fold that could not run does not count either way
    assert lt.decide([])["used"] is False and lt.decide([])["auc_gain"] == 0.0
    assert "two thirds" in lt.decide([])["rule"]


def test_the_lstm_can_learn_a_signal_that_is_really_there_and_nothing_from_noise():
    r = np.random.default_rng(0)
    X = r.normal(0, 1, (6000, lt.L, lt.F)).astype(np.float32)
    y_signal = (X[:, -5:, 0].mean(axis=1) > 0).astype(int)                                              # the last five returns decide the answer
    net, ep = lt.train_lstm(X[:5000], y_signal[:5000], seconds=60, max_epochs=4)
    assert lt.auc(y_signal[5000:], lt.predict(net, X[5000:])) > 0.85 and 0 < ep <= 4
    y_noise = r.integers(0, 2, 6000)
    net2, _ = lt.train_lstm(X[:5000], y_noise[:5000], seconds=60, max_epochs=3)
    assert abs(lt.auc(y_noise[5000:], lt.predict(net2, X[5000:])) - 0.5) < 0.06


def test_training_stops_at_its_time_budget():
    X = np.random.default_rng(1).normal(0, 1, (4000, lt.L, lt.F)).astype(np.float32)
    y = np.random.default_rng(2).integers(0, 2, 4000)
    import time
    t0 = time.time()
    _, ep = lt.train_lstm(X, y, seconds=0.5, max_epochs=8)
    assert time.time() - t0 < 10 and ep < 8


def test_a_whole_walk_forward_run_on_synthetic_stocks_reports_every_fold_and_a_verdict():
    r = np.random.default_rng(5)
    feats, index_of, recs = {}, {}, []
    idx = pd.bdate_range("2015-01-01", periods=1500)
    for k in range(25):
        df = bars(1500, seed=k)
        df.index = idx
        feats[f"S{k}"] = lt.make_features(df)
        index_of[f"S{k}"] = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(idx)}
        for d in idx[80::5]:
            recs.append({"date": d, "sym": f"S{k}", "y": int(r.integers(0, 2)), "p": float(r.uniform(0.4, 0.6))})
    rows = pd.DataFrame(recs)
    res = lt.run(rows, feats, index_of, budget_s=20, log=lambda *a: None, first_year=2019, max_epochs=1, cap=20000)
    ran = [f for f in res["folds"] if f["auc_lgb"] is not None]
    assert len(res["folds"]) >= 2 and ran and all(0.4 < f["auc_lstm"] < 0.6 for f in ran)               # random stocks: nothing to find
    assert res["tested"] and res["note"].startswith("tested, no out-of-sample gain") and res["used"] is False
    assert all(f["year"] >= 2019 and f["n_train"] > 0 for f in res["folds"])
    assert res["window"] == 60 and res["units"] == 32 and res["inputs"] == 4 and res["dropout"] == 0.2


def test_main_without_the_saved_record_explains_what_to_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(lt, "OOS", tmp_path / "missing.pkl")
    assert lt.main([]) == 0 and "aladin_model.py --full" in capsys.readouterr().out
