"""
Angel One SmartAPI feed helpers for the local tick daemon's "angel" source (scripts/aladin_ticker_daemon.py --source angel).

Why this file repeats logic that is also in relay/relay.py: relay.py is installed on its OWN on a server (relay/setup.sh downloads only relay.py), so it cannot import
from here, and I will not edit a working server I cannot run against Angel One. Instead tests/test_angel_feed.py loads relay.py with stubbed Angel/Firebase libraries and
checks that the instrument-master parsing, the tick conversion and the connection grouping here give IDENTICAL results, so the two copies cannot drift apart unnoticed.

Prices are exactly what Angel One sends (paise -> rupees); nothing is estimated. Licence: Angel One's market data is licensed to the account holder. This feed is shown only
on the machine that runs the daemon (loopback), and sharing it with the cohort needs Angel One's written permission and the server relay. The MPIN, TOTP secret and API key are
read from the environment, are never logged, never printed and never written anywhere.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
SERIES = ("-EQ", "-BE", "-BZ")
INDEXES = [("NSE", "99926000", "^NSEI"), ("NSE", "99926009", "^NSEBANK"), ("BSE", "99919000", "^BSESN")]
EXCH_TYPE = {"NSE": 1, "BSE": 3}
PER_CONN = 1000                                            # Angel One allows 3 connections of 1,000 tokens each
MAX_CONN = 3
REQUIRED_ENV = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_MPIN", "ANGEL_TOTP_SECRET")


def missing_env(env):
    """Names (never values) of the Angel One settings that are not set."""
    return [k for k in REQUIRED_ENV if not str(env.get(k, "")).strip()]


def parse_master(rows):
    """Angel One's instrument list -> (sym_token {SYM: (exchange, token)}, token_sym {"NSE:2885": "RELIANCE"}). NSE cash-market stocks, then the three indices."""
    sym_token = {}
    for r in rows:
        if r.get("exch_seg") == "NSE" and r.get("symbol", "").endswith(SERIES) and r.get("instrumenttype", "") == "":
            sym = r["symbol"].rsplit("-", 1)[0]
            if sym not in sym_token or r["symbol"].endswith("-EQ"):
                sym_token[sym] = ("NSE", r["token"])
    for exch, tok, sym in INDEXES:
        sym_token[sym] = (exch, tok)
    return sym_token, {f"{e}:{t}": s for s, (e, t) in sym_token.items()}


def tick_row(msg, token_sym):
    """One Angel One QUOTE-mode message -> (symbol, [ltp, open, high, low, prev_close, volume, exchange_ms]) in rupees, or None when it cannot be used."""
    try:
        exch = "BSE" if msg.get("exchange_type") == 3 else "NSE"
        sym = token_sym.get(f"{exch}:{msg['token']}")
        if not sym:
            return None
        p = lambda k: (msg.get(k) or 0) / 100                                  # noqa: E731
        row = [p("last_traded_price"), p("open_price_of_the_day"), p("high_price_of_the_day"), p("low_price_of_the_day"),
               p("closed_price"), int(msg.get("volume_trade_for_the_day") or 0), int(msg.get("exchange_timestamp") or 0)]
        return (sym, row) if row[0] > 0 else None
    except Exception:  # noqa: BLE001 - a malformed message must never stop the feed
        return None


def token_groups(sym_token, per_conn=PER_CONN, max_conn=MAX_CONN):
    """-> (groups, left_out). One group per WebSocket connection: [{"exchangeType": 1, "tokens": [...]}, ...]; symbols beyond what 3 connections hold are left out."""
    syms = list(sym_token)
    groups = []
    for i in range(0, len(syms), per_conn):
        by_exch = {}
        for s in syms[i:i + per_conn]:
            e, t = sym_token[s]
            by_exch.setdefault(EXCH_TYPE[e], []).append(t)
        groups.append([{"exchangeType": k, "tokens": v} for k, v in by_exch.items()])
    left = sum(len(g["tokens"]) for grp in groups[max_conn:] for g in grp)
    return groups[:max_conn], left


