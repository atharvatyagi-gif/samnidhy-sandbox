"""
ALADIN trading bot, round 2: trading behaviour on the tested edge (owner, 2026-10-14, after the swing rules failed: "trading behaviour on the current edge").

  python -m scripts.aladin2.trader --backtest      -> data/aladin2/paper/trader_backtest.json

RULES, written down BEFORE any result was seen (2026-10-14). Only three things change from the current bot (v3); everything else is v3 exactly:
  same     the Friday list from ALADIN 1's 5-day score (best 1% = long), entry at the next open, out at the open five trading days later, 2% of the
           account at risk to the sizing level, at most 20% of the account in one stock, at most 10 positions, at most 30% in one sector, the liquidity
           and edge caps, full delivery costs, idle cash in the liquid fund.
  NEW 1    SHORTS: the bottom of the same ranking (the existing SELL bucket, worst 2%) is shorted through stock futures, only stocks with futures that
           day, only from 2020 (F&O data starts then). Same entry, same 5-day hold, sized the same way to a level as far ABOVE the price as the long
           sizing level is below it, futures costs on both legs, all shorts together at most 50% of the account. Lot sizes and the futures-spot basis
           are not modelled (stated limitation).
  NEW 2    A PROTECTIVE STOP on every position, 3 x ATR(14) from the entry (below for longs, above for shorts), a live order checked against each day's
           low/high; a gap through it fills at the open. Wide on purpose: it is there for disasters, not to trade the noise (round 1 showed that
           tight stops destroy this edge).
  NEW 3    A daily check of every position (the live page shows each day's orders, fills and exits); this changes no number in a replay.

GATES (judged ONCE on 2013-01 to 2026-09; the current bot v3 is replayed with the SAME code, books, prices and dates):
  1  return     CAGR above v3's
  2  risk       maximum drawdown no deeper than v3's
  3  quality    profit factor at least 1.2 over at least 300 closed trades
  4  stability  at least as many positive full calendar years (2013-2025) as v3
  5  shorts     the short side's own net P/L after its costs is positive; if not, the SAME rules without shorts (v3 + protective stop) are judged
                instead, once, and the record says so.
  All pass -> the live paper account switches to these rules (rule v4, written into the rule history). Any fail -> v3 stays and this report is published.
"""
import argparse
import json
import time
from pathlib import Path

import pandas as pd

from . import costs as C
from . import data_lake as L
from . import paper as P

OUT = P.OUT / "trader_backtest.json"
PROTECT_ATR, SHORT_CAP = 3.0, 50.0
GATES = {"years": (2013, 2025), "min_trades": 300, "min_pf": 1.2}


def fno_lookup():
    """-> f(date) giving the set of stocks with futures on the latest F&O day on or before date (None before 2020 or without data)."""
    folder = L.TERM / "aladin2" / "fno"; days = {}
    for f in sorted(folder.glob("20*.json")):
        try:
            days[pd.Timestamp(f.stem)] = set(json.loads(f.read_text(encoding="utf-8")).get("d", {}))
        except (OSError, ValueError):
            pass
    keys = sorted(days)

    def f(d):
        if d < pd.Timestamp("2020-01-01") or not keys:
            return None
        import bisect
        j = bisect.bisect_right(keys, d) - 1
        return days[keys[j]] if j >= 0 else None
    return f


def judge(new, base, years=GATES["years"]):
    """Pure. new, base: stats() dicts. -> (gates, all passed)."""
    pos = lambda st: sum(1 for y in range(years[0], years[1] + 1) if (st["by_year_pct"].get(y, st["by_year_pct"].get(str(y))) or 0) > 0)
    g = {"return": (new["cagr_pct"] or -99) > (base["cagr_pct"] or 99), "risk": new["max_drawdown_pct"] >= base["max_drawdown_pct"],
         "quality": (new["profit_factor"] or 0) >= GATES["min_pf"] and new["trades"] >= GATES["min_trades"], "stability": pos(new) >= pos(base)}
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
    books = P.books_from_scores(O, prep, cfg, universe, shorts=fno_lookup())
    longs = [{**b, "picks": [p for p in b["picks"] if p.get("side", "long") == "long"]} for b in books]
    syms = sorted({p["sym"] for b in books for p in b["picks"]}); prices = {s: prep(s)["px"] for s in syms if prep(s) is not None}
    cal = L.load_index().index; cal = cal[cal >= pd.Timestamp(books[0]["as_of"]) - pd.Timedelta(days=5)]
    rate = P.fund_daily(cal)
    print(f"{len(books)} books, {sum(1 for b in books for p in b['picks'] if p.get('side') == 'short')} short picks ({time.time() - t0:.0f}s)", flush=True)

    def bot(bk, protect):
        r = P.simulate(bk, prices, cal, cfg, exits=P.BOT["exits"], risk_pct=P.BOT["risk_pct"], max_pos_pct=P.BOT["max_pos_pct"], protect_atr=protect, short_cap_pct=SHORT_CAP)
        r["equity"] = P.overlay(r["equity"], rate); return r                               # idle cash in the liquid fund, exactly as the bot
    runs = {"v3 (current bot, same code)": bot(longs, None), "v4: long + short + protective stop": bot(books, PROTECT_ATR), "v4 without shorts: long + protective stop": bot(longs, PROTECT_ATR)}
    st = {k: P.stats(r) for k, r in runs.items()}
    for k, r in runs.items():
        st[k]["by_side_net"] = {s: round(sum(t["net"] for t in r["trades"] if t.get("side", "long") == s), 2) for s in ("long", "short")}
        print(f"  {k}: CAGR {st[k]['cagr_pct']}% DD {st[k]['max_drawdown_pct']}% PF {st[k]['profit_factor']} trades {st[k]['trades']} by side {st[k]['by_side_net']} exits {st[k]['exits']}", flush=True)
    base = st["v3 (current bot, same code)"]
    judged = "v4: long + short + protective stop" if st["v4: long + short + protective stop"]["by_side_net"]["short"] > 0 else "v4 without shorts: long + protective stop"
    gates, ok = judge(st[judged], base)
    doc = {"kind": "HISTORICAL SIMULATION (trading rules on the tested edge, pre-declared)", "created_utc": pd.Timestamp.utcnow().isoformat(), "protocol": __doc__.strip(),
           "protect_atr": PROTECT_ATR, "short_cap_pct": SHORT_CAP, "gates_declared": GATES, "stats": st,
           "equity": {k: r["equity"][::5] + [r["equity"][-1]] for k, r in runs.items()}, "recent_trades": runs[judged]["trades"][-150:],
           "verdict": {"judged": judged, "why_judged": "the short side made money after its costs" if judged.startswith("v4: long + short") else "the short side lost money after its costs, so the rules without shorts are judged (declared in advance)",
                       "gates": gates, "pass": ok}, "runtime_s": round(time.time() - t0)}
    f = Path(out or OUT); f.write_text(json.dumps(doc, separators=(",", ":"), default=float), encoding="utf-8")
    print(f"VERDICT ({judged}): {'PASS' if ok else 'FAIL'} {gates}")
    return doc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--backtest", action="store_true"); a = ap.parse_args()
    if a.backtest:
        run_backtest()


if __name__ == "__main__":
    main()
