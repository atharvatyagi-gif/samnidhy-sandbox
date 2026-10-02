/* Browser side of the local tick daemon (scripts/aladin_ticker_daemon.py).
   Opt-in only: nothing is contacted until the user types TICKS ON (remembered in localStorage). Stays quiet when
   the daemon isn't running: retries every 30 s with backoff, gives up after 3 failures until the tab is shown
   again. Never overrides the Angel One relay (LIVE.ok): ticks from this PC are only used when that is off.
   The label is "LIVE · NSE WEB (THIS PC, ~3 s)", never "real-time": it is the free web feed, polled. */
import { LOCAL_TICKS_URL } from "./config.js";

let ctx = null, ws = null, timer = null, poll = null, fails = 0, connected = false, lastTickAt = 0, warned = new Set();
const listeners = new Set();
const IDX = { "NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK" };
const KEY = "aladin.ticks";
const LOCAL = typeof location !== "undefined" && ["127.0.0.1", "localhost"].includes(location.hostname);       // (guarded so the module can be imported by the node tests)

const store = {
  get() { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; } },
  set(v) { try { v ? localStorage.setItem(KEY, "1") : localStorage.removeItem(KEY); } catch (e) { /* private mode */ } },
};

export function init(c) {
  ctx = c;
  document.addEventListener("visibilitychange", () => { if (!document.hidden && store.get() && !connected && fails >= 3) { fails = 0; connect(); } });
  if (store.get()) setTimeout(connect, 1500);
}
export function onTick(cb) { listeners.add(cb); return () => listeners.delete(cb); }
export function emitTick(batch) { listeners.forEach(cb => { try { cb(batch); } catch (e) { /* one bad listener must not stop the rest */ } }); }
export const enabled = () => store.get();
/* true while ticks from this PC are arriving (used by the masthead chip) */
export const active = () => connected && !ctx.LIVE.ok && Date.now() - lastTickAt < 120000;

export function setEnabled(on) {
  store.set(on);
  if (on) { fails = 0; connect(); ctx.toast("Local ticks on: looking for the daemon on this PC (python scripts/aladin_ticker_daemon.py)"); }
  else { close(); ctx.toast("Local ticks off"); }
  ctx.renderMast && ctx.renderMast();
}

function close() {
  clearTimeout(timer); clearInterval(poll); poll = null;
  if (ws) { ws.onclose = null; try { ws.close(); } catch (e) { /* already closed */ } ws = null; }
  connected = false;
}

function retry() {
  fails++;
  ctx.renderMast && ctx.renderMast();
  if (!store.get() || fails >= 3) { if (fails >= 3 && store.get() && LOCAL) startPoll(); return; }
  timer = setTimeout(connect, 30000 * fails);
}

function connect() {
  if (!store.get() || ws || ctx.LIVE.ok) return;
  let s;
  try { s = new WebSocket(LOCAL_TICKS_URL); } catch (e) { retry(); return; }
  ws = s;
  s.onmessage = e => { let m; try { m = JSON.parse(e.data); } catch (err) { return; } onMsg(m); };
  s.onclose = () => { const was = connected; ws = null; connected = false; if (was) ctx.toast("Local tick feed disconnected"); retry(); };
  s.onerror = () => { /* onclose follows */ };
}

function convert(q) {
  const out = {};
  for (const [k, v] of Object.entries(q || {})) {
    if (k.startsWith("NIFTY") || k.includes(" ")) { if (IDX[k]) out[IDX[k]] = v; }   // NSE index names have spaces; stock symbols don't
    else out[k] = v;
  }
  return out;
}

function onMsg(m) {
  if (ctx.LIVE.ok) return;                                    // the relay feed wins
  if (m.type === "hello") {
    connected = !!m.ok; fails = 0; lastTickAt = Date.now(); clearInterval(poll); poll = null;
    if (m.ok) { ctx.toast("Local tick feed connected (NSE web, this PC)"); sendFocus(); }
    ctx.renderMast && ctx.renderMast();
  } else if (m.type === "snap" || m.type === "ticks") {
    lastTickAt = Date.now();
    const q = convert(m.q);
    if (Object.keys(q).length) { ctx.applyTicks(q, true); emitTick({ type: "ticks", q }); }
  } else if (m.type === "sweeps") {
    ctx.S.sweep = ctx.S.sweep || {};
    Object.assign(ctx.S.sweep, m.agg || {});
    ctx.S.sweepEv = (ctx.S.sweepEv || []).concat(m.s || []).slice(-200);
    emitTick({ type: "sweeps", s: m.s || [], agg: m.agg || {} });
  } else if (m.type === "warn" && !warned.has(m.msg)) { warned.add(m.msg); ctx.toast(m.msg); }
}

export function sendFocus(syms) {
  if (!ws || ws.readyState !== 1) return;
  const list = (syms || []).filter(Boolean).slice(0, 5);
  if (list.length) ws.send(JSON.stringify({ type: "focus", syms: list }));
}

/* dev fallback: the daemon also writes data/live_extra/ticks.json, which scripts/dev_preview.py serves at /ticks.json */
function startPoll() {
  if (poll) return;
  const go = async () => {
    try {
      const r = await fetch("ticks.json", { cache: "no-store" });
      if (!r.ok) return;
      const j = await r.json();
      if (j && j.q && Object.keys(j.q).length && !ctx.LIVE.ok) {
        lastTickAt = Date.now(); connected = true;
        const q = convert(j.q); ctx.applyTicks(q, true); emitTick({ type: "ticks", q });
        if (j.sweeps) { ctx.S.sweep = ctx.S.sweep || {}; for (const [s, v] of Object.entries(j.sweeps)) ctx.S.sweep[s] = v.s; }
        ctx.renderMast && ctx.renderMast();
      }
    } catch (e) { /* offline: stay quiet */ }
  };
  go(); poll = setInterval(go, 2000);
}
