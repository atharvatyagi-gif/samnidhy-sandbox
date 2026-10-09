"""
ALADIN BOT console: the data behind the page that shows what ALADIN is doing, step by step, with graphs, and how it reaches a call. The page is locked by an access CODE.

How the lock works (honest version): the site is static files, so a password prompt alone would only hide the page. Here the DATA is encrypted: AES-256-GCM, with the key derived from the code by
PBKDF2-SHA256 (600,000 rounds). The encrypted file (aladin2/bot.enc.json) is public but unreadable without the code; the browser derives the key and decrypts in memory. Wrong code or any tampering
fails the GCM check. Limits: anyone who has the code can read it and share it (rotate the code to revoke: rebuild with a new one); the page's JavaScript is public (it contains no data); the code must be long
and random (the generator below makes 99 bits).

  python -m scripts.aladin2.bot --new-code            print a fresh random code (nothing is written)
  python -m scripts.aladin2.bot --build               build data/aladin2/bot.enc.json from today's files using the code in the environment variable ALADIN_BOT_CODE
Without ALADIN_BOT_CODE nothing is built and the page says the console is not published. The code is never written to disk, logged or committed by this script.
"""
import argparse
import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CUT = json.loads((ROOT / "data" / "config" / "aladin2.json").read_text(encoding="utf-8"))["weekly"]          # the signal cut-offs (best / worst share of the ranked stocks)
DATA = ROOT / "data" / "aladin2"
AAD = b"aladin-bot-v1"
ITER = 600_000
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"            # no I, L, O, 0, 1: nothing to misread when typing


def new_code():
    return "ALADIN-" + "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(5))


def normalise(code):
    """Case, spaces and dashes do not matter: 'aladin-abcd-...' and 'ALADINABCD...' are the same code. The JavaScript does exactly the same."""
    return "".join(ch for ch in str(code).upper() if ch.isalnum())


def _key(code, salt, iterations):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(normalise(code).encode())


def encrypt(payload, code, iterations=ITER):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(code, salt, iterations)).encrypt(iv, json.dumps(payload, separators=(",", ":"), default=str).encode(), AAD)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iterations, "salt": b(salt), "iv": b(iv), "aad": AAD.decode(), "ct": b(ct)}


