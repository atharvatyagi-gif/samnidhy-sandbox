"""
ALADIN 2.0 per-stock backtest engine.

  signal  Series aligned to the bars: value at the CLOSE of day t, in [-1, +1]. >0 = want long, <0 = want short, 0 = flat.
  fills   the order goes in after the close of t and fills at the OPEN of t+1 (never at t's close). The exit fills at an open too, except an ATR stop,
          which fills at the stop price (or at the open when the bar gaps through it).
  no fill the bar is missing or has zero volume; the open is a one-price day (circuit-limit lock: open == high == low == close and |move| >= circuit_proxy_min_move);
          or the reference order (assumed_order_inr) would be more than adv_participation_max of that day's traded value. A skipped entry is simply not taken
          (no retry); a blocked exit waits for the next fillable open.
  sides   long is always possible. Short only when kind == "futures" (a futures-eligible stock) or kind == "intraday" (same-day, not used by the daily library);
          for kind == "delivery" negative signals mean "exit / stay out", never a short trade.
  costs   leg costs from costs.py as basis points of value, charged on entry and exit (brokerage, STT, exchange, SEBI, GST, stamp, slippage by liquidity decile).
  rules   {"type": "fixed", "n": 10}                   exit at the open n bars after entry
          {"type": "flip", "max_n": 250}                exit at the open after the first close where the signal is no longer on the side of the trade
          {"type": "atr_trail", "mult": 2.5, "max_n": 60, "atr": Series}   trailing stop mult x ATR(at signal time) from the highest close since entry
One position per stock at a time. Output: trade list, daily net P&L (fraction of the capital allocated to the stock while invested), exposure.
"""
import numpy as np
import pandas as pd

from . import costs as C


def _fillable(px, i, cfg, ref=None):
    o, v = px["o"].values, px["v"].values
    if i >= len(o) or not (v[i] > 0) or not (o[i] > 0):
        return False
    b = cfg["backtest"]
    if "locked_eff" in px.columns:
        if px["locked_eff"].values[i]:
            return False
    elif "locked" in px.columns and px["locked"].values[i]:
        pc = px["pc"].values[i] if "pc" in px.columns else np.nan
        if np.isnan(pc) or abs(o[i] / pc - 1) >= b["circuit_proxy_min_move"]:
            return False
    return (b["assumed_order_inr"] / (v[i] * o[i])) <= cfg["risk"]["adv_participation_max"]


