"""
ALADIN swing trading bot (owner, 2026-10-14: "not an investing bot, a TRADING bot"; chose swing 1-5 days, long AND short, backtest gate before live).

  python -m scripts.aladin2.swing --backtest      -> data/aladin2/paper/swing_backtest.json   (the pre-declared test; its verdict decides whether the live account switches)

RULES, written down BEFORE any result was seen (2026-10-14). Nothing below is tuned on the test years.
  BIAS (weekly)   the ALADIN movers ranking (scripts/aladin_movers.py, stocks only; the one ALADIN signal that passed its own test: ranking by expected 5-day
                  move, top tenth minus bottom tenth +0.186%/week after costs, 8 of 11 years). Each Friday after the close: LONG LIST = the top tenth by
                  expected move; SHORT LIST = the bottom tenth, only stocks with futures that day (NSE F&O list), only from 2020 (F&O data starts then).
                  A list is used for every daily decision until the next Friday's list replaces it.
  TRIGGERS (daily, at each close, acted on at the NEXT open)
                  long   a stock on the long list whose close is above the highest high of the previous 20 days (breakout), OR whose 2-day RSI is below 15
                         while the close is above its 50-day average (pullback in an uptrend)
                  short  a stock on the short list whose close is below the lowest low of the previous 20 days (breakdown), OR whose 2-day RSI is above 85
                         while the close is below its 50-day average (bounce in a downtrend)
                  Several triggers on one day: taken in ranking order (strongest expected move first).
  ENTRY           the next day's open. Not taken if the stock is already held, if 12 positions are open, or if it opens beyond its own stop.
  EXITS           initial stop 1.5 x ATR(14) from the entry; profit-taking level 3 x ATR (twice the risk). Both are live orders checked against each day's
                  high and low (the stop first when one day touches both; a gap through either fills at the open). Once a trade is 1.5 ATR in profit at a
                  close, the stop moves to the entry price, and from then trails 1.5 ATR behind the best close. Time limit: out at the open of the 6th
                  trading day (at most 5 days held).
  SIZE            1% of the account lost if the stop is hit; at most 10% of the account in one stock; at most 5% of the stock's average daily volume;
                  longs need the cash (no leverage); shorts are stock futures: their notional counts against a cap of 50% of the account, and the
                  long + short notional together may not exceed 100% of the account. Futures lot sizes and the futures-spot basis are NOT modelled
                  (stated limitation): the short is priced on the stock's own prices.
  COSTS           longs: the full delivery cost model (costs.py) at the stock's liquidity decile, both legs; shorts: the futures cost model, both legs.
                  Idle cash earns the liquid-fund rate, exactly as the current bot.
  UNIVERSE        the movers universe (ordinary equity on NSE's main board, liquid); stocks listed today, so the past is flattered (survivorship), as before.

GATES (judged ONCE on 2016-01 to 2026-09, against the CURRENT bot v3's own replay over exactly the same dates, both after all costs):
  1  return     CAGR above the current bot's CAGR over the same dates
  2  risk       maximum drawdown no deeper than the current bot's over the same dates, and no deeper than 30%
  3  quality    profit factor at least 1.2 over at least 300 closed trades
  4  stability  positive in at least 6 of the 10 full calendar years 2016-2025
  5  shorts     the short side's own net P/L (after its costs) is positive; if it is not, the SAME rules without shorts are judged instead, once,
                and the record says so
  All pass -> the live paper account switches to these rules (a rule-history line is written). Any fail -> the current bot stays; this report is published.
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

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "aladin2" / "paper" / "swing_backtest.json"
MOVERS_OOS = ROOT / "data" / "aladin_movers" / "oos.csv.gz"
RULES = {"bias": "ALADIN movers ranking: long list = top tenth by expected 5-day move, short list = bottom tenth (F&O stocks, from 2020)", "breakout_days": 20,
         "rsi2_long_below": 15, "rsi2_short_above": 85, "trend_sma": 50, "stop_atr": 1.5, "target_atr": 3.0, "breakeven_after_atr": 1.5, "trail_atr": 1.5,
         "max_days": 5, "risk_pct": 1.0, "max_pos_pct": 10.0, "adv_participation": 0.05, "max_open": 12, "short_cap_pct": 50.0, "gross_cap_pct": 100.0,
         "costs": "longs: delivery; shorts: stock futures; both legs, at the stock's liquidity decile", "idle_cash": "liquid-fund rate, as the current bot"}
GATES = {"years": (2016, 2025), "min_trades": 300, "min_pf": 1.2, "max_dd_floor_pct": -30.0, "min_positive_years": 6}


def _rsi2(c):
    d = np.diff(c, prepend=np.nan); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    a = 1 / 2.0
    ru = pd.Series(up).ewm(alpha=a, adjust=False).mean().values; rd = pd.Series(dn).ewm(alpha=a, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + ru / rd)


def prep(px):
    """Per-stock daily arrays known at each close (row t uses bars up to t only). Pure."""
    if px is None or len(px) < 80:
        return None
    px = L.clean_prices(px)
    o, h, l, c, v = (px[k].values.astype(float) for k in ("o", "h", "l", "c", "v"))
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); tr[0] = h[0] - l[0]
    atr = pd.Series(tr).rolling(14, min_periods=14).mean().values
    hh = pd.Series(h).shift(1).rolling(RULES["breakout_days"], min_periods=RULES["breakout_days"]).max().values
    ll = pd.Series(l).shift(1).rolling(RULES["breakout_days"], min_periods=RULES["breakout_days"]).min().values
    sma = pd.Series(c).rolling(RULES["trend_sma"], min_periods=RULES["trend_sma"]).mean().values
    rsi = _rsi2(c)
    adv_cr = (pd.Series(c * v).rolling(250, min_periods=120).mean() / 1e7).values
    with np.errstate(invalid="ignore"):
        long_t = ((c > hh) | ((rsi < RULES["rsi2_long_below"]) & (c > sma)))
        short_t = ((c < ll) | ((rsi > RULES["rsi2_short_above"]) & (c < sma)))
    return {"idx": {d: i for i, d in enumerate(px.index)}, "dates": px.index, "o": o, "h": h, "l": l, "c": c, "atr": atr, "adv_cr": adv_cr,
            "adv_sh": np.where(c > 0, adv_cr * 1e7 / np.where(c > 0, c, 1), 0), "long": long_t, "short": short_t}


def lists_from_movers(M, fno_by_date):
    """M: movers out-of-sample rows (sym, date, exp_move). -> {friday: {"long": [syms best first], "short": [syms worst first]}}. Pure."""
    out = {}
    fno_dates = sorted(fno_by_date)
    for d, g in M.groupby("date"):
        g = g.sort_values("exp_move", ascending=False); k = max(1, len(g) // 10)
        longs = list(g["sym"].values[:k]); shorts = []
        if d >= pd.Timestamp("2020-01-01") and fno_dates:
            j = np.searchsorted(fno_dates, d, side="right") - 1
            if j >= 0:
                fno = fno_by_date[fno_dates[j]]
                shorts = [s for s in g["sym"].values[::-1][:k] if s in fno]
        out[pd.Timestamp(d)] = {"long": longs, "short": shorts}
    return out


def simulate(lists, prices, cal, cfg, cash0=P.START_CASH, allow_short=True, deciles=None, sectors=None):
    """The rules above, day by day on the calendar cal. prices: {sym: prep()}. -> {equity, trades, open}. Pure apart from the cost model."""
    R = RULES; fridays = sorted(lists); cash = float(cash0); pos = {}; trades = []; rows = []; pending = []
    deciles = deciles or {}; sectors = sectors or {}

    def mark(sym, p, i):
        a = prices[sym]; j = a["idx"].get(cal[i]); return a["c"][j] if j is not None and np.isfinite(a["c"][j]) else p["last"]

    def equity(i):
        e = cash
        for s, p in pos.items():
            m = mark(s, p, i); p["last"] = m
            e += p["qty"] * m if p["side"] == "long" else p["qty"] * (p["entry"] - m)
        return e

    def leg(side, kind_leg, value, sym):
        kind = "delivery" if side == "long" else "futures"
        return float(C.leg_cost(kind_leg, value, kind, deciles.get(sym, 5), cfg)["total"])

    def close(sym, i, fill, why):
        nonlocal cash
        p = pos.pop(sym); val = p["qty"] * fill
        cost_out = leg(p["side"], "sell" if p["side"] == "long" else "buy", val, sym)
        gross = p["qty"] * (fill - p["entry"]) * (1 if p["side"] == "long" else -1)
        cash += (val if p["side"] == "long" else gross) - cost_out
        net = gross - p["cost_in"] - cost_out
        trades.append({"sym": sym, "side": p["side"], "setup": p["setup"], "entry_date": str(cal[p["i"]].date()), "exit_date": str(cal[i].date()), "days": int(i - p["i"]),
                       "qty": p["qty"], "entry": round(p["entry"], 2), "exit": round(float(fill), 2), "reason": why, "capital": round(p["qty"] * p["entry"], 2),
                       "gross": round(gross, 2), "costs": round(p["cost_in"] + cost_out, 2), "net": round(net, 2), "ret_pct": round(net / (p["qty"] * p["entry"]) * 100, 3)})

    for i in range(len(cal)):
        d = cal[i]
        # 1. the time limit, at the open
        for s, p in list(pos.items()):
            a = prices[s]; j = a["idx"].get(d)
            if j is not None and i - p["i"] >= R["max_days"] and np.isfinite(a["o"][j]):          # entered on day i0: out at the open of day i0 + 5
                close(s, i, a["o"][j], "time")
        # 2. entries at the open from yesterday's triggers (strongest first)
        eq = equity(i - 1) if i else cash
        for side, s, setup in pending:
            if s in pos or len(pos) >= R["max_open"]:
                continue
            a = prices[s]; j = a["idx"].get(d)
            if j is None or j == 0 or not np.isfinite(a["o"][j]) or not np.isfinite(a["atr"][j - 1]) or a["atr"][j - 1] <= 0:
                continue
            o, atr = a["o"][j], a["atr"][j - 1]; sgn = 1 if side == "long" else -1
            stop, target = o - sgn * R["stop_atr"] * atr, o + sgn * R["target_atr"] * atr
            if stop <= 0:
                continue
            q = min(eq * R["risk_pct"] / 100 / (R["stop_atr"] * atr), eq * R["max_pos_pct"] / 100 / o, R["adv_participation"] * (a["adv_sh"][j - 1] if np.isfinite(a["adv_sh"][j - 1]) else 0))
            longs = sum(p["qty"] * p["last"] for p in pos.values() if p["side"] == "long"); shorts = sum(p["qty"] * p["last"] for p in pos.values() if p["side"] == "short")
            room = eq * R["gross_cap_pct"] / 100 - longs - shorts
            if side == "short":
                room = min(room, eq * R["short_cap_pct"] / 100 - shorts)
            q = int(max(0, min(q, room / o)))
            while q > 0:
                cost_in = leg(side, "buy" if side == "long" else "sell", q * o, s)
                if (q * o + cost_in if side == "long" else cost_in) <= cash:
                    break
                q -= 1
            if q < 1:
                continue
            cash -= (q * o + cost_in) if side == "long" else cost_in
            pos[s] = {"side": side, "setup": setup, "qty": q, "entry": o, "stop": stop, "target": target, "atr": atr, "i": i, "best": o, "cost_in": cost_in, "last": o}
        pending = []
        # 3. stops and profit-taking during the day (the stop first when both are touched; a gap fills at the open)
        for s, p in list(pos.items()):
            a = prices[s]; j = a["idx"].get(d)
            if j is None or not np.isfinite(a["l"][j]):
                continue
            o, hi, lo = a["o"][j], a["h"][j], a["l"][j]
            if p["side"] == "long":
                if lo <= p["stop"]:
                    close(s, i, min(o, p["stop"]) if i > p["i"] else p["stop"], "stop")
                elif hi >= p["target"]:
                    close(s, i, max(o, p["target"]) if i > p["i"] else p["target"], "target")
            else:
                if hi >= p["stop"]:
                    close(s, i, max(o, p["stop"]) if i > p["i"] else p["stop"], "stop")
                elif lo <= p["target"]:
                    close(s, i, min(o, p["target"]) if i > p["i"] else p["target"], "target")
        # 4. at the close: move the stop to the entry after 1.5 ATR in profit, then trail it behind the best close
        for s, p in pos.items():
            a = prices[s]; j = a["idx"].get(d)
            if j is None or not np.isfinite(a["c"][j]):
                continue
            c = a["c"][j]
            if p["side"] == "long":
                p["best"] = max(p["best"], c)
                if p["best"] - p["entry"] >= R["breakeven_after_atr"] * p["atr"]:
                    p["stop"] = max(p["stop"], p["entry"], p["best"] - R["trail_atr"] * p["atr"])
            else:
                p["best"] = min(p["best"], c)
                if p["entry"] - p["best"] >= R["breakeven_after_atr"] * p["atr"]:
                    p["stop"] = min(p["stop"], p["entry"], p["best"] + R["trail_atr"] * p["atr"])
        # 5. tonight's triggers, from the latest list (a Friday's list is used from that Friday's close)
        k = np.searchsorted(fridays, d, side="right") - 1
        if k >= 0 and (d - fridays[k]).days <= 9:
            lst = lists[fridays[k]]
            for side in ("long", "short") if allow_short else ("long",):
                for s in lst[side]:
                    a = prices.get(s); j = a["idx"].get(d) if a else None
                    if j is None or not (a[side][j]) or not np.isfinite(a["adv_cr"][j]) or a["adv_cr"][j] < 5.0:
                        continue
                    pending.append((side, s, "breakout" if (side == "long" and j > 20 and a["c"][j] > np.nanmax(a["h"][j - 20:j])) or (side == "short" and j > 20 and a["c"][j] < np.nanmin(a["l"][j - 20:j])) else "pullback"))
        rows.append([str(d.date()), round(equity(i), 2), round(cash, 2), len(pos)])
    return {"equity": rows, "trades": trades, "open": [{"sym": s, **{k: v for k, v in p.items() if k in ("side", "qty", "entry", "stop", "target")}} for s, p in pos.items()]}


def judge(sw, cur, years=GATES["years"]):
    """The gates. sw, cur: stats() of the swing bot and the current bot over the same dates, plus by-side P/L. Pure."""
    yrs = [sw["by_year_pct"].get(y) for y in range(years[0], years[1] + 1)]
    g = {"return": sw["cagr_pct"] is not None and cur["cagr_pct"] is not None and sw["cagr_pct"] > cur["cagr_pct"],
         "risk": sw["max_drawdown_pct"] >= max(cur["max_drawdown_pct"], GATES["max_dd_floor_pct"]),
         "quality": (sw["profit_factor"] or 0) >= GATES["min_pf"] and sw["trades"] >= GATES["min_trades"],
         "stability": sum(1 for v in yrs if v is not None and v > 0) >= GATES["min_positive_years"]}
    return g, all(g.values())


def window_stats(rows, cash0, trades=()):
    """stats() over a slice of equity rows, rebased to its first value."""
    if not rows:
        return {"started": False}
    base = rows[0][1]; sc = cash0 / base
    return P.stats({"equity": [[d, e * sc, c * sc, n] for d, e, c, n in rows], "trades": list(trades)}, cash0)


def run_backtest(out=None, workers=None):
    cfg = C.load_cfg(); t0 = time.time()
    M = pd.read_csv(MOVERS_OOS, usecols=["sym", "date", "exp_move"], parse_dates=["date"])
    fdir = L.TERM / "aladin2" / "fno"; fno = {}
    for f in sorted(fdir.glob("20*.json")):
        try:
            fno[pd.Timestamp(f.stem)] = set(json.loads(f.read_text(encoding="utf-8")).get("d", {}))
        except (OSError, ValueError):
            pass
    lists = lists_from_movers(M, fno)
    syms = sorted({s for v in lists.values() for k in ("long", "short") for s in v[k]})
    prices = {}
    for s in syms:
        a = prep(L.load_prices(s))
        if a is not None:
            prices[s] = a
    lists = {d: {k: [s for s in v[k] if s in prices] for k in v} for d, v in lists.items()}
    uni = P._universe_meta(); allv = [v["adv_cr"] for v in uni.values()]
    deciles = {s: C.adv_decile(uni[s]["adv_cr"], allv) for s in prices if s in uni}
    start, end = min(lists) + pd.Timedelta(days=1), max(lists) + pd.Timedelta(days=7)
    cal = pd.DatetimeIndex(sorted({d for a in prices.values() for d in a["dates"] if start <= d <= end}))
    print(f"{len(lists)} weekly lists, {len(prices)} stocks, {len(cal)} trading days ({time.time() - t0:.0f}s)", flush=True)
    rate = P.fund_daily(cal)
    res = {}
    for name, sh in (("long_short", True), ("long_only", False)):
        r = simulate(lists, prices, cal, cfg, allow_short=sh, deciles=deciles); r["equity"] = P.overlay(r["equity"], rate); res[name] = r
        print(f"  {name}: {len(r['trades'])} trades ({time.time() - t0:.0f}s)", flush=True)
    cur_doc = json.loads((P.OUT / "backtest.json").read_text(encoding="utf-8"))
    d0, d1 = res["long_short"]["equity"][0][0], res["long_short"]["equity"][-1][0]
    cur_rows = [r for r in cur_doc["equity"] if d0 <= r[0] <= d1]
    cur = window_stats(cur_rows, P.START_CASH)
    out_doc = {"kind": "HISTORICAL SIMULATION (swing trading rules, pre-declared)", "created_utc": pd.Timestamp.utcnow().isoformat(), "rules": RULES, "gates_declared": GATES,
               "protocol": __doc__.strip(), "period": [d0, d1], "current_bot_same_dates": cur, "runtime_s": round(time.time() - t0)}
    side_pl = {k: {s: round(sum(t["net"] for t in r["trades"] if t["side"] == s), 2) for s in ("long", "short")} for k, r in res.items()}
    judged = "long_short" if side_pl["long_short"]["short"] > 0 else "long_only"
    for k, r in res.items():
        st = P.stats(r)
        st["by_side_net"] = side_pl[k]; st["by_setup_net"] = {s: round(sum(t["net"] for t in r["trades"] if t["setup"] == s), 2) for s in ("breakout", "pullback")}
        st["exits_detail"] = {x: sum(1 for t in r["trades"] if t["reason"] == x) for x in ("stop", "target", "time")}
        out_doc[k] = {"stats": st, "equity": r["equity"][::5] + [r["equity"][-1]], "recent_trades": r["trades"][-150:]}
    gates, ok = judge(out_doc[judged]["stats"], cur)
    out_doc["verdict"] = {"judged": judged, "why_judged": "the short side made money after its costs" if judged == "long_short" else "the short side lost money after its costs, so the same rules without shorts are judged (declared in advance)",
                          "gates": gates, "pass": ok}
    f = Path(out or OUT); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(out_doc, separators=(",", ":"), default=float), encoding="utf-8")
    s = out_doc[judged]["stats"]
    print(f"VERDICT ({judged}): {'PASS' if ok else 'FAIL'} {gates}\n  swing: CAGR {s['cagr_pct']}%, max DD {s['max_drawdown_pct']}%, PF {s['profit_factor']}, trades {s['trades']}, win {s['win_rate']}"
          f"\n  current bot same dates: CAGR {cur['cagr_pct']}%, max DD {cur['max_drawdown_pct']}%\n  by side {side_pl}")
    return out_doc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--backtest", action="store_true"); a = ap.parse_args()
    if a.backtest:
        run_backtest()


if __name__ == "__main__":
    main()
