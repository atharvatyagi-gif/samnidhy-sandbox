"""
ALADIN, model E (version aladin-e-1): momentum with a daily risk check. The single model shown on the public site.
Specification: aladin-audit/SPEC_ALADIN_E.md (approved 2026-11-10); settings: data/config/aladin_e.json; the measured "chance" table:
data/config/aladin_e_calibration.json (aladin-audit/scripts/e_calibration.py).

  python scripts/aladin_e.py            -> data/aladin_e/latest.json (the page's data) and data/aladin_e/paper.json (the paper account)

Every evening after the Daily update has saved the day's prices:
  1. Orders decided on an earlier evening are filled at the OPEN of the first session after that evening (never at the close that
     produced the signal), plus slippage and every cost in the settings, including the DP charge per stock sold.
  2. The paper account is valued at today's close.
  3. Checks: prices older than `stale_sessions` sessions -> DEGRADED (no new decisions, signals hidden); a fall of `kill_drawdown`
     from the peak -> the kill switch (no buying, invested share at its risk-off level until the owner reviews); a one-day fall of
     `daily_loss_pause_entries` -> no buys at the next open.
  4. Ranks: the 126-session return of the 500 most-traded stocks (>= Rs 5 Cr a day, >= 250 sessions of prices). The best 5% are
     "In the portfolio". Every `rebalance_every_sessions` sessions the portfolio is rebalanced (leavers sold, newcomers bought,
     stayers untouched); whenever the invested share changes (NIFTY 500 crosses its 200-day average, kill switch) every position is
     resized at the next open.
Running twice on the same day changes nothing in the account (the last processed date is stored).
Paper trading only: nothing here touches a broker or real money. Not investment advice.
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TERM = ROOT / "data" / "terminal"
OUT = ROOT / "data" / "aladin_e"
CFG = ROOT / "data" / "config" / "aladin_e.json"
CAL = ROOT / "data" / "config" / "aladin_e_calibration.json"
INDEX_FILE = TERM / "idx" / "out" / "d" / "Nifty_20500.json"
VIX_FILE = TERM / "idx" / "out" / "d" / "India_20VIX.json"
FII_FILE = ROOT / "data" / "institutional" / "fii_dii.json"
JUMP = 0.45                                                # one-day moves above this are treated as data errors


def load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


# ------------------------------------------------------------------ data

def price_frame(sym, hist_shards):
    """Daily o/c/v, split-adjusted (data/terminal/daily) extended with the newer NSE end-of-day rows (data/terminal/hist), rescaled to join."""
    d = load(TERM / "daily" / f"{key(sym)}.json", {})
    rows = d.get("d") or []
    h = (hist_shards.get(sym[0].upper() if sym[0].isalpha() else "0") or {}).get(sym) or []
    if not rows and not h:
        return None
    df = pd.DataFrame([r[:6] for r in rows], columns=["date", "o", "h", "l", "c", "v"]) if rows else None
    hd = pd.DataFrame([r[:6] for r in h], columns=["date", "o", "h", "l", "c", "v"]) if h else None
    if df is None:
        df = hd
    elif hd is not None:
        last = df["date"].iloc[-1]
        newer = hd[hd["date"] > last]
        same = hd[hd["date"] == last]
        if len(newer):
            k = float(df["c"].iloc[-1]) / float(same["c"].iloc[0]) if len(same) and float(same["c"].iloc[0]) > 0 else 1.0
            newer = newer.assign(o=newer["o"] * k, c=newer["c"] * k, v=newer["v"] / k)
            df = pd.concat([df, newer], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates("date").set_index("date").sort_index()[["o", "c", "v"]]


def load_market(stocks):
    hist = {p.stem: load(p, {}) for p in (TERM / "hist").glob("*.json")}
    frames = {}
    for s in stocks:
        f = price_frame(s["s"], hist)
        if f is not None and len(f):
            frames[s["s"]] = f
    idx = load(INDEX_FILE, {}).get("d") or []
    n5 = pd.Series([r[4] for r in idx], index=pd.to_datetime([r[0] for r in idx])).sort_index() if idx else pd.Series(dtype=float)
    return frames, n5


def series_of(path):
    rows = load(path, {}).get("d") or []
    return pd.Series([r[4] for r in rows], index=pd.to_datetime([r[0] for r in rows])).sort_index() if rows else pd.Series(dtype=float)


def market_strip(frames, n5, vix, fii, asof, cfg):
    """The facts shown above the list, each with its own as-of date. Nothing here changes a decision except the NIFTY 500 trend."""
    out = {}
    s = n5[n5.index <= asof]
    if len(s) >= cfg["index_ma_days"]:
        ma = s.iloc[-cfg["index_ma_days"]:].mean()
        out["nifty500"] = {"as_of": str(s.index[-1].date()), "close": round(float(s.iloc[-1]), 2), "vs_200d_pct": round(float(s.iloc[-1] / ma - 1) * 100, 2),
                           "change_3m_pct": round(float(s.iloc[-1] / s.iloc[-64] - 1) * 100, 2) if len(s) > 64 else None}
    v = vix[vix.index <= asof] if len(vix) else vix
    if len(v) > 30:
        out["india_vix"] = {"as_of": str(v.index[-1].date()), "level": round(float(v.iloc[-1]), 2), "higher_than_pct_of_last_year": round(float((v.iloc[-252:] < v.iloc[-1]).mean()) * 100, 0)}
    above, n = 0, 0
    for f in frames.values():
        c = f["c"][f.index <= asof]
        if len(c) >= 200 and c.index[-1] >= asof - pd.Timedelta(days=7):
            n += 1; above += int(c.iloc[-1] > c.iloc[-200:].mean())
    if n:
        out["breadth"] = {"as_of": str(asof.date()), "share_above_200d_pct": round(100 * above / n, 1), "stocks": n}
    days = (fii or {}).get("days") or []
    if days:
        last = days[-20:]
        out["fii_dii_20d"] = {"from": last[0].get("date"), "to": last[-1].get("date"), "fii_net_cr": round(sum(((x.get("fii") or {}).get("net_cr") or 0) for x in last)),
                              "dii_net_cr": round(sum(((x.get("dii") or {}).get("net_cr") or 0) for x in last))}
    return out


def health(acct, n5, cfg):
    """Live record of closed positions: a 'hit' is a position whose net return beat the NIFTY 500 over the same days."""
    sells = [t for t in acct["trades"] if t["side"] == "exit" and t.get("index_return") is not None]
    def rate(k):
        x = sells[-k:]
        return {"n": len(x), "hit_rate": round(sum(1 for t in x if t["net_return"] > t["index_return"]) / len(x), 3) if x else None}
    alarm = None
    h = acct["history"]
    if len(h) >= 250 and len(n5):
        a, b = h[-250], h[-1]
        n0, n1 = n5[n5.index <= pd.Timestamp(a[0])], n5[n5.index <= pd.Timestamp(b[0])]
        if len(n0) and len(n1):
            gap = (b[1] / a[1] - 1) - (float(n1.iloc[-1]) / float(n0.iloc[-1]) - 1)
            if gap < -cfg["alarm_trail_vs_nifty500_12m"]:
                alarm = f"the paper account trails the NIFTY 500 by {abs(gap):.0%} over the last 12 months"
    return {"last_20": rate(20), "last_60": rate(60), "last_250": rate(250), "closed_positions": len(sells), "alarm": alarm}


def eligible_stocks(universe):
    return [s for s in universe.get("stocks", []) if s.get("board") == "Main" and not s.get("etf") and s.get("series") in ("EQ", "BE", "BZ")]


# ------------------------------------------------------------------ pure parts (tests/test_aladin_e.py)

def rank_table(frames, asof, cfg):
    """-> DataFrame index=sym, columns r126 (fraction), adv60 (Rs), rank_pct (0..1, 1 = best), rank (1 = best), in_universe; only data up to `asof`."""
    rows = []
    for sym, f in frames.items():
        f = f[f.index <= asof]
        if len(f) < cfg["min_history_days"] or f.index[-1] < asof - pd.Timedelta(days=10):
            continue
        c = f["c"].values
        w = c[-1 - cfg["lookback_days"]:]
        if len(w) > 1 and np.nanmax(np.abs(w[1:] / w[:-1] - 1)) > JUMP:
            continue                                       # a one-day move above any NSE price band: an unadjusted split or demerger, not a real move
        adv = float((f["c"] * f["v"]).iloc[-60:].mean())
        if c[-1 - cfg["lookback_days"]] <= 0 or not math.isfinite(adv):
            continue
        rows.append((sym, c[-1] / c[-1 - cfg["lookback_days"]] - 1, adv))
    T = pd.DataFrame(rows, columns=["sym", "r126", "adv60"]).set_index("sym")
    T = T[T["adv60"] >= cfg["min_adv_inr"]].sort_values("adv60", ascending=False).head(cfg["universe_top"])
    T["rank_pct"] = T["r126"].rank(pct=True)
    T["rank"] = T["r126"].rank(ascending=False, method="first").astype(int)
    return T.sort_values("rank")


def pick(T, cfg):
    n = max(1, int(round(cfg["pick_share"] * len(T))))
    return list(T.index[:n])


def risk_on(n5, asof, cfg):
    s = n5[n5.index <= asof]
    if len(s) < cfg["index_ma_days"]:
        return None, None, None
    ma = float(s.iloc[-cfg["index_ma_days"]:].mean())
    return bool(s.iloc[-1] > ma), float(s.iloc[-1]), ma


def target_share(on, kill, cfg):
    return cfg["invested_share_risk_off"] if (kill or on is False) else cfg["invested_share"]


def slip(adv, cfg):
    s = cfg["costs"]["slippage_pct"]
    return (s["adv_ge_100cr"] if adv >= 1e9 else s["adv_ge_20cr"] if adv >= 2e8 else s["below"]) / 100


def buy_cost(value, adv, cfg):
    c = cfg["costs"]
    ch = value * (c["exchange_txn_pct"] + c["sebi_fee_pct"] + c["brokerage_pct"]) / 100
    return value * (c["stt_entry_pct"] + c["stamp_duty_entry_pct"]) / 100 + ch * (1 + c["gst_pct_on_brokerage_and_charges"] / 100) + value * slip(adv, cfg)


def sell_cost(value, adv, cfg):
    c = cfg["costs"]
    ch = value * (c["exchange_txn_pct"] + c["sebi_fee_pct"] + c["brokerage_pct"]) / 100
    return value * c["stt_exit_pct"] / 100 + ch * (1 + c["gst_pct_on_brokerage_and_charges"] / 100) + value * slip(adv, cfg) + c["dp_charge_per_scrip_exit_inr"]


def position_cap(cal, cfg):
    """Quarter-Kelly ceiling per stock from the measured edge of the best group, never above max_position_share."""
    b = (cal or {}).get("buckets") or []
    if b and b[0].get("sd_excess_pct"):
        m, sd = b[0]["mean_excess_pct"] / 100, b[0]["sd_excess_pct"] / 100
        return float(min(cfg["max_position_share"], max(0.0, cfg["kelly_fraction"] * m / sd ** 2)))
    return cfg["max_position_share"]


def bucket(pct, cal):
    for b in (cal or {}).get("buckets", []):
        if b["from"] <= pct < b["to"] + (1e-9 if b["to"] >= 1 else 0):
            return b
    return None


def sessions_between(dates, a, b):
    """Number of sessions after date a up to and including date b, counted on the market's own calendar (the index dates)."""
    return int(((dates > pd.Timestamp(a)) & (dates <= pd.Timestamp(b))).sum())


