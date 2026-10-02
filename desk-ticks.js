/* Browser side of the local tick daemon (scripts/aladin_ticker_daemon.py). Phase-1 stub: the listener registry
   only. The WebSocket client arrives with the daemon; it must stay quiet when the daemon isn't running. */
let ctx = null;
const listeners = new Set();
export function init(c) { ctx = c; }
export function onTick(cb) { listeners.add(cb); return () => listeners.delete(cb); }
export function emitTick(batch) { listeners.forEach(cb => { try { cb(batch); } catch (e) { /* one bad listener must not stop the rest */ } }); }
