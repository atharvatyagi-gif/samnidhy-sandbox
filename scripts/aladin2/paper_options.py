"""
ALADIN paper bot: ways to raise the return, tested on the same 13-year history as the bot (HISTORICAL SIMULATION, not live, not real money).

  python -m scripts.aladin2.paper_options [--workers 12]      -> data/aladin2/paper/options.json
Every option re-runs the ONE simulator (paper.simulate) on the same Friday books, prices and costs; only the named setting changes. Options declared 2026-10-09 before any result was seen:
  O0  the bot today: stop + 5-day time exit, 1% risk, at most 10% a stock, idle cash earns nothing
  O1  no stop (time exit only)                         the 13-year ablation already hinted the stop cuts recoveries
  O2  idle cash in a liquid fund                        India call-money rate (FRED IRSTCI01INM156N, monthly) minus 0.30% a year for fund costs
  O3  idle cash in a NIFTY 50 index fund                NIFTY price index (no dividends: understated), each switch in or out pays 0.10% (stamp duty, exchange and SEBI fees, GST, spread; the stock
                                                        cost model's 0.49% at the most liquid decile was used in the first run and is far above an index fund's real cost)
  O4  bigger bets                                       2% risk per trade, at most 20% a stock (same 10 positions)
  O5  O1 + O2                                           no stop, idle cash in a liquid fund
  O6  O1 + O3 + O4                                      the aggressive mix
  O7  O1 + O2 + O4                                      ADDED AFTER the first results were seen (2026-10-09): the mix without the index fund's -38% falls; treat it as a hypothesis
Idle-cash overlays are added on top of the bot's account: their gains compound in their own pot and are NOT fed back into the bot's position sizes (simpler, slightly understated).
Each option is also reported for 2013-2020 and 2021-2026 separately, so an option that only worked early is visible. Picking the best of eight on the same history flatters the winner.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import paper as P

SPLIT = "2021-01-01"
india_rate, overlay, RATE_FILE, FUND_FEE = P.india_rate, P.overlay, P.RATE_FILE, P.FUND_FEE          # moved into paper.py when O7 became the bot (2026-10-09)


def period(eq, start=None, end=None):
    e = pd.Series([r[1] for r in eq], index=pd.to_datetime([r[0] for r in eq]))
    if start:
        e = e[e.index >= pd.Timestamp(start)]
    if end:
        e = e[e.index < pd.Timestamp(end)]
    if len(e) < 20:
        return None
    yrs = (e.index[-1] - e.index[0]).days / 365.25; dd = (e / e.cummax() - 1).min()
    return {"return_pct": round(float(e.iloc[-1] / e.iloc[0] - 1) * 100, 1), "cagr_pct": round(float((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100, 2), "max_drawdown_pct": round(float(dd) * 100, 1)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--refresh-rate", action="store_true"); ap.add_argument("--out", default=str(P.OUT / "options.json")); a = ap.parse_args()
    t0 = time.time(); cfg = C.load_cfg()
    O = pd.read_pickle(P.ROOT.parent / "SAMNIDHY_EDUCATIONAL_DASHBOARD" / "data" / "aladin_cache" / "oos_5.pkl"); O["date"] = pd.to_datetime(O["date"]); O = O.dropna(subset=["p"])
    cache = {}
    def prep(sym):
        if sym not in cache:
            cache[sym] = P.prep_prices(L.load_prices(sym), cfg)
        return cache[sym]
    uni = {s: v for s, v in P._universe_meta().items() if s in set(O["sym"])}
    books = P.books_from_scores(O, prep, cfg, uni); syms = sorted({p["sym"] for b in books for p in b["picks"]}); prices = {s: prep(s)["px"] for s in syms if prep(s) is not None}
    nifty = L.load_index(); cal = nifty.index; cal = cal[cal >= pd.Timestamp(books[0]["as_of"]) - pd.Timedelta(days=5)]
    nifty_ret = nifty.pct_change().reindex(cal).fillna(0.0); nifty_ret = nifty_ret.where(nifty_ret.abs() < 0.2, 0.0)
    rate = india_rate(a.refresh_rate); r_day = ((rate - FUND_FEE * 100).clip(lower=0) / 100 / 252).reindex(cal, method="ffill").fillna(0.0)
    etf_cost = 0.0010                                                                                 # one switch into or out of an index fund (see O3)
    print(f"{len(books)} books, {len(prices)} stocks ({time.time() - t0:.0f}s); NIFTY switch cost {etf_cost * 1e4:.1f} bps", flush=True)
    base = lambda **k: P.simulate(books, prices, cal, cfg, **k)
    r0 = base(); r1 = base(exits=("time",)); r4 = base(risk_pct=2.0, max_pos_pct=20); r14 = base(exits=("time",), risk_pct=2.0, max_pos_pct=20)
    eqs = {"O0 the bot today": (r0, r0["equity"]), "O1 no stop (time exit only)": (r1, r1["equity"]), "O2 idle cash in a liquid fund": (r0, overlay(r0["equity"], r_day)),
           "O3 idle cash in a NIFTY 50 index fund": (r0, overlay(r0["equity"], nifty_ret, etf_cost)), "O4 bigger bets (2% risk, 20% a stock)": (r4, r4["equity"]),
           "O5 no stop + liquid fund": (r1, overlay(r1["equity"], r_day)), "O6 no stop + NIFTY fund + bigger bets": (r14, overlay(r14["equity"], nifty_ret, etf_cost)),
           "O7 no stop + liquid fund + bigger bets (added after first results)": (r14, overlay(r14["equity"], r_day))}
    mkt = pd.Series((1 + nifty_ret).cumprod().values * P.START_CASH, index=cal); mkt_eq = [[str(d.date()), float(v), 0.0, 0] for d, v in mkt.items()]
    out = {"kind": "HISTORICAL SIMULATION", "label": "HISTORICAL SIMULATION 2013-2026: the same signals and costs as the bot, one setting changed per option. Not live, not real money. Picking the best of eight on the same history flatters the winner.",
           "protocol": __doc__.strip(), "created_utc": pd.Timestamp.utcnow().isoformat(), "rate_source": json.loads(RATE_FILE.read_text(encoding="utf-8"))["src"], "nifty_switch_cost_bps": round(etf_cost * 1e4, 1), "options": {}}
    for name, (res, eq) in list(eqs.items()) + [("NIFTY 50 held all the time (price index, no costs)", (None, mkt_eq))]:
        st = P.stats({"equity": eq, "trades": res["trades"] if res else []}) if res else {}
        weekly = [[r[0], r[1]] for k, r in enumerate(eq) if k % 5 == 0 or k == len(eq) - 1]
        out["options"][name] = {"all": period(eq), "2013-2020": period(eq, end=SPLIT), "2021-2026": period(eq, start=SPLIT), "trades": st.get("trades"), "win_rate": st.get("win_rate"), "profit_factor": st.get("profit_factor"),
                                "avg_invested_pct": st.get("avg_invested_pct"), "end_equity": round(eq[-1][1]), "curve": weekly}
        print(f"  {name:45s} all {out['options'][name]['all']}  | 13-20 {out['options'][name]['2013-2020']} | 21-26 {out['options'][name]['2021-2026']}", flush=True)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8"); print("wrote", a.out, f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
