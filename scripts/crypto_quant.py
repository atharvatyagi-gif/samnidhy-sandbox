"""
Bitcoin all-weather quant model: one position from fully short (-1) to fully long (+1), decided every 4 hours, sized to a volatility target,
retrained every month on the newest data. Meant to work in rising, falling and sideways markets, not only in one of them.

  python scripts/crypto_quant.py --study       -> data/crypto/quant_study.json   (walk-forward test, candidates, regime breakdown)
  python scripts/crypto_quant.py --fit         -> data/crypto/quant_model.json   (the model the live engine uses: ridge weights + LightGBM text)

Everything below was written down BEFORE any result was seen (2026-10-12, owner: "a strategy that can be traded in each and every type of market, quant heavy").

DATA     Binance BTCUSDT spot 15-minute bars with taker-buy volume (crypto_data.py) -> 4-hour bars; Binance USD-M funding rates every 8 hours (crypto_funding.py).
FEATURES (row i uses bars up to and including i only; sigma = standard deviation of 4-hour log returns over the previous 180 bars)
         trend     mom_h = log(c_i / c_{i-h}) / (sigma * sqrt(h)) for h = 1, 6, 18, 42, 84, 180, 360 bars (4 h, 1 d, 3 d, 7 d, 14 d, 30 d, 60 d)
         averages  (c - SMA_n) / ATR for n = 20, 50, 200
         range     where the close sits in the high-low range of the last 42 and 180 bars (0..1)
         volatility realised vol 6 vs 180 bars (ratio), ATR% z-score vs the previous 1,500 bars
         flow      taker-buy imbalance summed over 6, 18, 42 bars, z-scored vs the previous 500 bars (crypto_flow._z); volume z
         crowding  last funding rate, 7-day mean funding, its z-score vs 90 days
         candle    Heikin-Ashi bar green (1/0)
TARGET   the next 6 bars' (24 h) log return / (sigma * sqrt(6)), clipped to +-3.
CANDIDATES (each long/short AND long-only; 8 in all)
         TREND     s = mean of mom_h for h = 6..360, each clipped to +-2                     (classic multi-horizon time-series momentum)
         REVERT    s = -(mom_6 + mom_18) / 2, clipped to +-2                                 (short-term mean reversion)
         ML        ridge regression (alpha 10, standardised features) and LightGBM (200 trees, 15 leaves, learning rate 0.03, min 200 rows a leaf,
                   70% row and feature sampling), each prediction divided by its own training spread, averaged
         ML+TREND  the average of ML and TREND
POSITION target = clip(tanh(s) * 0.40 / annualised realised vol (42 bars), -1, +1)   (long-only: floored at 0). No leverage: |position| <= 100% of the sleeve.
         Changed only when the target differs from the current position by at least 0.15 (fewer, cheaper trades). Decided at a 4-hour close, filled at the
         next open; every change pays 0.12% of the traded value (fee + slippage). A short is a 1x perpetual future: it RECEIVES the funding rate when the rate
         is positive and PAYS it when negative, at each 8-hour funding time it is held. A long is spot (no funding).
TRAINING walk-forward: on the first day of every month the ML models are refitted on the previous 3 years (at least 1), leaving out the last 6 bars (their target
         is not known yet), and predict that month only. This is the "self-evolving" part: the model always learns from the newest three years.
SELECTION choose ONE candidate by Sharpe on 2021-2023 (walk-forward predictions). Judge it ONCE on 2024-01 to the last bar. It may replace the two Bitcoin sleeves
         now traded only if, on 2024-2026, its Sharpe beats theirs (combined 50/50, as traded) AND it is positive at double cost (0.25% a fill).
         Also reported: results inside rising, falling and sideways quarters (BTC's own quarterly return above +10%, below -10%, in between), so "every market"
         is checked, not assumed. Eight candidates were tried, so the chosen one is flattered; the live record decides.

ROUND 2 (written after round 1 failed, BEFORE any round-2 result; 2024-2026 is now looked at a SECOND time, so a pass is flattered more):
  Diagnosis of round 1: 30-80 position changes a month (costs ate everything) and 4-hour moves are mostly noise; shorts lost money in falling quarters too.
  Changes: decide ONCE A DAY (at the 00:00 UTC bar close), ML target = the next 7 days (42 bars), the score is smoothed (mean of the last 3 daily scores),
  no-trade band 0.25. New candidate CARRY: s = -fund_z clipped to +-2 (lean against crowded futures positions), and TREND+CARRY (average).
  Candidates: TREND, ML, ML+TREND, TREND+CARRY, each long/short and long-only (8). Same selection on 2021-2023 and the same gate.
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypto_flow as CF  # noqa: E402
import crypto_extra as CX  # noqa: E402
import crypto_funding as FU  # noqa: E402

OUT = CF.OUT
H_MOM = [1, 6, 18, 42, 84, 180, 360]
TARGET_H, TV, BAND, COST = 6, 0.40, 0.15, CF.COST
BARS_PER_YEAR = 6 * 365
WIN_Y = 3
RIDGE_ALPHA = 10.0
LGB = dict(n_estimators=200, num_leaves=15, learning_rate=0.03, min_child_samples=200, subsample=0.7, subsample_freq=1, colsample_bytree=0.7, verbose=-1, random_state=7)
CANDS = ["TREND", "REVERT", "ML", "ML+TREND"]


def build(bars=None, funding=None, target_h=None):
    """4-hour frame with every feature and the target. Row i uses data up to the close of bar i only (the target looks ahead and is only used for training)."""
    b = CF.resample(CF.load_bars(symbol="BTCUSDT") if bars is None else bars, "4h")
    f = CF.features(b); f = CX.extra_features(f)
    lr = np.log(f["c"]).diff(); sig = lr.rolling(180, min_periods=60).std()
    X = pd.DataFrame(index=f.index)
    for h in H_MOM:
        X[f"mom_{h}"] = np.log(f["c"] / f["c"].shift(h)) / (sig * math.sqrt(h))
    for n in (20, 50, 200):
        X[f"ma_{n}"] = (f["c"] - f["c"].rolling(n).mean()) / f["atr"]
    for n in (42, 180):
        lo, hi = f["l"].rolling(n).min(), f["h"].rolling(n).max(); X[f"rng_{n}"] = (f["c"] - lo) / (hi - lo)
    X["vol_ratio"] = lr.rolling(6).std() / lr.rolling(180, min_periods=60).std()
    atrp = f["atr"] / f["c"]; X["atr_z"] = (atrp - atrp.rolling(1500, min_periods=300).mean().shift(1)) / atrp.rolling(1500, min_periods=300).std().shift(1)
    imb = f["delta"] / f["v"]
    for n in (6, 18, 42):
        X[f"flow_{n}"] = CF._z(f["delta"].rolling(n).sum() / f["v"].rolling(n).sum())
    X["vol_z"] = f["vol_z"]; X["ha"] = f["ha_green"].astype(float)
    fu = FU.load() if funding is None else funding
    if len(fu):
        fr = fu.set_index("ts")["rate"].sort_index(); fr = fr[~fr.index.duplicated()]
        last = fr.reindex(X.index.union(fr.index)).ffill().reindex(X.index)
        m7 = fr.rolling(21, min_periods=5).mean(); m7 = m7.reindex(X.index.union(m7.index)).ffill().reindex(X.index)
        z = (fr - fr.rolling(270, min_periods=60).mean()) / fr.rolling(270, min_periods=60).std(); z = z.reindex(X.index.union(z.index)).ffill().reindex(X.index)
        X["fund_last"], X["fund_7d"], X["fund_z"] = last * 1e4, m7 * 1e4, z                     # in basis points
    else:
        X["fund_last"] = X["fund_7d"] = X["fund_z"] = np.nan
    th = target_h or TARGET_H
    y = (np.log(f["c"].shift(-th) / f["c"]) / (sig * math.sqrt(th))).clip(-3, 3)
    rv = lr.rolling(42, min_periods=20).std() * math.sqrt(BARS_PER_YEAR)
    return f, X, y.rename("y"), rv.rename("rv")


FEATS = [f"mom_{h}" for h in H_MOM] + ["ma_20", "ma_50", "ma_200", "rng_42", "rng_180", "vol_ratio", "atr_z", "flow_6", "flow_18", "flow_42", "vol_z", "ha", "fund_last", "fund_7d", "fund_z"]


def rule_score(X, name):
    if name == "TREND":
        return pd.concat([X[f"mom_{h}"].clip(-2, 2) for h in H_MOM[1:]], axis=1).mean(axis=1)
    if name == "CARRY":
        return (-X["fund_z"]).clip(-2, 2)
    if name == "REVERT":
        return (-(X["mom_6"] + X["mom_18"]) / 2).clip(-2, 2)
    raise KeyError(name)


class Ridge:
    def fit(self, X, y, alpha=RIDGE_ALPHA):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9; Z = (X - self.mu) / self.sd
        A = Z.T @ Z + alpha * np.eye(Z.shape[1]); self.w = np.linalg.solve(A, Z.T @ (y - y.mean())); self.b = float(y.mean()); return self

    def predict(self, X):
        return ((X - self.mu) / self.sd) @ self.w + self.b


def fit_models(Xtr, ytr):
    import lightgbm as lgb
    Xa, ya = Xtr.values.astype(float), ytr.values.astype(float); med = np.nanmedian(Xa, axis=0); Xa = np.where(np.isnan(Xa), med, Xa)
    r = Ridge().fit(Xa, ya); g = lgb.LGBMRegressor(**LGB).fit(Xa, ya)
    sr, sg = float(np.std(r.predict(Xa))) or 1.0, float(np.std(g.predict(Xa))) or 1.0
    return {"ridge": r, "lgb": g, "med": med, "sr": sr, "sg": sg}


def predict_models(m, X):
    Xa = X.values.astype(float); Xa = np.where(np.isnan(Xa), m["med"], Xa)
    return pd.Series((m["ridge"].predict(Xa) / m["sr"] + m["lgb"].predict(Xa) / m["sg"]) / 2, index=X.index)


def walk_forward_ml(X, y, start="2021-01-01", target_h=TARGET_H):
    """Monthly refit on the previous 3 years; each month predicted by a model that never saw it."""
    pred = pd.Series(np.nan, index=X.index); idx = X.index
    for m in pd.date_range(start, idx[-1], freq="MS"):
        nxt = m + pd.offsets.MonthBegin(1); lo = m - pd.DateOffset(years=WIN_Y)
        tr = (idx >= lo) & (idx < m); tr_idx = idx[tr][:-target_h]                           # the last 6 bars' targets reach into the month being predicted
        d = X.loc[tr_idx, FEATS].join(y).dropna(subset=["y"])
        d = d[d[FEATS].notna().sum(axis=1) >= len(FEATS) - 3]
        if len(d) < 1500:
            continue
        mdl = fit_models(d[FEATS], d["y"]); te = (idx >= m) & (idx < nxt)
        pred[te] = predict_models(mdl, X.loc[te, FEATS]).values
    return pred


def positions(score, rv, long_only=False):
    tgt = (np.tanh(score) * TV / rv).clip(-1, 1)
    return tgt.clip(lower=0) if long_only else tgt


def simulate(f, target, funding=None, cost=COST, band=BAND):
    """Account of 1.0. Target decided at bar i's close -> traded at bar i+1's open (only if it moved by >= band). Marked at every bar's close.
    Short side receives positive funding at each 8-hour funding time inside the bar it is held over."""
    o, c, idx = f["o"].values, f["c"].values, f.index; n = len(f); tg = target.reindex(idx).values
    fu = (FU.load() if funding is None else funding)
    fr = fu.set_index("ts")["rate"] if len(fu) else pd.Series(dtype=float)
    fund_at = {}
    if len(fr):
        bins = pd.Series(fr.values, index=fr.index).groupby(fr.index.floor("4h")).sum(); fund_at = bins.to_dict()
    eq, pos, cash_eq, trades, curve, turnover, fund_paid, missing_fund = 1.0, 0.0, None, [], np.full(n, np.nan), 0.0, 0.0, 0
    pend = None; last_px = None
    for i in range(n):
        if pend is not None and not math.isnan(pend):
            new = pend
            if abs(new - pos) >= band or (new == 0 and pos != 0 and abs(pos) < band):
                tr = abs(new - pos) * eq; eq -= tr * cost; turnover += tr
                trades.append({"t": str(idx[i]), "from": round(pos, 3), "to": round(new, 3), "px": round(float(o[i]), 2)}); pos = new
        pend = None
        # P&L from this bar's open to its close
        eq *= 1 + pos * (c[i] / o[i] - 1)
        if pos < 0:
            r = fund_at.get(idx[i])
            if r is None:
                missing_fund += 1
            else:
                eq += -pos * r * eq; fund_paid -= -pos * r
        curve[i] = eq
        # carry the position from this close to the next open
        if i + 1 < n:
            eq *= 1 + pos * (o[i + 1] / c[i] - 1)
        if not math.isnan(tg[i]):
            pend = float(tg[i])
    return {"equity": pd.Series(curve, index=idx), "trades": trades, "turnover": turnover, "funding_received_pct": round(-fund_paid * 100, 2), "bars_short_without_funding_data": missing_fund}


def stats(eq, trades, lo, hi=None):
    e = eq.dropna(); e = e[(e.index >= pd.Timestamp(lo)) & ((e.index <= pd.Timestamp(hi)) if hi else True)]
    if len(e) < 100:
        return {}
    d = e.resample("1D").last().dropna(); dr = d.pct_change().dropna(); yrs = (e.index[-1] - e.index[0]).days / 365.25
    dd = float((e / e.cummax() - 1).min()); n = sum(1 for t in trades if lo <= t["t"] <= (hi or "9999"))
    return {"return_pct": round((e.iloc[-1] / e.iloc[0] - 1) * 100, 1), "cagr_pct": round(((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100, 1), "sharpe": round(float(dr.mean() / dr.std() * math.sqrt(365)), 2) if dr.std() > 0 else None,
            "max_drawdown_pct": round(dd * 100, 1), "rebalances": n, "per_month": round(n / max(yrs * 12, 1e-9), 1)}


def regimes(f):
    q = f["c"].resample("QE").last(); r = q.pct_change(); lab = pd.Series(np.where(r > 0.10, "rising", np.where(r < -0.10, "falling", "sideways")), index=q.index); return lab, r


def by_regime(eq, f, lo):
    lab, r = regimes(f); out = {"rising": [], "falling": [], "sideways": []}
    e = eq.dropna().resample("QE").last(); er = e.pct_change()
    for t, L in lab.items():
        if t < pd.Timestamp(lo) or pd.isna(er.get(t)) or pd.isna(r.get(t)):
            continue
        out[L].append(float(er[t]))
    return {k: {"quarters": len(v), "avg_quarter_pct": round(float(np.mean(v)) * 100, 1) if v else None, "positive_quarters": sum(1 for x in v if x > 0)} for k, v in out.items()}


def fixed_btc(f, cost=COST):
    """The two Bitcoin sleeves traded now (momentum + trailing stop, breakout), 50/50 as in the live account."""
    a = CX.run(f, "momentum_trail", cost); b = CX.run(f, "breakout", cost)
    return (a["equity"] + b["equity"]) / 2, a["trades"] + b["trades"]


ROUNDS = {1: {"target_h": TARGET_H, "daily": False, "smooth": 1, "band": BAND, "cands": ["TREND", "REVERT", "ML", "ML+TREND"]},
          2: {"target_h": 42, "daily": True, "smooth": 3, "band": 0.25, "cands": ["TREND", "ML", "ML+TREND", "TREND+CARRY"]}}


def daily_target(score, rv, long_only, daily, smooth):
    s = score
    if daily:
        s = score[score.index.hour == 0]
    s = s.rolling(smooth, min_periods=1).mean() if smooth > 1 else s
    t = positions(s, rv.reindex(s.index), long_only)
    return t.reindex(score.index) if daily else t                                # other bars: no new decision (NaN = keep)


def study(rnd=2):
    R = ROUNDS[rnd]
    f, X, y, rv = build(target_h=R["target_h"]); fu = FU.load(); f = f[f.index >= "2020-01-15"]; X, y, rv = X.loc[f.index], y.loc[f.index], rv.loc[f.index]
    ml = walk_forward_ml(X, y, target_h=R["target_h"]); scores = {"TREND": rule_score(X, "TREND"), "REVERT": rule_score(X, "REVERT"), "CARRY": rule_score(X, "CARRY"), "ML": ml}
    scores["ML+TREND"] = (ml + scores["TREND"]) / 2; scores["TREND+CARRY"] = (scores["TREND"] + scores["CARRY"].fillna(0)) / 2
    res, curves = {}, {}
    for name in R["cands"]:
        for lo_only in (False, True):
            key = name + ("_long_only" if lo_only else "_long_short"); sc = scores[name].where(ml.notna()) if name.startswith("ML") else scores[name]
            tgt = daily_target(sc, rv, lo_only, R["daily"], R["smooth"])
            tgt[tgt.index < pd.Timestamp("2021-01-01")] = np.nan
            r = simulate(f, tgt, fu, band=R["band"]); r2 = simulate(f, tgt, fu, cost=0.0025, band=R["band"])
            res[key] = {"2021-2023": stats(r["equity"], r["trades"], "2021-01-01", CF.SELECT_END), "2024-2026": stats(r["equity"], r["trades"], "2024-01-01"),
                        "2024-2026_cost_0.25pct": stats(r2["equity"], r2["trades"], "2024-01-01"), "by_market_2021_2026": by_regime(r["equity"], f, "2021-01-01"),
                        "funding_received_pct_total": r["funding_received_pct"], "short_bars_missing_funding": r["bars_short_without_funding_data"],
                        "avg_abs_position": round(float(tgt.abs().mean()), 3), "time_short_pct": round(float((tgt < 0).mean() * 100), 1)}
            curves[key] = r["equity"]
    eqf, trf = fixed_btc(f); eqf2, trf2 = fixed_btc(f, 0.0025)
    eqf = eqf / eqf[eqf.index >= "2021-01-01"].dropna().iloc[0]
    base = {"2021-2023": stats(eqf, trf_to(trf), "2021-01-01", CF.SELECT_END), "2024-2026": stats(eqf, trf_to(trf), "2024-01-01"), "2024-2026_cost_0.25pct": stats(eqf2, trf_to(trf2), "2024-01-01"), "by_market_2021_2026": by_regime(eqf, f, "2021-01-01")}
    bh = f["c"] / f["c"][f.index >= "2021-01-01"].iloc[0]
    buyhold = {"2021-2023": stats(bh, [], "2021-01-01", CF.SELECT_END), "2024-2026": stats(bh, [], "2024-01-01"), "by_market_2021_2026": by_regime(bh, f, "2021-01-01")}
    chosen = max(res, key=lambda k: res[k]["2021-2023"].get("sharpe") or -9)
    c = res[chosen]; gate = (c["2024-2026"].get("sharpe") or -9) > (base["2024-2026"].get("sharpe") or 9) and (c["2024-2026_cost_0.25pct"].get("return_pct") or -1) > 0
    return {"round": rnd, "settings": R, "protocol": __doc__.strip(), "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bars": f"{f.index[0]} to {f.index[-1]}", "candidates": res,
            "current_btc_sleeves": base, "buy_and_hold": buyhold, "chosen_on_2021_2023": chosen, "passes_gate": bool(gate)}, curves


def trf_to(tr):
    return [{"t": t["out"]} for t in tr]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--study", action="store_true"); ap.add_argument("--round", type=int, default=2); a = ap.parse_args()
    if a.study:
        doc, _ = study(a.round); (OUT / f"quant_study_r{a.round}.json").write_text(json.dumps(doc, separators=(",", ":"), default=str), encoding="utf-8")
        P = lambda d: f"ret {d.get('return_pct')!s:>7}% cagr {d.get('cagr_pct')!s:>6}% sh {d.get('sharpe')!s:>5} dd {d.get('max_drawdown_pct')!s:>6}% reb/mo {d.get('per_month')!s:>5}"
        for k, v in list(doc["candidates"].items()) + [("CURRENT_BTC_SLEEVES", doc["current_btc_sleeves"]), ("BUY_AND_HOLD", doc["buy_and_hold"])]:
            print(f"{k:22s} 21-23 {P(v['2021-2023'])} || 24-26 {P(v['2024-2026'])}" + (f" || x2cost {v['2024-2026_cost_0.25pct'].get('return_pct')}%" if "2024-2026_cost_0.25pct" in v else ""))
            print(f"{'':22s} by market: " + " ".join(f"{m}: {x['avg_quarter_pct']}%/q ({x['positive_quarters']}/{x['quarters']} up)" for m, x in v["by_market_2021_2026"].items()) + (f" | short {v['time_short_pct']}% of time, funding {v['funding_received_pct_total']}%" if "time_short_pct" in v else ""))
        print("chosen on 2021-2023:", doc["chosen_on_2021_2023"], "| passes the gate:", doc["passes_gate"])


if __name__ == "__main__":
    main()
