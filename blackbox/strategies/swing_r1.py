"""ALADIN swing rules, round 1 (failed its history gate on 2026-10-14; kept in the terminal's code as the record).

Mirrors scripts/aladin2/swing.py: RULES (line 60), prep() lines 70-90 (20-day breakout/breakdown, 2-day RSI as an EWM with alpha 1/2, 50-day average),
lists_from_movers() (top / bottom tenth of the weekly movers ranking; shorts only for F&O stocks), simulate() lines 111-200 (entry at the next open,
stop 1.5 ATR, profit-taking 3 ATR, stop to break-even after 1.5 ATR at a close then trailing 1.5 ATR behind the best close, out at the open of day 6,
1% risk, 10% a stock, 5% of volume, 12 positions, shorts <= 50%, long + short <= 100%).
The movers ranking (LightGBM) is a stand-in: panel.score(5, ic) with the measured ic 0.06.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import Book, adv_shares, atr, cached, finish, floor, hold_value, sma

SOURCE = "scripts/aladin2/swing.py (RULES, prep, lists_from_movers, simulate)"


def _rsi2(c: np.ndarray) -> np.ndarray:
    d = np.diff(c, axis=0, prepend=np.nan); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    ru = pd.DataFrame(up).ewm(alpha=0.5, adjust=False).mean().values; rd = pd.DataFrame(dn).ewm(alpha=0.5, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + ru / rd)


def run(panel, p: dict, cm, start: int):
    T, c, o, h, l = panel.T, panel.c, panel.o, panel.h, panel.l; A = atr(panel); advsh = adv_shares(panel)
    n = int(p["breakout_days"])
    hh = cached(panel, f"hh{n}", lambda: pd.DataFrame(h).shift(1).rolling(n, min_periods=n).max().values)
    ll = cached(panel, f"ll{n}", lambda: pd.DataFrame(l).shift(1).rolling(n, min_periods=n).min().values)
    trend = cached(panel, f"sma{p['trend_sma']}", lambda: sma(c, int(p["trend_sma"]))); rsi = cached(panel, "rsi2", lambda: _rsi2(c))
    with np.errstate(invalid="ignore"):
        long_t = (c > hh) | ((rsi < p["rsi_long"]) & (c > trend)); short_t = (c < ll) | ((rsi > p["rsi_short"]) & (c < trend))
    score = panel.score(5, p["ic"]); fridays = np.where(panel.dates.weekday == 4)[0]
    bk = Book(1_000_000.0, cm, fund=False); pending, eq, gadd, expo = [], [bk.cash], [0.0], [0.0]
    marks = lambda t: {i: hold_value(c[t], i, q["ref"]) for i, q in bk.pos.items()}
    lists = {}
    for t in range(start, T):
        for i, q in list(bk.pos.items()):                                       # time limit at the open
            if t - q["t"] >= p["max_days"] and np.isfinite(o[t, i]):
                bk.close(i, o[t, i], t, "time")
        eqn = bk.value(marks(t - 1))
        for side, i in pending:                                                  # entries at the open
            if i in bk.pos or len(bk.pos) >= p["max_open"] or not np.isfinite(A[t - 1, i]) or A[t - 1, i] <= 0:
                continue
            px, a = o[t, i], A[t - 1, i]; stop = px - side * p["stop_atr"] * a; tgt = px + side * p["target_atr"] * a
            if stop <= 0:
                continue
            q = min(eqn * p["risk_pct"] / 100 / (p["stop_atr"] * a), eqn * p["max_pos_pct"] / 100 / px, 0.05 * (advsh[t - 1, i] if np.isfinite(advsh[t - 1, i]) else 0))
            lv = sum(x["qty"] * x["ref"] for x in bk.pos.values() if x["side"] > 0); sv = sum(x["qty"] * x["ref"] for x in bk.pos.values() if x["side"] < 0)
            room = eqn - lv - sv
            if side < 0:
                room = min(room, eqn * p["short_cap_pct"] / 100 - sv)
            q = floor(max(0.0, min(q, room / px)))
            if q >= 1:
                bk.open(i, side, q, px, t, i, stop=stop, target=tgt, atr=a, best=px)
        pending = []
        for i, q in list(bk.pos.items()):                                       # stop first, then profit-taking; a gap fills at the open
            s, op = q["side"], o[t, i]
            if s > 0 and l[t, i] <= q["stop"]:
                bk.close(i, min(op, q["stop"]) if t > q["t"] else q["stop"], t, "stop")
            elif s > 0 and h[t, i] >= q["target"]:
                bk.close(i, max(op, q["target"]) if t > q["t"] else q["target"], t, "target")
            elif s < 0 and h[t, i] >= q["stop"]:
                bk.close(i, max(op, q["stop"]) if t > q["t"] else q["stop"], t, "stop")
            elif s < 0 and l[t, i] <= q["target"]:
                bk.close(i, min(op, q["target"]) if t > q["t"] else q["target"], t, "target")
        for i, q in bk.pos.items():                                             # break-even, then trail behind the best close
            x = c[t, i]
            if q["side"] > 0:
                q["best"] = max(q["best"], x)
                if q["best"] - q["ref"] >= p["breakeven_atr"] * q["atr"]:
                    q["stop"] = max(q["stop"], q["ref"], q["best"] - p["trail_atr"] * q["atr"])
            else:
                q["best"] = min(q["best"], x)
                if q["ref"] - q["best"] >= p["breakeven_atr"] * q["atr"]:
                    q["stop"] = min(q["stop"], q["ref"], q["best"] + p["trail_atr"] * q["atr"])
        if panel.dates.weekday[t] == 4:                                         # Friday close: the new lists
            ok = np.where((panel.adv_cr >= 5.0) & np.isfinite(score[t]))[0]; k = max(1, int(len(ok) * p["list_pct"]))
            order = ok[np.argsort(-score[t, ok], kind="stable")]
            lists = {"long": list(order[:k]), "short": [i for i in order[::-1][:k] if panel.fno[i]] if p["short_cap_pct"] > 0 else []}
        if lists and t < T - 1:                                                 # tonight's triggers from the latest list
            for side, key, trig in ((1, "long", long_t), (-1, "short", short_t)):
                pending += [(side, i) for i in lists[key] if trig[t, i]]
        mk = marks(t); v = bk.value(mk); eq.append(v); gadd.append(bk.costs); expo.append(bk.invested(mk) / v if v > 0 else 0.0)
    return finish(bk, eq, gadd, expo)
