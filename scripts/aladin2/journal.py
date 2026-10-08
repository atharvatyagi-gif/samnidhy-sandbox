"""
ALADIN 2.0 journal (section 7.6): every change ALADIN makes to itself is an event with its evidence, written as plain text from the numbers (templates, no free generation).

  data/aladin2/journal.jsonl   append-only; one line per event: {key, date, kind, strategy, scope, text, evidence}
  data/aladin2/journal.json    the latest 500 events for the site (written by publish())
Kinds: promoted_to_probation, promoted_to_active, demoted, retired, reentered, capped, candidate_tested, candidate_rejected, drift_alarm, kill_switch, calibration.
An event is written once: its key (date + kind + strategy + scope) is checked before appending, so replays and re-runs never duplicate.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT = ROOT / "data" / "aladin2"
NICE = {"ma_cross": "Moving-average crossover", "donchian": "Donchian breakout", "tsmom": "Time-series momentum", "hi52": "Near 52-week high", "rsi2": "RSI(2) oversold", "bb_z": "Bollinger oversold",
        "reversal5": "5-day reversal", "gapfill": "Gap fill", "bb_squeeze": "Bollinger squeeze breakout", "atr_channel": "ATR channel break", "nr7": "Narrow-range breakout",
        "rel_strength": "Relative strength", "delivery_surge": "Delivery surge"}


def name(sid):
    for k, v in NICE.items():
        if sid.startswith(k):
            return f"{v} ({sid})"
    return sid


def bps(x):
    return f"{x:+.0f} bps"


def text_for(e):
    """Plain-language sentence from a lifecycle event dict (keys: from, to, why, evidence, strategy, sym). Only numbers present in the evidence are used."""
    ev = e.get("evidence") or {}; who = name(e["strategy"]); scope = "across the universe" if e.get("sym") in (None, "*POOL*") else f"on {e['sym']}"
    to, frm = e["to"], e["from"]
    if frm == "Candidate" and to == "Probation":
        return (f"Started paper-trading {who} {scope}: out of sample it earned {bps(ev.get('mean_bps', 0))} per trade over {ev.get('n', '?')} trades (lower bound {bps(ev.get('lb_bps', 0))}, "
                f"positive in {ev.get('years_positive', '?')} years, false-discovery test p = {ev.get('p', '?')}).")
    if to == "Active":
        if "live_trades" in ev:
            return f"Promoted {who} {scope} to Active: {ev['live_trades']} paper-forward trades averaged {bps(ev.get('live_mean_bps', 0))} (p = {ev.get('live_p', '?')})."
        return f"Restored {who} {scope} to Active: it passes the evaluation protocol again ({ev.get('n', '?')} trades, {bps(ev.get('mean_bps', 0))})."
    if to == "Demoted":
        if "cusum" in ev:
            return f"Demoted {who} {scope}: live returns drifted down, CUSUM {ev['cusum']} above its limit {ev.get('h', '?')}."
        if "live_mean_bps" in ev:
            return f"Demoted {who} {scope}: {ev.get('live_trades', '?')} live trades averaged {bps(ev['live_mean_bps'])}, significantly negative."
        if ev.get("reason") == "feature drift":
            return f"Demoted {who} {scope}: its inputs shifted ({', '.join(f'{k} PSI {v['psi']}' for k, v in (ev.get('features') or {}).items())})."
        return f"Demoted {who} {scope}: it no longer passes the evaluation protocol on the latest data."
    if to == "Retired":
        return f"Retired {who} {scope}: {e.get('why', 'did not recover')}. It is archived, never deleted, and can return only with fresh out-of-sample evidence."
    if frm == "Retired" and to == "Probation":
        return f"{who} {scope} re-entered Probation with fresh out-of-sample evidence ({ev.get('n', '?')} trades, {bps(ev.get('mean_bps', 0))})."
    if to == "Probation" and frm == "Active":
        return f"{who} {scope} moved from Active back to Probation: {e.get('why', '')}."
    return f"{who} {scope}: {frm} to {to}. {e.get('why', '')}"


def key(ev):
    return f"{ev['date'][:10]}|{ev['kind']}|{ev['strategy']}|{ev.get('scope', '')}"


def from_lifecycle(e):
    kind = {("Candidate", "Probation"): "promoted_to_probation", ("Retired", "Probation"): "reentered", ("Active", "Probation"): "capped"}.get((e["from"], e["to"]))
    kind = kind or {"Active": "promoted_to_active", "Demoted": "demoted", "Retired": "retired"}.get(e["to"], "state_change")
    ev = {"date": str(e["date"])[:10], "kind": kind, "strategy": e["strategy"], "scope": "universe" if e.get("sym") in (None, "*POOL*") else e["sym"], "text": text_for(e), "evidence": e.get("evidence") or {}}
    ev["key"] = key(ev); return ev


def read(folder=None):
    f = Path(folder or DEFAULT) / "journal.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


def append(events, folder=None):
    """Append events not already present (by key). Returns the number written."""
    folder = Path(folder or DEFAULT); folder.mkdir(parents=True, exist_ok=True); have = {e["key"] for e in read(folder)}; n = 0
    with open(folder / "journal.jsonl", "a", encoding="utf-8", newline="\n") as h:
        for ev in events:
            ev = ev if "key" in ev else {**ev, "key": key(ev)}
            if ev["key"] in have:
                continue
            h.write(json.dumps(ev, separators=(",", ":"), default=str) + "\n"); have.add(ev["key"]); n += 1
    return n


def publish(folder=None, n=500):
    """data/aladin2/journal.json: the latest n events, newest first."""
    folder = Path(folder or DEFAULT); ev = sorted(read(folder), key=lambda e: e["date"], reverse=True)[:n]
    (folder / "journal.json").write_text(json.dumps({"events": ev}, separators=(",", ":"), default=str), encoding="utf-8"); return len(ev)