def new_account(cfg, start):
    return {"version": cfg["version"], "start": str(start), "capital": cfg["capital_inr"], "cash": float(cfg["capital_inr"]), "positions": {}, "pending": None,
            "last_processed": None, "last_rebalance": None, "share": None, "peak": float(cfg["capital_inr"]), "kill": None, "history": [], "trades": [], "costs_paid": 0.0}


def fill_pending(acct, frames, dates, cfg, n5=None):
    """Fill the orders queued on an earlier evening at the open of the first session after that evening. -> list of fills."""
    p = acct.get("pending")
    if not p:
        return []
    created = pd.Timestamp(p["created"])
    after = dates[dates > created]
    if not len(after):
        return []
    day = after[0]
    fills = []
    for o in sorted(p["orders"], key=lambda o: o["side"] != "exit"):                         # sells first: they free the cash for the buys
        f = frames.get(o["sym"])
        if f is None or day not in f.index or not np.isfinite(f.loc[day, "o"]) or f.loc[day, "o"] <= 0:
            fills.append({**o, "status": "not filled: no opening price that day"}); continue
        px = float(f.loc[day, "o"])
        adv = o.get("adv", 0)
        pos = acct["positions"].get(o["sym"])
        if o["side"] == "exit" and pos:
            sh = pos["shares"] if o.get("all") else min(pos["shares"], math.floor(o["value"] / px))
            if sh <= 0:
                continue
            gross = sh * px
            c = sell_cost(gross, adv, cfg)
            acct["cash"] += gross - c; acct["costs_paid"] += c
            cost_basis = pos["entry_px"] * sh + pos["buy_cost"] * sh / pos["shares"]
            ir = None
            if n5 is not None and pos.get("n5_entry"):
                e1 = n5[n5.index <= day]
                ir = round(float(e1.iloc[-1]) / pos["n5_entry"] - 1, 4) if len(e1) else None
            acct["trades"].append({"sym": o["sym"], "side": "exit", "date": str(day.date()), "px": round(px, 2), "shares": sh, "cost": round(c, 2),
                                   "net_return": round((gross - c) / cost_basis - 1, 4), "index_return": ir, "entry_date": pos["entry_date"], "why": o["why"]})
            if sh >= pos["shares"]:
                del acct["positions"][o["sym"]]
            else:
                pos["buy_cost"] *= (pos["shares"] - sh) / pos["shares"]; pos["shares"] -= sh
            fills.append({**o, "status": f"sold {sh} at {px:.2f}"})
        elif o["side"] == "enter":
            budget = min(o["value"], acct["cash"])
            sh = math.floor(budget / (px * (1 + 0.003)))
            if sh <= 0:
                fills.append({**o, "status": "not filled: price above the position size or not enough cash"}); continue
            c = buy_cost(sh * px, adv, cfg)
            acct["cash"] -= sh * px + c; acct["costs_paid"] += c
            if o["sym"] in acct["positions"]:
                q = acct["positions"][o["sym"]]
                q["entry_px"] = (q["entry_px"] * q["shares"] + px * sh) / (q["shares"] + sh); q["shares"] += sh; q["buy_cost"] += c
            else:
                n5e = n5[n5.index <= day] if n5 is not None else []
                acct["positions"][o["sym"]] = {"shares": sh, "entry_px": px, "entry_date": str(day.date()), "buy_cost": c, "n5_entry": float(n5e.iloc[-1]) if len(n5e) else None}
            acct["trades"].append({"sym": o["sym"], "side": "enter", "date": str(day.date()), "px": round(px, 2), "shares": sh, "cost": round(c, 2), "why": o["why"]})
            fills.append({**o, "status": f"bought {sh} at {px:.2f}"})
    acct["pending"] = None
    return fills


