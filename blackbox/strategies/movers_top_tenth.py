"""ALADIN movers forward-test portfolio: the top tenth of the weekly ranking, equal weight, Monday open to Friday close.

Mirrors scripts/aladin_movers.py: make_book() line 296 (Friday ranking by expected 5-day move, top k = tenth), realised() line 310 (Monday open ->
the 5th close), evaluate_forward() line 322 (equal weight, COST_RT = 0.30% round trip, compounded from BUDGET_INR = Rs 10 lakh).
The ranking (LightGBM) is a stand-in, panel.score(5, ic), measured ic 0.06. The terminal charges a flat 0.30%; here the scenario's spread and
liquidity widen it (cost x spread multiplier on the day) and a liquidity haircut leaves part of the week in cash.
"""
from __future__ import annotations

import numpy as np

from ..engine.metrics import Result

SOURCE = "scripts/aladin_movers.py (make_book, realised, evaluate_forward)"


def run(panel, p: dict, cm, start: int) -> Result:
    T, o, c = panel.T, panel.o, panel.c; score = panel.score(5, p["ic"]); eq, gross, trades, expo = [1_000_000.0], [1_000_000.0], [], [0.0]
    week_ret = {}; traded = 0.0
    for t in range(start, T):
        if panel.dates.weekday[t] == 4 and t + 5 < T:
            ok = np.where((panel.adv_cr >= 5.0) & np.isfinite(score[t]))[0]; k = max(1, int(len(ok) * p["list_pct"]))
            top = ok[np.argsort(-score[t, ok], kind="stable")[:k]]
            rt = p["roundtrip_cost"] * cm.cost_mult * 0.5 * (cm.spread_mult[t + 1] + cm.spread_mult[t + 5]) * cm.slip_mult ** 0.5
            r = c[t + 5, top] / o[t + 1, top] - 1; fill = cm.filled_share(t + 1)
            net = fill * (np.nanmean(r) - rt); grossr = fill * np.nanmean(r)
            week_ret[t + 5] = (net, grossr, t + 1)
            cap = eq[-1] * fill / k
            for x in r:
                trades.append({"side": "long", "entry_t": t + 1, "exit_t": t + 5, "days": 4, "pnl": cap * (x - rt), "pnl_pct": x - rt, "cost": cap * rt, "capital": cap, "reason": "week"})
            traded += 2 * eq[-1] * fill
        if t in week_ret:
            net, grossr, _ = week_ret.pop(t); eq.append(eq[-1] * (1 + net)); gross.append(gross[-1] * (1 + grossr)); expo.append(1.0)
        else:
            inside = any(s <= t for _, _, s in week_ret.values())
            eq.append(eq[-1]); gross.append(gross[-1]); expo.append(1.0 if inside else 0.0)
    # a weekly book is marked at Friday closes only (as the terminal's ledger does)
    return Result(equity=np.array(eq), gross_equity=np.array(gross), trades=trades, exposure=np.array(expo), traded_value=traded)
