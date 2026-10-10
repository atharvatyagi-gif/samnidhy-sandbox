/* Crypto tab: the Bitcoin order-flow paper account (scripts/crypto_live.py) and its research (scripts/crypto_flow.py).
   Live in the browser: Binance's public trade stream (each trade says whether the buyer or the seller was the aggressor) -> buy and sell volume, imbalance and cumulative delta for the last minutes.
   Every other number is read from t/c/live.json (the engine, refreshed every 15 minutes) and t/c/study.json (the 2020-2026 research). A missing input says "not measured".
   Simulated money, hard budget Rs 10,00,000, no exchange account. Educational analysis only, not investment advice. */
import { esc, inr } from "./desk-aladin2.js";
import { lineChart } from "./desk-signals.js";

let ctx = null, root = null, L = null, S = null, ws = null, timer = null, beat = null;
const feed = { price: null, trades: [], status: "connecting", last: 0 };
const WINDOW_MS = 5 * 60 * 1000;
export function init(c) { ctx = c; }

const usd = (v, d = 2) => v == null ? "--" : "$" + inr(v, d);
const sgn = (v, d = 2, s = "%") => v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(d) + s;
const cls = v => v == null ? "" : v >= 0 ? "up" : "down";

/* ---------- pure helpers (tests/js/crypto.test.mjs) ---------- */
/* trades: [{t, q, buy}] where buy = the buyer was the aggressor. -> buy and sell volume, imbalance -1..1 and the cumulative delta line inside the window */
export function flowStats(trades, now, windowMs = WINDOW_MS) {
  const w = trades.filter(x => x.t >= now - windowMs); let b = 0, s = 0, cvd = 0; const line = [];
  for (const x of w) { if (x.buy) b += x.q; else s += x.q; cvd += x.buy ? x.q : -x.q; line.push([x.t, cvd]); }
  return { buy: b, sell: s, total: b + s, imbalance: b + s > 0 ? (b - s) / (b + s) : 0, cvd, line, n: w.length };
}
/* account value now: each sleeve's cash plus its bitcoin at the live price */
export function liveEquity(doc, price) {
  if (!doc) return null; const p = price || doc.bid || doc.price;
  return Object.values(doc.sleeves).reduce((t, s) => t + s.cash + s.btc * p, 0);
}
export const minutesSince = (iso, now = Date.now()) => iso ? (now - Date.parse(iso)) / 60000 : null;
export const isStale = (doc, now = Date.now()) => !doc || minutesSince(doc.engine_ts, now) > (doc.stale_after_min || 45);
const fmtT = iso => iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) + " IST" : "--";
const DESC = { flow_momentum: "Buys when aggressive buyers have dominated the last 24 four-hour bars, unusually so, while price is above its 50-bar average. Leaves when that buying fades. Stop 3 average bar ranges below.",
  flow_breakout: "Buys a close above the 24-bar high only when the buy-minus-sell volume and the total volume are both well above normal. Leaves below the 12-bar low or on a red Heikin-Ashi bar. Stop 3 average bar ranges below." };

/* ---------- loading ---------- */
async function load() {
  try { L = await ctx.getJSON("t/c/live.json", true); } catch (e) { L = null; }
  if (!S) { try { S = await ctx.getJSON("t/c/study.json", false); } catch (e) { S = null; } }
}
function connect() {
  if (ws || typeof WebSocket === "undefined") return;
  const urls = ["wss://stream.binance.com:9443/ws/btcusdt@aggTrade", "wss://data-stream.binance.vision/ws/btcusdt@aggTrade"]; let k = 0;
  const open = () => {
    try { ws = new WebSocket(urls[k % urls.length]); } catch (e) { feed.status = "unavailable"; return; }
    ws.onopen = () => { feed.status = "live"; };
    ws.onmessage = ev => { try { const m = JSON.parse(ev.data); feed.price = +m.p; feed.last = Date.now(); feed.trades.push({ t: m.T, q: +m.q, buy: !m.m }); if (feed.trades.length > 20000) feed.trades.splice(0, 5000); } catch (e) { /* ignore a bad frame */ } };
    ws.onclose = () => { ws = null; if (root && root.isConnected) { feed.status = "reconnecting"; k++; setTimeout(open, 3000); } };
    ws.onerror = () => { feed.status = "reconnecting"; try { ws.close(); } catch (e) { /* closing */ } };
  }; open();
}