def decrypt(blob, code):
    """-> the payload dict. Raises cryptography.exceptions.InvalidTag for a wrong code or a changed file."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = lambda x: base64.b64decode(x)
    return json.loads(AESGCM(_key(code, d(blob["salt"]), blob["iter"])).decrypt(d(blob["iv"]), d(blob["ct"]), blob["aad"].encode()))


# ------------------------------------------------------------------ the payload

def _j(p):
    p = Path(p); return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _cut_txt(f):
    return f"{round(f * 100, 1):g}%"


def build_payload(weekly=None, study=None, phase3=None, ledger_lines=None, journal=None, summary=None, run_report=None, strategies=None, prices=None, aladin=None, counts=None):
    """Everything the console draws, from plain dicts (testable without files). Nothing is invented: a missing input is None and the page says so."""
    book = (weekly or {}).get("book") or {}; ch = (study or {}).get("charts") or {}; rec = (study or {}).get("record") or {}
    fcs = [r for r in (ledger_lines or []) if r["t"] == "fc"]; wks = [r for r in (ledger_lines or []) if r["t"] == "wk"]; outs = [r for r in (ledger_lines or []) if r["t"] == "out"]
    n_pred = sum(len(f["syms"]) * len(f["H"]) for f in fcs)
    wc = (study or {}).get("charts", {}).get("weekly_curves") or {}
    live = (weekly or {}).get("live_record") or {}
    k = {"forecasts_made": n_pred, "forecast_batches": len(fcs), "weekly_books": len(wks), "signals_today": {"bull": len(book.get("bull", [])), "bear": len(book.get("bear", [])), "hold": (book.get("counts") or {}).get("hold")},
         "stocks_ranked": book.get("universe"), "outcomes_resolved": sum(len(o["syms"]) for o in outs), "live_weekly": live,
         "history": {"weeks": (study or {}).get("weeks"), "stock_weeks": (study or {}).get("rows"), "bull_closed_higher": (rec.get("buy") or {}).get("share_closing_up"), "bear_closed_higher": (rec.get("sell") or {}).get("share_closing_up"),
                     "bull_net_bps_per_week": (rec.get("buy") or {}).get("net_bps"), "bull_net_ci95_bps": (rec.get("buy") or {}).get("net_ci95_bps"), "bull_years_positive": (rec.get("buy") or {}).get("years_positive_net"),
                     "bear_vs_market_bps_per_week": (rec.get("sell") or {}).get("gross_excess_bps"), "bear_years_below_market": (rec.get("sell") or {}).get("years_below_market"), "label": "HISTORICAL SIMULATION 2013-2026 (out of sample, survivors to today): not live and not real money"}}
    timings = (summary or {}).get("timings_s") or []
    stages = [
        {"id": "ingest", "name": "1 · Read the market", "what": "Loads daily prices for every NSE stock, the NIFTY index, India VIX, currency and global indices, NSE delivery percentage and futures open interest.", "how": "Only data public by the close is used; later-published data waits one more trading day. Bad prints are dropped, unadjusted corporate actions are flagged and avoided.",
         "numbers": {"stocks_with_prices": (counts or {}).get("price_files"), "delivery_files": (counts or {}).get("deliv_files"), "futures_files": (counts or {}).get("fno_files"), "last_bar": (counts or {}).get("last_bar")}},
        {"id": "score", "name": "2 · Score every stock", "what": "ALADIN 1's ensemble of gradient-boosted trees turns about 60 price, volume and market inputs per stock into a 5-day probability of closing higher.", "how": "Trained only on earlier years and tested on unseen ones; the 5-day score is the one input that ranked next week's winners and losers.",
         "numbers": {"stocks_scored": len((aladin or {}).get("stocks", {})) or None, "liquid_stocks_ranked": book.get("universe")}},
        {"id": "rank", "name": "3 · Rank and apply the rule", "what": "Ranks the liquid stocks (at least Rs 2 crore traded a day). Best " + _cut_txt(1 - CUT["buy_top_pct"]) + " get a positive signal, worst " + _cut_txt(CUT["sell_bottom_pct"]) + " a negative one, the rest nothing.", "how": "The cut-offs were fixed from a 310,816 stock-week study before any live signal existed; the negative band was narrowed from 5% to 2% on 2026-10-09 (picked on 2013-2020, held-out 2021-2026 confirmed it).",
         "numbers": {"positive": (book.get("counts") or {}).get("bull"), "negative": (book.get("counts") or {}).get("bear"), "none": (book.get("counts") or {}).get("hold")}},
        {"id": "chance", "name": "4 · Turn rank into a chance", "what": "Looks up how often stocks at that rank closed higher, and beat the market, in the next 5 trading days.", "how": "Frequencies from 2013-2026 with 95% intervals; checked out of sample (calibration error 0.015 and 0.010).",
         "numbers": {"buckets": len((study or {}).get("probability_curve") or []), "check": (study or {}).get("probability_check")}},
        {"id": "range", "name": "5 · Forecast the range", "what": "For the 500 most-traded stocks, a volatility model plus quantile regression plus a conformal correction gives the 50, 80 and 95% price ranges at 1, 5, 10, 20 and 60 days.", "how": "The correction is learned on the previous two years and makes the ranges hold their promise: 48-49%, 78-80% and 94-95% of the time out of sample.",
         "numbers": {"stocks_forecast": (summary or {}).get("stocks_forecast"), "horizons": (summary or {}).get("horizons"), "seconds": next((t[1] for t in timings if str(t[0]).startswith("panel")), None)}},
        {"id": "risk", "name": "6 · Plan the trade and the risk", "what": "Entry zone, exit level (2 ATR), exit time (5th trading day), round-trip cost, and a position size for your capital capped by risk, position size, liquidity and a fraction of Kelly.", "how": "A stop does not always fill at its level; sizing reduces the risk of loss, it does not remove it.", "numbers": {"max_risk_per_trade_pct": 1.0, "max_position_pct": 10}},
        {"id": "learn", "name": "7 · Keep a record and learn", "what": "Writes every forecast and signal to an append-only ledger, scores it when its date arrives, judges 35 trading rules in a nightly test, retires rules that fade, and searches a fixed grammar for new ones.", "how": "Nothing in the ledger is ever edited; the journal records every change with its evidence.",
         "numbers": {"ledger_lines": len(ledger_lines or []), "journal_events": len((journal or {}).get("events", [])), "strategies": {s: sum(1 for v in (strategies or {}).get("strategies", {}).values() if v["state"] == s) for s in ("Active", "Probation", "Demoted", "Retired")}}}]
    cs = {"score_hist": None, "by_decile": ch.get("by_decile"), "by_year": ch.get("by_year"), "weekly_curves": wc, "probability_curve": (study or {}).get("probability_curve"), "probability_check": (study or {}).get("probability_check"),
          "coverage": {h: {"coverage": v["coverage"], "by_year_80": v.get("coverage_80_by_year")} for h, v in ((phase3 or {}).get("horizons") or {}).items()}}
    if aladin and book:
        ps = sorted(float(e["t"]["p"]["5"]) for s, e in aladin["stocks"].items() if s in (book.get("ranks") or {}) and (e.get("t") or {}).get("p", {}).get("5") is not None)
        if ps:
            import numpy as np
            h, edges = np.histogram(ps, bins=40); q = lambda f: float(np.quantile(ps, f)); cs["score_hist"] = {"counts": [int(x) for x in h], "edges": [round(float(x), 4) for x in edges], "cut_bull": round(q(CUT["buy_top_pct"]), 4), "cut_bear": round(q(CUT["sell_bottom_pct"]), 4), "n": len(ps)}
    state, pts, mp = {}, [], {"promoted_to_probation": "P", "reentered": "P", "capped": "P", "promoted_to_active": "A", "demoted": "D", "retired": "R"}
    for e in sorted(((journal or {}).get("events") or []), key=lambda e: e["date"]):
        if e.get("kind") in mp and e.get("scope") == "universe":
            state[e["strategy"]] = mp[e["kind"]]; n = sum(1 for v in state.values() if v in ("P", "A"))
            if pts and pts[-1]["d"] == e["date"]:
                pts[-1]["n"] = n
            else:
                pts.append({"d": e["date"], "n": n})
    cs["trial_curve"] = pts
    traces = []
    for side, key in (("bull", "bull"), ("bear", "bear")):
        for r in book.get(side, []):
            px = (prices or {}).get(r["sym"]) or {}
            traces.append({"sym": r["sym"], "name": r["name"], "sector": r["sector"], "signal": key, "close": r["close"], "rank_pct": r["rank_pct"], "p5": r["p5"], "chance": r.get("chance"), "cost_bps": r["round_trip_cost_bps"], "entry_zone": r.get("entry_zone"), "invalidation": r.get("invalidation"), "exit": r["exit"],
                           "what_to_do": r["what_to_do"], "fno": r["fno"], "evidence": r["evidence"], "size": r.get("size_for_capital"), "record": r.get("record"), "series": px, "range5": ((r["evidence"] or {}).get("range_5d_80pct"))})
    scan = sorted(([sy, round(v[0], 4), v[1], v[2]] for sy, v in (book.get("ranks") or {}).items()), key=lambda r: -r[1])     # every ranked stock: symbol, rank percentile, chance of closing higher, chance of beating the market
    act = []
    for f in fcs[-3:]:
        act.append({"when": f["created"], "what": f"Wrote the forecast batch for the {f['d']} close: {len(f['syms'])} stocks x {len(f['H'])} horizons ({len(f['syms']) * len(f['H']):,} ranges), model {f['v']}"})
    for w in wks[-3:]:
        act.append({"when": w["created"], "what": f"Wrote the weekly book for the {w['d']} close: {len(w['buy'])} positive and {len(w['sell'])} negative signals out of {w['universe']:,} ranked"})
    for t in timings:
        act.append({"when": (summary or {}).get("created_utc"), "what": f"Step '{t[0]}' took {t[1]} s" + (f" ({t[2]:,} items)" if len(t) > 2 and isinstance(t[2], int) else "")})
    for e in ((journal or {}).get("events") or [])[:8]:
        act.append({"when": e["date"], "what": e["text"], "historical": e.get("historical")})
    return {"v": 1, "cuts": {"bull": CUT["buy_top_pct"], "bear": CUT["sell_bottom_pct"]}, "as_of": book.get("as_of"), "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mode": (weekly or {}).get("mode"), "labels": (weekly or {}).get("labels"), "disclaimer": (weekly or {}).get("disclaimer"),
            "kpis": k, "stages": stages, "charts": cs, "scan": scan, "traces": traces, "activity": act, "status": {"engine_suspended": (summary or {}).get("engine_suspended"), "states": (summary or {}).get("product_state_counts"), "kill_reasons": (summary or {}).get("kill_reasons"), "rule": book.get("rules")},
            "decision_steps": ["Rank the stock's 5-day score among all liquid stocks", "Compare the rank with the fixed cut-offs (best " + _cut_txt(1 - CUT["buy_top_pct"]) + ", worst " + _cut_txt(CUT["sell_bottom_pct"]) + ")", "Look up the measured chance for that rank", "Subtract the stock's round-trip cost", "Set the exit level and the 5-day time limit", "Size the position for your capital and stand aside if the edge is inside the cost"]}


def build_from_files(code, out=None):
    from . import data_lake as L
    weekly = _j(DATA / "weekly.json"); study = _j(DATA / "weekly_study.json")
    if not weekly or not weekly.get("built"):
        return {"built": False, "why": "no weekly book yet"}
    led = []
    for f in sorted((DATA / "ledger").glob("*.jsonl")):
        led += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    prices = {}
    for r in weekly["book"]["bull"] + weekly["book"]["bear"]:
        px = L.load_prices(r["sym"])
        if px is not None:
            px = px.tail(120); prices[r["sym"]] = {"d": [str(x.date()) for x in px.index], **{k: [round(float(x), 2) for x in px[k]] for k in ("o", "h", "l", "c")}}
    term = Path(L.TERM) / "aladin2"; cnt = {"price_files": len(list((Path(L.TERM) / "daily").glob("*.json"))), "deliv_files": len(list((term / "deliv").glob("2*.csv.gz"))), "fno_files": len(list((term / "fno").glob("2*.json"))),
                                            "last_bar": str(L.load_index().index[-1].date())}
    payload = build_payload(weekly, study, _j(DATA / "phase3_report.json"), led, _j(DATA / "journal.json"), _j(DATA / "state" / "latest_summary.json"), _j(DATA / "state" / "run_report.json"), _j(DATA / "state" / "strategies.json"), prices, _j(ROOT / "data" / "aladin" / "latest.json"), cnt)
    blob = encrypt(payload, code); out = Path(out or DATA / "bot.enc.json"); out.write_text(json.dumps(blob, separators=(",", ":")), encoding="utf-8")
    return {"built": True, "bytes": out.stat().st_size, "plain_bytes": len(json.dumps(payload)), "signals": len(payload["traces"]), "as_of": payload["as_of"]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--new-code", action="store_true"); ap.add_argument("--build", action="store_true"); a = ap.parse_args()
    if a.new_code:
        print(new_code()); return
    code = os.environ.get("ALADIN_BOT_CODE", "")
    if not code:
        print("ALADIN_BOT_CODE is not set: the console is not built (it stays locked / unpublished)."); return
    if a.build:
        print(json.dumps(build_from_files(code), indent=1))


if __name__ == "__main__":
    main()
