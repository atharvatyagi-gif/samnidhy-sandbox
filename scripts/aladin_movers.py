"""
ALADIN movers: which stocks will move in the next 5 trading days, how far, and which way.

  python scripts/aladin_movers.py --study     -> data/aladin_movers/study.json   (walk-forward test 2016-2026; the pre-declared verdict)
  python scripts/aladin_movers.py --live      -> data/aladin_movers/latest.json  (this week's forecast for every covered stock, only with a model that passed)

Method, written down BEFORE any result was seen (2026-10-13, owner: "size + direction, ranked; next 5 days"):
  ROWS     every Friday close (the last trading day of each week) from 2012, every stock in the price archive with at least 260 bars of history, an average
           traded value of Rs 5 crore a day over 20 days, a price above Rs 20, and no unadjusted corporate action in the last 250 bars. Nothing after the Friday close is used.
  TARGET   r5 = close 5 trading days later / Friday close - 1.
           BIG = |r5| > 5% (a big move, either way)        UP = r5 > 0        SIZE = |r5|
  INPUTS   ALADIN's causal price/volume features (aladin2/data_lake.py: returns over 1-250 days, 12-1 momentum, distance from 20/50/200-day averages, ATR, 20/60-day
           volatility and their ratio, RSI 2 and 14, Bollinger position and width, 52-week high/low distance, 20-day breakout, overnight and intraday drift, volume
           surge, traded value, range, NR7), the macro series it attaches (India VIX, USD/INR, Brent, S&P 500, Nikkei, US 10-year), delivery %, plus:
           beta and stock-specific volatility against the Nifty 50 (120 days), the Nifty's own 20-day return, volatility and distance from its 200-day average,
           the stock's sector's 20-day return, the share of the past year's weeks in which the stock moved more than 5%, and each input's rank among that Friday's stocks.
  MODELS   LightGBM (fixed settings, never tuned on the test years): a classifier for BIG, a classifier for UP, a regressor for SIZE. Walk-forward by calendar year:
           the model for year Y is trained on every earlier year from 2012 (at least 4 years) and only then scores year Y. 2016-2026 are all out of sample.
  OUTPUT   per stock: P(big move), P(up), expected size, and EXPECTED MOVE = (2 x P(up) - 1) x expected size (signed), ranked.
  BASELINES the size heads must beat "recent volatility" (the stock's own 20-day volatility, the textbook forecast); the direction head must beat 50%.
  GATES (judged once, on 2016-2026 out of sample):
     size     AUC of P(big) >= 0.70 AND at least 0.01 above the recent-volatility baseline's AUC, AND the top tenth by P(big) has at least twice the base rate of big moves
     direction AUC of P(up) >= 0.53 AND in at least 7 of the 11 years the top tenth by expected move beats the bottom tenth on r5
     ranking  the top tenth by expected move minus the bottom tenth, after 0.30% round-trip costs on each side, is positive on average and in at least 7 of 11 years
  A head that fails is published as "not shown: did not pass" instead of a number. Survivorship: stocks listed today with their past; flattered, disclosed.

ROUND 1 RESULT (2026-10-13): size FAIL (AUC 0.642 vs recent volatility 0.635; top tenth 1.65x the base rate), direction FAIL (AUC 0.511), ranking +0.005%/week.

ROUND 2 (written after round 1 failed, BEFORE any round-2 result; the same years are looked at a second time, so a pass is flattered more). Adds information
that price charts do not contain, everything as known at the Friday close:
  RESULTS CALENDAR  NSE board meetings (scripts/events_calendar.py) counted only if the company had INTIMATED the meeting by the Friday:
                    results meeting in the next 7 days (1/0), days to the next intimated results meeting (cap 90), days since the last results meeting (cap 120),
                    any other intimated meeting in the next 7 days (dividend, fund raising, bonus, split, buyback), results meetings in the last year.
  F&O POSITIONING   NSE F&O bhavcopy (2020 on, F&O stocks only; missing elsewhere): futures open interest change over 5 days as a share of open interest,
                    put/call open-interest ratio and its 5-day change.
  Same models, same settings, same walk-forward, same gates.
"""
import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aladin2 import data_lake as L  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "aladin_movers"
H, BIG, START, FIRST_TEST, MIN_TRAIN_Y = 5, 0.05, "2012-01-01", 2016, 4
MIN_ADV_CR, MIN_PX, COST_RT = 5.0, 20.0, 0.003
LGB = dict(n_estimators=300, num_leaves=31, learning_rate=0.03, min_child_samples=400, subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=1.0, verbose=-1, random_state=11, n_jobs=8)
DROP = {"o", "h", "l", "c", "v", "pc", "suspect_action", "post_break", "locked", "atr14", "adv_cr"}


