"""ALADIN model pieces that can be tested without the full data run: combiner, stacker, evaluation, fundamentals maths, filings maths."""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_filings as fl  # noqa: E402
import aladin_fund as af  # noqa: E402
import aladin_model as am  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "combiner_cases.json").read_text(encoding="utf-8"))["cases"]


# ---------------------------------------------------------------- combiner
def test_combiner_meets_every_shared_fixture_case():
    assert len(CASES) > 300
    for c in CASES:
        i = c["in"]
        r = am.combine_py(i["p_tech"], i["F"], i["S"], i["sweep"], i["w"])
        assert {k: r[k] for k in c["out"]} == c["out"], c["name"]


def test_combiner_hand_worked_numbers_are_independent_of_the_code():
    # logit(0.6) = ln 1.5 = 0.405465; +0.2*0.5 = 0.505465 -> 1/(1+exp(-0.505465)) = 0.6238
    assert am.combine_py(0.6, F=50)["p"] == pytest.approx(0.6238, abs=1e-3)
    assert am.combine_py(0.6, S=-100)["p"] == pytest.approx(1 / (1 + math.exp(-(math.log(1.5) - 0.12))), abs=1e-4)
    assert am.combine_py(0.97, 100, 100, 100)["p"] == 0.98 and am.combine_py(0.03, -100, -100, -100)["p"] == 0.02
    r = am.combine_py(0.7, F=40, S=30)
    assert r["agree"] == "3/3" and r["conf"] == "High"
    assert am.combine_py(0.4, F=30, S=20)["agree"] == "1/3"                    # p leans down; only the technical front agrees
    for x in CASES:
        assert 0.02 <= x["out"]["p"] <= 0.98 and abs(x["out"]["p"] + x["out"]["q"] - 1) < 2e-4


def test_confidence_boundaries_and_missing_fronts():
    assert am.combine_py(0.529)["conf"] == "Low" and am.combine_py(0.531)["conf"] == "Medium"
    assert am.combine_py(0.569)["conf"] == "Medium" and am.combine_py(0.571)["conf"] == "High"
    assert am.combine_py(0.5)["p"] == 0.5 and am.combine_py(0.5, None, None, None)["agree"] == "0/1"
    assert am.combine_py(0.6, None, 50)["agree_n"] == 2


def test_deciles_are_1_to_10_with_10_highest():
    d = am.decile_of(np.linspace(0, 1, 1000))
    assert min(d) == 1 and max(d) == 10 and d[0] == 1 and d[-1] == 10 and d.count(5) == 100