class AngelFeed:
    """Logs in, loads the instrument list and keeps up to 3 WebSocket connections open, handing every usable tick to `on_row(sym, row)` (called from the feed's threads)."""

    SESSION_MAX_S = 18 * 3600                                                     # Angel One sessions end daily: log in again well before a stale token is all we have
    AUTH_WORDS = ("token", "unauthor", "401", "403", "forbidden", "session", "invalid")

    def __init__(self, env, on_row, http_get=None, smart_connect=None, totp=None, ws_cls=None, sleep=time.sleep, clock=time.time):
        self.env, self.on_row, self.sleep, self.clock = env, on_row, sleep, clock
        self.session_at, self.auth_bad, self.relogins = 0.0, False, 0
        self.http_get, self.smart_connect, self.totp, self.ws_cls = http_get, smart_connect, totp, ws_cls
        self.token_sym, self.sym_token, self.session = {}, {}, {}
        self.stop_flag = threading.Event()
        self.status = {"feed": "starting", "login_at": None, "connections": 0, "ticks": 0, "symbols": 0, "left_out": 0, "last_error": None}
        self._lock = threading.Lock()

    def prepare(self):
        """Login and instrument list. Raises RuntimeError with a message that contains no secret when something fails."""
        miss = missing_env(self.env)
        if miss:
            raise RuntimeError("missing " + ", ".join(miss))
        if self.http_get is None:
            import requests
            self.http_get = requests.get
        if self.smart_connect is None:
            from SmartApi import SmartConnect                                  # optional dependency: pip install -r requirements-angel.txt
            self.smart_connect = SmartConnect
        if self.totp is None:
            import pyotp
            self.totp = lambda secret: pyotp.TOTP(secret).now()
        try:
            self.sym_token, self.token_sym = parse_master(self.http_get(MASTER_URL, timeout=60).json())
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"instrument list could not be read ({type(e).__name__})") from None
        self._login()
        self.status.update(symbols=len(self.sym_token) - len(INDEXES))

    def _login(self):
        """One login (TOTP included). Raises RuntimeError with no secret in the message."""
        api = self.smart_connect(api_key=self.env["ANGEL_API_KEY"])
        try:
            res = api.generateSession(self.env["ANGEL_CLIENT_CODE"], self.env["ANGEL_MPIN"], self.totp(self.env["ANGEL_TOTP_SECRET"]))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"login call failed ({type(e).__name__})") from None
        if not res or not res.get("status"):
            raise RuntimeError("Angel One refused the login: " + str((res or {}).get("message") or "no reason given")[:80])
        self.session = {"jwt": res["data"]["jwtToken"], "feed": api.getfeedToken()}
        self.session_at, self.auth_bad = self.clock(), False
        self.status.update(login_at=datetime.now(IST).isoformat(timespec="seconds"))

    def _ensure_session(self):
        """Before every (re)connect: a session older than SESSION_MAX_S, or one a connection reported as rejected, is replaced. A failed re-login is noted and retried on the
        next cycle; the old token is kept meanwhile (it may still work)."""
        if self.smart_connect is None or not (self.auth_bad or self.clock() - self.session_at > self.SESSION_MAX_S):
            return                                                                  # (never prepared, or still fresh)
        with self._lock:
            if not (self.auth_bad or self.clock() - self.session_at > self.SESSION_MAX_S):
                return                                                              # another connection thread already renewed it
            try:
                self._login()
                self.relogins += 1
            except RuntimeError as e:
                self.status["last_error"] = f"relogin failed: {e}"

    def _on_data(self, msg):
        r = tick_row(msg, self.token_sym)
        if r:
            with self._lock:
                self.status["ticks"] += 1
            self.on_row(*r)

    def start(self):
        if self.ws_cls is None:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2
            self.ws_cls = SmartWebSocketV2
        groups, left = token_groups(self.sym_token)
        self.status.update(left_out=left, feed="live")
        for i, g in enumerate(groups):
            threading.Thread(target=self._run_conn, args=(i, g), daemon=True).start()

    def _run_conn(self, i, groups):
        key, client = self.env["ANGEL_API_KEY"], self.env["ANGEL_CLIENT_CODE"]
        while not self.stop_flag.is_set():
            try:
                self._ensure_session()
                sws = self.ws_cls(self.session["jwt"], key, client, self.session["feed"], max_retry_attempt=3)
                sws.on_open = lambda ws: (sws.subscribe(f"blab{i}", 2, groups), self._conn(+1))
                sws.on_data = lambda ws, m: self._on_data(m)
                sws.on_error = lambda ws, e: self._on_error(i, e)
                sws.on_close = lambda ws: self._conn(-1)
                sws.connect()
            except Exception as e:  # noqa: BLE001 - reconnect forever
                self.status["last_error"] = f"feed {i} stopped: {type(e).__name__}"
            self.sleep(5)

    def _on_error(self, i, e):
        text = str(e)
        self.status["last_error"] = f"feed {i}: {text[:80]}"
        if any(w in text.lower() for w in self.AUTH_WORDS):
            self.auth_bad = True                                                    # the next reconnect logs in again first

    def _conn(self, d):
        with self._lock:
            self.status["connections"] = max(0, self.status["connections"] + d)

    def stop(self):
        self.stop_flag.set()
