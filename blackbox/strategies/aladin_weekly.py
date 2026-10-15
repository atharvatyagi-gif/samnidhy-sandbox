"""ALADIN paper bot, the weekly family: v3 (the live bot), v4 shadow (F&O shorts + protective stop) and the Rs 10,000 account.

Mirrors (all paths relative to the repository root):
  scripts/aladin2/paper.py  books_from_scores() lines ~260-292 (Friday list: liquid stocks with >= Rs 2 crore traded value, rank by ALADIN 1's 5-day score,
                            best 1% = long, worst 2% = short when shorts are on), prep_prices() (stop = close - 2 ATR, clipped to 1.5..2.5 ATR),
                            simulate() lines 110-200 (entry at the next open, skip if held / 10 open / opened beyond the stop, sector cap 30%,
                            exit at the open 5 trading days later, protective stop as a live order, shorts as stock futures capped at 50%),
                            run_bot() line 95 (v3 = time exit only, 2% risk, 20% a stock, idle cash in a liquid fund), SMALL (line 47: Rs 10,000,
                            whole shares, Rs 15.93 depository charge per sale), SHADOW (line 437: protect 3 ATR, short cap 50%)
  scripts/aladin2/signals.py position_size() lines 122-136 (risk %, max position %, 5% of average volume, fractional Kelly cap)
  scripts/aladin2/weekly.py decide() line 78 with data/config/aladin2.json "weekly" (buy_top_pct 0.99, sell_bottom_pct 0.02)
Not reproduced: the ALADIN 1 LightGBM score itself (a stand-in with the measured skill, panel.score(5, ic)); the real futures lot sizes (not modelled in
the terminal either). The synthetic universe has 300 stocks, so the best 1% is 3 names a week, against about 12 live.
"""
from __future__ import annotations

import numpy as np

from ._common import Book, adv_shares, atr, finish, floor, hold_value, kelly_cap_value
from ..engine.metrics import Result

SOURCE = "scripts/aladin2/paper.py (books_from_scores, simulate, run_bot, SMALL, SHADOW); scripts/aladin2/signals.py position_size"


def run(panel, p: dict, cm, start: int, shorts: bool = False, protect: float | None = None, cash0: float = 1_000_000.0, dp_charge: float = 0.0) -> Result:
    T, N = panel.T, panel.N; c, o, h, l = panel.c, panel.o, panel.h, panel.l; A = atr(panel); advsh = adv_shares(panel)
    score = panel.score(5, p["ic"]); fridays = panel.dates.weekday == 4
    bk = Book(cash0, cm, fund=True); pending: list = []; eq, gadd, expo = [], [], []
    marks = lambda t: {i: hold_value(c[t], i, q["ref"]) for i, q in bk.pos.items()}
    eq.append(bk.value({})); gadd.append(0.0); expo.append(0.0)
    for t in range(start, T):
        # 1. the time exit at the open (terminal: i >= exit_i, out at the open)
        for i, q in list(bk.pos.items()):
            if t - q["t"] >= p["hold_days"] and np.isfinite(o[t, i]):
                bk.close(i, o[t, i], t, "time")
                if dp_charge:
                    bk.cash -= dp_charge; bk.costs += dp_charge; bk.trades[-1]["pnl"] -= dp_charge; bk.trades[-1]["cost"] += dp_charge
        # 2. entries at the open from Friday's list (best first)
        eq_now = bk.value(marks(t - 1))
        for side, i, stop in pending:
            if i in bk.pos or len(bk.pos) >= p["max_open"] or not np.isfinite(o[t, i]):
                continue
            px = o[t, i]
            if (px - stop) * side <= 0:
                continue                                                            # opened at or beyond the sizing level
            per = abs(px - stop)
            q_risk = floor(eq_now * p["risk_pct"] / 100 / per); q_pos = floor(eq_now * p["max_pos_pct"] / 100 / px)
            q_liq = floor(p["adv_part"] * (advsh[t - 1, i] if np.isfinite(advsh[t - 1, i]) else 0))
            q_kel = floor(kelly_cap_value(eq_now, p["kelly_mu"], p["kelly_sd"], p["kelly_cap"]) / px)
            q = min(q_risk, q_pos, q_liq, q_kel)
            sec_val = sum(x["qty"] * hold_value(c[t - 1], j, x["ref"]) for j, x in bk.pos.items() if panel.sector[j] == panel.sector[i])
            q = min(q, floor((eq_now * p["sector_cap_pct"] / 100 - sec_val) / px))
            if side < 0:
                sh = sum(x["qty"] * hold_value(c[t - 1], j, x["ref"]) for j, x in bk.pos.items() if x["side"] < 0)
                q = min(q, floor((eq_now * p["short_cap_pct"] / 100 - sh) / px))
            while q > 0 and side > 0 and q * px * 1.01 > bk.cash:
                q -= 1
            if q >= 1:
                pstop = px - side * protect * A[t - 1, i] if protect and np.isfinite(A[t - 1, i]) else None
                bk.open(i, side, q, px, t, i, pstop=pstop)
        pending = []
        # 3. the protective stop during the day (a gap through it fills at the open)
        for i, q in list(bk.pos.items()):
            ps = q.get("pstop")
            if ps and np.isfinite(l[t, i]):
                if q["side"] > 0 and l[t, i] <= ps:
                    bk.close(i, min(o[t, i], ps) if t > q["t"] else ps, t, "protective stop")
                elif q["side"] < 0 and h[t, i] >= ps:
                    bk.close(i, max(o[t, i], ps) if t > q["t"] else ps, t, "protective stop")
        # 4. Friday's close: tomorrow's list
        if fridays[t] and t < T - 1:
            liq = panel.adv_cr >= 2.0
            ok = liq & np.isfinite(score[t]) & np.isfinite(A[t]) & (A[t] > 0)
            ids = np.where(ok)[0]; n = len(ids)
            if n >= 50:
                order = ids[np.argsort(-score[t, ids], kind="stable")]; pct = 1 - (np.arange(n) + 0.5) / n
                stopd = np.clip(p["stop_atr"], 1.5, 2.5)
                for k, i in enumerate(order):
                    if pct[k] < p["buy_top_pct"]:
                        break
                    pending.append((1, i, c[t, i] - stopd * A[t, i]))
                if shorts:
                    for k in range(n - 1, -1, -1):
                        i = order[k]
                        if pct[k] > p.get("sell_bottom_pct", 0.02):
                            break
                        if panel.fno[i]:
                            pending.append((-1, i, c[t, i] + stopd * A[t, i]))
        bk.accrue()
        mk = marks(t); v = bk.value(mk); eq.append(v); gadd.append(bk.costs); expo.append(bk.invested(mk) / v if v > 0 else 0.0)
    return finish(bk, eq, gadd, expo)


def v3(panel, p, cm, start):
    return run(panel, p, cm, start)


def v4_shadow(panel, p, cm, start):
    return run(panel, p, cm, start, shorts=p.get("short_cap_pct", 50) > 0, protect=p.get("protect_atr"))


def small_10k(panel, p, cm, start):
    return run(panel, p, cm, start, cash0=float(p.get("cash", 10_000)), dp_charge=cm.cfg["dp_charge_inr"] if p.get("dp_charge") else 0.0)
