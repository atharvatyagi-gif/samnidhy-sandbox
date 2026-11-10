"""
ALADIN audit, phase 4: one simulator for every option, so the comparison is fair.

Rules shared by every option (written before any result was seen, 2026-11-10):
  * Universe on each rebalance date (point in time): main-board, non-ETF stocks with >= 250 days of prices, 60-day average traded
    value >= Rs 5 Cr, the 500 largest by that traded value. Only companies listed TODAY have free price history (survivorship bias).
  * Signal at the close of day t, trades at the OPEN of day t+1, plus slippage (costs.json). Long-only, cash delivery.
  * Equal weight; capital Rs 1,00,000 compounding; a stock whose price is above one position's value is skipped (whole shares).
  * Costs from aladin-audit/costs.json on every buy and sell, plus the DP charge per stock sold.
  * Hold-out: 2026-05-08 .. 2026-11-06 is never used to choose anything; it is reported once at the end for the finalists.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

AUDIT = Path(__file__).resolve().parent.parent
COSTS = json.loads((AUDIT / "costs.json").read_text(encoding="utf-8"))
HOLDOUT_START = pd.Timestamp("2026-05-08")
SCRATCH = None


# ------------------------------------------------------------------ data

def build_panel(main, cache):
    """-> dict(O, C, V matrices (dates x symbols, float32), dates, syms, idx: DataFrame of index series). Cached as a pickle."""
    cache = Path(cache)
    if cache.exists():
        return pd.read_pickle(cache)
    import sys
    sys.path.insert(0, str(main / "scripts"))
    import aladin_model as am
    am.TERM = main / "data" / "terminal"
    uni = json.loads((main / "data" / "terminal" / "universe.json").read_text(encoding="utf-8"))["stocks"]
    ok = {s["s"] for s in uni if s.get("board") == "Main" and not s.get("etf") and s.get("series") in ("EQ", "BE", "BZ")}
    bh = {}
    for f in sorted((main / "data" / "terminal" / "bhav").glob("*.csv.gz")):
        df = pd.read_csv(f)
        df = df[df["SERIES"].astype(str).str.strip().isin(["EQ", "BE", "BZ"])]
        bh[pd.Timestamp(f.name[:10])] = df.set_index(df["SYMBOL"].astype(str).str.strip())[["OPEN_PRICE", "CLOSE_PRICE", "TTL_TRD_QNTY"]]
    bdates = sorted(bh)
    O, C, V = {}, {}, {}
    for s in sorted(ok):
        df = am.load_prices(s, min_bars=60)
        if df is None:
            continue
        last = df.index[-1]
        ext = [d for d in bdates if d > last]
        if ext and last in bh and s in bh[last].index and bh[last].loc[s, "CLOSE_PRICE"] > 0:
            k = df["c"].iloc[-1] / bh[last].loc[s, "CLOSE_PRICE"]                     # keep the split-adjusted scale
            rows = [(d, bh[d].loc[s, "OPEN_PRICE"] * k, bh[d].loc[s, "CLOSE_PRICE"] * k, bh[d].loc[s, "TTL_TRD_QNTY"] / k) for d in ext if s in bh[d].index]
            if rows:
                add = pd.DataFrame(rows, columns=["date", "o", "c", "v"]).set_index("date")
                df = pd.concat([df[["o", "c", "v"]], add])
        O[s], C[s], V[s] = df["o"], df["c"], df["v"]
    C = pd.DataFrame(C).sort_index()
    dates = C.index
    O = pd.DataFrame(O).reindex(dates)
    V = pd.DataFrame(V).reindex(dates)
    C = C[C.index >= "2008-01-01"]; O = O.loc[C.index]; V = V.loc[C.index]
    import yfinance as yf
    idx = {}
    for k, t in {"nifty50": "^NSEI", "nifty500": "^CRSLDX", "vix": "^INDIAVIX"}.items():
        s = yf.download(t, start="2007-01-01", progress=False, auto_adjust=False)["Close"]
        s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
        idx[k] = s.dropna()
    P = {"O": O.astype("float32"), "C": C.astype("float32"), "V": V.astype("float32"), "idx": pd.DataFrame(idx).reindex(C.index).ffill()}
    pd.to_pickle(P, cache)
    return P


# ------------------------------------------------------------------ costs

def slip(adv):
    s = COSTS["slippage_pct_per_side"]
    return (s["adv_ge_100cr"] if adv >= 1e9 else s["adv_ge_20cr"] if adv >= 2e8 else s["below"]) / 100


def buy_cost(value, adv):
    d = COSTS["delivery"]
    charges = value * (d["exchange_txn_pct"] + d["sebi_fee_pct"] + d["brokerage_pct"]) / 100
    return value * (d["stt_buy_pct"] + d["stamp_duty_buy_pct"]) / 100 + charges * (1 + d["gst_pct_on_brokerage_and_charges"] / 100) + value * slip(adv)


def sell_cost(value, adv):
    d = COSTS["delivery"]
    charges = value * (d["exchange_txn_pct"] + d["sebi_fee_pct"] + d["brokerage_pct"]) / 100
    return value * d["stt_sell_pct"] / 100 + charges * (1 + d["gst_pct_on_brokerage_and_charges"] / 100) + value * slip(adv) + d["dp_charge_per_scrip_sell_inr"]


# ------------------------------------------------------------------ simulator

class Ctx:
    """Precomputed matrices shared by all options."""

    def __init__(self, P):
        self.O, self.C, self.V = P["O"].values, P["C"].values, P["V"].values
        self.dates = P["C"].index
        self.syms = np.array(P["C"].columns)
        self.idx = P["idx"]
        Cdf = P["C"]
        tv = (P["C"] * P["V"])
        self.adv = tv.rolling(60, min_periods=40).mean().values
        self.nbars = Cdf.notna().cumsum().values
        self.logc = np.log(Cdf.values.astype("float64"))
        lr = np.diff(self.logc, axis=0, prepend=np.nan)
        self.vol252 = pd.DataFrame(lr).rolling(252, min_periods=200).std().values
        self.vol63 = pd.DataFrame(lr).rolling(63, min_periods=50).std().values
        self.sma200 = Cdf.rolling(200, min_periods=180).mean().values
        n500 = self.idx["nifty500"]
        self.mkt_up = (n500 > n500.rolling(200).mean()).values
        vix = self.idx["vix"]
        self.vix_pct = vix.rolling(252, min_periods=120).rank(pct=True).values
        self.n500 = n500.values

    def universe(self, t, top=500, min_adv=5e7):
        a = self.adv[t]
        ok = (self.nbars[t] >= 250) & np.isfinite(a) & (a >= min_adv) & np.isfinite(self.C[t])
        ids = np.flatnonzero(ok)
        if len(ids) > top:
            ids = ids[np.argsort(-a[ids])[:top]]
        return ids

    def ret(self, t, L, skip=0):
        return self.logc[t - skip] - self.logc[t - L]


def simulate(ctx, score_fn, step, pick, start="2010-01-01", end=None, exposure_fn=None, universe_top=500, capital=None, seed=None, record=True, daily_risk=False):
    """score_fn(ctx, t, ids) -> scores (higher = better, NaN = not eligible). pick: ('pct', 0.05) or ('n', 20).
    exposure_fn(ctx, t, history_returns) -> 0..1 share of capital invested. Returns dict(daily (Series of daily returns), trades (DataFrame), costs, gross)."""
    capital = capital or COSTS["capital_inr"]
    rng = np.random.default_rng(seed) if seed is not None else None
    D = ctx.dates
    t0 = int(D.searchsorted(pd.Timestamp(start)))
    t1 = len(D) - 1 if end is None else int(D.searchsorted(pd.Timestamp(end), side="right")) - 1
    cash, pos = float(capital), {}          # pos: j -> [shares, entry_px, entry_date, buy_cost]
    eq = np.full(len(D), np.nan)
    trades, costs_paid, hist = [], 0.0, []
    next_rebal = t0
    last_e = 1.0
    for t in range(t0, t1 + 1):
        # 1. orders decided at the previous close execute at today's open
        if t == next_rebal + 1 and t <= t1:
            pass
        # mark to market at the close
        val = cash + sum(p[0] * (ctx.C[t, j] if np.isfinite(ctx.C[t, j]) else p[1]) for j, p in pos.items())
        eq[t] = val
        if t > t0:
            hist.append(eq[t] / eq[t - 1] - 1)
        if daily_risk and exposure_fn and t != next_rebal and t < t1:      # option E: the market state is checked every day, not only on rebalance days
            e_now = exposure_fn(ctx, t, hist)
            if abs(e_now - last_e) >= 0.25:
                next_rebal = t
        if t == next_rebal and t < t1:
            ids = ctx.universe(t, universe_top)
            if rng is not None:
                sc = rng.random(len(ids))
            else:
                sc = score_fn(ctx, t, ids)
            good = np.isfinite(sc)
            ids, sc = ids[good], sc[good]
            n = max(1, int(round(pick[1] * len(ids)))) if pick[0] == "pct" else int(pick[1])
            chosen = ids[np.argsort(-sc)[:n]] if len(ids) else np.array([], int)
            e = exposure_fn(ctx, t, hist) if exposure_fn else 1.0
            last_e = e
            target = val * e / max(1, len(chosen)) if e > 0 else 0.0
            keep = set(chosen.tolist()) if e > 0 else set()
            # execute at the next open
            u = t + 1
            for j in [j for j in pos if j not in keep]:
                px = ctx.O[u, j] if np.isfinite(ctx.O[u, j]) else ctx.C[t, j]
                sh, epx, edate, bc = pos.pop(j)
                gross = sh * px
                c = sell_cost(gross, ctx.adv[t, j] if np.isfinite(ctx.adv[t, j]) else 0)
                cash += gross - c; costs_paid += c
                if record:
                    trades.append((ctx.syms[j], edate, D[u], epx, px, (gross - c) / (sh * epx + bc) - 1, (px / epx) - 1, bc + c))
            for j in chosen:
                if j in pos or target <= 0:
                    continue
                px = ctx.O[u, j]
                if not np.isfinite(px) or px <= 0 or px > target:
                    continue
                spend = min(target, cash)
                if spend < px:
                    continue
                c = buy_cost(spend, ctx.adv[t, j])
                sh = (spend - c) / px
                cash -= spend; costs_paid += c
                pos[j] = [sh, px, D[u], c]
            next_rebal = t + step
    daily = pd.Series(eq, index=D).dropna().pct_change().dropna()
    tr = pd.DataFrame(trades, columns=["sym", "entry", "exit", "entry_px", "exit_px", "net_ret", "gross_ret", "cost_inr"])
    return {"daily": daily, "trades": tr, "costs": costs_paid, "equity": pd.Series(eq, index=D).dropna()}


# ------------------------------------------------------------------ measures

def sharpe(r):
    r = np.asarray(r)
    return float(r.mean() / r.std() * math.sqrt(252)) if len(r) > 20 and r.std() > 0 else float("nan")


def max_dd(r):
    e = np.cumprod(1 + np.asarray(r))
    return float((e / np.maximum.accumulate(e) - 1).min()) if len(e) else float("nan")


def cagr(r):
    r = np.asarray(r)
    return float(np.prod(1 + r) ** (252 / len(r)) - 1) if len(r) else float("nan")


def deflated_sharpe(r, n_trials, sr_trials_var):
    """Bailey and Lopez de Prado (2014): probability that the true Sharpe is above what the best of n_trials would show by luck."""
    from scipy.stats import norm, skew, kurtosis
    r = np.asarray(r)
    T = len(r)
    sr = r.mean() / r.std()
    g3, g4 = skew(r), kurtosis(r, fisher=False)
    emc = 0.5772156649
    sr0 = math.sqrt(max(sr_trials_var, 1e-12)) * ((1 - emc) * norm.ppf(1 - 1 / max(n_trials, 2)) + emc * norm.ppf(1 - 1 / (max(n_trials, 2) * math.e)))
    z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(norm.cdf(z))


def regime_split(r, ctx):
    n5 = pd.Series(ctx.n500, index=ctx.dates)
    m = (n5 / n5.shift(63) - 1).reindex(r.index)
    up, dn = r[m > 0.05], r[m < -0.05]
    side = r[(m >= -0.05) & (m <= 0.05)]
    f = lambda x: round(cagr(x) * 100, 1) if len(x) > 40 else None
    return {"up_market": f(up), "down_market": f(dn), "sideways": f(side), "days": [len(up), len(dn), len(side)]}


def report(res, ctx, capital=None):
    capital = capital or COSTS["capital_inr"]
    r, tr = res["daily"], res["trades"]
    gross_profit = float(((tr["exit_px"] - tr["entry_px"]) / tr["entry_px"]).clip(lower=0).sum()) if len(tr) else 0
    wins, losses = tr[tr["net_ret"] > 0]["net_ret"], tr[tr["net_ret"] <= 0]["net_ret"]
    years = r.groupby(r.index.year).apply(lambda x: np.prod(1 + x) - 1)
    pre, post = r[r.index < "2020-01-01"], r[r.index >= "2020-01-01"]
    best5 = None
    if len(tr) > 10:
        t2 = tr.drop(tr["net_ret"].nlargest(5).index)
        best5 = round(float(t2["net_ret"].mean() * 1e4), 1)
    final = capital * float(np.prod(1 + r))
    return {"cagr_pct": round(cagr(r) * 100, 2), "sharpe": round(sharpe(r), 3), "max_dd_pct": round(max_dd(r) * 100, 1), "max_dd_inr_on_1L": round(max_dd(r) * 1e5, 0),
            "final_inr_from_1L": round(final, 0), "trades": int(len(tr)), "win_rate": round(float((tr["net_ret"] > 0).mean()), 3) if len(tr) else None,
            "avg_win_pct": round(float(wins.mean() * 100), 2) if len(wins) else None, "avg_loss_pct": round(float(losses.mean() * 100), 2) if len(losses) else None,
            "net_per_trade_bps": round(float(tr["net_ret"].mean() * 1e4), 1) if len(tr) else None, "net_per_trade_bps_without_best5": best5,
            "costs_inr": round(float(res["costs"]), 0), "costs_share_of_gross_gains": round(float(tr["cost_inr"].sum() / max(1e-9, gross_profit * capital / max(1, len(set(tr["entry"]))))), 3) if len(tr) else None,
            "time_in_market": round(float((r != 0).mean()), 3), "pre_2020_cagr": round(cagr(pre) * 100, 1) if len(pre) else None, "post_2020_cagr": round(cagr(post) * 100, 1) if len(post) else None,
            "regimes": regime_split(r, ctx), "by_year": {int(k): round(float(v) * 100, 1) for k, v in years.items()},
            "from": str(r.index[0].date()), "to": str(r.index[-1].date())}