def universe():
    term = L.TERM
    syms = sorted({p.stem for p in (term / "archive").glob("*.json")} | {p.stem for p in (term / "daily").glob("*.json")})
    return [s for s in syms if not s.startswith("_")]


def sector_map():
    try:
        u = json.loads((L.TERM / "universe.json").read_text(encoding="utf-8"))
        return {s["s"]: s.get("ind") for s in u["stocks"]}
    except (OSError, ValueError, KeyError):
        return {}


def nifty_frame():
    n = L.load_index()
    if n is None:
        return None
    lr = np.log(n / n.shift())
    return pd.DataFrame({"nifty_r20": lr.rolling(20).sum(), "nifty_vol20": lr.rolling(20).std(), "nifty_d200": n / n.rolling(200).mean() - 1, "nifty_lr": lr, "nifty_c": n})


def load_events():
    f = OUT / "board_meetings.csv.gz"
    if not f.exists():
        return {}
    E = pd.read_csv(f); E["meeting"] = pd.to_datetime(E["meeting"]); E["intimated"] = pd.to_datetime(E["intimated"], errors="coerce").fillna(E["meeting"] - pd.Timedelta(days=7))
    return {sym: g[["meeting", "intimated", "results"]].sort_values("meeting").values for sym, g in E.groupby("sym")}


def event_features(dates, ev):
    """dates: Friday timestamps; ev: array rows (meeting, intimated, results). Only meetings intimated by the Friday 23:59 count."""
    out = np.full((len(dates), 5), np.nan)
    if ev is None or not len(ev):
        out[:, [0, 3]] = 0; out[:, 4] = 0
        return out
    mt, it, rs = pd.to_datetime(ev[:, 0]).values, pd.to_datetime(ev[:, 1]).values, ev[:, 2].astype(int)
    for i, d in enumerate(dates):
        cut = np.datetime64(d + pd.Timedelta(hours=23, minutes=59)); dd = np.datetime64(d)
        known = it <= cut
        fut = known & (mt > dd); past = mt <= dd
        nxt_r = mt[fut & (rs == 1)]; lst_r = mt[past & (rs == 1)]
        out[i, 0] = float(((nxt_r - dd) <= np.timedelta64(7, "D")).any()) if len(nxt_r) else 0.0
        out[i, 1] = min(90.0, (nxt_r.min() - dd) / np.timedelta64(1, "D")) if len(nxt_r) else 90.0
        out[i, 2] = min(120.0, (dd - lst_r.max()) / np.timedelta64(1, "D")) if len(lst_r) else 120.0
        oth = mt[fut & (rs == 0)]; out[i, 3] = float(((oth - dd) <= np.timedelta64(7, "D")).any()) if len(oth) else 0.0
        out[i, 4] = float((past & (rs == 1) & (mt > dd - np.timedelta64(365, "D"))).sum())
    return out


