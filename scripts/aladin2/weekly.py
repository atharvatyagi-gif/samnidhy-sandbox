"""
ALADIN 2.0 WEEKLY signal: a BUY or SELL for the next five trading days, from everything the engine measures.

What was measured first (scripts/aladin2/weekly_study.py, 310,816 stock-weeks, 655 Fridays, 2013-2026, trade at the next open and out five trading days later, full costs, market-adjusted):
  * ALADIN 1's 5-day score is the only input with weekly skill. 5-day reversal and 3-month momentum, and a blend or stack of all three, added nothing net of costs.
  * SELL side (the worst 5% of the week): 14 of 14 years below the market, about -72 bps a week before costs (95% interval -87 to -56), 42% close up. This is the reliable side.
  * BUY side: the best 10% earns about +30 bps a week before costs against a 37 bps round trip, so it does NOT pay on average. Only the very best 1% clears costs (+27 bps net, interval +6 to +47, 9 of 14 years positive).
Rules (fixed before this code was written, from that study):
  BUY   = top 1% of the week's liquid stocks by the 5-day score (about 5 stocks), Friday close basis
  SELL  = bottom 5% (about 24 stocks). Cash-equity delivery cannot be shorted: SELL means EXIT if you hold it, do not buy it; a short is possible only through futures in F&O stocks.
  HOLD  = everything else. Exit rule for every signal: the open of the 5th trading day after entry (the weekly time limit), or the invalidation level if hit first.
The other inputs (fundamental, sentiment, supply-chain impact, the 20-day Outlook, the forecast range, the strategy states) are shown with every signal and tested: none of them improved the weekly result,
and the ones with no weekly history (fundamental, sentiment, supply-chain impact) cannot be tested at all. They are context, not part of the rule. Survivorship flatters the BUY side and understates the SELL side.
"""
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import forecast as FC
from . import ledger as LG
from . import signals as SG

ROOT = Path(__file__).resolve().parent.parent.parent
H = 5
MIN_ADV_CR = 2.0


