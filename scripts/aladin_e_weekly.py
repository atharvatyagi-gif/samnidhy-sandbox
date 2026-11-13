"""ALADIN model E: the Friday report of the paper account (ALADIN audit, phase 7).

Runs every evening after scripts/aladin_e.py; writes only when the latest session is a Friday, or on a Friday / weekend run
when Friday was a holiday. Plain words, real numbers only; anything it cannot check says "not checked" and why.

  python scripts/aladin_e_weekly.py [--force]
  -> data/aladin_e/weekly/<session>.json, <session>.md, latest.json, index.json

The Continue / Fix / Stop rules were written before the first report (aladin-audit/PHASE7_RULES.md); their numbers are in
data/config/aladin_e_phase7.json and the back-test ranges in aladin-audit/phase7/backtest_ranges.json.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import aladin_e as AE  # noqa: E402

OUT = AE.OUT / "weekly"
CFG7 = ROOT / "data" / "config" / "aladin_e_phase7.json"
RANGES = ROOT / "aladin-audit" / "phase7" / "backtest_ranges.json"
IST = timezone(timedelta(hours=5, minutes=30))


def rs(x):
    """Indian digit grouping: 101121.01 -> 'Rs 1,01,121'."""
    n = round(abs(x)); s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = head + "," + tail
    return ("-" if x < 0 else "") + "Rs " + s


def pct(x, d=2):
    return "not measured" if x is None else f"{x:+.{d}f}%"


def due(asof, now_ist):
    """Write a report for this session? Fridays; or the last session of a week whose Friday was a holiday, once that Friday has come."""
    if asof.weekday() == 4:
        return True
    same_week = now_ist.date().isocalendar()[:2] == asof.date().isocalendar()[:2]
    return same_week and now_ist.weekday() >= 4 and now_ist.date() > asof.date()


def band(x, r):
    """Where a return sits among the back-test's spans of the same length."""
    if x is None or not r:
        return "not measured"
    if x < r["p01"]:
        return "worse than 99 in 100 back-test spans"
    if x < r["p05"]:
        return "worse than 95 in 100 back-test spans"
    if x < r["p25"]:
        return "in the weaker quarter of back-test spans"
    if x <= r["p75"]:
        return "in the middle half of back-test spans"
    if x <= r["p95"]:
        return "in the stronger quarter of back-test spans"
    return "better than 95 in 100 back-test spans"


def value_on(history, day):
    """Account value at the close of `day` (or the last record before it)."""
    v = None
    for d, e, _ in history:
        if d <= day:
            v = e
    return v


def checks(acct, latest, n5, frames, asof, since, cfg7):
    """The machine checks behind rules S3, F1 and F3. Each: {ok: True/False/None, what, detail}."""
    out = []
    hist_days = {d for d, _, _ in acct["history"]}
    first = acct["history"][0][0] if acct["history"] else None
    sessions = [str(d.date()) for d in n5.index if first and first < str(d.date()) <= str(asof.date())]
    missing = [d for d in sessions if d not in hist_days]
    out.append({"rule": "F1", "what": "every trading day since the start has a record", "ok": not missing,
                "detail": f"{len(sessions)} trading days checked" + (f"; missing {', '.join(missing)}" if missing else "")})
    g = latest.get("generated_utc")
    close_utc = pd.Timestamp(str(asof.date()) + " 10:00", tz="UTC")              # 15:30 IST
    early = None if not g else pd.Timestamp(g) < close_utc
    out.append({"rule": "F1", "what": "this evening's run used closing prices (it ran after 15:30 IST)", "ok": None if early is None else not early,
                "detail": f"run at {g}" if g else "not checked: the run time is not recorded"})
    hold = latest.get("holdings") or []
    if hold and all(h.get("last_close") is not None for h in hold):
        calc = acct["cash"] + sum(h["shares"] * h["last_close"] for h in hold)
        rep = (latest.get("paper") or {}).get("equity")
        ok = rep is not None and abs(calc - rep) <= 1.0
        out.append({"rule": "S3", "what": "cash plus holdings at the close equals the reported value", "ok": ok,
                    "detail": f"{rs(calc)} worked out, {rs(rep) if rep is not None else 'none'} reported"})
    else:
        out.append({"rule": "S3", "what": "cash plus holdings at the close equals the reported value", "ok": None if hold else True,
                    "detail": "not checked: a holding has no closing price" if hold else "no holdings; value is cash"})
    bad, seen = [], 0
    for t in acct["trades"]:
        if t["date"] <= since or t["date"] > str(asof.date()):
            continue
        f = frames.get(t["sym"])
        day = pd.Timestamp(t["date"])
        if f is None or day not in f.index:
            continue
        seen += 1
        o = float(f.loc[day, "o"])
        if o <= 0 or abs(t["px"] / o - 1) > 0.005:
            bad.append(f"{t['sym']} {t['date']} at {t['px']} (open {o:.2f})")
    n_trades = sum(1 for t in acct["trades"] if since < t["date"] <= str(asof.date()))
    out.append({"rule": "S3", "what": "every fill this week was at that day's opening price", "ok": (not bad) if seen else None,
                "detail": (f"{seen} of {n_trades} fills checked" + (f"; off: {'; '.join(bad)}" if bad else "")) if seen
                else ("no fills this week" if not n_trades else "not checked: no opening prices on file")})
    if not n_trades and not seen:
        out[-1]["ok"] = True
    sg = latest.get("signals") or {}
    held = {b["sym"]: round(b["ref_price"], 2) for b in sg.get("buy", []) if b.get("state") == "held"}
    pos = {s: round(p["entry_px"], 2) for s, p in acct["positions"].items()}
    out.append({"rule": "S3", "what": "the public signals list exactly the account's holdings, at the prices it paid", "ok": held == pos if sg else None,
                "detail": f"{len(held)} held in the signals, {len(pos)} in the account" if sg else "not checked: no signals published"})
    nf = list(cfg7.get("not_filled_before_logging", [])) + list(acct.get("not_filled", []))
    out.append({"rule": "F3", "what": f"no more than {cfg7['fix']['max_not_filled']} orders not filled", "ok": len(nf) <= cfg7["fix"]["max_not_filled"],
                "detail": f"{len(nf)} so far" + (": " + "; ".join(f"{x['sym']} {x['date']} ({x['why']})" for x in nf) if nf else "")})
    return out


