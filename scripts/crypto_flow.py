"""
Bitcoin order-flow and Heikin-Ashi strategies: research simulator shared with the live engine (scripts/crypto_live.py), so the backtest and the front test cannot drift apart.

  python scripts/crypto_flow.py --study        -> data/crypto/study.json

Data: Binance BTCUSDT, 15-minute bars built from 1-minute candles (scripts/crypto_data.py), with TAKER BUY volume (aggressive buyers) -> signed flow, delta = taker buy - taker sell = 2 x taker buy - volume.
Long-only, spot-style, no leverage: the position is at most 100% of the account (a hard budget). Cash earns nothing.
Signals are computed at a bar's close; the order fills at the NEXT bar's open; a stop fills at its price, or at the open if the bar opens through it. Every fill pays COST (taker fee + slippage).
Size: risk 2% of the account to the stop, capped at 100% of the account.

Strategies, written down before any result was seen (timeframes 1h and 4h each; nothing is added or changed after a result):
  ha_trend       two Heikin-Ashi bars in a row that are green with no lower wick -> in; a red Heikin-Ashi bar -> out; stop 3 ATR
  ha_flow        the same entry only while buyers dominate the last 12 bars (flow z > 0.5); out on a red bar or flow z < -0.5; stop 3 ATR
  flow_momentum  buyers dominate the last 24 bars (flow z > 1) and price is above its 50-bar average -> in; out when flow z < 0; stop 3 ATR
  flow_absorb    price 1.5 sd below its 48-bar mean while the last 6 bars show strong net buying (flow z > 1): sellers are being absorbed -> in; out at the mean or after 24 bars; stop 2.5 ATR
  flow_breakout  close above the 24-bar high with delta and volume both more than 1 sd above normal -> in; out below the 12-bar low or on a red Heikin-Ashi bar; stop 3 ATR
flow z = how unusual the buy share of the last N bars' volume is, against the previous 500 bars. Selection years 2020-2023, held-out 2024 to 2026-09 (judged once). Ten variants were tried, so the best of them is flattered.
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BARS = ROOT / "data" / "crypto" / "bars_15m.csv.gz"
OUT = ROOT / "data" / "crypto"
COST = 0.0012                      # per fill: 0.10% taker fee + 0.02% slippage (Binance spot, no discount)
RISK = 0.02
SELECT_END = "2023-12-31 23:59"
MIN_TRADES = 50
TFS = {"1h": "1h", "4h": "4h"}
STRATS = ["ha_trend", "ha_flow", "flow_momentum", "flow_absorb", "flow_breakout"]


def bars_path(symbol="BTCUSDT"):
    return BARS if symbol == "BTCUSDT" else OUT / f"bars_15m_{symbol[:-4].lower()}.csv.gz"


def load_bars(path=None, symbol="BTCUSDT"):
    return pd.read_csv(path or bars_path(symbol), index_col=0, parse_dates=True)


def resample(b, tf):
    g = b.resample(TFS.get(tf, tf), label="left", closed="left")
    r = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(), "v": g["v"].sum(), "n": g["n"].sum(), "tbv": g["tbv"].sum(), "k": g["o"].count()}).dropna(subset=["o"])
    need = int(pd.Timedelta(TFS.get(tf, tf)) / pd.Timedelta("15min")); return r[r["k"] == need].drop(columns="k")


def _z(x, n=500):
    m, s = x.rolling(n, min_periods=100).mean().shift(1), x.rolling(n, min_periods=100).std().shift(1); return (x - m) / s


def features(b):
    """Everything a strategy needs, row i using bars up to and including i only."""
    f = b.copy(); f["delta"] = 2 * f["tbv"] - f["v"]
    pc = f["c"].shift(); tr = pd.concat([f["h"] - f["l"], (f["h"] - pc).abs(), (f["l"] - pc).abs()], axis=1).max(axis=1); f["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    hc = (f["o"] + f["h"] + f["l"] + f["c"]) / 4; ho = np.empty(len(f)); ho[0] = (f["o"].iloc[0] + f["c"].iloc[0]) / 2
    for i in range(1, len(f)):
        ho[i] = (ho[i - 1] + hc.iloc[i - 1]) / 2
    f["ha_c"], f["ha_o"] = hc, ho; f["ha_l"] = np.minimum(f["l"], np.minimum(ho, hc)); f["ha_green"] = f["ha_c"] > f["ha_o"]; f["ha_nowick"] = f["ha_l"] >= f["ha_o"] - 1e-9
    for n in (6, 12, 24):
        f[f"flow{n}"] = _z(f["delta"].rolling(n).sum() / f["v"].rolling(n).sum())
    f["delta_z"] = f["delta"] / f["delta"].rolling(100, min_periods=50).std().shift(1); f["vol_z"] = _z(f["v"], 100)
    f["sma50"] = f["c"].rolling(50).mean(); m48, s48 = f["c"].rolling(48).mean(), f["c"].rolling(48).std(); f["pz"] = (f["c"] - m48) / s48
    f["hi24"] = f["h"].shift(1).rolling(24).max(); f["lo12"] = f["l"].shift(1).rolling(12).min(); return f


STOP_ATR = {"ha_trend": 3.0, "ha_flow": 3.0, "flow_momentum": 3.0, "flow_absorb": 2.5, "flow_breakout": 3.0}
MAX_HOLD = {"flow_absorb": 24}


def signals(f, strat):
    """(enter, exit) boolean arrays: decided at each bar's close, acted on at the next open. 'exit' is the rule's own exit, besides the stop and the time limit."""
    nan = lambda s: s.fillna(0).values
    if strat == "ha_trend":
        e = f["ha_green"] & f["ha_nowick"] & f["ha_green"].shift(1, fill_value=False) & f["ha_nowick"].shift(1, fill_value=False); x = ~f["ha_green"]
    elif strat == "ha_flow":
        e = f["ha_green"] & f["ha_nowick"] & f["ha_green"].shift(1, fill_value=False) & f["ha_nowick"].shift(1, fill_value=False) & (f["flow12"] > 0.5); x = ~f["ha_green"] | (f["flow12"] < -0.5)
    elif strat == "flow_momentum":
        e = (f["flow24"] > 1.0) & (f["c"] > f["sma50"]); x = f["flow24"] < 0
    elif strat == "flow_absorb":
        e = (f["pz"] < -1.5) & (f["flow6"] > 1.0); x = f["pz"] > 0
    elif strat == "flow_breakout":
        e = (f["c"] > f["hi24"]) & (f["delta_z"] > 1) & (f["vol_z"] > 1); x = (f["c"] < f["lo12"]) | ~f["ha_green"]
    else:
        raise KeyError(strat)
    ok = f[["atr", "flow12", "flow24", "sma50", "pz", "hi24", "lo12", "vol_z", "delta_z"]].notna().all(axis=1)
    return (e & ok).fillna(False).values, x.fillna(False).values


def size_value(equity, price, stop, cost=COST, risk=RISK, cap=1.0):
    """Value to buy: risk 2% of the account to the stop, never more than the whole account (cap 1.0 = no leverage), fees included. Shared with the live engine."""
    dist = price - stop
    return max(0.0, min(equity * cap / (1 + cost), equity * risk / (dist / price))) if dist > 0 and price > 0 else 0.0


def simulate(f, strat, cash0=1.0, cost=COST, risk=RISK, cap=1.0, enter=None, exit_=None):
    """One sleeve over the bars. Returns {equity: Series (marked at each bar close), trades: [...]}. State machine mirrors the live engine."""
    en, ex = signals(f, strat) if enter is None else (enter, exit_); o, h, l, c, atr = (f[k].values for k in ("o", "h", "l", "c", "atr")); idx = f.index; n = len(f); k_atr = STOP_ATR[strat]; hold_max = MAX_HOLD.get(strat)
    cash, qty, entry, stop, held, eq, trades, pend_en, pend_ex, pend_stop = cash0, 0.0, 0.0, 0.0, 0, np.full(n, np.nan), [], False, False, 0.0
    ecost = 0.0
    def close(i, px, why):
        nonlocal cash, qty, ecost
        val = qty * px; fee = val * cost; cash += val - fee; net = qty * (px - entry) - ecost - fee
        trades.append({"in": str(idx[ent_i]), "out": str(idx[i]), "entry": round(entry, 2), "exit": round(px, 2), "ret_pct": round(net / (qty * entry) * 100, 4), "net": net, "why": why, "bars": held}); qty = 0.0
    ent_i = 0
    for i in range(n):
        if qty > 0 and pend_ex:
            close(i, o[i], "signal"); pend_ex = False
        if qty == 0 and pend_en and pend_stop > 0:
            equity = cash; dist = o[i] - pend_stop
            if dist > 0:
                val = size_value(equity, o[i], pend_stop, cost, risk, cap)
                if val > 0:
                    qty = val / o[i]; fee = val * cost; cash -= val + fee; entry, stop, held, ent_i, ecost = o[i], pend_stop, 0, i, fee
        pend_en = False
        if qty > 0:
            held += 1
            if l[i] <= stop:
                close(i, min(o[i], stop), "stop"); pend_ex = False
            elif hold_max and held >= hold_max:
                close(i, c[i], "time"); pend_ex = False
        eq[i] = cash + qty * c[i]
        if qty > 0 and ex[i]:
            pend_ex = True
        if qty == 0 and en[i] and not (math.isnan(atr[i])):
            pend_en, pend_stop = True, c[i] - k_atr * atr[i]
    return {"equity": pd.Series(eq, index=idx), "trades": trades}


def period_stats(eq, trades, start=None, end=None):
    e = eq.dropna(); lo = pd.Timestamp(start) if start else e.index[0]; hi = pd.Timestamp(end) if end else e.index[-1]
    seg = e[(e.index >= lo) & (e.index <= hi)]; tr = [t for t in trades if lo <= pd.Timestamp(t["out"]) <= hi]
    if len(seg) < 100:
        return {"trades": 0}
    base = e[e.index < lo].iloc[-1] if (e.index < lo).any() else seg.iloc[0]; d = seg.resample("1D").last().dropna(); dr = pd.concat([pd.Series([base]), d]).pct_change().dropna(); yrs = max((seg.index[-1] - seg.index[0]).days / 365.25, 1e-9)
    win = [t for t in tr if t["net"] > 0]; los = [t for t in tr if t["net"] <= 0]; gw, gl = sum(t["net"] for t in win), -sum(t["net"] for t in los); dd = (seg / np.maximum.accumulate(np.maximum(seg.values, base)) - 1).min()
    sd = dr.std()
    return {"trades": len(tr), "return_pct": round(float(seg.iloc[-1] / base - 1) * 100, 1), "cagr_pct": round(float((seg.iloc[-1] / base) ** (1 / yrs) - 1) * 100, 2), "max_drawdown_pct": round(float(dd) * 100, 1),
            "sharpe": round(float(dr.mean() / sd * math.sqrt(365)), 2) if sd > 0 else None, "win_rate": round(len(win) / len(tr), 3) if tr else None, "avg_net_pct": round(float(np.mean([t["ret_pct"] for t in tr])), 3) if tr else None,
            "profit_factor": round(gw / gl, 2) if gl > 0 else None, "stop_exits": sum(1 for t in tr if t["why"] == "stop"), "avg_bars": round(float(np.mean([t["bars"] for t in tr])), 1) if tr else None}


def boot_mean(tr, n=2000, seed=0):
    if len(tr) < 10:
        return None
    m = pd.Series([pd.Timestamp(t["out"]).strftime("%Y-%m") for t in tr]); r = np.array([t["ret_pct"] for t in tr]); s = pd.DataFrame({"m": m, "r": r}).groupby("m")["r"].agg(["sum", "count"]); rng = np.random.default_rng(seed)
    i = rng.integers(0, len(s), size=(n, len(s))); b = s["sum"].values[i].sum(1) / s["count"].values[i].sum(1); return [round(float(np.percentile(b, 2.5)), 3), round(float(np.percentile(b, 97.5)), 3)]


def study(bars=None, symbol="BTCUSDT"):
    bars = load_bars(symbol=symbol) if bars is None else bars; res, curves = {}, {}
    for tf in TFS:
        f = features(resample(bars, tf)); f = f[f.index >= "2020-01-15"]
        bh = (f["c"] / f["c"].iloc[0]).rename("bh")
        for s in STRATS:
            r = simulate(f, s); key = f"{s}_{tf}"
            res[key] = {"strategy": s, "timeframe": tf, "selection": period_stats(r["equity"], r["trades"], None, SELECT_END), "held_out": period_stats(r["equity"], r["trades"], "2024-01-01", None),
                        "held_out_trade_ci95_pct": boot_mean([t for t in r["trades"] if pd.Timestamp(t["out"]) >= pd.Timestamp("2024-01-01")]),
                        "held_out_high_cost": period_stats(simulate(f, s, cost=0.0025)["equity"], simulate(f, s, cost=0.0025)["trades"], "2024-01-01", None) if False else None}
            curves[key] = r["equity"].resample("7D").last().dropna()
        bhe = f["c"] / f["c"].iloc[0]
        res[f"buy_hold_{tf}"] = {"strategy": "buy_hold", "timeframe": tf, "selection": period_stats(bhe, [], None, SELECT_END), "held_out": period_stats(bhe, [], "2024-01-01", None)}
    for k in [k for k in res if not k.startswith("buy_hold")]:
        s, tf = res[k]["strategy"], res[k]["timeframe"]; f = features(resample(bars, tf)); f = f[f.index >= "2020-01-15"]; r2 = simulate(f, s, cost=0.0025)
        res[k]["held_out_cost_0.25pct"] = period_stats(r2["equity"], r2["trades"], "2024-01-01", None)
    elig = {k: v["selection"] for k, v in res.items() if not k.startswith("buy_hold") and v["selection"].get("trades", 0) >= MIN_TRADES and v["selection"].get("sharpe") is not None}
    rank = sorted(elig, key=lambda k: -elig[k]["sharpe"])
    return {"protocol": __doc__.strip(), "cost_per_fill": COST, "risk_per_trade": RISK, "selection_years": "2020-2023", "held_out_years": "2024-2026-09", "bars": f"{bars.index[0].date()} to {bars.index[-1].date()}",
            "symbol": symbol, "variants": res, "ranked_on_selection": rank, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}, curves


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--study", action="store_true"); ap.add_argument("--symbol", default="BTCUSDT"); a = ap.parse_args()
    if a.study:
        s, curves = study(symbol=a.symbol); (OUT / ("study.json" if a.symbol == "BTCUSDT" else f"study_{a.symbol[:-4].lower()}.json")).write_text(json.dumps(s, separators=(",", ":")), encoding="utf-8")
        P = lambda d: f"n={d.get('trades', 0):4d} ret {d.get('return_pct')!s:>7}% dd {d.get('max_drawdown_pct')!s:>6}% sharpe {d.get('sharpe')!s:>5} win {d.get('win_rate')!s:>5} avg {d.get('avg_net_pct')!s:>6}% pf {d.get('profit_factor')!s:>5}"
        for k, v in s["variants"].items():
            print(f"{k:22s} SEL {P(v['selection'])} || HELD {P(v['held_out'])}" + (f" || @0.25%: ret {v['held_out_cost_0.25pct'].get('return_pct')}% avg {v['held_out_cost_0.25pct'].get('avg_net_pct')}%" if "held_out_cost_0.25pct" in v else ""))
        print("ranked on selection:", s["ranked_on_selection"])


if __name__ == "__main__":
    main()