def load_fno():
    folder = L.TERM / "aladin2" / "fno"
    if not folder.exists():
        return None
    rows = []
    for f in sorted(folder.glob("20*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        d = pd.Timestamp(f.stem)
        rows += [(d, k, *v[:4]) for k, v in j.get("d", {}).items()]
    if not rows:
        return None
    F = pd.DataFrame(rows, columns=["date", "sym", "fut_oi", "fut_oi_chg", "call_oi", "put_oi"]).sort_values(["sym", "date"])
    g = F.groupby("sym")
    F["oi_chg5"] = g["fut_oi_chg"].transform(lambda x: x.rolling(5, min_periods=3).sum()) / F["fut_oi"].replace(0, np.nan)
    F["pcr"] = F["put_oi"] / F["call_oi"].replace(0, np.nan); F["pcr_chg5"] = F["pcr"] - g["pcr"].shift(5) if False else F["pcr"] - F.groupby("sym")["pcr"].shift(5)
    return F[["date", "sym", "oi_chg5", "pcr", "pcr_chg5"]]


EVENTS = None


def stock_rows(sym, nf=None, fridays=None, ev=None):
    """Friday rows for one stock: features + targets. Runs in a worker process."""
    try:
        F = L.build_frame(sym)
    except Exception:  # noqa: BLE001
        return None
    if F is None or len(F) < 300:
        return None
    F = F[F.index >= pd.Timestamp(START) - pd.Timedelta(days=500)]
    c = F["c"]; fwd = c.shift(-H) / c - 1
    if nf is not None:
        j = nf.reindex(F.index).ffill()
        lr = np.log(c / c.shift()); cov = lr.rolling(120, min_periods=90).cov(j["nifty_lr"]); var = j["nifty_lr"].rolling(120, min_periods=90).var()
        F["beta120"] = cov / var; F["idio120"] = (lr - F["beta120"] * j["nifty_lr"]).rolling(120, min_periods=90).std()
        for k in ("nifty_r20", "nifty_vol20", "nifty_d200"):
            F[k] = j[k]
    wk = (c.pct_change(H).abs() > BIG).astype(float)
    F["big_freq250"] = wk.rolling(250, min_periods=200).mean()
    F["y_r5"] = fwd
    idx = F.index.intersection(fridays) if fridays is not None else F.index[F.index.weekday == 4]
    R = F.loc[idx]
    R = R[(R["adv_cr"] >= MIN_ADV_CR) & (R["c"] >= MIN_PX) & (~R["post_break"].astype(bool)) & (R.index >= pd.Timestamp(START))]
    R = R.dropna(subset=["r250", "vol20"])
    if not len(R):
        return None
    if ev is not False:
        E = event_features(list(R.index), ev)
        for j, k in enumerate(("res_next7", "res_days_to", "res_days_since", "other_next7", "res_last_year")):
            R[k] = E[:, j]
    R = R.drop(columns=[k for k in DROP if k in R.columns]); R.insert(0, "sym", sym)
    return R.reset_index().rename(columns={"index": "date"})


def build_panel(workers=None):
    nf = nifty_frame()
    cal = nf.index if nf is not None else None
    fr = pd.Series(cal, index=cal).groupby(cal.to_period("W-FRI")).max() if cal is not None else None     # the last trading day of each week
    fridays = pd.DatetimeIndex(fr.values) if fr is not None else None
    syms = universe(); evs = load_events()
    with ProcessPoolExecutor(max_workers=workers or max(2, (os.cpu_count() or 4) - 2)) as ex:
        parts = [p for p in ex.map(stock_rows, syms, [nf] * len(syms), [fridays] * len(syms), [evs.get(s) if evs else False for s in syms], chunksize=8) if p is not None]
    P = pd.concat(parts, ignore_index=True)
    fo = load_fno()
    if fo is not None:
        P = P.merge(fo, on=["sym", "date"], how="left")
    sec = sector_map(); P["sector"] = P["sym"].map(sec).fillna("Unknown")
    P["sector_r20"] = P.groupby(["date", "sector"])["r20"].transform("mean")
    rank_cols = ["r5", "r20", "r60", "mom12_1", "vol20", "vol_ratio", "vz20", "rsi14", "hi52", "bb_w", "atr_pct", "idio120", "big_freq250"]
    for k in [k for k in rank_cols if k in P.columns]:
        P[f"{k}_xr"] = P.groupby("date")[k].rank(pct=True)
    P["sector_code"] = P["sector"].astype("category").cat.codes
    return P


def feats(P):
    return [k for k in P.columns if k not in ("sym", "date", "sector", "y_r5")]


def walk_forward(P):
    import lightgbm as lgb
    P = P.dropna(subset=["y_r5"]).copy(); P["year"] = P["date"].dt.year
    X = feats(P); out = []
    for y in range(FIRST_TEST, int(P["year"].max()) + 1):
        tr, te = P[P["year"] < y], P[P["year"] == y]
        if tr["year"].nunique() < MIN_TRAIN_Y or not len(te):
            continue
        a = abs(tr["y_r5"])
        m_big = lgb.LGBMClassifier(**LGB).fit(tr[X], (a > BIG).astype(int))
        m_up = lgb.LGBMClassifier(**LGB).fit(tr[X], (tr["y_r5"] > 0).astype(int))
        m_sz = lgb.LGBMRegressor(**LGB).fit(tr[X], a.clip(upper=0.5))
        t = te[["sym", "date", "year", "y_r5", "vol20", "sector"]].copy()
        t["p_big"] = m_big.predict_proba(te[X])[:, 1]; t["p_up"] = m_up.predict_proba(te[X])[:, 1]; t["size"] = m_sz.predict(te[X]).clip(min=0)
        t["exp_move"] = (2 * t["p_up"] - 1) * t["size"]
        out.append(t); print(f"  year {y}: trained on {len(tr):,} rows, scored {len(te):,}", flush=True)
    return pd.concat(out, ignore_index=True)


def auc(y, s):
    y = np.asarray(y).astype(int); s = np.asarray(s, dtype=float); ok = ~np.isnan(s); y, s = y[ok], s[ok]
    pos, neg = y.sum(), len(y) - y.sum()
    if pos == 0 or neg == 0:
        return None
    r = pd.Series(s).rank().values
    return float((r[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def evaluate(T):
    T = T.copy(); T["big"] = (T["y_r5"].abs() > BIG).astype(int); T["up"] = (T["y_r5"] > 0).astype(int)
    base = T["big"].mean()
    T["dec_big"] = T.groupby("date")["p_big"].transform(lambda s: pd.qcut(s.rank(method="first"), 10, labels=False))
    T["dec_em"] = T.groupby("date")["exp_move"].transform(lambda s: pd.qcut(s.rank(method="first"), 10, labels=False))
    top_big = T[T["dec_big"] == 9]["big"].mean()
    per_year = []
    for y, g in T.groupby("year"):
        w = g.groupby("date").apply(lambda d: d[d["dec_em"] == 9]["y_r5"].mean() - d[d["dec_em"] == 0]["y_r5"].mean() - 2 * COST_RT, include_groups=False)
        per_year.append({"year": int(y), "rows": len(g), "auc_big": round(auc(g["big"], g["p_big"]), 4), "auc_big_vol20": round(auc(g["big"], g["vol20"]), 4),
                         "auc_up": round(auc(g["up"], g["p_up"]), 4), "top_minus_bottom_weekly_pct": round(float(w.mean()) * 100, 3),
                         "top_beats_bottom_raw": bool((g[g["dec_em"] == 9]["y_r5"].mean() - g[g["dec_em"] == 0]["y_r5"].mean()) > 0)})
    a_big, a_vol, a_up = auc(T["big"], T["p_big"]), auc(T["big"], T["vol20"]), auc(T["up"], T["p_up"])
    w_all = T.groupby("date").apply(lambda d: d[d["dec_em"] == 9]["y_r5"].mean() - d[d["dec_em"] == 0]["y_r5"].mean() - 2 * COST_RT, include_groups=False)
    deciles = T.groupby("dec_big").agg(p_big=("p_big", "mean"), big_rate=("big", "mean"), mean_abs_r5=("y_r5", lambda s: s.abs().mean())).reset_index()
    dec_em = T.groupby("dec_em").agg(exp_move=("exp_move", "mean"), mean_r5=("y_r5", "mean"), up_rate=("up", "mean")).reset_index()
    years_tb = sum(1 for r in per_year if r["top_beats_bottom_raw"]); years_net = sum(1 for r in per_year if r["top_minus_bottom_weekly_pct"] > 0); ny = len(per_year)
    gates = {"size": bool(a_big >= 0.70 and a_big - a_vol >= 0.01 and top_big >= 2 * base),
             "direction": bool(a_up >= 0.53 and years_tb >= min(7, ny)),
             "ranking": bool(w_all.mean() > 0 and years_net >= min(7, ny))}
    return {"rows": len(T), "weeks": int(T["date"].nunique()), "stocks": int(T["sym"].nunique()), "base_rate_big": round(base, 4), "top_tenth_big_rate": round(top_big, 4),
            "auc_big": round(a_big, 4), "auc_big_recent_volatility": round(a_vol, 4), "auc_up": round(a_up, 4),
            "ranking_top_minus_bottom_weekly_pct_after_costs": round(float(w_all.mean()) * 100, 3), "years_top_beats_bottom": years_tb, "years_positive_after_costs": years_net,
            "gates": gates, "per_year": per_year, "deciles_big": deciles.round(4).to_dict("records"), "deciles_expected_move": dec_em.round(4).to_dict("records")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--study", action="store_true"); ap.add_argument("--workers", type=int, default=None); a = ap.parse_args()
    if a.study:
        OUT.mkdir(parents=True, exist_ok=True); t0 = datetime.now()
        P = build_panel(a.workers); print(f"panel: {len(P):,} stock-weeks, {P['sym'].nunique()} stocks, {len(feats(P))} inputs, {P['date'].min().date()} to {P['date'].max().date()}", flush=True)
        T = walk_forward(P); ev = evaluate(T)
        doc = {"protocol": __doc__.strip(), "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "inputs": feats(P), "runtime_s": round((datetime.now() - t0).total_seconds()), **ev}
        (OUT / "study.json").write_text(json.dumps(doc, separators=(",", ":"), default=float), encoding="utf-8")
        T.to_csv(OUT / "oos.csv.gz", index=False)                      # every out-of-sample forecast, for later checks (not published)
        print(json.dumps({k: v for k, v in ev.items() if k not in ("per_year", "deciles_big", "deciles_expected_move")}, indent=1))
        for r in ev["per_year"]:
            print(r)


if __name__ == "__main__":
    main()
