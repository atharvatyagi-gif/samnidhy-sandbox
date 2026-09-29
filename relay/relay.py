"""
B-LAB real-time relay: Angel One SmartAPI live NSE prices -> signed-in B-Lab terminal users.

Runs 24/7 on a small server (see relay/README.md). It
  1. logs in to Angel One SmartAPI every morning with your client code, MPIN and a TOTP code made from your
     TOTP secret (all read from /opt/blab-relay/.env, never from git),
  2. opens Angel One's WebSocket feed for every NSE main-board stock + NIFTY 50 / BANK NIFTY / SENSEX
     (Angel allows 3 connections x 1,000 tokens; stocks are split across them),
  3. serves a WebSocket at /ws. A browser must first send its Firebase ID token; the relay checks with
     Firestore that this user has a completed B-Lab registration (ExpertUsers/<uid>) before sending anything,
  4. sends the latest prices: the stocks the user is looking at every 250 ms, everything else every 2 s,
  5. answers candle requests (1m / 5m / 15m / 1h / 1D) from Angel One's historical candle API.

Prices are exactly what Angel One sends (paise -> rupees). Nothing is estimated or filled in.
"""

import asyncio
import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

import pyotp
import requests
import websockets
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger("relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def env(name, default=None, required=True):
    v = os.environ.get(name, default)
    if required and not v:
        raise SystemExit(f"missing {name} in the relay's .env file")
    return v


API_KEY = env("ANGEL_API_KEY")
CLIENT = env("ANGEL_CLIENT_CODE")
MPIN = env("ANGEL_MPIN")
TOTP_SECRET = env("ANGEL_TOTP_SECRET")
FIREBASE_PROJECT = env("FIREBASE_PROJECT_ID", "terminal-b-863a0")
ALLOWED_ORIGINS = [o.strip() for o in env("ALLOWED_ORIGINS", "https://atharvatyagi-gif.github.io").split(",") if o.strip()]
PORT = int(env("PORT", "8765"))
MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
SERIES = ("-EQ", "-BE", "-BZ")
INDEXES = [("NSE", "99926000", "^NSEI"), ("NSE", "99926009", "^NSEBANK"), ("BSE", "99919000", "^BSESN")]
EXCH_TYPE = {"NSE": 1, "BSE": 3}
PER_CONN = 1000

# ---------------- shared state (written by feed threads, read by the asyncio server) ----------------
LOCK = threading.Lock()
QUOTES = {}                 # sym -> [ltp, open, high, low, prev_close, volume, exchange_ms]
DIRTY = set()               # symbols changed since the last broadcast sweep
TOKEN_SYM = {}              # "NSE:2885" -> "RELIANCE"
SYM_TOKEN = {}              # "RELIANCE" -> ("NSE", "2885")
STATUS = {"feed": "starting", "login_at": None, "connections": 0, "ticks": 0}
SESSION = {"api": None}


def load_master():
    """Angel One's instrument list: NSE cash-market symbol -> token."""
    data = requests.get(MASTER_URL, timeout=60).json()
    for r in data:
        if r.get("exch_seg") == "NSE" and r.get("symbol", "").endswith(SERIES) and r.get("instrumenttype", "") == "":
            sym = r["symbol"].rsplit("-", 1)[0]
            if sym not in SYM_TOKEN or r["symbol"].endswith("-EQ"):
                SYM_TOKEN[sym] = ("NSE", r["token"])
    for exch, tok, sym in INDEXES:
        SYM_TOKEN[sym] = (exch, tok)
    TOKEN_SYM.clear()
    TOKEN_SYM.update({f"{e}:{t}": s for s, (e, t) in SYM_TOKEN.items()})
    log.info("instrument master: %d NSE stocks + %d indices", len(SYM_TOKEN) - len(INDEXES), len(INDEXES))


def login():
    api = SmartConnect(api_key=API_KEY)
    res = api.generateSession(CLIENT, MPIN, pyotp.TOTP(TOTP_SECRET).now())
    if not res or not res.get("status"):
        raise RuntimeError(f"Angel One login failed: {res and res.get('message')}")
    SESSION["api"] = api
    SESSION["jwt"] = res["data"]["jwtToken"]
    SESSION["feed"] = api.getfeedToken()
    STATUS["login_at"] = datetime.now(IST).isoformat(timespec="seconds")
    log.info("logged in to Angel One SmartAPI")


def on_tick(msg):
    """Angel One QUOTE-mode message (prices in paise)."""
    try:
        exch = "BSE" if msg.get("exchange_type") == 3 else "NSE"
        sym = TOKEN_SYM.get(f"{exch}:{msg['token']}")
        if not sym:
            return
        p = lambda k: (msg.get(k) or 0) / 100
        row = [p("last_traded_price"), p("open_price_of_the_day"), p("high_price_of_the_day"), p("low_price_of_the_day"),
               p("closed_price"), int(msg.get("volume_trade_for_the_day") or 0), int(msg.get("exchange_timestamp") or 0)]
        if row[0] <= 0:
            return
        with LOCK:
            QUOTES[sym] = row
            DIRTY.add(sym)
            STATUS["ticks"] += 1
    except Exception as exc:  # a malformed message must never stop the feed
        log.debug("bad tick %s: %s", msg, exc)


def run_feed(chunk_id, token_groups):
    """One Angel One WebSocket connection (blocking; run in a thread, reconnects forever)."""
    while True:
        try:
            sws = SmartWebSocketV2(SESSION["jwt"], API_KEY, CLIENT, SESSION["feed"], max_retry_attempt=3)
            sws.on_open = lambda ws: (sws.subscribe(f"blab{chunk_id}", 2, token_groups), STATUS.__setitem__("connections", STATUS["connections"] + 1))
            sws.on_data = lambda ws, m: on_tick(m)
            sws.on_error = lambda ws, e: log.warning("feed %d error: %s", chunk_id, e)
            sws.on_close = lambda ws: STATUS.__setitem__("connections", max(0, STATUS["connections"] - 1))
            sws.connect()
        except Exception as exc:
            log.warning("feed %d stopped: %s", chunk_id, exc)
        time.sleep(5)


def start_feeds():
    syms = list(SYM_TOKEN)
    groups = []
    for i in range(0, len(syms), PER_CONN):
        by_exch = {}
        for s in syms[i:i + PER_CONN]:
            e, t = SYM_TOKEN[s]
            by_exch.setdefault(EXCH_TYPE[e], []).append(t)
        groups.append([{"exchangeType": k, "tokens": v} for k, v in by_exch.items()])
    if len(groups) > 3:
        log.warning("%d symbols need %d connections; Angel allows 3, the rest are left out", len(syms), len(groups))
        groups = groups[:3]
    for i, g in enumerate(groups):
        threading.Thread(target=run_feed, args=(i, g), daemon=True).start()
    STATUS["feed"] = "live"


def daily_relogin():
    """Angel One sessions end each night: log in again at 08:45 IST and restart the feeds' tokens."""
    while True:
        now = datetime.now(IST)
        nxt = now.replace(hour=8, minute=45, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        time.sleep((nxt - now).total_seconds())
        try:
            load_master()
            login()
            log.info("daily re-login done; feeds reconnect with the new session")
            os.kill(os.getpid(), signal.SIGTERM)     # systemd restarts the service cleanly with the new session
        except Exception as exc:
            log.error("daily re-login failed: %s", exc)


# ---------------- candles ----------------
CANDLE_CACHE = {}
INTERVALS = {"1m": ("ONE_MINUTE", 5), "5m": ("FIVE_MINUTE", 20), "15m": ("FIFTEEN_MINUTE", 60), "1h": ("ONE_HOUR", 180), "1D": ("ONE_DAY", 400)}
CANDLE_LOCK = threading.Lock()


def candles(sym, iv):
    if sym not in SYM_TOKEN or iv not in INTERVALS:
        return None
    key = (sym, iv)
    hit = CANDLE_CACHE.get(key)
    if hit and time.time() - hit[0] < 20:
        return hit[1]
    name, days = INTERVALS[iv]
    exch, tok = SYM_TOKEN[sym]
    now = datetime.now(IST)
    with CANDLE_LOCK:                                   # Angel One allows only a few candle calls a second
        res = SESSION["api"].getCandleData({"exchange": exch, "symboltoken": tok, "interval": name,
                                            "fromdate": (now - timedelta(days=days)).strftime("%Y-%m-%d 09:00"), "todate": now.strftime("%Y-%m-%d %H:%M")})
        time.sleep(0.35)
    rows = (res or {}).get("data") or []
    out = [[r[0], r[1], r[2], r[3], r[4], int(r[5] or 0)] for r in rows]
    CANDLE_CACHE[key] = (time.time(), out)
    return out


# ---------------- browser side ----------------
async def verify(id_token):
    """Firebase ID token -> uid, only if that user has a completed B-Lab registration (read with their own token,
    so the Firestore rules decide: students with a valid key or guests with a valid invite code)."""
    import base64
    try:
        payload = json.loads(base64.urlsafe_b64decode(id_token.split(".")[1] + "==").decode())
        uid = payload["user_id"]
        if payload.get("aud") != FIREBASE_PROJECT:
            return None
        url = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}/databases/(default)/documents/ExpertUsers/{uid}"
        r = await asyncio.to_thread(requests.get, url, headers={"Authorization": f"Bearer {id_token}"}, timeout=10)
        return uid if r.status_code == 200 else None
    except Exception:
        return None


CLIENTS = {}   # websocket -> {"focus": set(), "uid": str}


async def handler(ws):
    origin = ws.request.headers.get("Origin", "")
    if ALLOWED_ORIGINS and origin not in ALLOWED_ORIGINS:
        await ws.close(4003, "origin not allowed"); return
    try:
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
    except Exception:
        await ws.close(4001, "auth required"); return
    uid = await verify(first.get("idToken", "")) if first.get("type") == "auth" else None
    if not uid:
        await ws.send(json.dumps({"type": "hello", "ok": False, "reason": "Not a registered B-Lab user"}))
        await ws.close(4001, "not registered"); return
    CLIENTS[ws] = {"focus": set(), "uid": uid}
    with LOCK:
        snap = dict(QUOTES)
    await ws.send(json.dumps({"type": "hello", "ok": True, "source": "Angel One SmartAPI (NSE real-time)", "status": STATUS}))
    await ws.send(json.dumps({"type": "snap", "q": snap}, separators=(",", ":")))
    try:
        async for raw in ws:
            m = json.loads(raw)
            if m.get("type") == "focus":
                CLIENTS[ws]["focus"] = set(m.get("syms", [])[:50])
            elif m.get("type") == "candles":
                bars = await asyncio.to_thread(candles, m.get("sym"), m.get("iv"))
                await ws.send(json.dumps({"type": "candles", "id": m.get("id"), "sym": m.get("sym"), "iv": m.get("iv"), "bars": bars}, separators=(",", ":")))
    except websockets.ConnectionClosed:
        pass
    finally:
        CLIENTS.pop(ws, None)


async def broadcaster():
    """Focus symbols every 250 ms; everything else every 2 s. Only symbols that changed are sent."""
    pending_all = set()
    k = 0
    while True:
        await asyncio.sleep(0.25)
        k += 1
        with LOCK:
            changed = set(DIRTY); DIRTY.clear()
            snapshot = {s: QUOTES[s] for s in changed}
        pending_all |= changed
        send_all = k % 8 == 0
        for ws, info in list(CLIENTS.items()):
            if send_all:
                with LOCK:
                    payload = {s: QUOTES[s] for s in pending_all if s in QUOTES}
            else:
                payload = {s: snapshot[s] for s in info["focus"] if s in snapshot}
            if payload:
                try:
                    await ws.send(json.dumps({"type": "ticks", "q": payload}, separators=(",", ":")))
                except Exception:
                    pass
        if send_all:
            pending_all.clear()


async def health(connection, request):
    if request.path == "/health":
        return connection.respond(200, json.dumps({**STATUS, "symbols": len(QUOTES), "clients": len(CLIENTS)}) + "\n")
    return None


async def main():
    load_master()
    login()
    start_feeds()
    threading.Thread(target=daily_relogin, daemon=True).start()
    async with websockets.serve(handler, "127.0.0.1", PORT, process_request=health, max_size=2 ** 20, ping_interval=20):
        log.info("relay listening on 127.0.0.1:%d (Caddy adds HTTPS in front)", PORT)
        await broadcaster()


if __name__ == "__main__":
    asyncio.run(main())