def study():
    p = ROOT / "data" / "aladin2" / "weekly_study.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def liquid(universe_stocks):
    """{symbol: dict(name, sector, adv_cr, close, avgv20)} for Main-board non-ETF stocks with 20-day average traded value >= Rs 2 crore."""
    out = {}
    for s in universe_stocks:
        if s.get("board") != "Main" or s.get("etf"):
            continue
        adv = (s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7
        if adv >= MIN_ADV_CR:
            out[s["s"]] = {"name": s.get("n") or s["s"], "sector": s.get("ind") or "Unknown", "adv_cr": adv, "close": s.get("c")}
    return out


def rank_universe(aladin, liq):
    """Percentile rank (0 = worst, 1 = best) of the 5-day technical probability among the liquid stocks. Ties (the published probabilities are rounded) are broken by the combined probability, then
    by the symbol, so the same inputs always give the same list. Returns a DataFrame sorted best first."""
    rows = []
    for sym, e in aladin["stocks"].items():
        if sym not in liq:
            continue
        p5 = (e.get("t") or {}).get("p", {}).get("5"); comb = (e.get("comb") or {}).get("5")
        if p5 is None:
            continue
        rows.append((sym, float(p5), float(comb[0]) if comb else float(p5), comb[1] if comb else None, comb[2] if comb else None))
    D = pd.DataFrame(rows, columns=["sym", "p5", "comb5", "conf", "agree"]).sort_values(["p5", "comb5", "sym"], ascending=[False, False, True]).reset_index(drop=True)
    n = len(D); D["pct"] = 1 - (D.index.values + 0.5) / n
    return D


def chance(pct, curve):
    """The measured chance, for a stock whose rank percentile is `pct`: how often stocks in that rank bucket CLOSED HIGHER over the next 5 trading days and how often they BEAT THE MARKET, with 95% intervals
    (calendar months resampled), from the weekly study. The numbers are frequencies from 2013-2026 (and were checked out of sample: calibration error 0.015 and 0.010). They are the chance for a typical
    stock in that bucket, not a forecast for one stock. None if the study is not on disk."""
    if not curve:
        return None
    for b in curve:
        if b["from"] <= pct < b["to"] + (1e-9 if b["to"] >= 1.0 else 0):
            return {"closes_higher": b["p_up"], "closes_higher_ci95": b["p_up_ci95"], "beats_market": b["p_beat_market"], "beats_market_ci95": b["p_beat_market_ci95"], "n_stock_weeks": b["n"], "bucket": [b["from"], b["to"]]}
    return None


def decide(pct, cfg_w):
    return "bull" if pct >= cfg_w["buy_top_pct"] else "bear" if pct <= cfg_w["sell_bottom_pct"] else "none"


def record_of(st, key):
    """The measured weekly record of a signal bucket, as stored by the study (bull -> top 1%, bear -> bottom 5%)."""
    if not st:
        return None
    return st.get("record", {}).get("buy" if key == "bull" else "sell")


def business_day(d, n):
    """The date n weekdays after d (exchange holidays are not known, so it can be a day or two early)."""
    x = pd.Timestamp(d); k = 0
    while k < n:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5:
            k += 1
    return str(x.date())


def build(as_of, aladin, universe_stocks, cfg, predict=None, sentiment=None, fno=None, forecasts=None, prices=None, calendar=None, capital=1_000_000):
    """The weekly signal book for the signal date `as_of` (a string date). All inputs are plain dicts so the function is testable without files.
    forecasts: {sym: {"bands5": [lo50, hi50, lo80, hi80, lo95, hi95], "bands20": [...]}} from the ledger batch; prices: {sym: DataFrame o,h,l,c,v} for ATR; fno: set of futures-eligible symbols."""
    W = cfg["weekly"]; st = study(); liq = liquid(universe_stocks); R = rank_universe(aladin, liq); curve = (st or {}).get("probability_curve"); decile_pool = [v["adv_cr"] for v in liq.values()]; out = {"bull": [], "bear": [], "universe": int(len(R))}
    pred = (predict or {}).get("stocks", {}); sent = (sentiment or {}).get("stocks", {}); fno = fno or set()
    friday = pd.Timestamp(as_of).weekday() == 4
    for r in R.itertuples():
        key = decide(r.pct, W)
        if key == "none":
            continue
        sym = r.sym; meta = liq[sym]; dec = C.adv_decile(meta["adv_cr"], decile_pool); rt = C.round_trip_bps("long", "delivery", dec, cfg); fut = C.round_trip_bps("long", "futures", dec, cfg)
        px = (prices or {}).get(sym); close = float(px["c"].iloc[-1]) if px is not None and len(px) else float(meta["close"] or 0)
        atr = float(L.price_features(L.clean_prices(px))["atr14"].iloc[-1]) if px is not None and len(px) > 60 else close * 0.02
        rec = record_of(st, key); f = (forecasts or {}).get(sym) or {}
        row = {"sym": sym, "name": meta["name"], "sector": meta["sector"], "signal": key, "rank_pct": round(float(r.pct), 4), "p5": r.p5, "close": round(close, 2), "atr": round(atr, 2), "round_trip_cost_bps": round(rt, 1),
               "entry": "next session open", "adv_shares": int(meta["adv_cr"] * 1e7 / max(close, 1)), "exit": f"open of the 5th trading day after entry ({business_day(as_of, 6)})", "weekday_validated": bool(friday), "chance": chance(float(r.pct), curve), "fno": sym in fno, "state": "Provisional",
               "state_why": "supported by 13 years of out-of-sample weekly history, but ALADIN has no live weekly record yet: it needs 60 live days and a positive live result to become Validated",
               "evidence": {"aladin1_technical_p5": r.p5, "aladin1_combined_p5": r.comb5, "aladin1_confidence": r.conf, "aladin1_agreement": r.agree, "outlook_p_beat_nifty_20d": (pred.get(sym) or {}).get("p") if isinstance(pred.get(sym), dict) else None,
                            "sentiment_level": (sent.get(sym) or {}).get("lvl"), "supply_chain_impact": ((aladin["stocks"].get(sym) or {}).get("x") or {}).get("i"), "range_5d_80pct": f.get("bands5", [None] * 6)[2:4] if f else None,
                            "strategies_active": 0}}
        if key == "bull":
            stop = SG.choose_stop(close, atr, None, None, cfg); zone = SG.entry_zone(close, atr, cfg); sz = SG.position_size(capital, close, stop, (meta["adv_cr"] * 1e7 / max(close, 1)), (rec or {}).get("net_bps", 0) / 1e4, W["weekly_sd"], cfg)
            row.update({"entry_zone": [round(zone[0], 2), round(zone[1], 2)], "invalidation": round(stop, 2), "expected_net_bps": (rec or {}).get("net_bps"), "record": rec, "size_for_capital": {"capital": capital, "qty": sz["qty"], "binding": sz["binding"], "capital_at_risk": round(sz["capital_at_risk"], 0)},
                        "what_to_do": f"Enter near {zone[0]:.2f}-{zone[1]:.2f} at the next open; leave at the open of the 5th trading day, or earlier if the price closes below {stop:.2f}."})
            out["bull"].append(row)
        else:
            row.update({"expected_vs_market_bps": (rec or {}).get("gross_excess_bps"), "record": rec, "short_net_bps_via_futures": round(abs((rec or {}).get("gross_excess_bps", 0)) - fut, 1) if (sym in fno and rec) else None,
                        "what_to_do": "If you hold it, exit at the next open. If you do not, do not add it this week. Cash shares cannot be shorted" + ("; it has futures, so a short through futures is possible (costs about %.0f bps a round trip)." % fut if sym in fno else ".")})
            out["bear"].append(row)
    out["ranks"] = {x.sym: [round(float(x.pct), 4), (chance(float(x.pct), curve) or {}).get("closes_higher"), (chance(float(x.pct), curve) or {}).get("beats_market")] for x in R.itertuples()}
    out["as_of"] = str(as_of); out["horizon_trading_days"] = H; out["counts"] = {"bull": len(out["bull"]), "bear": len(out["bear"]), "hold": int(len(R) - len(out["bull"]) - len(out["bear"]))}
    out["rules"] = {"bull": f"best {100 - W['buy_top_pct'] * 100:.0f}% of {len(R)} liquid stocks by the 5-day score", "bear": f"worst {W['sell_bottom_pct'] * 100:.0f}%"}
    out["study"] = {k: st[k] for k in ("rows", "weeks", "stocks", "from", "to", "universe_mean_weekly_return_bps", "avg_round_trip_cost_bps")} if st else None
    return out


# ------------------------------------------------------------------ ledger: weekly signals and what happened to them

def ledger_record(book, created):
    return {"t": "wk", "d": book["as_of"], "H": H, "created": str(created), "buy": [[r["sym"], r["close"], r["rank_pct"]] for r in book["bull"]], "sell": [[r["sym"], r["close"], r["rank_pct"]] for r in book["bear"]], "universe": book["universe"],
            "weekday_validated": bool(book["bull"] and book["bull"][0]["weekday_validated"] or book["bear"] and book["bear"][0]["weekday_validated"])}


def resolve(wk, prices, cfg, decile_of, mkt):
    """The `wkout` line for one signal week: realised return from the open after the signal date to the open five trading days later, per signal, net of costs, and the equal-weight market over the same
    days (`mkt`, computed by the caller from the liquid universe). prices(sym) -> DataFrame o. Returns None when the exit open is not in the data yet."""
    def trade(sym):
        px = prices(sym)
        if px is None:
            return None
        i = px.index.searchsorted(pd.Timestamp(wk["d"]))
        if i >= len(px) or px.index[i] != pd.Timestamp(wk["d"]) or i + 1 + H >= len(px):
            return None
        return float(px["o"].iloc[i + 1 + H] / px["o"].iloc[i + 1] - 1), str(px.index[i + 1 + H].date())
    res = {"t": "wkout", "d": wk["d"], "H": H, "buy": [], "sell": [], "mkt": None}
    for side in ("buy", "sell"):
        for sym, close, pct in wk[side]:
            t = trade(sym)
            if t is None:
                return None
            cost = C.round_trip_bps("long", "delivery", decile_of(sym), cfg) / 1e4
            res[side].append([sym, round(t[0], 5), round(cost, 5)]); res["on"] = t[1]
    res["mkt"] = round(float(mkt), 5)
    return res


def made_in_time(wk):
    """A signal is LIVE only if it was written before the entry open: the next weekday after the signal date at 09:15 India time (03:45 UTC). Exchange holidays are not known, so a signal written
    during a holiday gap counts as in time only if it is before that weekday's open; that errs toward excluding."""
    entry_day = pd.Timestamp(W_next_weekday(wk["d"])); cutoff = entry_day + pd.Timedelta(hours=3, minutes=45)
    created = pd.Timestamp(wk["created"]); created = created.tz_convert("UTC").tz_localize(None) if created.tzinfo else created
    return created < cutoff


def W_next_weekday(d):
    x = pd.Timestamp(d) + pd.Timedelta(days=1)
    while x.weekday() >= 5:
        x += pd.Timedelta(days=1)
    return x.normalize()


def live_record(folder=None):
    """Live weekly record recomputed from the raw ledger lines: for BUY and SELL signals that were created BEFORE their entry day, how many resolved, how many closed up, the mean return and the mean
    excess over the market, net of costs for BUY. -> {} until a week has resolved."""
    L_ = LG.read_all(folder); wks = {r["d"]: r for r in L_ if r["t"] == "wk"}; outs = [r for r in L_ if r["t"] == "wkout"]; rec = {"weeks_resolved": 0, "bull": {"n": 0}, "bear": {"n": 0}}
    for o in outs:
        wk = wks.get(o["d"])
        if wk is None or not made_in_time(wk):
            continue                                                         # made after the entry open had already happened: not a live signal
        rec["weeks_resolved"] += 1
        for side, name in (("buy", "bull"), ("sell", "bear")):
            for sym, ret, cost in o[side]:
                d = rec[name]; d["n"] += 1; d["up"] = d.get("up", 0) + (ret > 0); d["ret_sum"] = d.get("ret_sum", 0) + ret; d["ex_sum"] = d.get("ex_sum", 0) + ret - o["mkt"]; d["exn_sum"] = d.get("exn_sum", 0) + ret - cost - o["mkt"]
    for side in ("bull", "bear"):
        d = rec[side]
        if d["n"]:
            d.update({"share_up": round(d["up"] / d["n"], 4), "mean_return_bps": round(d["ret_sum"] / d["n"] * 1e4, 1), "mean_excess_bps": round(d["ex_sum"] / d["n"] * 1e4, 1), "mean_excess_net_bps": round(d["exn_sum"] / d["n"] * 1e4, 1)})
    return rec