def value(acct, frames, asof):
    v = acct["cash"]
    for sym, p in acct["positions"].items():
        f = frames.get(sym)
        px = float(f["c"][f.index <= asof].iloc[-1]) if f is not None and (f.index <= asof).any() else p["entry_px"]
        v += p["shares"] * px
    return v


def decide(acct, T, chosen, share, equity, asof, dates, cfg, cal, no_buys):
    """Queue tomorrow's orders. -> (orders, reason or None)."""
    due = acct["last_rebalance"] is None or sessions_between(dates, acct["last_rebalance"], asof) >= cfg["rebalance_every_sessions"]
    share_changed = acct.get("share") is not None and abs(share - acct["share"]) > 1e-9
    if not (due or share_changed):
        return [], None
    cap = position_cap(cal, cfg)
    n = max(1, len(chosen))
    per = min(equity * share / n, equity * cap)
    adv = T["adv60"].to_dict()
    orders = []
    keep = set(chosen)
    for sym in list(acct["positions"]):
        if due and sym not in keep:
            orders.append({"sym": sym, "side": "exit", "all": True, "value": 0, "adv": adv.get(sym, 0), "why": f"left the best {cfg['pick_share']:.0%} at the rebalance"})
    if not no_buys or share_changed:
        for sym in chosen:
            have = acct["positions"].get(sym)
            px = float(T.loc[sym, "last_close"]) if "last_close" in T.columns and sym in T.index else None
            cur = have["shares"] * px if (have and px) else 0.0
            gap = per - cur
            if have and share_changed and gap < -0.25 * per:
                orders.append({"sym": sym, "side": "exit", "all": False, "value": -gap, "adv": adv.get(sym, 0), "why": "invested share lowered (risk check)"})
            elif gap > 0.25 * per and not no_buys and not (acct.get("kill")):
                if not have or share_changed:
                    orders.append({"sym": sym, "side": "enter", "value": gap, "adv": adv.get(sym, 0), "why": "joined the best 5%" if not have else "invested share raised (risk check)"})
    reason = "rebalance" if due else "invested share changed"
    return orders, reason