# ---------------------------------------------------------------- stacker
def stack_rows(n_days, signal, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        for _ in range(60):
            lt = rng.normal(0, 0.2)
            F, S = rng.normal(0, 30), rng.normal(0, 30)
            hmm = rng.random()
            true_logit = lt + signal * (F / 100) * 3 + signal * (S / 100) * 2
            rows.append({"date": d, "y": int(rng.random() < 1 / (1 + math.exp(-true_logit))), "logit_t": lt, "F": F, "S": S, "hmm": hmm})
    return pd.DataFrame(rows)


def test_stacker_stays_in_prior_mode_until_120_matured_days():
    r = am.fit_stacker(stack_rows(100, 1.0))
    assert r["mode"] == "prior" and "120 needed" in r["reason"] and r["fit"] is None


def test_stacker_replaces_priors_only_when_it_wins_out_of_sample():
    strong = am.fit_stacker(stack_rows(200, 1.0))                              # F and S carry much more signal than the priors assume
    assert strong["mode"] == "fitted" and strong["fit"]["brier_fitted"] < strong["fit"]["brier_prior"]
    noise = am.fit_stacker(stack_rows(200, 0.0, seed=5))                       # F and S are pure noise: the priors' small weights are already near right
    assert noise["mode"] in ("prior", "fitted")
    if noise["mode"] == "fitted":
        assert noise["fit"]["brier_fitted"] < noise["fit"]["brier_prior"]


# ---------------------------------------------------------------- evaluation
def oos_frame(n_years=3, per_year=4000, signal=0.5, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for y in range(n_years):
        dates = pd.bdate_range(f"{2020 + y}-01-01", periods=per_year // 40)
        for d in dates:
            lat = rng.normal(0, 1, 40)
            yv = (rng.random(40) < 1 / (1 + np.exp(-(0.1 + signal * lat)))).astype(int)
            p = 1 / (1 + np.exp(-(0.1 + signal * lat)))
            rows.append(pd.DataFrame({"date": d, "sym": [f"S{i}" for i in range(40)], "y": yv, "p": p, "p_reg": np.nan}))
    return pd.concat(rows, ignore_index=True)


def test_evaluate_reports_base_rate_brier_deciles_and_calibration():
    O = oos_frame()
    ev, iso, use_reg = am.evaluate(O, 10)
    m = ev["metrics"]
    assert not use_reg and m["regime"]["tested"] is False
    assert 0.5 < m["auc"] < 0.7 and m["brier"] < m["brier_base"]                # the signal is real, so it beats the base-rate forecast
    assert m["top_decile_hit"] > m["base_rate"] > m["bottom_decile_hit"]
    assert m["accuracy"] <= 1 and m["always_up_accuracy"] >= 0.5 and len(ev["calibration"]) == 10
    assert [y["year"] for y in ev["years"]] == [2020, 2021, 2022]
    assert np.all(np.diff(iso["x"]) >= 0) and np.all(np.diff(iso["y"]) >= 0)     # isotonic = monotone
    assert 0.02 <= min(iso["y"]) and max(iso["y"]) <= 0.98


def test_regime_blend_is_kept_only_if_its_brier_score_is_better():
    O = oos_frame()
    better = O.assign(p_reg=np.clip(O["p"] * 0.9 + O["y"] * 0.1, 0.02, 0.98))   # leaks the answer: certainly better
    worse = O.assign(p_reg=np.clip(O["p"] * 0.6 + 0.2, 0.02, 0.98))
    assert am.evaluate(better, 10)[2] is True and am.evaluate(worse, 10)[2] is False
    assert am.evaluate(worse, 10)[0]["metrics"]["regime"]["tested"] is True


def test_isotonic_state_round_trips():
    ev, iso, _ = am.evaluate(oos_frame(), 10)
    p = am.apply_iso(iso, np.array([0.1, 0.5, 0.9]))
    assert p[0] <= p[1] <= p[2]


# ---------------------------------------------------------------- fundamentals
def test_reverse_dcf_growth_inverts_the_dcf():
    g = af.reverse_dcf_growth(ev=1000.0, fcf=40.0)
    assert g is not None
    cf, tot = 40.0, 0.0
    for t in range(1, 11):
        cf *= 1 + g
        tot += cf / 1.12 ** t
    tot += cf * 1.05 / (0.12 - 0.05) / 1.12 ** 10
    assert tot == pytest.approx(1000.0, rel=1e-3)
    assert af.reverse_dcf_growth(1000, -5) is None and af.reverse_dcf_growth(1000, 0) is None and af.reverse_dcf_growth(None, 5) is None
    assert af.reverse_dcf_growth(1e9, 1.0) is None                              # no growth rate in range justifies this price


def test_merton_distance_to_default_matches_the_formula():
    E, D, sE, mu = 800.0, 200.0, 0.30, 0.10
    V = E + D
    sD = 0.05 + 0.25 * sE
    sV = (E / V) * sE + (D / V) * sD
    dd = (math.log(V / D) + (mu - sV ** 2 / 2)) / sV
    got_dd, got_pd = af.merton_dd(E, D, sE, mu)
    assert got_dd == pytest.approx(dd, abs=1e-3) and got_pd == pytest.approx(0.5 * math.erfc(dd / math.sqrt(2)), abs=1e-5)
    assert af.merton_dd(None, 100, 0.3, 0.1) == (None, None) and af.merton_dd(100, 0, 0.3, 0.1) == (None, None)


def test_altman_z2_and_the_worse_of_two_band():
    assert af.altman_z2(wc=10, re=20, ebit=15, be=50, ta=100, tl=50) == pytest.approx(3.25 + 6.56 * 0.1 + 3.26 * 0.2 + 6.72 * 0.15 + 1.05 * 1.0, abs=1e-3)
    assert af.altman_z2(None, 1, 1, 1, 1, 1) is None
    assert af.distress_band(5.0, 7.0) == "Low" and af.distress_band(5.0, 5.0) == "Moderate" and af.distress_band(5.0, 3.0) == "High"
    assert af.distress_band(1.0, 7.0) == "High" and af.distress_band(2.0, None) == "Moderate" and af.distress_band(None, None) is None


def test_f_score_formula_and_renormalisation():
    f, cov = af.f_score(1.0, 1.0, 1.0, 1.0, None)
    assert f == pytest.approx(100 * math.tanh(1 / 1.5), abs=0.1) and cov == 1.0
    f2, cov2 = af.f_score(1.0, 1.0, None, None, None)                           # weights 0.35 + 0.35 renormalised
    assert f2 == pytest.approx(100 * math.tanh(1 / 1.5), abs=0.1) and cov2 == 0.5
    assert af.f_score(0.0, 0.0, 0.0, 0.0, "High")[0] == pytest.approx(100 * math.tanh(-1 / 1.5), abs=0.1)
    assert af.f_score(0.0, 0.0, 0.0, 0.0, "Moderate")[0] == pytest.approx(100 * math.tanh(-0.4 / 1.5), abs=0.1)
    assert af.f_score(None, None, None, None, "Low") == (None, 0.0)


def test_winsorise_and_orthogonalise():
    rng = np.random.default_rng(2)
    n = 300
    size = rng.normal(0, 1, n)
    q = 0.8 * size + rng.normal(0, 0.5, n)
    q[0] = 50                                                                    # an outlier
    df = pd.DataFrame({"q": q, "size": size})
    z = af.winsorise_z(df, ["q"])
    assert abs(z["q"].mean()) < 1e-9 and abs(z["q"].std() - 1) < 1e-9 and z["q"].max() < 5     # the outlier is pulled in
    res, r2 = af.orthogonalise(z.assign(size=size), "q", ["size"])
    assert abs(np.corrcoef(res.dropna(), size[res.notna()])[0, 1]) < 1e-8 and 0.3 < r2 < 0.9
    assert abs(res.std() - 1) < 1e-9


def test_factor_extraction_from_a_statement():
    stmt = {"ann": {"inc": {"Total Revenue": [["2026-03-31", 1100.0], ["2025-03-31", 1000.0], ["2024-03-31", 950.0]], "EBIT": [["2026-03-31", 200.0], ["2025-03-31", 150.0]],
                            "Operating Income": [["2026-03-31", 200.0], ["2025-03-31", 150.0]], "Net Income": [["2026-03-31", 120.0]], "Gross Profit": [["2026-03-31", 400.0]]},
                     "bal": {"Total Assets": [["2026-03-31", 1000.0], ["2025-03-31", 900.0]], "Total Debt": [["2026-03-31", 100.0]], "Stockholders Equity": [["2026-03-31", 600.0]],
                             "Cash And Cash Equivalents": [["2026-03-31", 50.0]], "Total Liabilities Net Minority Interest": [["2026-03-31", 400.0]],
                             "Working Capital": [["2026-03-31", 150.0]], "Retained Earnings": [["2026-03-31", 300.0]]},
                     "cf": {"Free Cash Flow": [["2026-03-31", 80.0]], "Operating Cash Flow": [["2026-03-31", 140.0]]}}, "qtr": {"inc": {}, "bal": {}, "cf": {}}}
    r = af.factors(stmt, {"mcap": 1500.0, "vol1y": 0.015, "ret1y": 0.1, "last": 100.0}, financial=False)
    ev = 1500 + 100 - 50
    assert r["ebit_ev"] == pytest.approx(200 / ev, abs=1e-6) and r["fcf_mcap"] == pytest.approx(80 / 1500, abs=1e-6) and r["book_price"] == pytest.approx(600 / 1500, abs=1e-6)
    assert r["roic"] == pytest.approx(200 * 0.75 / (100 + 600 - 50), abs=1e-6)
    assert r["accrual"] == pytest.approx((120 - 140) / ((1000 + 900) / 2), abs=1e-6) and r["rev_acc_basis"] == "ann"
    assert r["rev_acc"] == pytest.approx((1100 / 1000 - 1) - (1000 / 950 - 1), abs=1e-6) and r["eps_stab"] is None     # no quarterly EPS -> not measured
    assert r["opm_chg"] is not None and r["band"] in ("Low", "Moderate", "High")
    fin = af.factors(stmt, {"mcap": 1500.0, "vol1y": 0.015, "ret1y": 0.1, "last": 100.0}, financial=True)
    assert fin["ebit_ev"] is None and fin["roic"] is None and fin["band"] is None and fin["book_price"] is not None     # financials: book/price, ROE, momentum only


# ---------------------------------------------------------------- filings
def test_hedging_ratio_and_filing_tone_window():
    hedge, conf = {"may", "could"}, {"will", "strong"}
    assert fl.hedging_ratio("we may and could, but will", hedge, conf) == round(2 / 3, 3) and fl.hedging_ratio("nothing here", hedge, conf) is None
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    def ann(sid, days, desc="Press Release", text="Good results"):
        d = (now - timedelta(days=days)).astimezone(timezone(timedelta(hours=5, minutes=30)))
        return {"seq_id": sid, "an_dt": d.strftime("%d-%b-%Y %H:%M:%S"), "desc": desc, "attchmntText": text}
    anns = [ann(1, 1), ann(2, 30), ann(3, 200), ann(4, 2, desc="Trading Window", text="closed")]
    r = fl.filing_nlp(anns, {"1": 0.8, "2": 0.8, "3": 0.8, "4": -0.9}, hedge, conf, now)
    assert r["n"] == 2                                                           # 200 days old and boilerplate are both excluded
    w1, w2 = 0.5 ** (1 / 30), 0.5
    assert r["tone"] == pytest.approx(0.8 * (w1 + w2) / (w1 + w2 + 1), abs=2e-3)
    assert fl.filing_nlp([], {}, hedge, conf, now) is None


def test_nlp_z_is_cross_sectional_and_needs_enough_stocks():
    per = {f"S{i}": {"tone": i / 20, "hedge": None} for i in range(20)}
    z = fl.nlp_z(per)
    assert len(z) == 20 and abs(np.mean(list(z.values()))) < 0.05 and z["S19"] > 1 > -1 > z["S0"]
    assert fl.nlp_z({f"S{i}": {"tone": 0.1} for i in range(5)}) == {}


def test_delivery_trend_and_deal_parsing(tmp_path):
    series = [40.0] * 100 + [60.0] * 20
    assert fl.delivery_trend(series) == pytest.approx((60 / ((40 * 100 + 60 * 20) / 120)) - 1, abs=1e-3)
    assert fl.delivery_trend([40.0] * 30) is None
    txt = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
           "01-OCT-2026,ABC,Abc Ltd,X FUND,BUY,\"100,000\",50.00,-\n01-OCT-2026,ABC,Abc Ltd,Y FUND,SELL,20000,50.50,-\nbad,line\n")
    rows = fl.parse_deals(txt, "bulk")
    assert rows[0] == ("2026-10-01", "ABC", "BUY", 100000.0, 50.0) and len(rows) == 2
    fl.save_deals(tmp_path, rows)
    net = fl.net_deal_value(tmp_path, 30, datetime(2026, 10, 5).date())
    assert net["ABC"] == pytest.approx((100000 * 50 - 20000 * 50.5) / 1e7, abs=0.01)
    assert fl.net_deal_value(tmp_path, 30, datetime(2026, 12, 25).date()) == {}   # older than 30 days: dropped


def test_filings_run_with_a_fake_session_and_scorer(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "CACHE", tmp_path)
    monkeypatch.setattr(fl, "OUT", tmp_path / "alt.json")
    monkeypatch.setattr(fl, "load_delivery", lambda *a, **k: {})
    now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    ist = timezone(timedelta(hours=5, minutes=30))
    def anns(n):
        return [{"seq_id": f"{n}{i}", "an_dt": (now - timedelta(days=i + 1)).astimezone(ist).strftime("%d-%b-%Y %H:%M:%S"), "desc": "Press Release", "attchmntText": f"strong results may {i}"} for i in range(5)]
    class Sess:
        def get_json(self, path, params=None, referer=None, max_tries=2):
            return anns(params["symbol"])
    calls = []
    doc = fl.run([f"S{i}" for i in range(12)], use_nse=True, transcripts=False, now=now, session=Sess(), scorer=lambda t: [calls.append(1) or (0.5 if i % 2 else -0.2) for i, _ in enumerate(t)], http_get=lambda u: None)
    assert sum(1 for v in doc["stocks"].values() if v.get("nlp")) == 12 and len(calls) == 60
    assert all("nlp_z" in v for v in doc["stocks"].values())
    n = len(calls)
    fl.run([f"S{i}" for i in range(12)], use_nse=True, transcripts=False, now=now, session=Sess(), scorer=lambda t: [calls.append(1) or 0.0 for _ in t], http_get=lambda u: None)
    assert len(calls) == n                                                       # every announcement is scored only once (cache)
    class Dead:
        def get_json(self, *a, **k):
            raise RuntimeError("timeout")
    dead = fl.run([f"S{i}" for i in range(12)], use_nse=True, transcripts=False, now=now, session=Dead(), scorer=lambda t: [0.0] * len(t), http_get=lambda u: None)
    assert any("unreachable" in x for x in dead["notes"])                        # says so, instead of pretending


# ---------------------------------------------------------------- data helpers
def test_sample_dates_include_the_last_day_and_step_back_by_five():
    cal = pd.bdate_range("2020-01-01", periods=600)
    s = am.sample_dates(cal)
    assert s[-1] == cal[-1] and (np.diff(cal.get_indexer(s)) == 5).all() and cal.get_loc(s[0]) >= 250


def test_universe_training_rule(tmp_path, monkeypatch):
    stocks = [{"s": "BIG", "board": "Main", "series": "EQ", "n500": True}, {"s": "LIQ", "board": "Main", "series": "EQ", "avgv20": 1e6, "c": 100},
              {"s": "THIN", "board": "Main", "series": "EQ", "avgv20": 1000, "c": 10}, {"s": "SMEX", "board": "SME", "series": "SM", "n500": True},
              {"s": "ETF", "board": "Main", "series": "EQ", "etf": True, "n500": True}]
    (tmp_path / "universe.json").write_text(json.dumps({"stocks": stocks}))
    monkeypatch.setattr(am, "TERM", tmp_path)
    _, train = am.universe()
    assert train == {"BIG", "LIQ"}                                               # NIFTY 500 or >= Rs 5 crore a day; not SME, not ETF, not thin


def test_regime_blend_is_compared_only_where_it_exists():
    O = oos_frame()
    late = O["date"].dt.year >= 2021
    better = O.assign(p_reg=np.where(late, np.clip(O["p"] * 0.9 + O["y"] * 0.1, 0.02, 0.98), np.nan))      # blend only available for the later folds
    ev, iso, use = am.evaluate(better, 10)
    assert use is True and ev["metrics"]["regime"]["tested"] is True and ev["metrics"]["regime"]["rows_compared"] == int(late.sum())
    worse = O.assign(p_reg=np.where(late, np.clip(O["p"] * 0.6 + 0.2, 0.02, 0.98), np.nan))
    ev2, _, use2 = am.evaluate(worse, 10)
    assert use2 is False and ev2["metrics"]["regime"]["brier_regime"] > ev2["metrics"]["regime"]["brier_pooled"]
    none = O.assign(p_reg=np.nan)
    assert am.evaluate(none, 10)[0]["metrics"]["regime"]["tested"] is False
