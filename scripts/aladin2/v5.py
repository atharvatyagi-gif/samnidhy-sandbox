"""
ALADIN paper bot, rule v5: the Stress-Test Black Box's recommendations (owner, 2026-10-16: "take all the recommendations and make the reds green, then retest").

  python -m scripts.aladin2.v5 --backtest      -> data/aladin2/paper/v5_backtest.json

RULES, written down BEFORE any result was seen (2026-10-16). The same weekly list, entry, 5-day clock, sizing and costs as v3, plus:
  ROLL       a position whose stock is on the new Friday list on its exit day is kept (its 5-day clock restarts) instead of sold and bought back.
             Black Box: costs took 89-183% of the gross profit in quiet markets, turnover ~52x a year.
  TREND      new long positions only while the NIFTY 50 closed above its 200-day average on the list's Friday (otherwise the money stays in the
             liquid fund). Black Box: every long strategy fell 32-45% in a systemic crash.
  BRAKE      new sizes are halved while the account is 10% or more below its peak (data/config/aladin2.json risk.drawdown_brake_pct = 10, which the
             bot never applied).
  LOSS LIMIT no new positions (and no rolls) once the account is 20% below its peak, until the trend filter is on again at a list date.
  VOL SCALE  risk per trade and the per-stock cap x min(1, 16% / the NIFTY 50's 20-day realised volatility, annualised).
Nothing else changes. No parameter above is chosen from the real history: 200 days, 10% and 16% are the standard / configured values, 20% is the
Black Box's recommended loss limit.

GATES (judged ONCE on the full history 2013-2026, v3 replayed with the same code, books, prices and dates; both after all costs):
  1  risk      maximum drawdown at least 5 points shallower than v3's
  2  return    CAGR no more than 2 points below v3's
  3  quality   Sharpe over the cash rate (6.2%) higher than v3's
  4  stability at least as many positive calendar years 2013-2025 as v3
  All pass -> the live paper bot switches to v5 from the next list (rule history v5). Any fail -> v3 stays live and v5 runs as a published record.
Also reported (information only, NOT used for the verdict): each v5 component on its own.

ROUND 1 RESULT (2026-10-16): FAIL (risk passed, return and quality failed). v5: CAGR 14.71% vs v3 20.84%, max drawdown -17.4% vs -27.5%, Sharpe over
cash 0.837 vs 0.944, costs Rs 2.2 lakh a year vs Rs 7.1 lakh. The trend filter kept the bot out of too many Indian rallies (alone: CAGR 15.2%).
Components alone (information): roll 22.55% / -27.1% / 1.037; brake 18.85% / -21.3% / 0.956; trend 15.22% / -22.0% / 0.768;
loss limit 20.46% / -30.5% / 0.925; vol scale 19.05% / -27.2% / 0.888. v3 stays live.

ROUND 2 (written after round 1, BEFORE any round-2 result; a SECOND look at the same years, chosen from round 1's components, so a pass is flattered):
  v5.1 = v3 + ROLL + BRAKE only (both are mechanical: roll removes the sale and re-purchase of a stock still on the list; the brake is the
  configured 10% one). Same gates. A pass switches the live bot to v5.1 with this caveat recorded in its rule history.
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import paper as P

OUT = P.OUT / "v5_backtest.json"
V51 = {"roll": True, "brake_pct": 10.0}
V5 = {"roll": True, "trend_sma": 200, "brake_pct": 10.0, "stop_pct": 20.0, "vol_target": 0.16, "vol_days": 20}
RF = 0.062
GATES = {"dd_better_pts": 5.0, "cagr_worse_max_pts": 2.0, "years": (2013, 2025)}


def market_filters(nifty: pd.Series, v5: dict = V5):
    """-> (regime(as_of) -> bool, vol_scale(as_of) -> 0..1) from the NIFTY 50 closes known on the list's Friday (nothing later)."""
    s = nifty.dropna().sort_index(); sma = s.rolling(v5["trend_sma"], min_periods=v5["trend_sma"]).mean()
    rv = np.log(s).diff().rolling(v5["vol_days"], min_periods=v5["vol_days"]).std() * math.sqrt(252)
    up = (s > sma) | sma.isna()                                                       # no 200 days of history yet: no filter
    scale = (v5["vol_target"] / rv).clip(upper=1.0).fillna(1.0)

    def at(series, as_of, default):
        x = series.loc[:pd.Timestamp(as_of)]
        return x.iloc[-1] if len(x) else default
    return (lambda a: bool(at(up, a, True))), (lambda a: float(at(scale, a, 1.0)))


def sharpe(rows) -> float:
    e = np.array([r[1] for r in rows], float); r = e[1:] / e[:-1] - 1 - RF / 252
    return float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else 0.0