def price_range(px, b):
    """-> {low, typical, high} prices 63 sessions on, from the rank group's measured spread (10th, 50th, 90th percentile), or None."""
    q = (b or {}).get("price_change_pct")
    if not q or not px:
        return None
    return {"low": round(px * (1 + q["p10"] / 100), 2), "typical": round(px * (1 + q["p50"] / 100), 2), "high": round(px * (1 + q["p90"] / 100), 2),
            "pct": [q["p10"], q["p50"], q["p90"]]}


def signals(acct, T, cal, cfg, asof, next_rebalance, chosen=()):
    """Buy and sell signals, taken straight from the paper account: what it will trade at the next open and what it holds. No stop price:
    the stop-loss test (aladin-audit/phase7_stop_test.py, 2026-11-13) failed, so the exits are the model's own rules."""
    close = lambda s: float(T.loc[s, "last_close"]) if s in T.index else None
    grp = lambda s: bucket(float(T.loc[s, "rank_pct"]), cal) if s in T.index else None
    rank = lambda s: int(T.loc[s, "rank"]) if s in T.index else None
    pend = (acct.get("pending") or {}) if (acct.get("pending") or {}).get("created") == str(asof.date()) else {}
    buy, sell = [], []
    for o in pend.get("orders", []):
        px = close(o["sym"])
        sh = math.floor(o["value"] / (px * 1.003)) if (px and o["side"] == "enter") else (acct["positions"].get(o["sym"], {}).get("shares") if o.get("all") else (math.floor(o["value"] / px) if px else None))
        row = {"sym": o["sym"], "state": "next open", "shares": sh, "ref_price": px, "rank": rank(o["sym"]), "why": o["why"]}
        if o["side"] == "enter":
            buy.append({**row, "range": price_range(px, grp(o["sym"]))})
        else:
            p = acct["positions"].get(o["sym"])
            sell.append({**row, "part": not o.get("all"), "entry_px": round(p["entry_px"], 2) if p else None,
                         "change_since_entry": round(px / p["entry_px"] - 1, 4) if (p and px) else None})
    leaving = {o["sym"] for o in pend.get("orders", []) if o["side"] == "exit" and o.get("all")}
    for sym, p in acct["positions"].items():
        if sym in leaving:
            continue
        px = close(sym)
        buy.append({"sym": sym, "state": "held", "shares": p["shares"], "ref_price": round(p["entry_px"], 2), "entry_date": p["entry_date"], "last_close": px, "rank": rank(sym),
                    "change_since_entry": round(px / p["entry_px"] - 1, 4) if px else None, "range": price_range(p["entry_px"], grp(sym)),
                    "why": f"in the best {cfg['pick_share']:.0%}" if sym in chosen else "kept until the next rebalance"})
    done = [{"sym": t["sym"], "date": t["date"], "px": t["px"], "shares": t["shares"], "net_return": t.get("net_return"), "why": t["why"]}
            for t in acct["trades"] if t["side"] == "exit"][-20:][::-1]
    return {"as_of": str(asof.date()), "buy": buy, "sell": sell, "sold_recently": done,
            "exits": {"next_rebalance_in_sessions": next_rebalance, "risk_check": "every evening: if the NIFTY 500 closes below its 200-day average, every position is halved at the next open",
                      "kill_switch": f"if the paper account falls {cfg['kill_drawdown']:.0%} from its peak, all buying stops"},
            "stop_loss": "none: fixed 15%, fixed 25% and trailing 20% stops were tested on 2010-2026 and all lowered the return per unit of risk (aladin-audit/phase7_stop_test.json)",
            "range_note": "Low and high: 8 in 10 stocks of the same rank group ended between them 63 sessions (about 3 months) after the entry; typical: the middle one. Measured 2010-2026, before costs, companies listed today only. Not a forecast for this stock."}


