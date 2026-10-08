"""
ALADIN 2.0 weekly signal study: can ANY combination of the engine's inputs pick next week's winners and losers after costs?

  python -m scripts.aladin2.weekly_study --workers 12      -> data/aladin2/weekly_study.json
Rows: every stock, every Friday signal date of ALADIN 1's walk-forward record (oos_5.pkl: its 5-day probability was produced by models trained only on earlier years), 2013-2026.
Trade: signal at the Friday close, enter at the next open, exit at the open 5 trading days later (a weekly holding period), long only. Cost: the full model (costs.py) at the stock's liquidity decile.
Excess = trade return minus the equal-weight average of the same week's liquid stocks (the market-adjusted benchmark used everywhere else). Universe each week: stocks whose trailing 250-day
average traded value was at least Rs 2 crore (known on the signal date).
Scores compared: ALADIN 1's 5-day probability (alone), 5-day reversal (z of the last week's return), 3-month momentum, a blend of the three, and a walk-forward STACK (ridge regression trained each
year on earlier weeks only). For each: the top and bottom decile of the week, gross and net excess per trade, share positive, month-block bootstrap 95% interval.
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import evaluate as E

ROOT = Path(__file__).resolve().parent.parent.parent
OOS = ROOT.parent / "SAMNIDHY_EDUCATIONAL_DASHBOARD" / "data" / "aladin_cache" / "oos_5.pkl"
H = 5


def _one(args):
    sym, dates, cfgd = args
    px = L.load_prices(sym)
    if px is None or len(px) < 400:
        return None
    px = L.clean_prices(px); F = L.price_features(px); idx = px.index.searchsorted(pd.DatetimeIndex(dates)); ok = (idx < len(px) - H - 2) & (px.index[np.minimum(idx, len(px) - 1)] == pd.DatetimeIndex(dates))
    if not ok.any():
        return None
    i = idx[ok]; o = px["o"].values; v = px["v"].values; c = px["c"].values; entry = o[i + 1]; exit_ = o[i + 1 + H]
    sus = px["suspect_action"].values; bad = np.array([sus[a + 1:a + 2 + H].any() or px["post_break"].values[a] for a in i]); vol_ok = (v[i + 1] > 0) & (v[i + 1 + H] > 0)
    adv = ((px["c"] * px["v"]).rolling(250, min_periods=120).mean() / 1e7).values[i]
    d = pd.DataFrame({"sym": sym, "date": px.index[i], "ret": exit_ / entry - 1, "z5": (F["r5"] / (F["vol20"] * np.sqrt(5))).values[i], "z60": (F["r60"] / (F["vol20"] * np.sqrt(60))).values[i], "vol20": F["vol20"].values[i], "atr_pct": F["atr_pct"].values[i], "adv": adv})
    d = d[~bad & vol_ok & (adv >= 2.0) & np.isfinite(d["ret"].values) & (np.abs(d["ret"].values) < 0.6)]
    return d


def boot(x, months, n=2000, seed=0):
    s = pd.Series(x).groupby(months).agg(["sum", "count"]); rng = np.random.default_rng(seed); idx = rng.integers(0, len(s), size=(n, len(s))); b = s["sum"].values[idx].sum(1) / s["count"].values[idx].sum(1)
    return [round(float(np.percentile(b, 2.5)) * 1e4, 1), round(float(np.percentile(b, 97.5)) * 1e4, 1)]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--out", default="data/aladin2/weekly_study.json"); ap.add_argument("--panel", default=None); a = ap.parse_args()
    cfg = C.load_cfg(); O = pd.read_pickle(OOS); O["date"] = pd.to_datetime(O["date"]); by = {s: g["date"].values for s, g in O.groupby("sym")}
    with ProcessPoolExecutor(a.workers) as ex:
        parts = [d for d in ex.map(_one, [(s, v, None) for s, v in by.items()], chunksize=8) if d is not None]
    D = pd.concat(parts, ignore_index=True).merge(O[["sym", "date", "p"]], on=["sym", "date"]); u = json.load(open(L.TERM / "universe.json"))["stocks"]
    allv = [(s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7 for s in u if s.get("board") == "Main" and not s.get("etf")]; adv_now = {s["s"]: (s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7 for s in u}
    dec = {s: C.adv_decile(adv_now.get(s, 0.5), allv) for s in D["sym"].unique()}; cost = {k: C.round_trip_bps("long", "delivery", k, cfg) / 1e4 for k in range(10)}
    D["dec"] = D["sym"].map(dec); D["cost"] = D["dec"].map(cost); D["net"] = D["ret"] - D["cost"]; D["mkt"] = D.groupby("date")["ret"].transform("mean"); D["ex"] = D["ret"] - D["mkt"]; D["exn"] = D["net"] - D["mkt"]
    D["month"] = D["date"].dt.to_period("M").astype(str); D = D[D.groupby("date")["sym"].transform("size") >= 50].reset_index(drop=True)
    rk = lambda col: D.groupby("date")[col].rank(pct=True)
    D["s_aladin"] = rk("p"); D["s_rev"] = rk("z5") * -1 + 1; D["s_mom"] = rk("z60"); D["s_blend"] = (D["s_aladin"] + D["s_rev"] + D["s_mom"]) / 3
    # walk-forward stack: ridge on the ranked scores + volatility, trained on earlier years only, predicting the next-week excess return
    D["year"] = D["date"].dt.year; D["s_stack"] = np.nan; feats = ["s_aladin", "s_rev", "s_mom"] + ["vol20", "atr_pct"]
    for y in sorted(D["year"].unique()):
        tr = D[D["date"] < pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=14)]; te = D["year"] == y
        if len(tr) < 20000:
            continue
        X = tr[feats].values; mu, sd = X.mean(0), X.std(0) + 1e-9; Z = (X - mu) / sd; yv = tr["ex"].values; w = np.linalg.solve(Z.T @ Z + 1000 * np.eye(len(feats)), Z.T @ (yv - yv.mean()))
        D.loc[te, "s_stack"] = ((D.loc[te, feats].values - mu) / sd) @ w
    D["s_stack"] = D.groupby("date")["s_stack"].rank(pct=True); out = {"rows": int(len(D)), "weeks": int(D["date"].nunique()), "stocks": int(D["sym"].nunique()), "from": str(D["date"].min().date()), "to": str(D["date"].max().date()),
                                                                     "universe_mean_weekly_return_bps": round(float(D["ret"].mean() * 1e4), 1), "avg_round_trip_cost_bps": round(float(D["cost"].mean() * 1e4), 1), "scores": {}}
    for name in ("s_aladin", "s_rev", "s_mom", "s_blend", "s_stack"):
        d = D[D[name].notna()]; r = {}
        for lab, m in (("top_decile", d[name] >= 0.9), ("bottom_decile", d[name] <= 0.1), ("top_quintile", d[name] >= 0.8)):
            g = d[m]
            r[lab] = {"trades": int(len(g)), "gross_excess_bps": round(float(g["ex"].mean() * 1e4), 1), "net_excess_bps": round(float(g["exn"].mean() * 1e4), 1), "net_excess_ci95_bps": boot(g["exn"].values, g["month"].values), "gross_excess_ci95_bps": boot(g["ex"].values, g["month"].values),
                      "share_beating_market": round(float((g["ex"] > 0).mean()), 4), "share_closing_up": round(float((g["ret"] > 0).mean()), 4), "net_return_bps": round(float(g["net"].mean() * 1e4), 1)}
        r["spread_top_minus_bottom_gross_bps"] = round(float((d[d[name] >= 0.9]["ex"].mean() - d[d[name] <= 0.1]["ex"].mean()) * 1e4), 1); out["scores"][name] = r
    def rec(mask, side):
        g = D[mask]; yrs = g.groupby("year")["exn" if side == "buy" else "ex"].mean() * 1e4
        r = {"n": int(len(g)), "gross_excess_bps": round(float(g["ex"].mean() * 1e4), 1), "gross_excess_ci95_bps": boot(g["ex"].values, g["month"].values), "share_closing_up": round(float((g["ret"] > 0).mean()), 4), "avg_round_trip_cost_bps": round(float(g["cost"].mean() * 1e4), 1)}
        if side == "buy":
            r.update({"net_bps": round(float(g["exn"].mean() * 1e4), 1), "net_ci95_bps": boot(g["exn"].values, g["month"].values), "years_positive_net": f"{int((yrs > 0).sum())}/{len(yrs)}"})
        else:
            r.update({"years_below_market": f"{int((yrs < 0).sum())}/{len(yrs)}"})
        return r
    out["record"] = {"buy": rec(D["s_aladin"] >= 0.99, "buy"), "sell": rec(D["s_aladin"] <= 0.05, "sell")}
    out["thresholds_looked_at"] = {"buy_top_pct": {str(q): {"net_bps": round(float(D[D["s_aladin"] >= q]["exn"].mean() * 1e4), 1), "gross_bps": round(float(D[D["s_aladin"] >= q]["ex"].mean() * 1e4), 1), "n": int((D["s_aladin"] >= q).sum())} for q in (0.9, 0.95, 0.98, 0.99)},
                                   "sell_bottom_pct": {str(q): {"gross_bps": round(float(D[D["s_aladin"] <= q]["ex"].mean() * 1e4), 1), "n": int((D["s_aladin"] <= q).sum())} for q in (0.1, 0.05, 0.02, 0.01)},
                                   "note": "four thresholds were looked at on each side; the BUY side's 1% and the SELL side's 5% were chosen. With four looks, the BUY interval (+6 to +47) is the weaker claim."}
    # ---- chances: how often each rank bucket closed higher / beat the market that week, with month-block 95% intervals, and a walk-forward check that the numbers are honest out of sample
    edges = [0, 0.01, 0.02, 0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 0.90, 0.95, 0.98, 0.99, 1.0001]
    D["bin"] = pd.cut(D["s_aladin"], edges, right=False, labels=False)
    def pci(ind, months, n=1500):
        s_ = pd.Series(ind.astype(float)).groupby(months.values).agg(["sum", "count"]); rng = np.random.default_rng(0); i_ = rng.integers(0, len(s_), size=(n, len(s_))); b_ = s_["sum"].values[i_].sum(1) / s_["count"].values[i_].sum(1)
        return [round(float(np.percentile(b_, 2.5)), 4), round(float(np.percentile(b_, 97.5)), 4)]
    curve = []
    for k in range(len(edges) - 1):
        g = D[D["bin"] == k]
        if len(g) < 200:
            continue
        curve.append({"from": edges[k], "to": min(edges[k + 1], 1.0), "n": int(len(g)), "p_up": round(float((g["ret"] > 0).mean()), 4), "p_up_ci95": pci((g["ret"] > 0).values, g["month"]), "p_beat_market": round(float((g["ex"] > 0).mean()), 4),
                      "p_beat_market_ci95": pci((g["ex"] > 0).values, g["month"]), "mean_excess_bps": round(float(g["ex"].mean() * 1e4), 1)})
    out["probability_curve"] = curve; out["base_rates"] = {"p_up": round(float((D["ret"] > 0).mean()), 4), "p_beat_market": round(float((D["ex"] > 0).mean()), 4)}
    # walk-forward: probabilities fitted on earlier years only, scored on the next year (Brier vs the base rate of the earlier years, and expected calibration error)
    pu_hat, pb_hat = np.full(len(D), np.nan), np.full(len(D), np.nan)
    for y in sorted(D["year"].unique())[2:]:
        tr = D[D["year"] < y]; te = (D["year"] == y).values
        if len(tr) < 20000:
            continue
        tab_u = tr.groupby("bin").apply(lambda g: (g["ret"] > 0).mean()); tab_b = tr.groupby("bin").apply(lambda g: (g["ex"] > 0).mean())
        pu_hat[te] = D.loc[te, "bin"].map(tab_u).values; pb_hat[te] = D.loc[te, "bin"].map(tab_b).values
    ok = ~np.isnan(pu_hat); yu = (D["ret"] > 0).values[ok].astype(float); yb = (D["ex"] > 0).values[ok].astype(float)
    def ece(p, y, bins=10):
        o = np.argsort(p); e_ = 0.0
        for c in np.array_split(o, bins):
            e_ += len(c) / len(p) * abs(p[c].mean() - y[c].mean())
        return round(float(e_), 4)
    out["probability_check"] = {"scored_stock_weeks": int(ok.sum()), "from_year": int(D.loc[ok, "year"].min()), "closes_higher": {"brier": round(float(np.mean((pu_hat[ok] - yu) ** 2)), 5), "brier_base_rate": round(float(np.mean((yu.mean() - yu) ** 2)), 5), "ece": ece(pu_hat[ok], yu)},
                                "beats_market": {"brier": round(float(np.mean((pb_hat[ok] - yb) ** 2)), 5), "brier_base_rate": round(float(np.mean((yb.mean() - yb) ** 2)), 5), "ece": ece(pb_hat[ok], yb)}}
    # ---- chart data for the Bot page
    dec = pd.cut(D["s_aladin"], [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001], right=False, labels=False)
    out["charts"] = {"by_decile": [{"decile": int(k) + 1, "n": int(len(g)), "gross_excess_bps": round(float(g["ex"].mean() * 1e4), 1), "net_excess_bps": round(float(g["exn"].mean() * 1e4), 1), "share_closing_up": round(float((g["ret"] > 0).mean()), 4)} for k, g in D.groupby(dec)],
                     "by_year": [{"year": int(y), "bull_net_bps": round(float(g[g["s_aladin"] >= 0.99]["exn"].mean() * 1e4), 1), "bear_gross_bps": round(float(g[g["s_aladin"] <= 0.05]["ex"].mean() * 1e4), 1)} for y, g in D.groupby("year")]}
    wk = D.groupby("date").apply(lambda g: pd.Series({"bull_net": g[g["s_aladin"] >= 0.99]["net"].mean(), "bull_ex_net": g[g["s_aladin"] >= 0.99]["exn"].mean(), "bear_ex": g[g["s_aladin"] <= 0.05]["ex"].mean(), "mkt": g["ret"].mean()})).sort_index()
    bull_cum = wk["bull_ex_net"].fillna(0).cumsum(); avoid = (-wk["bear_ex"].fillna(0)).cumsum()
    out["charts"]["weekly_curves"] = {"dates": [str(d.date()) for d in wk.index], "bull_cumulative_net_excess": [round(float(x), 4) for x in bull_cum], "bear_cumulative_underperformance": [round(float(x), 4) for x in avoid]}
    by_year = {int(y): round(float(g[g["s_aladin"] >= 0.9]["exn"].mean() * 1e4), 1) for y, g in D.groupby("year")}; out["aladin_top_decile_net_excess_by_year_bps"] = by_year
    if a.panel:
        D.to_pickle(a.panel)
    json.dump(out, open(a.out, "w"), indent=1); print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
