"""ALADIN paper trader v1 (the first paper portfolio, data/paper_trades/portfolio.json).

Mirrors scripts/paper_trader.py: DEFAULT line 34 (threshold 0.60, hold 10 days, 0.5% round trip, at most 10 open, Rs 1,00,000 a position),
new_signals() line 75, open_positions() line 116 (entry at the OPEN of the first session after the signal, highest P(up) first, one per symbol),
close_due() line 143 (exit at the CLOSE of the 10th trading day after entry).
AMBIGUITY: the terminal also requires confidence High and 3/3 agreement of the Fundamental, Technical and Sentiment fronts; those fronts do not exist
on synthetic prices, so only the probability test is applied. The 10-day P(up) is a stand-in: p = 0.52 + prob_scale x score(10, ic), with
prob_scale 0.035 chosen so that about 1% of stocks clear 0.60 on a day (the terminal reports very few signals) - a GAP.
"""
from __future__ import annotations

import numpy as np

from ._common import Book, finish, hold_value

SOURCE = "scripts/paper_trader.py (DEFAULT, new_signals, open_positions, close_due)"
PROB_SCALE = 0.035


def run(panel, p: dict, cm, start: int):
    T, o, c = panel.T, panel.o, panel.c; prob = 0.52 + PROB_SCALE * panel.score(10, p["ic"])
    cash0 = p["notional"] * p["max_open"]; bk = Book(cash0, cm); eq, gadd, expo = [cash0], [0.0], [0.0]; pending = []
    half = p["roundtrip_cost"] / 2
    marks = lambda t: {i: hold_value(c[t], i, q["ref"]) for i, q in bk.pos.items()}
    for t in range(start, T):
        for i in pending:                                                       # entry at today's open, best first
            if i in bk.pos or len(bk.pos) >= p["max_open"] or not np.isfinite(o[t, i]):
                continue
            qty = p["notional"] / o[t, i]; px = o[t, i]
            fee = p["notional"] * half * cm.cost_mult * cm.spread_mult[t]
            if bk.cash >= p["notional"] + fee:
                fill = cm.filled_share(t); bk.cash -= p["notional"] * fill + fee; bk.costs += fee; bk.traded += p["notional"] * fill
                bk.pos[i] = {"side": 1, "qty": qty * fill, "entry": px, "ref": px, "t": t, "i": i, "cost_in": fee, "kind": "flat"}
        pending = []
        for i, q in list(bk.pos.items()):                                       # exit at the close of the 10th trading day after entry
            if t - q["t"] >= p["hold_days"] and np.isfinite(c[t, i]):
                val = q["qty"] * c[t, i]; fee = val * half * cm.cost_mult * cm.spread_mult[t]
                bk.cash += val - fee; bk.costs += fee; bk.traded += val; bk.pos.pop(i)
                gross = q["qty"] * (c[t, i] - q["ref"]); net = gross - q["cost_in"] - fee; cap = q["qty"] * q["ref"]
                bk.trades.append({"side": "long", "entry_t": q["t"], "exit_t": t, "days": t - q["t"], "pnl": net, "pnl_pct": net / cap, "cost": q["cost_in"] + fee, "capital": cap, "reason": "time"})
        if t < T - 1:
            cand = np.where((prob[t] > p["threshold"]) & (panel.adv_cr >= 5.0))[0]
            pending = list(cand[np.argsort(-prob[t, cand], kind="stable")])
        mk = marks(t); v = bk.value(mk); eq.append(v); gadd.append(bk.costs); expo.append(bk.invested(mk) / v if v > 0 else 0.0)
    return finish(bk, eq, gadd, expo)
