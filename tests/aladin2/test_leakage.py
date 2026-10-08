"""No look-ahead. Every feature and every backtest decision for dates <= D must be identical when everything after D is changed."""
import numpy as np
import pandas as pd

from scripts.aladin2 import backtest as B
from scripts.aladin2 import costs as C
from scripts.aladin2 import data_lake as L
from scripts.aladin2 import synthetic as S

CFG = C.load_cfg()


def frame(seed=3, n=900):
    px = S.make("momentum", n=n, seed=seed)
    return L.clean_prices(px)


def test_shifting_all_prices_after_D_by_50pct_leaves_features_up_to_D_unchanged():
    px = frame(); D = px.index[600]
    bad = px[["o", "h", "l", "c"]].copy(); bad.loc[bad.index > D] *= 1.5
    bad["v"] = px["v"]; bad = L.clean_prices(bad)
    a, b = L.price_features(px).loc[:D], L.price_features(bad).loc[:D]
    pd.testing.assert_frame_equal(a, b)


def test_permuting_future_returns_does_not_change_past_features():
    px = frame(); D = px.index[600]; rng = np.random.default_rng(0)
    r = np.log(px["c"] / px["c"].shift()).fillna(0).values
    k = int((px.index <= D).sum()); r2 = r.copy(); r2[k:] = rng.permutation(r[k:])
    ratio = np.exp(np.cumsum(r2) - np.cumsum(r)); bad = px.copy()
    for col in ("o", "h", "l", "c"):
        bad[col] = px[col] * ratio
    pd.testing.assert_frame_equal(L.price_features(px).loc[:D], L.price_features(L.clean_prices(bad)).loc[:D])


def test_backtest_trades_decided_up_to_D_do_not_change_when_the_future_changes():
    px = frame(); D = px.index[600]; f = L.price_features(px)
    sigf = lambda F: (F["r20"] > 0).astype(float)
    base = B.run(px, sigf(f), {"type": "fixed", "n": 10}, "delivery", 5, CFG)["trades"]
    bad = px[["o", "h", "l", "c"]].copy(); bad.loc[bad.index > D] *= 1.5; bad["v"] = px["v"]; bad = L.clean_prices(bad)
    alt = B.run(bad, sigf(L.price_features(bad)), {"type": "fixed", "n": 10}, "delivery", 5, CFG)["trades"]
    # trades whose ENTRY decision (signal date) is <= D are identical in entry; (exit may differ if it falls after D, so compare only trades fully inside)
    a = base[base["exit_date"] <= D].reset_index(drop=True); b = alt[alt["exit_date"] <= D].reset_index(drop=True)
    assert len(a) > 5; pd.testing.assert_frame_equal(a, b)


def test_features_are_causal_by_construction_truncation_equals_full():
    px = frame(); D = px.index[500]
    pd.testing.assert_frame_equal(L.price_features(px).loc[:D], L.price_features(px.loc[:D]))


def test_signal_is_never_filled_at_its_own_close():
    px = frame(); f = L.price_features(px)
    T = B.run(px, (f["r20"] > 0).astype(float), {"type": "fixed", "n": 5}, "delivery", 5, CFG)["trades"]
    assert (T["entry_date"] > T["signal_date"]).all()
    assert all(T.loc[i, "entry_px"] == px.loc[T.loc[i, "entry_date"], "o"] for i in T.index)


def test_side_series_respect_their_publication_lag():
    idx = pd.bdate_range("2024-01-01", periods=10); df = pd.DataFrame({"c": 1.0}, index=idx)
    s = pd.Series(np.arange(10, dtype=float), index=idx)                           # value on day i is i
    out = L.attach(df, s, "delivery")                                              # lag 1 trading day
    assert np.isnan(out["delivery"].iloc[0]) and out["delivery"].iloc[5] == 4      # row 5 sees day 4's value, not day 5's
    out0 = L.attach(df, s, "india_vix"); assert out0["india_vix"].iloc[5] == 5     # same-close source, lag 0
    s2 = s.copy(); s2.iloc[7:] = 999
    assert (L.attach(df, s2, "delivery")["delivery"].iloc[:8].values[1:] == out["delivery"].iloc[:8].values[1:]).all()   # a change on day 7+ cannot reach rows <= 7 via the lag


def test_fundamentals_wait_for_filing_or_sixty_days():
    assert L.fundamentals_available_at("2026-03-31", "2026-05-12") == pd.Timestamp("2026-05-12")
    assert L.fundamentals_available_at("2026-03-31") == pd.Timestamp("2026-05-30")


def test_unadjusted_split_is_flagged_not_treated_as_a_return():
    px = frame(n=300); px.loc[px.index[200]:, ["o", "h", "l", "c"]] *= 0.2        # a 1:5 split that was not adjusted
    p = L.clean_prices(px); assert p["suspect_action"].sum() == 1
    f = L.price_features(p); assert np.isnan(f["lr1"].iloc[200]) and f["lr1"].abs().max() < 0.35


def test_one_bar_spike_is_dropped_and_persistent_break_blocks_trades():
    px = frame(n=400)[["o", "h", "l", "c", "v"]].copy()
    px.iloc[100, [0, 1, 2, 3]] = px.iloc[100, [0, 1, 2, 3]] * 4.4                              # a bad print: one bar, then back to normal
    p = L.clean_prices(px); assert len(p) == 399 and not p["suspect_action"].any()
    px2 = frame(n=400)[["o", "h", "l", "c", "v"]].copy(); px2.iloc[250:, [0, 1, 2, 3]] *= 0.2    # unadjusted 1:5 split, persistent
    p2 = L.clean_prices(px2); assert p2["suspect_action"].sum() == 1 and p2["post_break"].iloc[260] and not p2["post_break"].iloc[200]
    r = B.run(p2, pd.Series(1.0, index=p2.index), {"type": "fixed", "n": 20}, "delivery", 5, CFG)
    T = r["trades"]; brk = p2.index[p2["suspect_action"]][0]
    assert not ((T["entry_date"] < brk) & (T["exit_date"] >= brk)).any() and r["discarded_across_action"] >= 1
    assert (T["entry_date"][T["entry_date"] > brk] > p2.index[250 + 250 - 1]).all() if (T["entry_date"] > brk).any() else True    # nothing is entered during the post-break window