def judge(new: dict, base: dict, s_new: float, s_base: float) -> tuple:
    y0, y1 = GATES["years"]
    pos = lambda st: sum(1 for y in range(y0, y1 + 1) if (st["by_year_pct"].get(y, st["by_year_pct"].get(str(y))) or 0) > 0)
    g = {"risk": new["max_drawdown_pct"] >= base["max_drawdown_pct"] + GATES["dd_better_pts"],
         "return": (new["cagr_pct"] or -99) >= (base["cagr_pct"] or 0) - GATES["cagr_worse_max_pts"],
         "quality": s_new > s_base, "stability": pos(new) >= pos(base)}
    return g, all(g.values())


def run_backtest(oos=None, out=None):
    cfg = C.load_cfg(); t0 = time.time()
    O = pd.read_pickle(oos or (P.ROOT / "data" / "aladin_cache" / "oos_5.pkl")); O["date"] = pd.to_datetime(O["date"]); O = O.dropna(subset=["p"])
    cache = {}

    def prep(sym):
        if sym not in cache:
            cache[sym] = P.prep_prices(L.load_prices(sym), cfg)
        return cache[sym]
    universe = P._universe_meta(); universe = {s: v for s, v in universe.items() if s in set(O["sym"])}
    books = P.books_from_scores(O, prep, cfg, universe)
    syms = sorted({p["sym"] for b in books for p in b["picks"]}); prices = {s: prep(s)["px"] for s in syms if prep(s) is not None}
    idx = L.load_index(); cal = idx.index[idx.index >= pd.Timestamp(books[0]["as_of"]) - pd.Timedelta(days=5)]; rate = P.fund_daily(cal)
    regime, vscale = market_filters(idx)
    print(f"{len(books)} books ({time.time() - t0:.0f}s)", flush=True)

    def bot(**kw):
        r = P.simulate(books, prices, cal, cfg, exits=P.BOT["exits"], risk_pct=P.BOT["risk_pct"], max_pos_pct=P.BOT["max_pos_pct"], **kw)
        r["equity"] = P.overlay(r["equity"], rate); return r
    variants = {"v3 (current bot, same code)": {}, "v5.1 (roll + brake)": dict(roll=True, brake_pct=V51["brake_pct"]), "v5 (all five changes)": dict(roll=True, regime=regime, brake_pct=V5["brake_pct"], stop_pct=V5["stop_pct"], vol_scale=vscale),
                "info: roll only": dict(roll=True), "info: trend filter only": dict(regime=regime), "info: brake only": dict(brake_pct=V5["brake_pct"]),
                "info: loss limit only": dict(stop_pct=V5["stop_pct"], regime=None), "info: vol scale only": dict(vol_scale=vscale)}
    runs, st = {}, {}
    for k, kw in variants.items():
        runs[k] = bot(**kw); s = P.stats(runs[k]); s["sharpe_over_cash"] = round(sharpe(runs[k]["equity"]), 3)
        s["costs_per_year"] = round(s["costs_paid"] / max(1, (pd.Timestamp(s["to"]) - pd.Timestamp(s["from"])).days / 365.25), 0); st[k] = s
        print(f"  {k}: CAGR {s['cagr_pct']}% DD {s['max_drawdown_pct']}% Sharpe(cash) {s['sharpe_over_cash']} trades {s['trades']} costs/yr {s['costs_per_year']:,.0f} ({time.time() - t0:.0f}s)", flush=True)
    base, new = st["v3 (current bot, same code)"], st["v5 (all five changes)"]
    gates, ok = judge(new, base, new["sharpe_over_cash"], base["sharpe_over_cash"])
    n2 = st["v5.1 (roll + brake)"]; gates2, ok2 = judge(n2, base, n2["sharpe_over_cash"], base["sharpe_over_cash"])
    doc = {"kind": "HISTORICAL SIMULATION (rule v5, pre-declared)", "created_utc": pd.Timestamp.utcnow().isoformat(), "protocol": __doc__.strip(), "v5": V5, "gates_declared": GATES,
           "stats": st, "equity": {k: r["equity"][::5] + [r["equity"][-1]] for k, r in runs.items() if not k.startswith("info")},
           "verdict": {"gates": gates, "pass": ok}, "verdict_round2": {"judged": "v5.1 (roll + brake)", "second_look": True, "gates": gates2, "pass": ok2},
           "runtime_s": round(time.time() - t0)}
    Path(out or OUT).write_text(json.dumps(doc, separators=(",", ":"), default=float), encoding="utf-8")
    print(f"VERDICT round 1 (v5): {'PASS' if ok else 'FAIL'} {gates}")
    print(f"VERDICT round 2 (v5.1, second look): {'PASS' if ok2 else 'FAIL'} {gates2}")
    return doc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--backtest", action="store_true"); a = ap.parse_args()
    if a.backtest:
        run_backtest()


if __name__ == "__main__":
    main()
