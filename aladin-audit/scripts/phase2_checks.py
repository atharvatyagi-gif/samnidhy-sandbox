"""
ALADIN audit, phase 2: the diagnosis numbers. Read-only: nothing in ALADIN is changed or retrained.

  python aladin-audit/scripts/phase2_checks.py --main <path of the main working copy>   -> aladin-audit/phase2/results.json + charts

Inputs (all already produced by ALADIN's own jobs):
  data/aladin_cache/oos_{5,10,20}.pkl   ALADIN 1's walk-forward predictions on unseen years (raw score p, regime blend p_reg, outcome y)
  data/aladin/history/<date>.json       ALADIN 1's live nightly snapshots (from 2026-09-29): per stock [F, S, T, p10, p5, p20, I]
  data/aladin/latest.json               today's published numbers
  data/terminal/daily + archive         split-adjusted daily prices (to 2026-10-05 on this PC), data/terminal/bhav NSE end-of-day files (to 2026-11-06)
  Yahoo (^NSEI, ^CRSLDX, ^INDIAVIX, INR=X, BZ=F)   market state; fetched once, not stored in the repository
Costs: a 37 bps round trip for delivery trades (the weekly study's measured average, data/config/aladin2.json cost model).
"""
import argparse
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

AUDIT = Path(__file__).resolve().parent.parent
OUT = AUDIT / "phase2"
COST = 0.0037
H = [5, 10, 20]
USE_REG = {5: False, 10: True, 20: False}                 # as published in latest.json (regime blend used only at 10 days)
EVENTS = {
    "election result": ["2014-05-16", "2019-05-23", "2024-06-04"],
    "Union Budget": ["2013-02-28", "2014-07-10", "2015-02-28", "2016-02-29", "2017-02-01", "2018-02-01", "2019-02-01", "2019-07-05", "2020-02-01",
                     "2021-02-01", "2022-02-01", "2023-02-01", "2024-02-01", "2024-07-23", "2025-02-01", "2026-02-01"],
    "global shock": ["2016-06-24", "2016-11-09", "2020-03-23", "2022-02-24", "2023-03-10", "2024-08-05"],
}


def load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def nested_calibrate(O, use_reg):
    """The published honest scheme: test year Y calibrated (isotonic) on unseen years before Y only."""
    raw = O["p_reg"].where(O["p_reg"].notna(), O["p"]) if use_reg else O["p"]
    O = O.assign(raw=raw.values, year=O["date"].dt.year.values, pc=np.nan)
    for yr in sorted(O["year"].unique())[2:]:
        prior, te = O[O["year"] < yr], O["year"] == yr
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98).fit(prior["raw"].values, prior["y"].values)
        O.loc[te, "pc"] = iso.predict(O.loc[te, "raw"].values)
    live = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98).fit(O["raw"].values, O["y"].values)
    return O[O["pc"].notna()].reset_index(drop=True), live


def price_panel(main, syms):
    """Split-adjusted closes (daily spliced onto archive, as aladin_model.load_prices) for the symbols."""
    import sys
    sys.path.insert(0, str(main / "scripts"))
    import aladin_model as am
    am.TERM = main / "data" / "terminal"
    cols = {}
    for s in syms:
        df = am.load_prices(s, min_bars=60)
        if df is not None:
            cols[s] = df["c"]
    return pd.DataFrame(cols).sort_index()


def fwd_returns(O, px, h):
    """Close-to-close h-trading-day return from each row's date (the model's own target), from the price panel."""
    idx = px.index
    out = np.full(len(O), np.nan)
    pos = idx.searchsorted(O["date"].values)
    for k, (i, s) in enumerate(zip(pos, O["sym"].values)):
        if s in px.columns and i + h < len(idx) and idx[i] == O["date"].values[k]:
            a, b = px[s].iat[i], px[s].iat[i + h]
            if a > 0 and b > 0:
                out[k] = b / a - 1
    return out