def build(acct, latest, n5, frames, asof, cfg7, ranges, prev_asof=None):
    """-> the report dict. Pure: tests drive it with synthetic inputs."""
    day = str(asof.date())
    start = cfg7["start"]
    since = prev_asof or start
    week_no = sum(1 for r in cfg7["reports"] if r <= day) or 1
    if day > cfg7["reports"][-1]:
        week_no = len(cfg7["reports"]) + len([d for d in n5.index if d.weekday() == 4 and cfg7["reports"][-1] < str(d.date()) <= day])
    v0, v1 = value_on(acct["history"], since), value_on(acct["history"], day)
    cap = acct["capital"]
    wk = None if not v0 or v1 is None else (v1 / v0 - 1) * 100
    tot = None if v1 is None else (v1 / cap - 1) * 100
    s = n5[n5.index <= asof]; s0 = n5[n5.index <= pd.Timestamp(since)]
    nw = None if not len(s) or not len(s0) else (float(s.iloc[-1]) / float(s0.iloc[-1]) - 1) * 100
    sb = n5[n5.index <= pd.Timestamp(start)]
    nt = None if not len(s) or not len(sb) else (float(s.iloc[-1]) / float(sb.iloc[-1]) - 1) * 100
    peak = max([e for d, e, _ in acct["history"] if d <= day] + [cap])
    dd = None if v1 is None else (v1 / peak - 1) * 100
    sessions = [d for d in n5.index if since < str(d.date()) <= day]
    trades = [t for t in acct["trades"] if since < t["date"] <= day]
    hold = latest.get("holdings") or []
    moves = sorted([(h["sym"], (h["last_close"] / h["entry_px"] - 1) * 100) for h in hold if h.get("last_close") and h.get("entry_px")], key=lambda x: x[1])
    risk = latest.get("risk") or {}
    ck = checks(acct, latest, n5, frames, asof, since, cfg7)
    stop, fix = [], []
    if acct.get("kill") or (dd is not None and dd <= cfg7["stop"]["risk_limit_pct"]):
        stop.append("S1: the kill switch fired or the account fell past the -25% limit")
    if tot is not None and tot < cfg7["stop"]["since_start_pct"]:
        stop.append(f"S2: return since the start {tot:+.2f}% is below {cfg7['stop']['since_start_pct']}%")
    for c in ck:
        if c["ok"] is False:
            (stop if c["rule"] == "S3" else fix).append(f"{c['rule']}: {c['what']}: {c['detail']}")
    if tot is not None and cfg7["stop"]["since_start_pct"] <= tot < cfg7["fix"]["since_start_pct"]:
        fix.append(f"F2: return since the start {tot:+.2f}% is below {cfg7['fix']['since_start_pct']}%")
    for f in cfg7.get("fixes", []):
        fix.append(f"F4: {f}")
    final = day >= cfg7["verdict_on"] and prev_asof is not None and prev_asof < cfg7["verdict_on"]
    verdict = "Stop" if stop else "Fix" if fix else "Continue"
    return {
        "version": "aladin-e-weekly-1", "week": week_no, "session": day, "since": since, "sessions_in_week": len(sessions),
        "account": {"value": v1, "value_week_start": v0, "capital": cap, "week_pct": None if wk is None else round(wk, 2),
                    "since_start_pct": None if tot is None else round(tot, 2), "from_peak_pct": None if dd is None else round(dd, 2),
                    "peak": round(peak, 2), "cash": round(acct["cash"], 2), "positions": len(acct["positions"]), "costs_paid_total": round(acct["costs_paid"], 2)},
        "nifty500": {"week_pct": None if nw is None else round(nw, 2), "since_start_pct": None if nt is None else round(nt, 2)},
        "backtest": {"week_band": band(wk, ranges.get("week_5_sessions")) if len(sessions) == 5 else
                     f"not compared: this week had {len(sessions)} sessions, the back-test range is for 5",
                     "since_start_band": band(tot, ranges.get("four_weeks_19_sessions")) if week_no >= 4 else "compared at week 4",
                     "week_range": ranges.get("week_5_sessions"), "four_week_range": ranges.get("four_weeks_19_sessions")},
        "trades": {"count": len(trades), "bought": sum(t["side"] == "enter" for t in trades), "sold": sum(t["side"] == "exit" for t in trades),
                   "costs": round(sum(t.get("cost", 0) for t in trades), 2), "list": trades},
        "holdings": {"best": [[s, round(m, 2)] for s, m in moves[::-1][:3]], "worst": [[s, round(m, 2)] for s, m in moves[:3]]},
        "risk": {"risk_on": risk.get("risk_on"), "invested_share": risk.get("invested_share"), "nifty500_close": risk.get("nifty500_close"),
                 "nifty500_ma200": risk.get("nifty500_ma200"), "kill": acct.get("kill"), "next_rebalance_in_sessions": latest.get("next_rebalance_in_sessions")},
        "checks": ck,
        "rules": {"stop": stop, "fix": fix, "verdict": verdict, "final": final,
                  "label": ("Phase 7 verdict" if final else "So far, by the rules") if day <= cfg7["verdict_on"] or final else "By the same rules (after phase 7)",
                  "rules_file": "aladin-audit/PHASE7_RULES.md"},
        "notes": ["The back-test ranges come from free data that covers only companies listed today, so they flatter model E.",
                  "Four weeks cannot show whether model E has an edge; that needs at least a year of live record.",
                  "Educational analysis on paper only, not investment advice."]}


