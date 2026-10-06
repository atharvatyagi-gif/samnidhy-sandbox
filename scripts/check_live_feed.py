"""
Smoke test of the Angel One live feed, for YOU to run on your own PC with your own keys (nobody else can: the keys and the account are yours).

    python scripts/check_live_feed.py [--seconds 30] [--symbols RELIANCE,TCS,INFY,HDFCBANK,SBIN]

Stages, each printed as PASS / FAIL / SKIP with its timing:
  1 keys        the five ANGEL_* settings are present (printed as set / missing, NEVER their values)
  2 packages    smartapi-python, pyotp and websocket-client can be imported (pip install -r requirements-angel.txt)
  3 login       instrument list downloaded, then login with your TOTP
  4 feed        a WebSocket opens and subscribes to the symbols
  5 ticks       prices arrive: how many per symbol, the delay between the exchange's time stamp and your PC's clock (p50 / p95 / max), the gaps between ticks
It never prints a key, a token or a TOTP code, and a failure prints the reason, not a traceback. Exit code 0 only when every stage passed or was skipped for a stated reason.
Outside market hours (Mon-Fri 09:15-15:30 IST) no prices are sent: stage 5 is then SKIP, and stages 1-4 still tell you whether the login and the connection work.
"""
import argparse
import math
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import angel_feed as af  # noqa: E402

KEYS = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_MPIN", "ANGEL_TOTP_SECRET")
DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"]


def pct(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(math.ceil(p / 100 * len(v))) - 1))]


def market_open(now=None):
    from datetime import timedelta, timezone
    ist = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=5, minutes=30)))
    return ist.weekday() < 5 and (9, 15) <= (ist.hour, ist.minute) <= (15, 30)


def stage(name, ok, detail="", t0=None, out=print):
    mark = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
    out(f"  {mark}  {name:<9}{(' ' + format(time.time() - t0, '.1f') + ' s') if t0 else '':>9}  {detail}")
    return ok is not False


def run(env, symbols, seconds, feed_factory=None, importer=None, clock=time.time, sleep=time.sleep, now=None, out=print):
    results = []
    out("Angel One live-feed check (no secret is ever printed)")
    out("  settings:")
    for k in KEYS:
        out(f"    {k}: {'set' if (env.get(k) or '').strip() else 'missing'}")
    miss = af.missing_env(env)
    results.append(stage("keys", not miss, "all present" if not miss else "keys missing: add " + ", ".join(miss) + " to your .env (see .env.example)", out=out))
    if miss:
        return 2, results
    t0 = clock()
    try:
        for mod in ("SmartApi", "pyotp", "websocket"):
            (importer or __import__)(mod)
        results.append(stage("packages", True, "SmartApi, pyotp, websocket-client import", t0, out))
    except ImportError as e:
        results.append(stage("packages", False, f"cannot import {e.name}: pip install -r requirements-angel.txt", t0, out))
        return 1, results
    rows, stamps = {}, {}
    feed = (feed_factory or (lambda env, on_row: af.AngelFeed(env, on_row)))(env, lambda sym, row: (rows.setdefault(sym, []).append(row), stamps.setdefault(sym, []).append(clock())))
    t0 = clock()
    try:
        feed.prepare()
        results.append(stage("login", True, f"instrument list read ({feed.status.get('symbols', '?')} symbols) and logged in", t0, out))
    except Exception as e:  # noqa: BLE001 - the feed's messages carry no secret
        results.append(stage("login", False, str(e)[:160], t0, out))
        return 1, results
    missing = [s for s in symbols if s not in feed.sym_token]
    if len(missing) == len(symbols):
        results.append(stage("feed", False, "none of the symbols is in the instrument list: " + ", ".join(symbols), out=out))
        return 1, results
    feed.sym_token = {s: feed.sym_token[s] for s in symbols if s in feed.sym_token}               # subscribe to just these (one connection)
    t0 = clock()
    try:
        feed.start()
        sleep(3)
        conns = feed.status.get("connections", 0)
        detail = (f"{conns} connection(s) open" + (f"; not in the instrument list: {', '.join(missing)}" if missing else "")) if conns >= 1 else f"no connection opened ({feed.status.get('last_error') or 'no reason given'})"
        results.append(stage("feed", conns >= 1, detail, t0, out))
        if conns < 1:
            feed.stop()
            return 1, results
    except Exception as e:  # noqa: BLE001
        results.append(stage("feed", False, f"{type(e).__name__}: {str(e)[:120]}", t0, out))
        return 1, results
    open_now = market_open(now)
    t0 = clock()
    sleep(max(0, seconds))
    feed.stop()
    n = sum(len(v) for v in rows.values())
    if not open_now and n == 0:
        results.append(stage("ticks", None, "market closed: no prices are sent outside Mon-Fri 09:15-15:30 IST; the login and the connection worked", t0, out))
    elif n == 0:
        results.append(stage("ticks", False, f"connected but no price arrived in {seconds} s during market hours ({feed.status.get('last_error') or 'no error reported'})", t0, out))
    else:
        delays = [(stamps[s][i] * 1000 - r[6]) for s, rs in rows.items() for i, r in enumerate(rs) if len(r) > 6 and r[6]]
        gaps = [b - a for s in stamps for a, b in zip(stamps[s], stamps[s][1:])]
        per = ", ".join(f"{s} {len(rows.get(s, []))}" for s in symbols)
        d = f"{n} ticks ({per}); delay exchange to PC p50 {pct(delays, 50) / 1000:.2f} s, p95 {pct(delays, 95) / 1000:.2f} s, max {max(delays) / 1000:.2f} s" if delays else f"{n} ticks ({per})"
        g = f"; gap between ticks p50 {pct(gaps, 50):.2f} s, p95 {pct(gaps, 95):.2f} s" if gaps else ""
        silent = [s for s in symbols if s not in missing and not rows.get(s)]
        results.append(stage("ticks", not silent, d + g + (f"; no tick for {', '.join(silent)}" if silent else ""), t0, out))
    return (0 if all(r is not False for r in results) else 1), results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the Angel One live feed with your own keys (never prints a secret)")
    ap.add_argument("--seconds", type=float, default=30, help="how long to listen (default 30)")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="comma separated NSE symbols (default 5 large ones)")
    a = ap.parse_args(argv)
    try:
        from aladin_env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    import os
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()][:5]
    code, _ = run(os.environ, syms, a.seconds)
    print("RESULT:", "ALL STAGES PASSED" if code == 0 else "SOMETHING FAILED (see above)" if code == 1 else "KEYS MISSING")
    return code


if __name__ == "__main__":
    sys.exit(main())
