"""
Smoke test of the live price feed the local tick daemon uses.

    python scripts/check_live_feed.py                 # no Angel One keys: checks the FREE NSE web feed (what the daemon uses without keys); keys present: checks Angel One
    python scripts/check_live_feed.py --source nse    # the free feed, whatever keys exist
    python scripts/check_live_feed.py --source angel [--seconds 30] [--symbols RELIANCE,TCS,INFY,HDFCBANK,SBIN]

FREE NSE WEB FEED (--source nse; needs no account and no keys). Stages: session (NSE's cookie handshake), endpoints (each list answers: rows, how long it took), coverage (how many
stocks and indices get a live price: gainers/losers, most active, and the futures-and-options stocks' spot prices), freshness (age of the newest exchange time stamp), movement
(a second round later: how many prices changed). It is NSE's own website data and NSE refreshes each list only every 1 to 3 minutes (measured 7 Oct 2026), so the movement stage listens for 150 seconds by default. Live for the stocks above (a few hundred), unofficial, and it can
change shape; every other stock stays on the delayed Yahoo prices.

ANGEL ONE (--source angel) is for an account holder only: it needs a demat account and the four ANGEL_* keys, and tests them.

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

ENDPOINTS = (("indices", "/api/allIndices", None, "parse_indices"),
             ("gainers", "/api/live-analysis-variations", {"index": "gainers"}, "parse_variations"),
             ("losers", "/api/live-analysis-variations", {"index": "loosers"}, "parse_variations"),
             ("most active by volume", "/api/live-analysis-most-active-securities", {"index": "volume"}, "parse_most_active"),
             ("most active by value", "/api/live-analysis-most-active-securities", {"index": "value"}, "parse_most_active"),
             ("futures-and-options stocks", "/api/live-analysis-oi-spurts-underlyings", None, "parse_fo_spot"))
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


def run_nse(seconds=20, session=None, daemon=None, now=None, clock=time.time, sleep=time.sleep, out=print):
    """The free NSE web feed. `session` and `daemon` (the module with the parsers) are injectable for tests."""
    if daemon is None:
        import aladin_ticker_daemon as daemon
    results = []
    out("Free NSE web feed check (no account, no keys)")
    t0 = clock()
    try:
        session = session or daemon.NseSession()
        warmed = session._warm() if hasattr(session, "_warm") else True
        results.append(stage("session", bool(warmed), "NSE's cookie handshake worked" if warmed else "NSE did not give a session (blocked, or the site is down): try again in a minute", t0, out))
    except Exception as e:  # noqa: BLE001
        results.append(stage("session", False, f"{type(e).__name__}: {str(e)[:120]}", t0, out))
        return 1, results
    if not warmed:
        return 1, results
    ref = "https://www.nseindia.com/market-data/live-equity-market"

    def one_round():
        got, ok_all = {}, True
        for name, path, params, parser in ENDPOINTS:
            t = clock()
            try:
                js = session.get_json(path, params, referer=ref) if params else session.get_json(path, referer=ref)
                rows = getattr(daemon, parser)(js)
                got[name] = (rows, clock() - t)
            except Exception as e:  # noqa: BLE001
                got[name] = (None, str(e)[:80])
                ok_all = False
        return got, ok_all
    t0 = clock()
    r1, _ = one_round()
    bad = [n for n, (rows, _) in r1.items() if rows is None]
    detail = "; ".join(f"{n}: {len(rows)} rows in {lat:.1f} s" if rows is not None else f"{n}: FAILED ({lat})" for n, (rows, lat) in r1.items())
    results.append(stage("endpoints", not bad, detail, t0, out))
    stocks, full = {}, set()
    for n in ("gainers", "losers", "most active by volume", "most active by value"):
        for sym, t in (r1[n][0] or {}).items():
            stocks[sym] = t
            full.add(sym)
    for sym, t in (r1["futures-and-options stocks"][0] or {}).items():
        stocks.setdefault(sym, t)
    idx = r1["indices"][0] or {}
    results.append(stage("coverage", len(stocks) > 0, f"{len(stocks)} stocks get a live price ({len(full)} with open/high/low/volume, {len(stocks) - len(full)} price only) and {len(idx)} indices; every other stock stays on delayed prices", out=out))
    newest = max([t[6] for t in list(stocks.values()) + list(idx.values()) if t[6]] or [0])
    open_now = market_open(now)
    age = (clock() * 1000 - newest) / 1000 if newest else None
    if not open_now:
        results.append(stage("freshness", None, "market closed (NSE sends the last session's prices outside Mon-Fri 09:15-15:30 IST)" + (f"; newest time stamp is {age / 3600:.1f} h old" if age else ""), out=out))
    else:
        results.append(stage("freshness", age is not None and age < 120, f"newest exchange time stamp is {age:.0f} s old" if age is not None else "no time stamp in the data", out=out))
    t0 = clock()
    if not open_now:
        results.append(stage("movement", None, "market closed: prices do not move", t0, out))
        return (0 if all(r is not False for r in results) else 1), results
    # NSE refreshes each list in bursts every 1-3 minutes, so ask every 10 s for `seconds` and note WHEN each list changed
    prev = {n: {s: t[0] for s, t in (rows or {}).items()} for n, (rows, _) in r1.items() if n != "indices"}
    changed_at, moved_syms = {}, set()
    elapsed = 0.0
    while True:
        sleep(min(10.0, max(0.0, seconds - elapsed)) if seconds > 0 else 0)
        elapsed += min(10.0, max(0.0, seconds - elapsed)) if seconds > 0 else 0
        rn, _ = one_round()
        for n, (rows, _) in rn.items():
            if n == "indices" or rows is None:
                continue
            now_px = {s: t[0] for s, t in rows.items()}
            diff = [s for s, px in now_px.items() if s in prev.get(n, {}) and px != prev[n][s]]
            if diff and n not in changed_at:
                changed_at[n] = elapsed
            moved_syms.update(diff)
            prev[n] = now_px
        if elapsed >= seconds:
            break
    when = "; ".join(f"{n} changed at +{t:.0f} s" for n, t in changed_at.items())
    results.append(stage("movement", len(moved_syms) > 0, (f"{len(moved_syms)} stocks changed price in {elapsed:.0f} s ({when}); NSE refreshes each list every 1-3 minutes" if moved_syms
                                                           else f"no price changed in {elapsed:.0f} s: NSE refreshes each list only every 1-3 minutes, try --seconds 240"), t0, out))
    return (0 if all(r is not False for r in results) else 1), results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the live price feed: the free NSE web feed (default without Angel One keys) or Angel One (account holders; never prints a secret)")
    ap.add_argument("--source", choices=["auto", "nse", "angel"], default="auto", help="auto: Angel One when its four keys exist, otherwise the free NSE feed")
    ap.add_argument("--seconds", type=float, default=None, help="how long to listen (default 30 for Angel One, 150 for the free feed, whose lists refresh every 1-3 minutes)")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="comma separated NSE symbols (default 5 large ones)")
    a = ap.parse_args(argv)
    try:
        from aladin_env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    import os
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()][:5]
    use_nse = a.source == "nse" or (a.source == "auto" and af.missing_env(os.environ))
    if use_nse:
        if a.source == "auto":
            print("No Angel One keys set: checking the free NSE web feed instead (that is the feed the daemon uses without keys).")
        code, _ = run_nse(150 if a.seconds is None else a.seconds)
    else:
        code, _ = run(os.environ, syms, 30 if a.seconds is None else a.seconds)
    print("RESULT:", "ALL STAGES PASSED" if code == 0 else "SOMETHING FAILED (see above)" if code == 1 else "KEYS MISSING")
    return code


if __name__ == "__main__":
    sys.exit(main())