def run(asof, frames, n5, cfg, cal, acct, now=None, vix=None, fii=None):
    """One evening. -> (acct, latest dict). Pure apart from the inputs: tests drive it with synthetic prices."""
    dates = n5.index
    out = {"version": cfg["version"], "as_of": str(asof.date()), "generated_utc": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    newest = max((f.index[-1] for f in frames.values() if len(f)), default=None)
    stale = newest is None or len(dates) == 0 or sessions_between(dates, newest, dates[-1]) > cfg["stale_sessions"] or asof - newest > pd.Timedelta(days=7)
    if acct is None:
        acct = new_account(cfg, asof)
    behind = bool(acct.get("last_processed")) and str(asof.date()) < acct["last_processed"]    # prices older than the account: show, never change it
    fills = fill_pending(acct, frames, dates[dates <= asof], cfg, n5) if not (stale or behind) else []
    equity = value(acct, frames, asof)
    prev = acct["history"][-1][1] if acct["history"] else acct["capital"]
    day_ret = equity / prev - 1 if prev else 0.0
    already = acct["last_processed"] == str(asof.date()) or behind
    if not already:
        acct["history"].append([str(asof.date()), round(equity, 2), acct.get("share")])
    if not behind:
        acct["peak"] = max(acct["peak"], equity)
    dd = equity / acct["peak"] - 1
    if dd <= -cfg["kill_drawdown"] and not acct.get("kill") and not behind:
        acct["kill"] = {"since": str(asof.date()), "reason": f"the paper account fell {dd:.1%} from its peak (limit {-cfg['kill_drawdown']:.0%})"}
    on, n5_close, n5_ma = risk_on(n5, asof, cfg)
    T = rank_table(frames, asof, cfg)
    T["last_close"] = [float(frames[s]["c"][frames[s].index <= asof].iloc[-1]) for s in T.index]
    chosen = pick(T, cfg) if len(T) else []
    share = target_share(on, acct.get("kill"), cfg)
    no_buys = day_ret <= -cfg["daily_loss_pause_entries"]
    orders, reason = ([], None)
    status = "degraded" if stale else "stopped" if acct.get("kill") else "running"
    if not stale and not already and len(T):
        orders, reason = decide(acct, T, chosen, share, equity, asof, dates, cfg, cal, no_buys)
        if orders:
            acct["pending"] = {"created": str(asof.date()), "orders": orders, "reason": reason}
            if reason == "rebalance":
                acct["last_rebalance"] = str(asof.date())
        if acct.get("share") is None or orders:
            acct["share"] = share
        acct["last_processed"] = str(asof.date())
    since = sessions_between(dates, acct["last_rebalance"], asof) if acct.get("last_rebalance") else None
    out.update({
        "status": status, "degraded_reason": (f"prices end {newest.date() if newest is not None else 'nowhere'}" if stale else None),
        "risk": {"nifty500_close": n5_close, "nifty500_ma200": None if n5_ma is None else round(n5_ma, 2), "risk_on": on, "invested_share": share,
                 "kill": acct.get("kill"), "pause_entries_next_open": bool(no_buys)},
        "rules": {"lookback_days": cfg["lookback_days"], "pick_share": cfg["pick_share"], "rebalance_every_sessions": cfg["rebalance_every_sessions"],
                  "universe": f"the {cfg['universe_top']} most-traded main-board stocks with at least Rs {cfg['min_adv_inr'] / 1e7:.0f} Cr a day and {cfg['min_history_days']} sessions of prices"},
        "universe_size": int(len(T)), "portfolio_size": len(chosen),
        "next_rebalance_in_sessions": None if since is None else max(0, cfg["rebalance_every_sessions"] - since),
        "stocks": {s: [int(T.loc[s, "rank"]), round(float(T.loc[s, "rank_pct"]), 4), round(float(T.loc[s, "r126"]), 4), 1 if s in chosen else 0] for s in T.index} if not stale else {},
        "portfolio": [{"sym": s, "rank": int(T.loc[s, "rank"]), "r126": round(float(T.loc[s, "r126"]), 4)} for s in chosen] if not stale else [],
        "signals": signals(acct, T, cal, cfg, asof, None if since is None else max(0, cfg["rebalance_every_sessions"] - since), chosen) if (not stale and len(T)) else None,
        "calibration": cal, "costs": cfg["costs"],
        "market": market_strip(frames, n5, vix if vix is not None else pd.Series(dtype=float), fii, asof, cfg),
        "health": health(acct, n5, cfg), "last_rebalance": acct.get("last_rebalance"),
        "holdings": [{"sym": s, "shares": p["shares"], "entry_px": round(p["entry_px"], 2), "entry_date": p["entry_date"],
                      "last_close": round(float(frames[s]["c"][frames[s].index <= asof].iloc[-1]), 2) if s in frames and (frames[s].index <= asof).any() else None} for s, p in acct["positions"].items()],
        "paper": {"equity": round(equity, 2), "start": acct["start"], "capital": acct["capital"], "cash": round(acct["cash"], 2), "drawdown": round(dd, 4),
                  "positions": len(acct["positions"]), "costs_paid": round(acct["costs_paid"], 2), "pending": acct.get("pending"), "fills_today": fills,
                  "last_trades": acct["trades"][-40:], "history": acct["history"][-400:]},
        "disclaimer": "ALADIN is a statistical model built by students. It is often wrong. Educational analysis on paper only, not investment advice."})
    return acct, out


def main():
    cfg, cal = load(CFG), load(CAL)
    uni = load(TERM / "universe.json", {})
    if not cfg or not uni.get("stocks"):
        print("aladin_e: settings or universe missing; nothing done")
        return 0
    frames, n5 = load_market(eligible_stocks(uni))
    if not len(n5):
        print("aladin_e: NIFTY 500 history missing; nothing done")
        return 0
    asof = n5.index[-1]
    OUT.mkdir(parents=True, exist_ok=True)
    acct = load(OUT / "paper.json")
    acct, latest = run(asof, frames, n5, cfg, cal, acct, vix=series_of(VIX_FILE), fii=load(FII_FILE))
    (OUT / "paper.json").write_text(json.dumps(acct, separators=(",", ":"), default=str), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(latest, separators=(",", ":"), default=str, allow_nan=False), encoding="utf-8")
    print(f"aladin_e: {latest['as_of']} {latest['status']}; universe {latest['universe_size']}, portfolio {latest['portfolio_size']}; risk on {latest['risk']['risk_on']}, "
          f"invested {latest['risk']['invested_share']:.0%}; paper equity Rs {latest['paper']['equity']:,.0f}; pending {len((acct.get('pending') or {}).get('orders', []))} orders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
