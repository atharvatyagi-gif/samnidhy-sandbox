"""
Shadow account for the Bitcoin all-weather quant model (owner's choice 2026-10-12: "shadow, auto-switch").

  python scripts/crypto_shadow.py          one step (run every 15 minutes by crypto-live.yml, BEFORE the main engine; it can never stop the main engine)

What runs: the ML+TREND long/short model of scripts/crypto_quant.py, round-2 settings (the candidate closest to "trades in every market"; it did NOT pass the
pre-declared backtest gate, which is why it starts in the shadow instead of with the money). Same budget as the Bitcoin half of the live account (50% of
Rs 10,00,000 at the account's start rate), no leverage: the position is a fraction of the shadow account from -1 (fully short, a 1x perpetual future) to +1
(fully long, spot).

  daily      once the 00:00 UTC 4-hour bar has closed: score = average of ML (ridge + LightGBM, refitted on the first run of every month on the previous 3 years)
             and TREND (multi-horizon momentum); smoothed over the last 3 daily scores; target = clip(tanh(score) x 0.40 / realised vol, -1, +1); traded only
             if it differs from the current position by 0.25 or more: buys at the live ask, sells at the live bid, 0.12% of the traded value each time.
  funding    while short, at every 8-hour funding time the short receives (rate > 0) or pays (rate < 0) rate x position value, applied when Binance has
             published that rate (until then it is listed as pending).
  promotion  after at least 182 days, if the shadow's return since its start beats the return of the two Bitcoin sleeves of the live account over the same
             days (both after all costs), a "promote" line is written; from then on the live engine hands the Bitcoin half of the account to this model.
             Checked once a day, decided once, never reversed automatically.
Everything is appended to data/crypto/shadow_ledger.jsonl and replayed from it; data/crypto/shadow.json is the page's copy.
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypto_flow as CF  # noqa: E402
import crypto_funding as FU  # noqa: E402
import crypto_quant as Q  # noqa: E402

OUT = CF.OUT
LEDGER, PAGE, MODEL, RECENT = OUT / "shadow_ledger.jsonl", OUT / "shadow.json", OUT / "quant_model.json", OUT / "bars_15m_recent.csv.gz"
R2 = Q.ROUNDS[2]
PROMOTE_DAYS = 182
SMOOTH = R2["smooth"]


def read(path=None):
    p = Path(path or LEDGER); return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def append(rec, path=None):
    p = Path(path or LEDGER); p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def replay(lines):
    """{cash, units, decided days, settled funding times, scores [(day, score)], start, promote} from the ledger alone. units < 0 = short."""
    st = {"cash": None, "units": 0.0, "decided": set(), "funded": set(), "pending": [], "scores": [], "start": None, "promote": None, "fills": 0, "cost": 0.0, "funding": 0.0}
    for r in lines:
        t = r["t"]
        if t == "start":
            st["cash"], st["start"] = r["budget_usd"], r
        elif t == "decision":
            st["decided"].add(r["day"]); st["scores"].append((r["day"], r["score"]))
        elif t == "fill":
            st["cash"] -= r["units"] * r["price"] + r["cost"]; st["units"] += r["units"]; st["fills"] += 1; st["cost"] += r["cost"]
        elif t == "funding":
            st["cash"] += r["amount"]; st["funded"].add(r["at"]); st["funding"] += r["amount"]
        elif t == "promote":
            st["promote"] = r
    return st


# ------------------------------------------------------------------ data and model
def history(fetched=None):
    """Full 15-minute history: the archived file, the recent file kept by this script, and what the main engine fetched this run."""
    parts = [CF.load_bars(symbol="BTCUSDT")]
    if RECENT.exists():
        parts.append(pd.read_csv(RECENT, index_col=0, parse_dates=True))
    if fetched is not None and len(fetched):
        parts.append(fetched)
    b = pd.concat(parts); b = b[~b.index.duplicated(keep="last")].sort_index(); return b


def save_recent(b):
    r = b[b.index >= CF.load_bars(symbol="BTCUSDT").index[-1]]; r.to_csv(RECENT, compression="gzip")


def model_fit(b, fu, now):
    """Refit ridge + LightGBM on the 3 years before the current month (the target needs 42 bars ahead, so the last 42 are left out)."""
    import lightgbm as lgb
    f, X, y, rv = Q.build(b, fu, target_h=R2["target_h"]); m = pd.Timestamp(now.date()).replace(day=1); lo = m - pd.DateOffset(years=Q.WIN_Y)
    idx = X.index; tr = idx[(idx >= lo) & (idx < m)][:-R2["target_h"]]; d = X.loc[tr, Q.FEATS].join(y).dropna(subset=["y"]); d = d[d[Q.FEATS].notna().sum(axis=1) >= len(Q.FEATS) - 3]
    mdl = Q.fit_models(d[Q.FEATS], d["y"])
    doc = {"month": str(m.date()), "fitted_utc": now.isoformat(timespec="seconds"), "rows": len(d), "train_from": str(d.index[0]), "train_to": str(d.index[-1]), "feats": Q.FEATS,
           "ridge": {"mu": mdl["ridge"].mu.tolist(), "sd": mdl["ridge"].sd.tolist(), "w": mdl["ridge"].w.tolist(), "b": mdl["ridge"].b}, "med": mdl["med"].tolist(), "sr": mdl["sr"], "sg": mdl["sg"],
           "lgb": mdl["lgb"].booster_.model_to_string()}
    MODEL.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8"); return doc


def model_load(doc):
    import lightgbm as lgb
    r = Q.Ridge(); r.mu, r.sd, r.w, r.b = np.array(doc["ridge"]["mu"]), np.array(doc["ridge"]["sd"]), np.array(doc["ridge"]["w"]), doc["ridge"]["b"]
    g = lgb.Booster(model_str=doc["lgb"])
    return {"ridge": r, "lgb": g, "med": np.array(doc["med"]), "sr": doc["sr"], "sg": doc["sg"]}


def score_rows(b, fu, mdl):
    f, X, y, rv = Q.build(b, fu, target_h=R2["target_h"])
    ml = Q.predict_models(mdl, X[Q.FEATS]); trend = Q.rule_score(X, "TREND"); return f, (ml + trend) / 2, rv


def naive(t):
    t = pd.Timestamp(t); return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t


# ------------------------------------------------------------------ one step
def step(now=None, fetched=None, quote=None, fu=None, ledger=None, page=None, live_doc=None, refit=True):
    now = now or datetime.now(timezone.utc); led = Path(ledger or LEDGER); ts = now.isoformat(timespec="seconds"); lines = read(led)
    if not lines:
        live = live_doc or json.loads((OUT / "live.json").read_text(encoding="utf-8"))
        btc0 = sum(v["equity"] for k, v in live["sleeves"].items() if v["asset"] == "BTCUSDT")
        append({"t": "start", "ts": ts, "budget_usd": round(live["budget_usd"] * 0.5, 2), "fx0": live["fx0"], "btc_sleeves_equity0": round(btc0, 2),
                "model": "ML+TREND long/short (crypto_quant.py round 2)", "rule": f"promote after {PROMOTE_DAYS} days if the shadow's return beats the live Bitcoin sleeves' return over the same days"}, led)
        lines = read(led)
    st = replay(lines)
    b = history(fetched); fu = FU.load() if fu is None else fu
    doc = json.loads(MODEL.read_text(encoding="utf-8")) if MODEL.exists() else None
    if refit and (doc is None or doc["month"] != str(pd.Timestamp(now.date()).replace(day=1).date())):
        doc = model_fit(b, fu, now); append({"t": "refit", "ts": ts, "month": doc["month"], "rows": doc["rows"], "train_from": doc["train_from"], "train_to": doc["train_to"]}, led); lines = read(led)
    mdl = model_load(doc)
    f, score, rv = score_rows(b, fu, mdl)
    q = quote or {"bid": float(f["c"].iloc[-1]), "ask": float(f["c"].iloc[-1])}; mid = (q["bid"] + q["ask"]) / 2
    # 1. funding for the time held short (pending until Binance publishes the rate)
    if st["units"] < 0:
        fr = fu.set_index("ts")["rate"] if len(fu) else pd.Series(dtype=float)
        last_fill = max((naive(r["ts"]) for r in lines if r["t"] == "fill"), default=naive(now))
        for t in pd.date_range(last_fill.ceil("8h"), naive(now), freq="8h"):
            key = str(t)
            if key in st["funded"]:
                continue
            if t in fr.index:
                amt = -st["units"] * mid * float(fr[t]); append({"t": "funding", "ts": ts, "at": key, "rate": float(fr[t]), "amount": round(amt, 4)}, led); st["funded"].add(key)
    st = replay(read(led))
    # 2. the daily decision, once the 00:00 UTC bar has closed
    days = f.index[f.index.hour == 0]; day = days[-1] if len(days) else None; nowt = naive(now)
    if day is not None and str(day.date()) not in st["decided"] and day + pd.Timedelta("4h") <= nowt and not math.isnan(score.loc[day]):
        prev = [s for d, s in st["scores"]][-(SMOOTH - 1):] if SMOOTH > 1 else []
        if len(prev) < SMOOTH - 1:                                                        # first days: the earlier daily scores from the same model
            earlier = [float(score.loc[d]) for d in days[-SMOOTH:-1] if not math.isnan(score.loc[d])]; prev = earlier[-(SMOOTH - 1):]
        s = float(np.mean(prev + [float(score.loc[day])])); vol = float(rv.loc[day]); target = float(np.clip(math.tanh(s) * Q.TV / vol, -1, 1)) if vol > 0 else 0.0
        eq = st["cash"] + st["units"] * mid; pos = st["units"] * mid / eq if eq > 0 else 0.0; act = "hold"
        if abs(target - pos) >= R2["band"]:
            px = q["ask"] if target > pos else q["bid"]; du = (target * eq - st["units"] * px) / px; cost = abs(du) * px * CF.COST
            append({"t": "fill", "ts": ts, "units": round(du, 8), "price": round(px, 2), "cost": round(cost, 4), "from_pos": round(pos, 3), "to_pos": round(target, 3), "bid": q["bid"], "ask": q["ask"]}, led); act = "trade"
        append({"t": "decision", "ts": ts, "day": str(day.date()), "bar": str(day), "score_raw": round(float(score.loc[day]), 4), "score": round(s, 4), "vol": round(vol, 4), "target": round(target, 3), "position_before": round(pos, 3), "action": act}, led)
    st = replay(read(led)); eq = st["cash"] + st["units"] * (q["bid"] if st["units"] > 0 else q["ask"])
    # 3. comparison with the live Bitcoin sleeves, and the promotion rule
    live = live_doc or (json.loads((OUT / "live.json").read_text(encoding="utf-8")) if (OUT / "live.json").exists() else None)
    s0 = st["start"]; days_run = (nowt - naive(s0["ts"])).days
    btc_now = sum(v["equity"] for k, v in live["sleeves"].items() if v["asset"] == "BTCUSDT") if live else None
    shadow_ret = eq / s0["budget_usd"] - 1; live_ret = (btc_now / s0["btc_sleeves_equity0"] - 1) if btc_now and s0["btc_sleeves_equity0"] else None
    if st["promote"] is None and days_run >= PROMOTE_DAYS and live_ret is not None and shadow_ret > live_ret:
        append({"t": "promote", "ts": ts, "days": days_run, "shadow_return_pct": round(shadow_ret * 100, 2), "live_btc_return_pct": round(live_ret * 100, 2), "shadow_equity": round(eq, 2)}, led); st = replay(read(led))
    pos = st["units"] * mid / eq if eq > 0 else 0.0; last = [r for r in read(led) if r["t"] == "decision"][-30:]
    out = {"kind": "SHADOW ACCOUNT (Bitcoin all-weather quant model)", "label": "SHADOW: simulated money beside the live account, same budget as its Bitcoin half. It takes over that half only if it does better over at least 182 days.",
           "engine_ts": ts, "started": s0["ts"], "budget_usd": s0["budget_usd"], "equity_usd": round(eq, 2), "return_pct": round(shadow_ret * 100, 3), "position": round(pos, 3),
           "side": "long" if pos > 0.01 else "short" if pos < -0.01 else "flat", "units": round(st["units"], 8), "fills": st["fills"], "costs_usd": round(st["cost"], 2), "funding_usd": round(st["funding"], 2),
           "live_btc_return_pct": round(live_ret * 100, 3) if live_ret is not None else None, "days": days_run, "promote_after_days": PROMOTE_DAYS, "promoted": st["promote"],
           "model": {k: doc[k] for k in ("month", "fitted_utc", "rows", "train_from", "train_to")}, "decisions": last, "price": round(mid, 2)}
    Path(page or PAGE).write_text(json.dumps(out, separators=(",", ":"), default=str), encoding="utf-8")
    return out


def main():
    import crypto_live as CL
    now = datetime.now(timezone.utc); fetched = CL.fetch_bars(now, symbol="BTCUSDT"); q = CL.quote("BTCUSDT")
    try:
        FU.update()
    except Exception as e:                                                       # noqa: BLE001  stale funding only delays the funding lines
        print("funding update failed:", type(e).__name__)
    b = history(fetched); save_recent(b)
    d = step(now, fetched=fetched, quote=q)
    print(f"shadow: equity ${d['equity_usd']:,.2f} ({d['return_pct']:+.3f}%) position {d['position']:+.2f} ({d['side']}) | live BTC sleeves {d['live_btc_return_pct']}% | day {d['days']} of {PROMOTE_DAYS}")


if __name__ == "__main__":
    main()
