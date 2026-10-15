"""Bitcoin Heikin-Ashi trend (the price-only one of the order-flow study's strategies), on the synthetic BTC series.

Mirrors scripts/crypto_flow.py: signals() line 77 "ha_trend" (two Heikin-Ashi bars in a row green with no lower wick -> in; a red Heikin-Ashi bar -> out),
STOP_ATR line 73 (3 ATR), size_value() (risk 2% of the account to the stop, never more than the whole account), COST line 32 (0.12% a fill),
"a stop fills at its price, or at the open if the bar opens through it", signals at a bar's close, fills at the next bar's open.
DEVIATION: the terminal studies 1-hour and 4-hour bars; the synthetic market is daily. The four order-flow strategies (ha_flow, flow_momentum,
flow_absorb, flow_breakout) need taker-buy volume, which the synthetic market does not have: NOT SIMULATED.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine.metrics import Result

SOURCE = "scripts/crypto_flow.py (signals ha_trend, STOP_ATR, size_value, COST)"


def heikin_ashi(o, h, l, c):
    hc = (o + h + l + c) / 4; ho = np.empty_like(hc); ho[0] = (o[0] + c[0]) / 2
    for t in range(1, len(c)):
        ho[t] = (ho[t - 1] + hc[t - 1]) / 2
    hl = np.minimum(l, np.minimum(ho, hc)); green = hc > ho; nowick = hl >= np.minimum(ho, hc) - 1e-12
    return green, nowick


def run(panel, p: dict, cm, start: int) -> Result:
    x = panel.extras["btc"]; o, h, l, c = x["o"], x["h"], x["l"], x["c"]; T = len(c)
    green, nowick = heikin_ashi(o, h, l, c)
    pc = np.concatenate([[c[0]], c[:-1]]); atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14, min_periods=14).mean().values
    enter = green & nowick & np.roll(green, 1) & np.roll(nowick, 1); enter[0] = False; leave = ~green
    fee = p["fee_bps"] / 1e4 * cm.cost_mult; eq, gross, expo, trades = [1.0], [1.0], [0.0], []; units = 0.0; cash = 1.0; gcash = 1.0; gunits = 0.0; cur = None; traded = 0.0
    for t in range(start, T):
        if units == 0 and enter[t - 1] and np.isfinite(atr[t - 1]):           # entry at the open
            stop = o[t] - p["stop_atr"] * atr[t - 1]; dist = o[t] - stop
            val = max(0.0, min(cash / (1 + fee), cash * p["risk"] / (dist / o[t]))) if dist > 0 else 0.0
            px = o[t] * (1 + cm.slip_bps(t, None, "crypto") / 1e4)
            if val > 0:
                units = val / px; cash -= val * (1 + fee); gunits = val / o[t]; gcash -= val; traded += val
                cur = {"t": t, "px": px, "stop": stop, "val": val}
        elif units > 0:
            hit = l[t] <= cur["stop"]; out_px = min(o[t], cur["stop"]) if hit else (o[t] if leave[t - 1] else None)
            if out_px is not None:
                px = out_px * (1 - cm.slip_bps(t, None, "crypto") / 1e4); proceeds = units * px; cash += proceeds * (1 - fee); gcash += gunits * out_px; traded += proceeds
                pnl = proceeds * (1 - fee) - cur["val"] * (1 + fee)
                trades.append({"side": "long", "entry_t": cur["t"], "exit_t": t, "days": t - cur["t"], "pnl": pnl, "pnl_pct": pnl / cur["val"], "cost": cur["val"] * fee + proceeds * fee,
                               "capital": cur["val"], "reason": "stop" if hit else "signal"}); units = 0.0; gunits = 0.0; cur = None
        v = cash + units * c[t]; eq.append(v); gross.append(gcash + gunits * c[t]); expo.append(units * c[t] / v if v > 0 else 0.0)
    return Result(equity=np.array(eq), gross_equity=np.array(gross), trades=trades, exposure=np.array(expo), traded_value=traded)
