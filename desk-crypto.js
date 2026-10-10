/* Crypto tab: the Bitcoin and Ethereum order-flow paper account (scripts/crypto_live.py), its research (scripts/crypto_flow.py) and a live 3D view of every trade (desk-crypto3d.js).
   Live in the browser: Binance's public trade stream and order book (desk-cryptofeed.js). Every other number is read from t/c/live.json (the engine, refreshed every 15 minutes) and t/c/study*.json (the 2020-2026 research).
   A missing input says "not measured". Simulated money, hard budget Rs 10,00,000, no exchange account. Educational analysis only, not investment advice. */
import { esc, inr } from "./desk-aladin2.js";
import { lineChart } from "./desk-signals.js";
import { feed, connect, flowWindow, ASSETS } from "./desk-cryptofeed.js";
import { mount3d } from "./desk-crypto3d.js";

let ctx = null, root = null, L = null, STUDY = {}, timer = null, beat = null, ctl = null, prevQty = null;
const st = { acctAt: null, hudAt: 0 };
export function init(c) { ctx = c; }

const usd = (v, d = 2) => v == null ? "--" : "$" + inr(v, d);
const compact = v => v >= 1e6 ? "$" + (v / 1e6).toFixed(2) + "M" : v >= 1e3 ? "$" + (v / 1e3).toFixed(1) + "k" : "$" + Math.round(v);
const sgn = (v, d = 2, s = "%") => v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(d) + s;
const cls = v => v == null ? "" : v >= 0 ? "up" : "down";
const short = s => s === "BTCUSDT" ? "BTC" : "ETH";

/* ---------- pure helpers (tests/js/crypto.test.mjs) ---------- */
/* account value now: each sleeve's cash plus its coins at the live price of that coin. prices: {BTCUSDT: p, ETHUSDT: p} */
export function liveEquity(doc, prices = {}) {
  if (!doc) return null; return Object.values(doc.sleeves).reduce((t, s) => t + s.cash + s.qty * (prices[s.asset] || (doc.assets && doc.assets[s.asset] && doc.assets[s.asset].bid) || 0), 0);
}
export const minutesSince = (iso, now = Date.now()) => iso ? (now - Date.parse(iso)) / 60000 : null;
export const isStale = (doc, now = Date.now()) => !doc || minutesSince(doc.engine_ts, now) > (doc.stale_after_min || 45);
/* which sleeves traded since the last look: [{sleeve, side}] (entered = quantity went from nothing to something, exited = back to nothing) */
export function tradedSince(prev, sleeves) {
  if (!prev) return []; const out = [];
  for (const [k, s] of Object.entries(sleeves || {})) { const was = prev[k] || 0; if (was === 0 && s.qty > 0) out.push({ sleeve: k, side: "buy", asset: s.asset, label: s.label }); else if (was > 0 && s.qty === 0) out.push({ sleeve: k, side: "sell", asset: s.asset, label: s.label }); }
  return out;
}
const fmtT = iso => iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) + " IST" : "--";
const DESC = { flow_momentum: "Buys when aggressive buyers have dominated the last 24 four-hour bars, unusually so, while price is above its 50-bar average. Leaves when that buying fades. Stop 3 average bar ranges below.",
  flow_breakout: "Buys a close above the 24-bar high only when the buy-minus-sell volume and the total volume are both well above normal. Leaves below the 12-bar low or on a red Heikin-Ashi bar. Stop 3 average bar ranges below." };

/* ---------- loading ---------- */
async function load() {
  try { L = await ctx.getJSON("t/c/live.json", true); } catch (e) { L = null; }
  for (const [k, f] of [["BTCUSDT", "study.json"], ["ETHUSDT", "study_eth.json"]]) if (!STUDY[k]) { try { STUDY[k] = await ctx.getJSON("t/c/" + f, false); } catch (e) { STUDY[k] = null; } }
}
const prices = () => { const p = {}; for (const a of Object.keys(ASSETS)) p[a] = feed.price[a] || (L && L.assets && L.assets[a] && L.assets[a].bid) || null; return p; };