def max_drawdown(r):
    eq = np.cumprod(1 + np.asarray(r))
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min()), float(eq[-1] - 1)


def scorecard(O, sel, h, label, rng):
    """Long-only, equal weight, enter at the signal date's close, hold h days, 37 bps round trip. Non-overlapping dates only for the
    equity curve (every (h/5)-th sample date, since the record is sampled every 5 trading days)."""
    D = O[O["ret"].notna()]
    dates = sorted(D["date"].unique())
    step = max(1, h // 5)
    keep = set(dates[::step])
    S = D[sel.reindex(D.index).fillna(False)]
    per_trade = S["ret"] - COST
    bydate = S[S["date"].isin(keep)].groupby("date")["ret"].mean() - COST
    rnd = []
    for d, g in D[D["date"].isin(keep)].groupby("date"):
        k = int((S["date"] == d).sum())
        if k:
            rnd.append((d, g["ret"].sample(n=min(k, len(g)), random_state=rng).mean() - COST))
    rnd = pd.Series(dict(rnd)).sort_index()
    allm = D[D["date"].isin(keep)].groupby("date")["ret"].mean()
    eq_dd, eq_tot = max_drawdown(bydate.fillna(0).values) if len(bydate) else (None, None)
    rd_dd, rd_tot = max_drawdown(rnd.values) if len(rnd) else (None, None)
    bh_dd, bh_tot = max_drawdown(allm.values)
    return {"label": label, "horizon_d": h, "trades": int(len(S)), "long_share": round(float(len(S) / max(1, len(D))), 4),
            "hit_rate_up": round(float((S["ret"] > 0).mean()), 4) if len(S) else None, "hit_rate_after_costs": round(float((per_trade > 0).mean()), 4) if len(S) else None,
            "net_per_trade_bps": round(float(per_trade.mean() * 1e4), 1) if len(S) else None,
            "random_same_count_net_bps": round(float(rnd.mean() * 1e4), 1) if len(rnd) else None,
            "equal_weight_all_stocks_gross_bps": round(float(allm.mean() * 1e4), 1),
            "worst_drawdown_signal_curve": None if eq_dd is None else round(eq_dd, 3), "total_signal_curve": None if eq_tot is None else round(eq_tot, 3),
            "worst_drawdown_random": None if rd_dd is None else round(rd_dd, 3), "worst_drawdown_all_stocks": round(bh_dd, 3), "total_all_stocks_gross": round(bh_tot, 3),
            "periods_in_curve": int(len(bydate)), "from": str(pd.Timestamp(min(dates)).date()), "to": str(pd.Timestamp(max(dates)).date())}


def market_series():
    import yfinance as yf
    out = {}
    for k, t in {"nifty50": "^NSEI", "nifty500": "^CRSLDX", "vix": "^INDIAVIX", "usdinr": "INR=X", "brent": "BZ=F"}.items():
        try:
            s = yf.download(t, start="2012-01-01", progress=False, auto_adjust=False)["Close"]
            s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
            out[k] = s.dropna()
        except Exception as e:  # noqa: BLE001 - reported as not measured
            print("market series", k, "failed:", e)
    return out


def bhav_closes(main):
    rows = []
    for f in sorted((main / "data" / "terminal" / "bhav").glob("*.csv.gz")):
        df = pd.read_csv(f)
        cols = {c.lower(): c for c in df.columns}
        sym = cols.get("symbol") or cols.get("tckrsymb"); ser = cols.get("series") or cols.get("sctysrs"); cl = cols.get("close") or cols.get("close_price") or cols.get("clspric")
        if not (sym and cl):
            continue
        d = df[df[ser].astype(str).str.strip().isin(["EQ", "BE", "BZ"])] if ser else df
        rows.append(pd.Series(d[cl].values, index=d[sym].astype(str).str.strip().values, name=pd.Timestamp(f.name[:10])))
    return pd.DataFrame(rows).sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True)
    a = ap.parse_args()
    main = Path(a.main)
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    R = {"cost_round_trip_bps": COST * 1e4}
    latest = load(AUDIT.parent / "data" / "aladin" / "latest.json")
    S = latest["stocks"]

    # ---------------- 2.1 bug checks on today's file
    p10 = np.array([v["t"]["p"]["10"] for v in S.values()]); c10 = np.array([v["comb"]["10"][0] for v in S.values() if v.get("comb")])
    R["today"] = {"as_of": latest["as_of"], "stocks": len(S),
                  "missing": {"F": int(sum(1 for v in S.values() if not (v.get("f") or {}).get("sc") and (v.get("f") or {}).get("sc") != 0)),
                              "S": int(sum(1 for v in S.values() if (v.get("cov") or {}).get("s") is None)),
                              "I": int(sum(1 for v in S.values() if ((v.get("x") or {}).get("i")) is None))},
                  "p10": {"max": float(p10.max()), "median": float(np.median(p10)), "share_ge_50": float((p10 >= 0.5).mean())},
                  "colour_counts_10d": {"home_page_green_ge_50": int((p10 >= 0.5).sum()), "home_page_red": int((p10 < 0.5).sum()),
                                        "terminal_green_ge_55": int((c10 >= 0.55).sum()), "terminal_grey": int(((c10 > 0.45) & (c10 < 0.55)).sum()), "terminal_red_le_45": int((c10 <= 0.45).sum())}}
    best = lambda p: 1 / (1 + math.exp(-(math.log(p / (1 - p)) + 0.20 + 0.12)))                  # F = +100 and S = +100: the most the other fronts can add
    R["today"]["known_good_fill"] = {"max_tech_p10": float(p10.max()), "with_F_and_S_at_plus100": round(best(float(p10.max())), 4),
                                     "median_with_F_and_S_at_plus100": round(best(float(np.median(p10))), 4)}
    drv = [d for v in S.values() for d in (v["t"].get("drv") or [])]
    top = pd.DataFrame([(v["t"]["drv"][0][0], abs(v["t"]["drv"][0][1])) for v in S.values() if v["t"].get("drv")], columns=["name", "size"])
    R["today"]["top_reason_counts"] = top["name"].value_counts().head(6).to_dict()
    dom = [d[1] for d in drv if d[0] == "dom"]
    R["today"]["dom_contribution"] = {"stocks_with_dom_in_top5": len(dom), "mean": round(float(np.mean(dom)), 4) if dom else None}

    # ---------------- ALADIN 1 unseen-year record
    O = {}
    cache = OUT / "_record_cache.pkl"                     # the slow step (prices for ~2,000 stocks); not committed
    if cache.exists():
        O = pd.read_pickle(cache)
    else:
        for h in H:
            raw = pd.read_pickle(main / "data" / "aladin_cache" / f"oos_{h}.pkl")
            O[h], _ = nested_calibrate(raw, USE_REG[h])
        px = price_panel(main, sorted(set(O[10]["sym"])))
        for h in H:
            O[h]["ret"] = fwd_returns(O[h], px, h)
        pd.to_pickle(O, cache)
    R["record"] = {h: {"rows": int(len(O[h])), "from": str(O[h]["date"].min().date()), "to": str(O[h]["date"].max().date()), "rows_with_return": int(O[h]["ret"].notna().sum())} for h in H}

    # 2.2.1 target balance by year
    R["base_rate_by_year"] = {h: O[h].groupby("year")["y"].mean().round(3).to_dict() for h in H}

    # 2.2.2 score level through time (monthly median of the calibrated 10-day probability vs the share that actually went up)
    m = O[10].assign(month=O[10]["date"].dt.to_period("M").astype(str)).groupby("month").agg(pred_median=("pc", "median"), pred_share_ge50=("pc", lambda s: (s >= 0.5).mean()), actual_up=("y", "mean"), n=("y", "size"))
    R["level_by_month_10d"] = m.round(3).reset_index().to_dict("records")
    daily = O[10].groupby("date").agg(pred=("pc", "mean"), actual=("y", "mean"))
    R["level_tracking_10d"] = {"corr_daily_mean_pred_vs_actual": round(float(daily["pred"].corr(daily["actual"])), 3), "dates": int(len(daily))}
    snaps = {}
    for f in sorted((AUDIT.parent / "data" / "aladin" / "history").glob("*.json")):
        j = load(f)
        st = j.get("s") or j.get("stocks") or {}
        vals = [r[3] for r in st.values() if isinstance(r, list) and len(r) > 3 and r[3] is not None]
        if vals:
            snaps[f.stem] = {"p10": vals, "p5": [r[4] for r in st.values() if isinstance(r, list) and r[4] is not None], "p20": [r[5] for r in st.values() if isinstance(r, list) and r[5] is not None], "raw": st}
    ago = {}
    for label, d in (("12 months ago", "2025-11-06"), ("6 months ago", "2026-05-06"), ("3 months ago", "2026-08-06")):
        near = O[10].loc[(O[10]["date"] - pd.Timestamp(d)).abs().idxmin(), "date"]
        v = O[10].loc[O[10]["date"] == near, "pc"]
        ago[label] = {"date": str(near.date()), "median": round(float(v.median()), 3), "share_ge_50": round(float((v >= 0.5).mean()), 3), "values": v.round(4).tolist()}
    ago["today"] = {"date": latest["as_of"], "median": round(float(np.median(p10)), 3), "share_ge_50": round(float((p10 >= 0.5).mean()), 3), "values": p10.round(4).tolist()}
    R["histograms_10d"] = {k: {kk: vv for kk, vv in v.items() if kk != "values"} for k, v in ago.items()}

    # 2.2.3 calibration (whole record and the last two years)
    def calib(D):
        D = D.assign(b=pd.cut(D["pc"], [0, 0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.60, 1]))
        return [{"bucket": str(k), "pred": round(float(g["pc"].mean()), 3), "actual": round(float(g["y"].mean()), 3), "n": int(len(g))} for k, g in D.groupby("b", observed=True) if len(g)]
    R["calibration_10d"] = {"all_years": calib(O[10]), "2025_2026": calib(O[10][O[10]["year"] >= 2025])}

    # 2.2.4 threshold sweep (10-day ALADIN 1)
    sw = []
    for t in [0.45, 0.48, 0.50, 0.52, 0.55, 0.58, 0.60]:
        sel = O[10]["pc"] >= t
        D = O[10][sel & O[10]["ret"].notna()]
        sw.append({"threshold": t, "share_long": round(float(sel.mean()), 4), "trades": int(len(D)), "went_up": round(float((D["ret"] > 0).mean()), 4) if len(D) else None,
                   "net_per_trade_bps": round(float((D["ret"] - COST).mean() * 1e4), 1) if len(D) else None})
    R["threshold_sweep_10d"] = sw
    rk = O[10].groupby("date")["pc"].rank(pct=True)
    sw2 = []
    for q in [0.99, 0.95, 0.90, 0.80, 0.70, 0.50]:
        sel = rk >= q
        D = O[10][sel & O[10]["ret"].notna()]
        sw2.append({"top_share": round(1 - q, 2), "trades": int(len(D)), "went_up": round(float((D["ret"] > 0).mean()), 4), "net_per_trade_bps": round(float((D["ret"] - COST).mean() * 1e4), 1)})
    R["rank_sweep_10d"] = sw2

    # 2.2.5 drift: today's raw scores vs the record (population stability index on the calibrated values)
    def psi(ref, cur, bins=10):
        q = np.quantile(ref, np.linspace(0, 1, bins + 1)); q[0], q[-1] = -np.inf, np.inf
        a = np.histogram(ref, q)[0] / len(ref) + 1e-6; b = np.histogram(cur, q)[0] / len(cur) + 1e-6
        return float(np.sum((b - a) * np.log(b / a)))
    R["drift_psi_10d"] = {"today_vs_2013_2024": round(psi(O[10].loc[O[10]["year"] <= 2024, "pc"].values, p10), 3),
                          "today_vs_2025_2026": round(psi(O[10].loc[O[10]["year"] >= 2025, "pc"].values, p10), 3), "rule_of_thumb": "< 0.1 stable, 0.1-0.25 moving, > 0.25 shifted"}

    # 2.2.6 skill through time (unseen years only; training AUC is not stored, see the report)
    R["auc_by_year_10d"] = {int(y): round(float(roc_auc_score(g["y"], g["pc"])), 3) for y, g in O[10].groupby("year") if g["y"].nunique() > 1}
    R["auc_within_day_10d"] = round(float(O[10].groupby("date").apply(lambda g: roc_auc_score(g["y"], g["pc"]) if g["y"].nunique() > 1 else np.nan).mean()), 3)

    # ---------------- the calendar inputs (day of month, month)
    D = O[10].assign(dom=O[10]["date"].dt.day, moy=O[10]["date"].dt.month)
    by = D.groupby(pd.cut(D["dom"], [0, 5, 10, 15, 20, 25, 31])).agg(pred=("pc", "mean"), actual=("y", "mean"), n=("y", "size"), dates=("date", "nunique"))
    R["calendar_10d"] = {"by_day_of_month": [{"days": str(k), "pred": round(float(r.pred), 3), "actual": round(float(r.actual), 3), "n": int(r.n), "dates": int(r.dates)} for k, r in by.iterrows()]}
    halves = {}
    for name, part in (("2013_2019", D[D["year"] <= 2019]), ("2020_2026", D[D["year"] >= 2020])):
        g = part.groupby(pd.cut(part["dom"], [0, 5, 10, 15, 20, 25, 31]))["y"].mean()
        halves[name] = {str(k): round(float(v), 3) for k, v in g.items()}
    R["calendar_10d"]["actual_by_half"] = halves
    dd = D.groupby("date").agg(actual=("y", "mean"), dom=("dom", "first"))
    R["calendar_10d"]["note"] = "Calendar inputs are identical for every stock on a date: they move every stock's probability together and cannot change the order of stocks."
    R["calendar_10d"]["dates_in_days_1_10"] = int((dd["dom"] <= 10).sum())

    # ---------------- live check of ALADIN 1 (snapshots since 2026-09-29)
    bc = bhav_closes(main)
    live = []
    for d, s in snaps.items():
        t = pd.Timestamp(d)
        if t not in bc.index:
            continue
        i = bc.index.get_loc(t)
        for h, k in ((5, 4), (10, 3), (20, 5)):
            if i + h >= len(bc):
                continue
            r = bc.iloc[i + h] / bc.iloc[i] - 1
            ps, ys = [], []
            for sym, row in s["raw"].items():
                if isinstance(row, list) and len(row) > k and row[k] is not None and sym in r.index and pd.notna(r[sym]):
                    ps.append(row[k]); ys.append(float(r[sym] > 0))
            if ps:
                live.append({"date": d, "h": h, "n": len(ps), "pred_mean": round(float(np.mean(ps)), 3), "actual_up": round(float(np.mean(ys)), 3)})
    R["live_check"] = live

    # ---------------- 2.3 market state
    ms = market_series()
    st = {}
    for k in ("nifty50", "nifty500"):
        s = ms.get(k)
        if s is not None and len(s) > 200:
            st[k] = {"as_of": str(s.index[-1].date()), "close": round(float(s.iloc[-1]), 1), "vs_50d": round(float(s.iloc[-1] / s.rolling(50).mean().iloc[-1] - 1), 4),
                     "vs_200d": round(float(s.iloc[-1] / s.rolling(200).mean().iloc[-1] - 1), 4), "3m": round(float(s.iloc[-1] / s.iloc[-64] - 1), 4), "1y": round(float(s.iloc[-1] / s.iloc[-251] - 1), 4)}
    for k in ("vix", "usdinr", "brent"):
        s = ms.get(k)
        if s is not None and len(s) > 60:
            st[k] = {"as_of": str(s.index[-1].date()), "last": round(float(s.iloc[-1]), 2), "1m_change": round(float(s.iloc[-1] / s.iloc[-22] - 1), 4), "3m_change": round(float(s.iloc[-1] / s.iloc[-64] - 1), 4),
                     "pct_rank_5y": round(float((s.iloc[-1250:] < s.iloc[-1]).mean()), 3)}
    uni = load(main / "data" / "terminal" / "universe.json")
    n500 = [x["s"] for x in uni["stocks"] if x.get("n500")]
    b = bc[[c for c in n500 if c in bc.columns]]
    above200 = (b.iloc[-1] > b.rolling(200).mean().iloc[-1]); above50 = (b.iloc[-1] > b.rolling(50).mean().iloc[-1])
    uptrend = (b.iloc[-1] > b.rolling(50).mean().iloc[-1]) & (b.rolling(50).mean().iloc[-1] > b.rolling(200).mean().iloc[-1])
    st["breadth_nifty500"] = {"as_of": str(bc.index[-1].date()), "stocks": int(b.shape[1]), "above_200d": round(float(above200.mean()), 3), "above_50d": round(float(above50.mean()), 3),
                              "uptrend_50_over_200": round(float(uptrend.mean()), 3), "note": "NSE closes, not split-adjusted (a split inside the window can misplace a stock)"}
    fii = load(main / "data" / "institutional" / "fii_dii.json")
    if fii:
        days = fii.get("days") or fii.get("history") or fii
        if isinstance(days, list) and days:
            last = days[-20:]
            st["fii_dii_last_20_days"] = {"from": str(last[0].get("date")), "to": str(last[-1].get("date")), "fii_net_cr": round(sum(((x.get("fii") or {}).get("net_cr") or 0) for x in last), 0),
                                          "dii_net_cr": round(sum(((x.get("dii") or {}).get("net_cr") or 0) for x in last), 0), "days": len(last)}
    R["market_state"] = st
    R["neutral_rule"] = {"nifty500_share_in_uptrend": st["breadth_nifty500"]["uptrend_50_over_200"], "aladin1_share_p10_ge_50_today": round(float((p10 >= 0.5).mean()), 3),
                         "aladin1_share_p5_ge_50_today": round(float((np.array([v["t"]["p"]["5"] for v in S.values()]) >= 0.5).mean()), 3)}

    # ---------------- 2.4 events
    ev = []
    nifty, vix = ms.get("nifty50"), ms.get("vix")
    for kind, ds in EVENTS.items():
        for d in ds:
            t = pd.Timestamp(d)
            near = O[10][(O[10]["date"] >= t - pd.Timedelta(days=7)) & (O[10]["date"] <= t + pd.Timedelta(days=7))]
            row = {"kind": kind, "date": d, "aladin_mean_p10": round(float(near["pc"].mean()), 3) if len(near) else None, "actual_up_10d": round(float(near["y"].mean()), 3) if len(near) else None,
                   "auc_near": round(float(roc_auc_score(near["y"], near["pc"])), 3) if len(near) and near["y"].nunique() > 1 else None}
            if nifty is not None:
                i = nifty.index.searchsorted(t)
                if 5 <= i < len(nifty) - 5:
                    row["nifty_5d_after"] = round(float(nifty.iloc[i + 5] / nifty.iloc[i - 1] - 1), 4)
            if vix is not None:
                i = vix.index.searchsorted(t)
                if 5 <= i < len(vix) - 5:
                    row["vix_change_5d"] = round(float(vix.iloc[i + 5] / vix.iloc[i - 1] - 1), 4)
            ev.append(row)
    R["events"] = ev
    near_mask = pd.Series(False, index=O[10].index)
    for ds in EVENTS.values():
        for d in ds:
            t = pd.Timestamp(d)
            near_mask |= (O[10]["date"] >= t - pd.Timedelta(days=10)) & (O[10]["date"] <= t + pd.Timedelta(days=10))
    A, Bn = O[10][near_mask], O[10][~near_mask]
    R["events_skill"] = {"auc_near_events": round(float(roc_auc_score(A["y"], A["pc"])), 3), "rows_near": int(len(A)), "auc_other_days": round(float(roc_auc_score(Bn["y"], Bn["pc"])), 3), "rows_other": int(len(Bn)),
                         "within_day_auc_near": round(float(A.groupby("date").apply(lambda g: roc_auc_score(g["y"], g["pc"]) if g["y"].nunique() > 1 else np.nan).mean()), 3),
                         "within_day_auc_other": round(float(Bn.groupby("date").apply(lambda g: roc_auc_score(g["y"], g["pc"]) if g["y"].nunique() > 1 else np.nan).mean()), 3)}

    # ---------------- 2.5 scorecard
    sc = []
    for h in H:
        sc.append(scorecard(O[h], O[h]["pc"] >= 0.55, h, f"ALADIN 1, {h} days: green (P >= 55%)", rng))
        rk = O[h].groupby("date")["pc"].rank(pct=True)
        sc.append(scorecard(O[h], rk >= 0.90, h, f"ALADIN 1, {h} days: top tenth by rank", rng))
    R["scorecard"] = sc
    Path(OUT / "results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")

    # ---------------- charts
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 4))
    for k, v in ago.items():
        ax.hist(v["values"], bins=np.linspace(0.38, 0.62, 49), histtype="step", linewidth=1.6, label=f"{k} ({v['date']}): median {v['median']:.1%}")
    ax.axvline(0.5, color="grey", linestyle="--"); ax.set_xlabel("ALADIN 1 calibrated chance of going up in 10 trading days"); ax.set_ylabel("stocks"); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "hist_10d.png", dpi=130); plt.close(fig)
    mm = m.reset_index()
    fig, ax = plt.subplots(figsize=(10, 4))
    x = pd.to_datetime(mm["month"])
    ax.plot(x, mm["pred_median"], label="ALADIN 1 median prediction (10 days)"); ax.plot(x, mm["actual_up"], label="share of stocks that actually went up", alpha=0.8)
    ax.axhline(0.5, color="grey", linestyle="--"); ax.set_ylim(0.25, 0.75); ax.legend(fontsize=8); ax.set_title("Prediction level vs what happened, by month (unseen years)")
    fig.tight_layout(); fig.savefig(OUT / "level_by_month.png", dpi=130); plt.close(fig)
    cb = R["calibration_10d"]
    fig, ax = plt.subplots(figsize=(5, 5))
    for k, mk in (("all_years", "o-"), ("2025_2026", "s--")):
        ax.plot([r["pred"] for r in cb[k]], [r["actual"] for r in cb[k]], mk, label=k.replace("_", " to "))
    ax.plot([0.3, 0.7], [0.3, 0.7], color="grey", linestyle=":"); ax.set_xlabel("said"); ax.set_ylabel("happened"); ax.set_title("Calibration, 10 days"); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "calibration_10d.png", dpi=130); plt.close(fig)
    print(json.dumps({k: R[k] for k in ("today", "histograms_10d", "level_tracking_10d", "drift_psi_10d", "calendar_10d", "neutral_rule", "events_skill")}, indent=1, default=str))


if __name__ == "__main__":
    main()
