"""Benchmarks in every scenario: buy-and-hold of the market proxy, and random entry with the strategy's own trade count and holding period."""
from __future__ import annotations

import numpy as np

from ..engine.metrics import Result

SOURCE = "blackbox benchmark (not a terminal strategy)"


def buy_hold(panel, cm, start: int, asset: str | None = None) -> Result:
    """Equal-weight market index (or BTC), bought at the first evaluated open with one fill's costs."""
    if asset:
        x = panel.extras[asset]; px = np.concatenate([[x["o"][start]], x["c"][start:]])
    else:
        px = np.concatenate([[panel.index[start - 1]], panel.index[start:]])
    cost = cm.slip_bps(start, 0 if asset is None else None) / 1e4 + cm.fee(1.0, "delivery" if asset is None else "crypto")
    eq = px / px[0] * (1 - cost); eq[0] = 1.0
    return Result(equity=eq, gross_equity=px / px[0], trades=[], exposure=np.ones(len(eq)), traded_value=1.0)


def random_entry(panel, cm, start: int, n_trades: int, hold: float, capital: float, cash0: float, rng: np.random.Generator,
                 asset: str | None = None, side_short_share: float = 0.0, cost_rate: float | None = None) -> Result:
    """`n_trades` long trades (shorts in the same share as the strategy's) on random liquid stocks (or BTC) on random days, each `capital` rupees,
    held `hold` trading days, open to open. Costs: `cost_rate` (the strategy's own average cost per rupee traded, both legs) when given, so the
    comparison isolates timing and selection skill; otherwise the cost model. A strategy that cannot beat this has no edge worth its rules."""
    T = panel.T; hold = max(1, int(round(hold or 5))); n = int(n_trades); eq = np.full(T - start + 1, cash0, float); gross = eq.copy(); trades = []
    if n <= 0:
        return Result(equity=eq, gross_equity=gross, trades=[], exposure=np.zeros(len(eq)))
    liquid = np.where(panel.adv_cr >= 2.0)[0]; pnl_by_exit = np.zeros(T + 1); gross_by_exit = np.zeros(T + 1); traded = 0.0
    for _ in range(n):
        t = int(rng.integers(start, max(start + 1, T - hold)))
        s = -1 if rng.random() < side_short_share else 1
        if asset:
            o = panel.extras[asset]["o"]; i = None
        else:
            i = int(rng.choice(liquid)); o = panel.o[:, i]
        x = min(T - 1, t + hold); e, q = o[t], o[x]
        if not (np.isfinite(e) and np.isfinite(q)) or e <= 0:
            continue
        fill_e = cm.fill(e, s, t, i); fill_x = cm.fill(q, -s, x, i); kind = "crypto" if asset else ("delivery" if s > 0 else "futures")
        units = capital / fill_e; cost = cm.fee(capital, kind) + cm.fee(units * fill_x, kind) + units * (abs(fill_e - e) + abs(fill_x - q))
        if cost_rate is not None:
            units = capital / e; cost = cost_rate * capital
        g = units * (q - e) * s; net = g - cost; pnl_by_exit[x] += net; gross_by_exit[x] += g; traded += 2 * capital
        trades.append({"side": "long" if s > 0 else "short", "entry_t": t, "exit_t": x, "days": x - t, "pnl": net, "pnl_pct": net / capital, "cost": cost, "capital": capital, "reason": "random"})
    eq = cash0 + np.concatenate([[0.0], np.cumsum(pnl_by_exit[start:T])]); gross = cash0 + np.concatenate([[0.0], np.cumsum(gross_by_exit[start:T])])
    return Result(equity=eq, gross_equity=gross, trades=trades, exposure=np.full(len(eq), np.nan), traded_value=traded)