/* ---------- drawing ---------- */
function flowHtml() {
  const f = flowStats(feed.trades, Date.now()), pct = Math.round(Math.abs(f.imbalance) * 100), side = f.imbalance >= 0 ? "buyers" : "sellers";
  const w = x => (f.total ? x / f.total * 100 : 50).toFixed(1);
  const pts = f.line.length > 2 ? f.line.filter((_, i) => i % Math.ceil(f.line.length / 160) === 0).map(([t, v]) => [new Date(t).toISOString().slice(0, 10) + "", v]) : [];
  const spark = f.line.length > 2 ? (() => { const xs = f.line, lo = Math.min(...xs.map(p => p[1])), hi = Math.max(...xs.map(p => p[1])), t0 = xs[0][0], t1 = xs[xs.length - 1][0] || t0 + 1, R = hi - lo || 1;
    return `<svg viewBox="0 0 300 60" class="cx-spark" role="img" aria-label="Cumulative buy minus sell volume over the last five minutes"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${xs.filter((_, i) => i % Math.ceil(xs.length / 150) === 0).map(([t, v]) => `${((t - t0) / ((t1 - t0) || 1) * 300).toFixed(1)},${(56 - (v - lo) / R * 52).toFixed(1)}`).join(" ")}"/></svg>`; })() : '<p class="note">Waiting for trades…</p>';
  return `<div class="sg-card"><h4>Live order flow · last 5 minutes · Binance BTCUSDT</h4>
    <p class="sg-beat"><i class="sg-dot ${feed.status === "live" ? "" : "off"}" aria-hidden="true"></i><span>${feed.status === "live" ? "Live trade stream connected" : `Trade stream ${esc(feed.status)}: showing the engine's price only`} · ${f.n.toLocaleString("en-IN")} trades in the window</span></p>
    <div class="cx-flow" role="img" aria-label="Buy volume ${w(f.buy)} percent, sell volume ${w(f.sell)} percent"><i class="up" style="width:${w(f.buy)}%"></i><i class="down" style="width:${w(f.sell)}%"></i></div>
    <div class="sg-stats sg-kp"><div class="sg-stat"><span>Aggressive buying</span><b class="up">${f.buy.toFixed(2)} BTC</b></div><div class="sg-stat"><span>Aggressive selling</span><b class="down">${f.sell.toFixed(2)} BTC</b></div>
      <div class="sg-stat"><span>Imbalance</span><b class="${cls(f.imbalance)}">${f.total ? pct + "% " + side : "--"}</b></div><div class="sg-stat"><span>Net flow (delta)</span><b class="${cls(f.cvd)}">${f.cvd >= 0 ? "+" : ""}${f.cvd.toFixed(2)} BTC</b></div></div>
    <div class="cx-cvd ${cls(f.cvd)}">${spark}</div><p class="note">Each trade is labelled by Binance as a buy or a sell made by the side that crossed the spread. Buy volume minus sell volume is the order-flow delta the strategies read, here over a short window.</p></div>`;
}
function accountHtml() {
  if (!L) return `<div class="sg-empty"><b>The account has not started yet.</b><span>It starts with the first engine run on GitHub (every 15 minutes). Budget Rs 10,00,000, simulated.</span></div>`;
  const px = feed.price || L.bid, eq = liveEquity(L, px), pnl = eq - L.budget_usd, ret = pnl / L.budget_usd * 100, fx = L.fx_now || L.fx0, stale = isStale(L), age = minutesSince(L.engine_ts);
  const curve = (L.curve || []).map(r => [r[0].slice(0, 10), r[1]]);
  const chart = L.curve && L.curve.length > 2 ? lineChart([{ name: "Paper account (USD)", pts: L.curve.map(r => [r[0].slice(0, 10), r[1]]), cls: "a" }], { base: L.budget_usd, label: "Paper account value over time", fmt: v => usd(v, 0) }) : '<p class="note">The equity line appears after a few hours of runs.</p>';
  return `<div class="sg-banner">${esc(L.label)}</div>
    ${stale ? `<div class="sg-warn"><b>Engine late.</b> Its last run was ${age != null ? age.toFixed(0) : "?"} minutes ago (GitHub's scheduler can lag). Stops and signals are only checked when it runs; the prices above are live.</div>` : ""}
    <div class="sg-stats sg-kp"><div class="sg-stat"><span>Hard budget</span><b>₹${inr(L.budget_inr, 0)}</b><small>= ${usd(L.budget_usd)} at ₹${L.fx0.toFixed(2)}; no top-ups, no leverage</small></div>
      <div class="sg-stat"><span>Account value now</span><b>${usd(eq)}</b><small>₹${inr(eq * fx, 0)} at today's rate · ₹${inr(eq * L.fx0, 0)} at the start rate</small></div>
      <div class="sg-stat"><span>Profit or loss</span><b class="${cls(pnl)}">${pnl >= 0 ? "+" : "-"}${usd(Math.abs(pnl))}</b><small class="${cls(ret)}">${sgn(ret, 2)}</small></div>
      <div class="sg-stat"><span>In Bitcoin</span><b>${L.invested_pct}%</b><small>the rest is cash earning nothing</small></div></div>
    <div class="sg-card"><h4>Account value since the start (hourly)</h4>${chart}<p class="note">For comparison, the same budget put into Bitcoin on day one and left there is worth ${usd(L.buy_hold_usd)} now. These strategies trade rarely and are often in cash, so in a rising market they will usually lag that.</p></div>
    <div class="cx-sleeves">${Object.entries(L.sleeves).map(([k, s]) => sleeveHtml(k, s, px)).join("")}</div>`;
}
function sleeveHtml(k, s, px) {
  const inp = s.btc > 0, n = s.now || {}, un = inp ? s.btc * (px - s.entry) : null;
  const read = k === "flow_momentum" ? `<li>Buyer dominance (flow z): <b>${n.flow24 ?? "--"}</b> <span class="mut">needs above 1.0</span></li><li>Price vs 50-bar average: <b>${n.c != null && n.sma50 ? sgn((n.c / n.sma50 - 1) * 100) : "--"}</b> <span class="mut">needs above 0%</span></li>`
    : `<li>Last close vs 24-bar high: <b>${n.c != null && n.hi24 ? sgn((n.c / n.hi24 - 1) * 100) : "--"}</b> <span class="mut">needs above 0%</span></li><li>Delta z: <b>${n.delta_z ?? "--"}</b> <span class="mut">needs above 1</span></li><li>Volume z: <b>${n.vol_z ?? "--"}</b> <span class="mut">needs above 1</span></li>`;
  return `<div class="sg-card"><h4>${esc(s.label)} · ${esc(s.timeframe)} bars · half the budget</h4><p class="note">${esc(DESC[k] || "")}</p>
    <p class="cx-state ${inp ? "in" : ""}"><b>${inp ? "IN BITCOIN" : "FLAT (cash)"}</b>${inp ? ` · ${s.btc.toFixed(5)} BTC bought at ${usd(s.entry)} · stop ${usd(s.stop)} · open P/L <i class="${cls(un)}">${un >= 0 ? "+" : "-"}${usd(Math.abs(un))}</i>` : " · waiting for the entry conditions on the next closed bar"}</p>
    <ul class="cx-read">${read}</ul><p class="note">${s.trades} closed trades, ${s.wins} profitable, net ${s.net >= 0 ? "+" : "-"}${usd(Math.abs(s.net))} · sleeve value ${usd(s.equity)}</p></div>`;
}
function studyHtml() {
  if (!S) return "";
  const V = S.variants, dep = new Set(["flow_momentum_4h", "flow_breakout_4h"]), names = { ha_trend: "Heikin-Ashi trend", ha_flow: "Heikin-Ashi + order flow", flow_momentum: "Order-flow momentum", flow_absorb: "Absorption (mean reversion)", flow_breakout: "Order-flow breakout", buy_hold: "Buy and hold" };
  const row = ([k, v]) => `<tr class="${dep.has(k) ? "on" : ""}"><td>${esc(names[v.strategy] || v.strategy)} <small>${esc(v.timeframe)}${dep.has(k) ? " · traded live" : ""}</small></td>
    <td class="r ${cls(v.selection.return_pct)}">${sgn(v.selection.return_pct, 0)}<small>${v.selection.trades || ""}${v.selection.trades ? " trades" : ""}</small></td><td class="r ${cls(v.held_out.return_pct)}">${sgn(v.held_out.return_pct, 0)}<small>${v.held_out.trades || ""}${v.held_out.trades ? " trades" : ""}</small></td>
    <td class="r">${v.held_out.sharpe ?? "--"}</td><td class="r down">${v.held_out.max_drawdown_pct != null ? v.held_out.max_drawdown_pct + "%" : "--"}</td><td class="r">${v.held_out.avg_net_pct != null ? sgn(v.held_out.avg_net_pct, 2) : "--"}</td>
    <td class="r">${v["held_out_cost_0.25pct"] ? sgn(v["held_out_cost_0.25pct"].return_pct, 0) : "--"}</td></tr>`;
  const rows = Object.entries(V).filter(([k]) => k.endsWith("_4h") || k.endsWith("_1h")).sort((a, b) => (a[1].timeframe === b[1].timeframe ? 0 : a[1].timeframe === "4h" ? -1 : 1) || (b[1].held_out.return_pct ?? -1e9) - (a[1].held_out.return_pct ?? -1e9));
  return `<div class="sg-card"><h4>The research behind it · ${esc(S.bars)}</h4><div class="sg-tablewrap"><table class="sg-table"><thead><tr><th>Strategy</th><th class="r">Selection 2020-23</th><th class="r">Held out 2024-26</th><th class="r">Sharpe</th><th class="r">Worst fall</th><th class="r">Avg trade</th><th class="r">Held out at double costs</th></tr></thead><tbody>${rows.map(row).join("")}</tbody></table></div>
    <p class="note">Return on the strategy's own account, after costs of ${(S.cost_per_fill * 100).toFixed(2)}% per fill. Selection years chose the strategies; the held-out years were looked at once. <b>Heikin-Ashi alone loses money after costs</b> (it trades constantly), and every 1-hour variant is eaten by fees. Only two 4-hour order-flow strategies made money in both periods, and they kept earning at double the costs, so those two are traded. Ten variants were tried, so the best looks better than it will be. Buy and hold beat all of them in raw return, with a worst fall of -77% in 2020-23 against roughly -11% to -21% here. Bitcoin's rise since 2020 is not a guarantee of anything.</p></div>`;
}
function logsHtml() {
  if (!L) return "";
  const tr = (L.trades || []).slice().reverse().slice(0, 40), dc = (L.decisions || []).slice().reverse().slice(0, 24);
  const t = tr.length ? `<div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>Strategy</th><th>In</th><th>Out</th><th class="r">Price in → out</th><th class="r">Net P/L</th><th>Why out</th></tr></thead><tbody>${tr.map(x => `<tr><td>${esc(x.sleeve)}</td><td>${esc(fmtT(x.in_ts))}</td><td>${esc(fmtT(x.out_ts))}</td><td class="r">${inr(x.in)} → ${inr(x.out)}</td><td class="r"><b class="${cls(x.net)}">${x.net >= 0 ? "+" : "-"}${usd(Math.abs(x.net))}</b><small class="${cls(x.ret_pct)}">${sgn(x.ret_pct, 2)}</small></td><td>${esc(x.why)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="note">No closed trade yet. Both strategies trade only a few times a month.</p>';
  const d = dc.length ? `<details class="tg-rows"><summary>Every decision the engine made (${L.decisions.length} shown)</summary><div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>When</th><th>Strategy</th><th>4-hour bar</th><th>Action</th><th>Why</th></tr></thead><tbody>${dc.map(x => `<tr><td>${esc(fmtT(x.ts))}</td><td>${esc(x.sleeve)}</td><td>${esc(x.bar)}</td><td>${esc(x.action)}</td><td>${esc(x.why || (x.signal_enter ? "entry conditions met" : x.signal_exit ? "exit conditions met" : "no signal"))}</td></tr>`).join("")}</tbody></table></div></details>` : "";
  return `<div class="sg-card"><h4>Closed trades</h4>${t}${d}</div>`;
}
function shell() {
  return `<div class="page-head"><p class="kick">— Crypto · Bitcoin · order flow · paper trading</p><h2>Bitcoin, <span class="acc">read by its order flow.</span></h2><p class="asof" id="cx-asof"></p></div>
    <div class="cx-price"><span>BTC / USDT</span><b id="cx-px">--</b><em id="cx-inr"></em></div><div id="cx-flow"></div><div id="cx-acct"></div><div id="cx-study"></div><div id="cx-logs"></div>
    <p class="note">Simulated money on real prices from the day the account started. No exchange account, no real order. Fills pay Binance's taker fee and slippage (0.12% each way); India's 30% tax on gains and 1% TDS are not modelled. Educational analysis only, not investment advice.</p>`;
}
function tick() {
  if (!root || !root.isConnected) { clearInterval(timer); timer = null; return; }
  const px = feed.price || (L && L.bid), fx = L && (L.fx_now || L.fx0);
  const e = root.querySelector("#cx-px"); if (e) e.textContent = px ? usd(px) : "--"; const i = root.querySelector("#cx-inr"); if (i) i.textContent = px && fx ? `₹${inr(px * fx, 0)}` : "";
  const f = root.querySelector("#cx-flow"); if (f) f.innerHTML = flowHtml();
  const a = root.querySelector("#cx-asof"); if (a) a.textContent = L ? `engine last ran ${fmtT(L.engine_ts)} · price feed ${feed.status}` : `price feed ${feed.status}`;
  if (L && st.acctAt !== L.engine_ts + (feed.price ? Math.round(feed.price / 5) : "")) { st.acctAt = L.engine_ts + (feed.price ? Math.round(feed.price / 5) : ""); const ac = root.querySelector("#cx-acct"); if (ac) ac.innerHTML = accountHtml(); }
}
const st = { acctAt: null };
export async function mount() {
  root = document.getElementById("crypto"); if (!root) return;
  root.innerHTML = '<p class="note">Loading…</p>'; await load(); root.innerHTML = shell();
  root.querySelector("#cx-acct").innerHTML = accountHtml(); root.querySelector("#cx-study").innerHTML = studyHtml(); root.querySelector("#cx-logs").innerHTML = logsHtml();
  connect(); tick(); if (!timer) timer = setInterval(tick, 1000);
  if (!beat) beat = setInterval(async () => { if (root && root.isConnected) { await load(); const ac = root.querySelector("#cx-acct"); if (ac) ac.innerHTML = accountHtml(); const lg = root.querySelector("#cx-logs"); if (lg) lg.innerHTML = logsHtml(); } }, 60000);
}
export const _test = { feed, reset: () => { L = null; S = null; feed.trades.length = 0; }, set: (l, s) => { L = l; S = s; } };