/* ---------- drawing ---------- */
function stageHtml() {
  return `<div class="cx3" id="cx3"><div id="cx3-host" class="cx3-host"></div>
    <div class="cx3-hud" aria-live="off"><div class="cx3-top"><div class="sg-chips" role="group" aria-label="Coin">${Object.keys(ASSETS).map(a => `<button type="button" class="sg-chip ${feed.sel === a ? "on" : ""}" data-asset="${a}" aria-pressed="${feed.sel === a}">${esc(ASSETS[a])}</button>`).join("")}</div>
      <div class="cx3-px"><b id="cx3-price">--</b><em id="cx3-inr"></em></div></div>
      <div class="cx3-stats"><span>Trades a second <b id="cx3-rate">--</b></span><span class="up">Aggressive buying, 1 min <b id="cx3-buy">--</b></span><span class="down">Aggressive selling, 1 min <b id="cx3-sell">--</b></span><span>Imbalance <b id="cx3-imb">--</b></span></div>
      <div class="cx-flow" aria-hidden="true"><i class="up" id="cx3-fb" style="width:50%"></i><i class="down" id="cx3-fs" style="width:50%"></i></div></div>
    <div class="cx3-toast" id="cx3-toast" role="status" aria-live="polite"></div>
    <div class="cx3-ctl"><button type="button" class="btn-line sm" data-c="rot">Rotate</button><button type="button" class="btn-line sm" data-c="reset">Reset view</button><button type="button" class="btn-line sm" data-c="pause">Pause</button></div>
    <p class="cx3-leg"><span class="up">● buyers hit the ask</span> · <span class="down">● sellers hit the bid</span> · size = trade value · ring = a trade over $250k · white burst = the paper account traded · bars = the order book · drag to turn, scroll to zoom · time runs right to left</p>
    <p class="cx3-off" id="cx3-off" hidden>The 3D view needs WebGL, which this browser does not offer. The numbers above still update live.</p></div>`;
}
function bindStage() {
  root.querySelectorAll("[data-asset]").forEach(b => b.onclick = () => { feed.sel = b.dataset.asset; root.querySelectorAll("[data-asset]").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); }); if (ctl) ctl.setAsset(feed.sel); });
  const c = k => root.querySelector(`[data-c="${k}"]`);
  if (c("rot")) c("rot").onclick = () => { if (ctl) c("rot").classList.toggle("on", ctl.toggleRotate()); };
  if (c("reset")) c("reset").onclick = () => { if (ctl) ctl.resetView(); };
  if (c("pause")) c("pause").onclick = () => { if (ctl) { const p = ctl.togglePause(); c("pause").textContent = p ? "Resume" : "Pause"; } };
}
function toast(text) {
  const t = root && root.querySelector("#cx3-toast"); if (!t) return; t.textContent = text; t.classList.add("on"); setTimeout(() => t.classList.remove("on"), 6000);
}
function accountHtml() {
  if (!L) return `<div class="sg-empty"><b>The account has not started yet.</b><span>It starts with the first engine run on GitHub (every 15 minutes). Budget Rs 10,00,000, simulated.</span></div>`;
  const px = prices(), eq = liveEquity(L, px), pnl = eq - L.budget_usd, ret = pnl / L.budget_usd * 100, fx = L.fx_now || L.fx0, stale = isStale(L), age = minutesSince(L.engine_ts);
  const chart = L.curve && L.curve.length > 2 ? lineChart([{ name: "Paper account (USD)", pts: L.curve.map(r => [r[0].slice(0, 10), r[1]]), cls: "a" }], { base: L.budget_usd, label: "Paper account value over time", fmt: v => usd(v, 0) }) : '<p class="note">The equity line appears after a few hours of runs.</p>';
  return `<div class="sg-banner">${esc(L.label)}</div>
    ${stale ? `<div class="sg-warn"><b>Engine late.</b> Its last run was ${age != null ? age.toFixed(0) : "?"} minutes ago (GitHub's scheduler can lag). Stops and signals are only checked when it runs; the prices above are live.</div>` : ""}
    <div class="sg-stats sg-kp"><div class="sg-stat"><span>Hard budget</span><b>₹${inr(L.budget_inr, 0)}</b><small>= ${usd(L.budget_usd)} at ₹${L.fx0.toFixed(2)}; no top-ups, no leverage</small></div>
      <div class="sg-stat"><span>Account value now</span><b>${usd(eq)}</b><small>₹${inr(eq * fx, 0)} at today's rate · ₹${inr(eq * L.fx0, 0)} at the start rate</small></div>
      <div class="sg-stat"><span>Profit or loss</span><b class="${cls(pnl)}">${pnl >= 0 ? "+" : "-"}${usd(Math.abs(pnl))}</b><small class="${cls(ret)}">${sgn(ret, 2)}</small></div>
      <div class="sg-stat"><span>In crypto</span><b>${L.invested_pct}%</b><small>the rest is cash earning nothing</small></div></div>
    <div class="sg-card"><h4>Account value since the start (hourly)</h4>${chart}<p class="note">For comparison, the same budget put half into Bitcoin and half into Ethereum on day one and left there is worth ${usd(L.buy_hold_usd)} now. These strategies trade rarely and are often in cash, so in a rising market they will usually lag that.</p></div>
    <div class="cx-sleeves">${Object.entries(L.sleeves).map(([k, s]) => sleeveHtml(k, s, px[s.asset])).join("")}</div>`;
}
function sleeveHtml(k, s, px) {
  const inp = s.qty > 0, n = s.now || {}, un = inp && px ? s.qty * (px - s.entry) : null, name = short(s.asset);
  const read = s.strategy === "flow_momentum" ? `<li>Buyer dominance (flow z): <b>${n.flow24 ?? "--"}</b> <span class="mut">needs above 1.0</span></li><li>Price vs 50-bar average: <b>${n.c != null && n.sma50 ? sgn((n.c / n.sma50 - 1) * 100) : "--"}</b> <span class="mut">needs above 0%</span></li>`
    : `<li>Last close vs 24-bar high: <b>${n.c != null && n.hi24 ? sgn((n.c / n.hi24 - 1) * 100) : "--"}</b> <span class="mut">needs above 0%</span></li><li>Delta z: <b>${n.delta_z ?? "--"}</b> <span class="mut">needs above 1</span></li><li>Volume z: <b>${n.vol_z ?? "--"}</b> <span class="mut">needs above 1</span></li>`;
  return `<div class="sg-card"><h4>${esc(s.label)} · ${esc(s.timeframe)} bars · ${Math.round(s.share * 100)}% of the budget</h4><p class="note">${esc(DESC[s.strategy] || "")}</p>
    <p class="cx-state ${inp ? "in" : ""}"><b>${inp ? "IN " + name : "FLAT (cash)"}</b>${inp ? ` · ${s.qty.toFixed(5)} ${name} bought at ${usd(s.entry)} · stop ${usd(s.stop)} · open P/L <i class="${cls(un)}">${un == null ? "--" : (un >= 0 ? "+" : "-") + usd(Math.abs(un))}</i>` : " · waiting for the entry conditions on the next closed bar"}</p>
    <ul class="cx-read">${read}</ul><p class="note">${s.trades} closed trades, ${s.wins} profitable, net ${s.net >= 0 ? "+" : "-"}${usd(Math.abs(s.net))} · sleeve value ${usd(s.equity)}</p></div>`;
}
function depthHtml() {
  const D = L && L.depth_experiment; if (!D) return "";
  const rows = Object.entries(D.stats || {}).map(([sym, v]) => {
    const f = v.next_1h || {}, g = v.next_4h || {}, ok = x => x && x.rho != null && Math.abs(x.rho) > x.needs_abs_rho_above;
    return `<tr><td>${esc(ASSETS[sym] || sym)}</td><td class="r">${v.n ?? 0}</td><td class="r">${f.rho ?? "--"}<small>${f.needs_abs_rho_above != null ? "needs beyond ±" + f.needs_abs_rho_above : "needs 30+ pairs"}</small></td><td class="r">${g.rho ?? "--"}<small>${g.needs_abs_rho_above != null ? "needs beyond ±" + g.needs_abs_rho_above : "needs 30+ pairs"}</small></td>
      <td>${ok(f) || ok(g) ? "a pattern is showing; still not traded" : "no evidence yet"}</td><td class="r">${v.latest && v.latest.imb_near != null ? sgn(v.latest.imb_near * 100, 0, "%") : "--"}</td></tr>`;
  }).join("");
  return `<div class="sg-card"><h4>Experiment, not traded · does the order book predict the next move?</h4><p class="note">${esc(D.label)}</p>
    <div class="sg-tablewrap"><table class="sg-table"><thead><tr><th>Coin</th><th class="r">Hourly samples</th><th class="r">Rank correlation, next hour</th><th class="r">Next 4 hours</th><th>Verdict</th><th class="r">Book now</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note">One sample an hour is slow by design: this checks whether the resting orders say anything over hours, not seconds. A correlation inside the "needs" band is indistinguishable from chance. With a sample every hour, expect weeks before the numbers mean anything.</p></div>`;
}
function studyHtml() {
  const names = { ha_trend: "Heikin-Ashi trend", ha_flow: "Heikin-Ashi + order flow", flow_momentum: "Order-flow momentum", flow_absorb: "Absorption (mean reversion)", flow_breakout: "Order-flow breakout", buy_hold: "Buy and hold" };
  const dep = new Set(["flow_momentum_4h", "flow_breakout_4h"]);
  const one = (sym, S) => {
    if (!S) return ""; const rows = Object.entries(S.variants).sort((a, b) => (a[1].timeframe === b[1].timeframe ? 0 : a[1].timeframe === "4h" ? -1 : 1) || (b[1].held_out.return_pct ?? -1e9) - (a[1].held_out.return_pct ?? -1e9));
    const row = ([k, v]) => `<tr class="${dep.has(k) ? "on" : ""}"><td>${esc(names[v.strategy] || v.strategy)} <small>${esc(v.timeframe)}${dep.has(k) ? " · traded live" : ""}</small></td><td class="r ${cls(v.selection.return_pct)}">${sgn(v.selection.return_pct, 0)}<small>${v.selection.trades ? v.selection.trades + " trades" : ""}</small></td>
      <td class="r ${cls(v.held_out.return_pct)}">${sgn(v.held_out.return_pct, 0)}<small>${v.held_out.trades ? v.held_out.trades + " trades" : ""}</small></td><td class="r">${v.held_out.sharpe ?? "--"}</td><td class="r down">${v.held_out.max_drawdown_pct != null ? v.held_out.max_drawdown_pct + "%" : "--"}</td><td class="r">${v.held_out.avg_net_pct != null ? sgn(v.held_out.avg_net_pct, 2) : "--"}</td><td class="r">${v["held_out_cost_0.25pct"] ? sgn(v["held_out_cost_0.25pct"].return_pct, 0) : "--"}</td></tr>`;
    return `<h4 style="margin-top:12px">${esc(ASSETS[sym])} · ${esc(S.bars)}</h4><div class="sg-tablewrap"><table class="sg-table"><thead><tr><th>Strategy</th><th class="r">Selection 2020-23</th><th class="r">Held out 2024-26</th><th class="r">Sharpe</th><th class="r">Worst fall</th><th class="r">Avg trade</th><th class="r">Held out, double costs</th></tr></thead><tbody>${rows.map(row).join("")}</tbody></table></div>`;
  };
  const any = STUDY.BTCUSDT || STUDY.ETHUSDT; if (!any) return "";
  return `<div class="sg-card"><h4>The research behind it</h4>${one("BTCUSDT", STUDY.BTCUSDT)}${one("ETHUSDT", STUDY.ETHUSDT)}
    <p class="note">Return on each strategy's own account, after costs of ${(any.cost_per_fill * 100).toFixed(2)}% per fill. Selection years chose the strategies; the held-out years were looked at once. <b>Heikin-Ashi alone loses money after costs</b> (it trades constantly), and every 1-hour variant is eaten by fees. The same two 4-hour order-flow strategies made money in both periods on both coins, and kept earning at double the costs, so those are traded. Ten variants were tried per coin, so the best looks better than it will be. Bitcoin and Ethereum move together, so two coins are not two independent proofs. Buy and hold beat the strategies on Bitcoin in raw return, with a far deeper worst fall; on Ethereum the strategies beat it.</p></div>`;
}
function logsHtml() {
  if (!L) return "";
  const tr = (L.trades || []).slice().reverse().slice(0, 40), dc = (L.decisions || []).slice().reverse().slice(0, 40);
  const t = tr.length ? `<div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>Strategy</th><th>In</th><th>Out</th><th class="r">Price in → out</th><th class="r">Net P/L</th><th>Why out</th></tr></thead><tbody>${tr.map(x => `<tr><td>${esc(x.sleeve)}</td><td>${esc(fmtT(x.in_ts))}</td><td>${esc(fmtT(x.out_ts))}</td><td class="r">${inr(x.in)} → ${inr(x.out)}</td><td class="r"><b class="${cls(x.net)}">${x.net >= 0 ? "+" : "-"}${usd(Math.abs(x.net))}</b><small class="${cls(x.ret_pct)}">${sgn(x.ret_pct, 2)}</small></td><td>${esc(x.why)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="note">No closed trade yet. The strategies trade only a few times a month each.</p>';
  const d = dc.length ? `<details class="tg-rows"><summary>Every decision the engine made (${L.decisions.length} shown)</summary><div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>When</th><th>Strategy</th><th>4-hour bar</th><th>Action</th><th>Why</th></tr></thead><tbody>${dc.map(x => `<tr><td>${esc(fmtT(x.ts))}</td><td>${esc(x.sleeve)}</td><td>${esc(x.bar)}</td><td>${esc(x.action)}</td><td>${esc(x.why || (x.signal_enter ? "entry conditions met" : x.signal_exit ? "exit conditions met" : "no signal"))}</td></tr>`).join("")}</tbody></table></div></details>` : "";
  return `<div class="sg-card"><h4>Closed trades</h4>${t}${d}</div>`;
}
function shell() {
  return `<div class="page-head"><p class="kick">— Crypto · Bitcoin · Ethereum · order flow · paper trading</p><h2>Every trade, <span class="acc">as it happens.</span></h2><p class="asof" id="cx-asof"></p></div>
    ${stageHtml()}<div id="cx-acct"></div><div id="cx-depth"></div><div id="cx-study"></div><div id="cx-logs"></div>
    <p class="note">Simulated money on real prices from the day the account started. No exchange account, no real order. Fills pay Binance's taker fee and slippage (0.12% each way); India's 30% tax on gains and 1% TDS are not modelled. Educational analysis only, not investment advice.</p>`;
}
function hud(h) {
  const q = s => root && root.querySelector(s); if (!q("#cx3-price")) return; const px = h.price || feed.price[feed.sel], fx = L && (L.fx_now || L.fx0), tot = h.buy + h.sell;
  q("#cx3-price").textContent = px ? usd(px) : "--"; q("#cx3-inr").textContent = px && fx ? `₹${inr(px * fx, 0)}` : ""; q("#cx3-rate").textContent = h.perSec.toFixed(1); q("#cx3-buy").textContent = compact(h.buy); q("#cx3-sell").textContent = compact(h.sell);
  q("#cx3-imb").textContent = tot ? Math.round(Math.abs(h.imbalance) * 100) + "% " + (h.imbalance >= 0 ? "buyers" : "sellers") : "--"; q("#cx3-fb").style.width = (tot ? h.buy / tot * 100 : 50).toFixed(1) + "%"; q("#cx3-fs").style.width = (tot ? h.sell / tot * 100 : 50).toFixed(1) + "%";
}
function tick() {
  if (!root || !root.isConnected) { clearInterval(timer); timer = null; return; }
  if (!ctl) hud({ ...flowWindow(feed.trades[feed.sel], Date.now()), price: feed.price[feed.sel] });
  const a = root.querySelector("#cx-asof"); if (a) a.textContent = L ? `engine last ran ${fmtT(L.engine_ts)} · live feed ${feed.status}` : `live feed ${feed.status}`;
  const key = (L ? L.engine_ts : "") + Object.values(prices()).map(p => p ? Math.round(p / 5) : "").join(","); if (L && st.acctAt !== key) { st.acctAt = key; const ac = root.querySelector("#cx-acct"); if (ac) ac.innerHTML = accountHtml(); }
}
function syncAccount() {
  if (!L) return; const moves = tradedSince(prevQty, L.sleeves); prevQty = Object.fromEntries(Object.entries(L.sleeves).map(([k, s]) => [k, s.qty]));
  if (ctl) { ctl.setPositions(L.sleeves, prices()); for (const m of moves) { const p = L.assets[m.asset] && L.assets[m.asset].mid; if (m.asset === feed.sel) ctl.burst(m.side, "", p); toast(`THE PAPER ACCOUNT ${m.side === "buy" ? "BOUGHT" : "SOLD"} · ${m.label}`); } }
  else for (const m of moves) toast(`THE PAPER ACCOUNT ${m.side === "buy" ? "BOUGHT" : "SOLD"} · ${m.label}`);
}
export async function mount() {
  root = document.getElementById("crypto"); if (!root) return;
  if (ctl) { ctl.destroy(); ctl = null; }
  root.innerHTML = '<p class="note">Loading…</p>'; await load(); root.innerHTML = shell(); bindStage();
  root.querySelector("#cx-acct").innerHTML = accountHtml(); root.querySelector("#cx-depth").innerHTML = depthHtml(); root.querySelector("#cx-study").innerHTML = studyHtml(); root.querySelector("#cx-logs").innerHTML = logsHtml();
  connect(() => !!(root && root.isConnected)); prevQty = null; syncAccount();
  const reduced = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  mount3d(root.querySelector("#cx3-host"), { reduced, onHud: hud, onToast: () => {} }).then(c => { if (!c) { const o = root && root.querySelector("#cx3-off"); if (o) o.hidden = false; return; } if (!root || !root.isConnected) { c.destroy(); return; } ctl = c; ctl.setAsset(feed.sel); if (L) ctl.setPositions(L.sleeves, prices()); }).catch(() => { const o = root && root.querySelector("#cx3-off"); if (o) o.hidden = false; });
  tick(); if (!timer) timer = setInterval(tick, 1000);
  if (!beat) beat = setInterval(async () => { if (root && root.isConnected) { await load(); syncAccount(); for (const [id, fn] of [["#cx-acct", accountHtml], ["#cx-depth", depthHtml], ["#cx-logs", logsHtml]]) { const el = root.querySelector(id); if (el) el.innerHTML = fn(); } } }, 60000);
}
export const _test = { reset: () => { L = null; STUDY = {}; prevQty = null; }, set: (l, s) => { L = l; STUDY = s || {}; } };
