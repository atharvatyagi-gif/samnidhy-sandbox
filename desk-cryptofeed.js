/* Live Bitcoin and Ethereum market data in the browser, shared by the Crypto tab and its 3D view.
   Trades: Binance's public trade stream (each trade says whether the BUYER or the SELLER was the aggressor). Order book: Binance's public depth endpoint, polled every two seconds.
   Nothing is stored or invented: when a feed is down the status says so. Educational analysis only, not investment advice. */
export const ASSETS = { BTCUSDT: "Bitcoin", ETHUSDT: "Ethereum" };
export const feed = { status: "connecting", price: {}, trades: { BTCUSDT: [], ETHUSDT: [] }, last: 0, sel: "BTCUSDT" };
const listeners = new Set();
export const onTrade = fn => { listeners.add(fn); return () => listeners.delete(fn); };
let ws = null, alive = () => true, tries = 0;

const URLS = ["wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/ethusdt@aggTrade", "wss://data-stream.binance.vision/stream?streams=btcusdt@aggTrade/ethusdt@aggTrade"];
/* one aggTrade message -> {sym, t, p, q, usd, buy}; m = "the buyer is the maker", so the SELLER was the aggressor */
export function parseTrade(msg) {
  const d = msg && msg.data; if (!d || !d.s || d.p == null) return null;
  const p = +d.p, q = +d.q; return { sym: d.s, t: d.T, p, q, usd: p * q, buy: !d.m };
}
export function connect(isAlive = () => true) {
  alive = isAlive; if (ws || typeof WebSocket === "undefined") { if (typeof WebSocket === "undefined") feed.status = "unavailable"; return; }
  const open = () => {
    try { ws = new WebSocket(URLS[tries % URLS.length]); } catch (e) { feed.status = "unavailable"; return; }
    ws.onopen = () => { feed.status = "live"; };
    ws.onmessage = ev => {
      let m; try { m = parseTrade(JSON.parse(ev.data)); } catch (e) { return; } if (!m || !feed.trades[m.sym]) return;
      feed.price[m.sym] = m.p; feed.last = Date.now(); const a = feed.trades[m.sym]; a.push(m); if (a.length > 20000) a.splice(0, 5000); listeners.forEach(fn => fn(m));
    };
    ws.onclose = () => { ws = null; if (alive()) { feed.status = "reconnecting"; tries++; setTimeout(open, 3000); } };
    ws.onerror = () => { feed.status = "reconnecting"; try { ws.close(); } catch (e) { /* already closing */ } };
  }; open();
}
/* Order book -> resting size in n price buckets either side of the mid, covering the whole book that was fetched (1,000 levels reach a very different distance for each coin, so the bucket width adapts).
   bids and asks are [[price, qty], ...]. Bucket 0 touches the mid. Sizes are in dollars so the two coins look alike. */
export function bucketBook(bids, asks, mid, n = 24) {
  const reach = Math.max(mid * 1e-6, ...bids.map(b => mid - +b[0]), ...asks.map(a => +a[0] - mid)), step = reach * 1.0001 / n, bu = new Array(n).fill(0), as = new Array(n).fill(0);
  for (const [p, q] of bids) { const i = Math.floor((mid - +p) / step); if (i >= 0 && i < n) bu[i] += +p * +q; }
  for (const [p, q] of asks) { const i = Math.floor((+p - mid) / step); if (i >= 0 && i < n) as[i] += +p * +q; }
  return { bids: bu, asks: as, step };
}
export async function fetchBook(sym) {
  const r = await fetch(`https://data-api.binance.vision/api/v3/depth?symbol=${sym}&limit=1000`); if (!r.ok) throw new Error("depth " + r.status); return r.json();
}
/* trades inside a window -> buy and sell dollars, imbalance -1..1, trades per second */
export function flowWindow(trades, now, ms = 60000) {
  let b = 0, s = 0, n = 0; for (let i = trades.length - 1; i >= 0 && trades[i].t >= now - ms; i--) { if (trades[i].buy) b += trades[i].usd; else s += trades[i].usd; n++; }
  return { buy: b, sell: s, imbalance: b + s ? (b - s) / (b + s) : 0, perSec: n / (ms / 1000), n };
}