def run(px, signal, rule, kind="delivery", decile=5, cfg=None, futures_ok=False, allow_short=None):
    cfg = cfg or C.load_cfg()
    if "locked" in px.columns and "pc" in px.columns:               # a circuit-limit lock lasts: a one-price day is locked if it moved >= circuit_proxy_min_move from the previous close OR the previous day was locked
        thr = cfg["backtest"]["circuit_proxy_min_move"]; lk = np.zeros(len(px), bool); lkv, pcv, ov = px["locked"].values, px["pc"].values, px["o"].values
        for i in range(len(px)):
            if lkv[i]:
                lk[i] = (i > 0 and lk[i - 1]) or (not np.isnan(pcv[i]) and abs(ov[i] / pcv[i] - 1) >= thr) or np.isnan(pcv[i])
        px = px.assign(locked_eff=lk)
    o, h, l, c = (px[k].values for k in ("o", "h", "l", "c")); n = len(px); idx = px.index
    sig = signal.reindex(idx).fillna(0).values
    shorts = (kind == "futures") if allow_short is None else allow_short
    shorts = shorts and (kind != "delivery")
    cin = {s: C.leg_bps("buy" if s == "long" else "sell", kind, decile, cfg) / 1e4 for s in ("long", "short")}
    cout = {s: C.leg_bps("sell" if s == "long" else "buy", kind, decile, cfg) / 1e4 for s in ("long", "short")}
    post = px["post_break"].values if "post_break" in px.columns else None
    susp = px["suspect_action"].values if "suspect_action" in px.columns else None
    dropped = 0
    atr = rule.get("atr"); atr = atr.reindex(idx).values if atr is not None else None
    trades, daily, expo = [], np.zeros(n), np.zeros(n)
    t = 0
    while t < n - 1:
        s = sig[t]
        if s == 0 or np.isnan(s) or (s < 0 and not shorts):
            t += 1; continue
        side = "long" if s > 0 else "short"; e = t + 1
        if (post is not None and post[t]) or not _fillable(px, e, cfg):
            t += 1; continue
        entry = o[e]; sgn = 1.0 if side == "long" else -1.0
        x, xpx, why = None, None, None
        typ = rule["type"]; cap = rule.get("n", rule.get("max_n", 250))
        if typ == "atr_trail":
            a = atr[t] if atr is not None else np.nan
            if not (a > 0):
                t += 1; continue
            extreme = entry
            stop = entry - sgn * rule["mult"] * a
        k = e
        while k < n:
            if typ == "fixed" and k - e >= cap and k > e and _fillable(px, k, cfg):
                x, xpx, why = k, o[k], "time"; break
            if typ == "flip" and k > e and sgn * sig[k - 1] <= 0 and _fillable(px, k, cfg):
                x, xpx, why = k, o[k], "signal"; break
            if typ == "flip" and k - e >= cap and k > e and _fillable(px, k, cfg):
                x, xpx, why = k, o[k], "time"; break
            if typ == "atr_trail":
                hit = (l[k] <= stop) if sgn > 0 else (h[k] >= stop)
                if hit:
                    gap = (o[k] <= stop) if sgn > 0 else (o[k] >= stop)
                    x, xpx, why = k, (o[k] if gap else stop), "stop"; break
                extreme = max(extreme, c[k]) if sgn > 0 else min(extreme, c[k])
                stop = extreme - sgn * rule["mult"] * a
                if k - e >= cap and k + 1 < n and _fillable(px, k + 1, cfg):
                    x, xpx, why = k + 1, o[k + 1], "time"; break
            k += 1
        if x is None:                                              # still open at the end of the data: marked at the last close, flagged open
            x, xpx, why = n - 1, c[n - 1], "open_at_end"
        if susp is not None and susp[e + 1:x + 1].any():           # held across an unadjusted corporate action in the source data: the P&L would be fiction
            dropped += 1; t = max(x, t + 1)
            continue
        gross = sgn * (xpx / entry - 1)
        net = gross - cin[side] - cout[side]
        seg_h, seg_l = h[e:x + 1], l[e:x + 1]
        mfe = (seg_h.max() / entry - 1) if side == "long" else (1 - seg_l.min() / entry)
        mae = (seg_l.min() / entry - 1) if side == "long" else (1 - seg_h.max() / entry)
        trades.append({"signal_date": idx[t], "entry_date": idx[e], "exit_date": idx[x], "side": side, "entry_px": entry, "exit_px": xpx, "bars": x - e,
                       "gross": gross, "cost": cin[side] + cout[side], "net": net, "mfe": mfe, "mae": mae, "reason": why})
        # daily mark-to-market, net of costs charged on the entry and exit days
        if x == e:
            daily[e] += sgn * (xpx / entry - 1)
        else:
            daily[e] += sgn * (c[e] / entry - 1)
            if x - 1 > e:
                daily[e + 1:x] += sgn * (c[e + 1:x] / c[e:x - 1] - 1)
            daily[x] += sgn * (xpx / c[x - 1] - 1)
        daily[e] -= cin[side]; daily[x] -= cout[side]; expo[e:x + 1] = 1.0
        t = max(x, t + 1)
        if why == "open_at_end":
            break
    T = pd.DataFrame(trades)
    return {"trades": T, "daily": pd.Series(daily, index=idx, name="net"), "exposure": pd.Series(expo, index=idx, name="exposure"), "discarded_across_action": dropped}


def buy_and_hold(px, kind="delivery", decile=5, cfg=None):
    """Baseline: buy at the first open, hold to the last close. One entry, one exit, same costs and fills as everything else."""
    s = pd.Series(1.0, index=px.index)
    return run(px, s, {"type": "fixed", "n": len(px) + 1}, kind, decile, cfg)


def summarize(res, periods_per_year=250):
    """Basic net metrics from one run(). Fuller metrics (PSR/DSR, bootstrap, FDR) live in evaluate.py (phase 2)."""
    T, d = res["trades"], res["daily"]
    if T.empty:
        return {"trades": 0}
    r = T["net"]; wins, loss = r[r > 0], r[r <= 0]
    eq = (1 + d).cumprod(); dd = (eq / eq.cummax() - 1).min()
    sd = d.std()
    return {"trades": int(len(T)), "win_rate": float((r > 0).mean()), "expectancy_bps": float(r.mean() * 1e4), "payoff": float(wins.mean() / -loss.mean()) if len(loss) and len(wins) else None,
            "profit_factor": float(wins.sum() / -loss.sum()) if loss.sum() < 0 else None, "ann_return": float(d.mean() * periods_per_year), "ann_vol": float(sd * np.sqrt(periods_per_year)),
            "sharpe": float(d.mean() / sd * np.sqrt(periods_per_year)) if sd > 0 else None, "max_drawdown": float(dd), "exposure": float(res["exposure"].mean()), "avg_bars": float(T["bars"].mean())}