def markdown(r):
    a, n, b, t, k = r["account"], r["nifty500"], r["backtest"], r["trades"], r["risk"]
    L = [f"# ALADIN model E: paper account, week {r['week']} (to the close of {r['session']})", "",
         f"Covers the {r['sessions_in_week']} trading days after the {r['since']} close. Paper money only, not investment advice.", "",
         "## Money", "",
         f"- Value: **{rs(a['value'])}** (started at {rs(a['capital'])}). This week: **{pct(a['week_pct'])}**; since the start: **{pct(a['since_start_pct'])}**.",
         f"- NIFTY 500 over the same days: this week {pct(n['week_pct'])}; since the start {pct(n['since_start_pct'])}.",
         f"- Furthest below its best value so far: {pct(a['from_peak_pct'])} (the limit is -25%).",
         f"- Cash {rs(a['cash'])}, {a['positions']} stocks held, costs paid since the start {rs(a['costs_paid_total'])}.", "",
         "## Is that normal?", "",
         f"- This week: {b['week_band']}.",
         f"- Since the start: {b['since_start_band']}.",
         f"- Back-test normal range for one week: {b['week_range']['p05']:+.1f}% to {b['week_range']['p95']:+.1f}% (9 weeks in 10), typical {b['week_range']['p50']:+.1f}%." if b.get("week_range") else "- Back-test range: not measured.",
         "", "## Trades this week", ""]
    if t["count"]:
        L.append(f"{t['count']} trades ({t['bought']} bought, {t['sold']} sold), costs {rs(t['costs'])}. Orders fill at the next day's opening price (see the machine checks).")
        L += [""] + [f"- {x['date']} {'bought' if x['side'] == 'enter' else 'sold'} {x['shares']} {x['sym']} at {x['px']:.2f} ({x['why']})" for x in t["list"][:40]]
    else:
        L.append("None. Model E only trades on its rebalance day (every 63 trading days), when the market check changes, or when the kill switch fires.")
    L += ["", "## Holdings since they were bought", ""]
    if r["holdings"]["best"]:
        L.append("- Best: " + ", ".join(f"{s} {m:+.1f}%" for s, m in r["holdings"]["best"]))
        L.append("- Worst: " + ", ".join(f"{s} {m:+.1f}%" for s, m in r["holdings"]["worst"]))
    else:
        L.append("- No holdings.")
    on = k["risk_on"]
    L += ["", "## Risk check", "",
          f"- NIFTY 500 {('above' if on else 'below') if on is not None else 'not measured against'} its 200-day average"
          + (f" ({k['nifty500_close']:,.0f} vs {k['nifty500_ma200']:,.0f})" if k.get("nifty500_close") and k.get("nifty500_ma200") else "")
          + (f"; {k['invested_share']:.0%} of the money is invested." if k.get("invested_share") is not None else "."),
          f"- Kill switch: {'FIRED since ' + k['kill']['since'] if k.get('kill') else 'not fired'}."
          + (f" Next rebalance in {k['next_rebalance_in_sessions']} trading days." if k.get("next_rebalance_in_sessions") is not None else ""),
          "", "## Machine checks", ""]
    for c in r["checks"]:
        mark = "OK" if c["ok"] else "NOT CHECKED" if c["ok"] is None else "PROBLEM"
        L.append(f"- {mark} ({c['rule']}) {c['what']}: {c['detail'].removeprefix('not checked: ')}")
    ru = r["rules"]
    L += ["", f"## {ru['label']}: **{ru['verdict']}**", ""]
    L += [f"- Stop rule hit: {x}" for x in ru["stop"]] + [f"- Fix rule hit: {x}" for x in ru["fix"]]
    if not ru["stop"] and not ru["fix"]:
        L.append("- No Stop or Fix rule is hit.")
    L.append(f"- Rules written before the first report: {ru['rules_file']}.")
    L += ["", "## Keep in mind", ""] + [f"- {x}" for x in r["notes"]] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    cfg7, ranges = AE.load(CFG7), AE.load(RANGES, {})
    acct, latest = AE.load(AE.OUT / "paper.json"), AE.load(AE.OUT / "latest.json")
    if not cfg7 or not acct or not latest:
        print("aladin_e_weekly: settings or the paper account missing; nothing done"); return 0
    idx = AE.load(AE.INDEX_FILE, {}).get("d") or []
    n5 = pd.Series([r[4] for r in idx], index=pd.to_datetime([r[0] for r in idx])).sort_index()
    asof = pd.Timestamp(latest["as_of"])
    if latest.get("status") == "degraded":
        print(f"aladin_e_weekly: model E is degraded ({latest.get('degraded_reason')}); no report"); return 0
    if not a.force and not due(asof, datetime.now(IST)):
        print(f"aladin_e_weekly: {asof.date()} is not a report day"); return 0
    OUT.mkdir(parents=True, exist_ok=True)
    index = AE.load(OUT / "index.json", {"reports": []})
    prev = max([d for d in index["reports"] if d < str(asof.date())], default=None)
    syms = {t["sym"] for t in acct["trades"]}
    hist = {p.stem: AE.load(p, {}) for p in (AE.TERM / "hist").glob("*.json")}
    frames = {s: f for s in syms if (f := AE.price_frame(s, hist)) is not None}
    rep = build(acct, latest, n5, frames, asof, cfg7, ranges, prev)
    day = rep["session"]
    old = AE.load(OUT / f"{day}.json")
    if old and {k: v for k, v in old.items() if k != "written_utc"} == rep:
        print(f"aladin_e_weekly: week {rep['week']} report for {day} unchanged"); return 0
    rep["written_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    txt = json.dumps(rep, indent=1, default=str, allow_nan=False)
    (OUT / f"{day}.json").write_text(txt, encoding="utf-8")
    (OUT / "latest.json").write_text(txt, encoding="utf-8")
    (OUT / f"{day}.md").write_text(markdown(rep), encoding="utf-8")
    index["reports"] = sorted(set(index["reports"]) | {day})
    (OUT / "index.json").write_text(json.dumps(index), encoding="utf-8")
    print(f"aladin_e_weekly: week {rep['week']} report for {day}: value {rs(rep['account']['value'] or 0)}, week {pct(rep['account']['week_pct'])}, "
          f"{rep['rules']['label'].lower()}: {rep['rules']['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
