/* B-LAB TERMINAL (expert-terminal.html). Every NSE stock, real data only.
   t/universe.json   all NSE stocks: NSE official end-of-day (daily)
   t/quotes.json     delayed live prices for ~2,950 main-board stocks (every ~15 min in market hours)
   t/h/<k>.json      one year of NSE daily candles, grouped by first letter (loaded on demand)
   t/i/<k>.json      the session's 5-minute candles (loaded on demand)
   t/fund.json       fundamentals for NIFTY 500 companies (daily)
   live.json         world indices + headlines;  screener.json  today's B-Lab screen (default watchlist)
   Nothing is simulated: values change only when fresh data arrives. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const IST = "Asia/Kolkata";
const POLL_MS = 60000;
const C = { up: "#00ff00", down: "#e0a060", txt: "#e8dcc3", dim: "#8a8064", line: "#b5a682", bg: "#061a10", sma20: "#e8dcc3", sma50: "#b5a682" };

const S = { uni: null, map: new Map(), quotes: {}, qmeta: {}, fund: null, live: {}, screen: {}, hist: {}, intra: {}, prevWei: {} };
let sec = null, range = "1Y", ctype = "candle", ind = { sma20: true, sma50: true, vol: true }, movMode = "gain", board = "All", sector = null, detTab = "DES";

/* ---------------- formatting ---------------- */
const inr = (v, d = 2) => v == null ? "--" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const us = (v, d = 2) => v == null ? "--" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const sg = (v, d = 2) => v == null ? "--" : (v > 0 ? "+" : "") + Number(v).toFixed(d);
const ud = v => v == null || v === 0 ? "flat" : v > 0 ? "up" : "down";
const big = v => v == null ? "--" : v >= 1e7 ? (v / 1e7).toFixed(2) + " Cr" : v >= 1e5 ? (v / 1e5).toFixed(2) + " L" : Math.round(v).toLocaleString("en-IN");
const cr = v => v == null ? "--" : "₹" + Math.round(v).toLocaleString("en-IN") + " Cr";
const pctF = (v, d = 1) => v == null ? "--" : (v * 100).toFixed(d) + "%";
const shard = s => /[A-Z]/i.test(s[0]) ? s[0].toUpperCase() : "0";
const toast = (t) => { const el = $("#toast"); el.textContent = t; el.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => el.classList.remove("show"), 2200); };

/* ---------------- quote model: live if we have it, else NSE end-of-day ---------------- */
function q(sym) {
  const e = S.map.get(sym);
  if (!e) return null;
  const l = S.quotes[sym];
  if (l && l.d >= e.date) return { live: true, p: l.p, chg: l.chg, pct: l.pct, o: l.o, h: l.h, l: l.l, v: l.v, t: l.t, d: l.d, pc: l.p - l.chg };
  return { live: false, p: e.c, chg: e.chg, pct: e.pct, o: e.o, h: e.h, l: e.l, v: e.v, t: "EOD", d: e.date, pc: e.pc };
}

/* ---------------- auth ---------------- */
function onReady(user) {
  $("#sys-user").textContent = user.email;
  $("#logout").onclick = async () => { try { await window.__expertSignOut?.(); } finally { location.replace("auth.html"); } };
}
document.addEventListener("expert-ready", e => { window.__expertSignOut = e.detail.signOut; onReady(e.detail.user); });
if (window.expertUser) onReady(window.expertUser);

/* ---------------- clock ---------------- */
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString("en-GB", { timeZone: IST, hour12: false }) + " IST"; }, 1000);

/* ---------------- loading ---------------- */
async function getJSON(url, bust = true) {
  const r = await fetch(url + (bust ? "?t=" + Date.now() : ""), { cache: bust ? "no-store" : "default" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}
async function boot() {
  try {
    const [uni, quotes, live, screen] = await Promise.all([
      getJSON("t/universe.json"), getJSON("t/quotes.json").catch(() => ({})), getJSON("live.json").catch(() => ({})), getJSON("screener.json").catch(() => ({})),
    ]);
    S.uni = uni; uni.stocks.forEach(s => S.map.set(s.s, s));
    applyQuotes(quotes); S.live = live; S.screen = screen;
  } catch (e) {
    $("#st-data").textContent = "DATA NOT AVAILABLE: THE STOCK LIST COULD NOT BE LOADED. NOTHING IS SHOWN IN ITS PLACE.";
    $("#movers").innerHTML = '<div class="empty">Data not available.</div>';
    return;
  }
  const start = new URLSearchParams(location.hash.slice(1)).get("s");
  sec = (start && S.map.has(start)) ? start : (loadWatch()[0] || S.uni.stocks[0].s);
  renderStatus(); renderTape(); renderWei(false); renderBreadth(); renderMovers(); renderHeat(); renderWatch(); renderNews();
  await openSec(sec);
  getJSON("t/fund.json", false).then(f => { S.fund = f.stocks || {}; if (["DES", "FA"].includes(detTab)) renderDetail(); }).catch(() => { S.fund = {}; });
  setInterval(poll, POLL_MS);
}
function applyQuotes(d) { S.quotes = (d && d.quotes) || {}; S.qmeta = d || {}; }
async function poll() {
  try {
    const [quotes, live] = await Promise.all([getJSON("t/quotes.json"), getJSON("live.json")]);
    const changed = quotes.generated_utc !== S.qmeta.generated_utc;
    applyQuotes(quotes); S.live = live;
    if (changed) {
      delete S.intra[shard(sec)];
      renderStatus(); renderTape(); renderWei(true); renderMovers(); renderHeat(); renderWatch(); renderNews(); renderHead();
      if (range === "1D") drawChart();
      toast("Prices updated · " + (S.qmeta.last_bar_ist || "") + " IST");
    }
  } catch (e) { /* keep showing the last loaded values */ }
}

/* ---------------- status / tape / breadth ---------------- */
function renderStatus() {
  const open = S.qmeta.market === "open";
  const m = $("#mkt"); m.className = "mkt" + (open ? " open" : "");
  m.querySelector("span").textContent = open ? "NSE OPEN · DELAYED" : "NSE CLOSED";
  $("#st-data").textContent = `NSE EOD ${S.uni.session_date} · LIVE ${S.qmeta.session_date || "--"} ${S.qmeta.last_bar_ist || ""} IST · UPD ${S.qmeta.generated_ist || "--"}`;
  $("#st-cover").textContent = `${S.uni.count.toLocaleString("en-IN")} NSE STOCKS · ${(S.qmeta.covered || 0).toLocaleString("en-IN")} WITH DELAYED LIVE PRICES · SME = NSE END-OF-DAY`;
}
function renderTape() {
  const ix = (S.live.indices || []).filter(r => !r.error);
  const items = ix.map(r => `<span><b>${esc(r.code)}</b>${us(r.value)} <span class="${ud(r.pct)}">${sg(r.pct)}%</span></span>`).join("");
  $("#tape").innerHTML = items + items;
}
function renderBreadth() {
  let a = 0, d = 0, u = 0;
  for (const s of S.uni.stocks) { const x = q(s.s); if (!x || x.pct == null) continue; x.pct > 0 ? a++ : x.pct < 0 ? d++ : u++; }
  const t = a + d + u || 1;
  $("#breadth").innerHTML = `<div class="b-bar"><i style="width:${a / t * 100}%;background:var(--up)"></i><i style="width:${u / t * 100}%;background:var(--dim)"></i><i style="width:${d / t * 100}%;background:var(--down)"></i></div>
    <div class="b-leg"><span class="up">▲ ${a.toLocaleString("en-IN")} advancing</span><span class="dim">${u} flat</span><span class="down">▼ ${d.toLocaleString("en-IN")} declining</span></div>`;
  $("#brd-note").textContent = "ALL NSE STOCKS";
}

/* ---------------- movers ---------------- */
function universeFiltered() {
  return S.uni.stocks.filter(s => (board === "All" || s.board === board) && (!sector || s.ind === sector));
}
function renderMovers() {
  const rows = universeFiltered().map(s => ({ s, x: q(s.s) })).filter(r => r.x && r.x.p != null);
  let list;
  if (movMode === "gain") list = rows.filter(r => r.x.pct != null && r.s.v > 0).sort((a, b) => b.x.pct - a.x.pct);
  else if (movMode === "lose") list = rows.filter(r => r.x.pct != null && r.s.v > 0).sort((a, b) => a.x.pct - b.x.pct);
  else if (movMode === "val") list = rows.map(r => ({ ...r, val: (r.x.v || 0) * r.x.p })).sort((a, b) => b.val - a.val);
  else if (movMode === "hi") list = rows.filter(r => r.s.hi52 && r.x.h >= r.s.hi52 * 0.999).sort((a, b) => b.x.pct - a.x.pct);
  else list = rows.filter(r => r.s.lo52 && r.x.l <= r.s.lo52 * 1.001).sort((a, b) => a.x.pct - b.x.pct);
  list = list.slice(0, 60);
  const mx = Math.max(...list.map(r => Math.abs(r.x.pct || 0)), 1);
  $("#movers").innerHTML = list.length ? list.map(r => `<div class="row ${r.s.s === sec ? "sel" : ""}" data-s="${esc(r.s.s)}">
      <span class="sy">${esc(r.s.s)}${r.s.board === "SME" ? '<span class="tag">SME</span>' : ""}</span><span class="px num">${inr(r.x.p)}</span>
      <span class="nm">${esc(r.s.n)}</span><span class="pc num ${ud(r.x.pct)}">${movMode === "val" ? big(r.val) : sg(r.x.pct) + "%"}</span>
      <i class="bar" style="width:${Math.abs(r.x.pct || 0) / mx * 100}%;background:${r.x.pct >= 0 ? "var(--up)" : "var(--down)"};opacity:.35"></i></div>`).join("")
    : `<div class="empty">No stocks match${sector ? " in " + esc(sector) : ""}.</div>`;
  $$("#movers .row").forEach(el => el.onclick = () => openSec(el.dataset.s));
}
$$("#mov-tabs button").forEach(b => b.onclick = () => { movMode = b.dataset.m; $$("#mov-tabs button").forEach(x => x.classList.toggle("on", x === b)); renderMovers(); });
$$("#board-seg button").forEach(b => b.onclick = () => { board = b.dataset.b; $$("#board-seg button").forEach(x => x.classList.toggle("on", x === b)); renderMovers(); });

/* ---------------- sector heatmap (NIFTY 500 industries) ---------------- */
function renderHeat() {
  const g = {};
  for (const s of S.uni.stocks) {
    if (!s.ind) continue;
    const x = q(s.s); if (!x || x.pct == null) continue;
    (g[s.ind] = g[s.ind] || []).push(x.pct);
  }
  const tiles = Object.entries(g).map(([k, v]) => ({ k, n: v.length, avg: v.reduce((a, b) => a + b, 0) / v.length, up: v.filter(x => x > 0).length }))
    .sort((a, b) => b.avg - a.avg);
  $("#heat").innerHTML = tiles.map(t => {
    const a = Math.min(1, Math.abs(t.avg) / 2.5), col = t.avg >= 0 ? `rgba(0,255,0,${0.08 + a * 0.42})` : `rgba(224,160,96,${0.1 + a * 0.5})`;
    return `<button class="${sector === t.k ? "on" : ""}" style="background:${col}" data-k="${esc(t.k)}" title="${esc(t.k)}: ${t.up} of ${t.n} up. Click to filter movers.">
      <span>${esc(t.k)}</span><b class="${t.avg >= 0 ? "up" : "down"}" style="color:${t.avg >= 0 ? "#bfffbf" : "#ffd9b0"}">${sg(t.avg)}%</b></button>`;
  }).join("") || '<div class="empty">No sector data.</div>';
  $$("#heat button").forEach(b => b.onclick = () => { sector = sector === b.dataset.k ? null : b.dataset.k; renderHeat(); renderMovers(); toast(sector ? "Movers: " + sector : "Movers: all sectors"); });
}

/* ---------------- watchlist (saved in this browser) ---------------- */
const WL_KEY = "blab-watch";
function loadWatch() {
  try { const w = JSON.parse(localStorage.getItem(WL_KEY)); if (Array.isArray(w) && w.length) return w.filter(s => S.map.has(s)); } catch (e) {}
  return (S.screen.picks || []).map(p => p.symbol).filter(s => S.map.has(s));
}
function saveWatch(w) { try { localStorage.setItem(WL_KEY, JSON.stringify(w)); } catch (e) {} }
function spark(sym) {
  const rows = (S.intra[shard(sym)] || {})[sym] || ((S.hist[shard(sym)] || {})[sym] || []).slice(-30);
  const v = rows.map(r => r[4]).filter(x => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), W = 64, H = 22;
  const d = v.map((x, i) => `${i ? "L" : "M"}${(i / (v.length - 1) * W).toFixed(1)} ${(H - 2 - (x - lo) / ((hi - lo) || 1) * (H - 4)).toFixed(1)}`).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${d}" fill="none" stroke="${v[v.length - 1] >= v[0] ? C.up : C.down}" stroke-width="1.2"/></svg>`;
}
function renderWatch() {
  const w = loadWatch();
  $("#watch").innerHTML = w.length ? w.map(sym => {
    const s = S.map.get(sym), x = q(sym);
    return `<div class="row w ${sym === sec ? "sel" : ""}" data-s="${esc(sym)}"><span class="sy">${esc(sym)}</span>${spark(sym)}<span class="px num">${inr(x?.p)}</span>
      <span class="nm">${esc(s.n)}</span><span class="pc num ${ud(x?.pct)}">${sg(x?.pct)}%</span><button class="x" data-rm="${esc(sym)}" title="Remove">×</button></div>`;
  }).join("") : '<div class="empty">Empty. Open a stock and press + ADD.</div>';
  $$("#watch .row").forEach(el => el.onclick = e => {
    if (e.target.dataset.rm) { saveWatch(loadWatch().filter(s => s !== e.target.dataset.rm)); renderWatch(); return; }
    openSec(el.dataset.s);
  });
  // sparklines need the intraday / history groups of the listed stocks
  const need = [...new Set(w.map(shard))].filter(k => !S.intra[k] && !S.hist[k]);
  if (need.length && !renderWatch.loading) {
    renderWatch.loading = true;
    Promise.all(need.map(k => loadIntra(k).catch(() => loadHist(k)))).finally(() => { renderWatch.loading = false; renderWatch(); });
  }
}
$("#wl-add").onclick = () => { const w = loadWatch(); if (!w.includes(sec)) { w.unshift(sec); saveWatch(w.slice(0, 40)); renderWatch(); toast(sec + " added to watchlist"); } };

/* ---------------- WEI / news ---------------- */
function renderWei(flash) {
  const rows = S.live.indices || [], tb = $("#wei tbody");
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="5" class="empty">Index data not available.</td></tr>'; return; }
  let html = "", rg = null;
  for (const r of rows) {
    if (r.region !== rg) { rg = r.region; html += `<tr class="rg"><td colspan="5">${esc(rg.toUpperCase())}</td></tr>`; }
    if (r.error) { html += `<tr><td class="code">${esc(r.code)}</td><td class="r dim" colspan="4">N/A</td></tr>`; continue; }
    const p = S.prevWei[r.code], fl = flash && p != null && p !== r.value ? (r.value > p ? "flash-up" : "flash-down") : "";
    html += `<tr title="${esc(r.name)} · ${esc(r.time)}"><td class="code">${esc(r.code)}<small>${esc(r.time)}</small></td><td class="r num ${fl}">${us(r.value)}</td>
      <td class="r num ${ud(r.net)}">${sg(r.net)}</td><td class="r num ${ud(r.pct)}">${sg(r.pct)}%</td><td class="r num ${ud(r.ytd)}">${r.ytd == null ? "--" : sg(r.ytd, 1) + "%"}</td></tr>`;
  }
  rows.forEach(r => { if (!r.error) S.prevWei[r.code] = r.value; });
  tb.innerHTML = html;
  $("#wei-asof").textContent = S.live.generated_ist ? "UPD " + S.live.generated_ist.replace(/^.*?, /, "") : "";
}
function newsTime(iso) {
  const d = new Date(iso), same = d.toLocaleDateString("en-CA", { timeZone: IST }) === new Date().toLocaleDateString("en-CA", { timeZone: IST });
  return same ? d.toLocaleTimeString("en-GB", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false }) : d.toLocaleDateString("en-GB", { timeZone: IST, day: "2-digit", month: "short" });
}
function renderNews() {
  const items = [...(S.live.news || [])].sort((a, b) => ((b.tickers || []).includes(sec)) - ((a.tickers || []).includes(sec)));
  $("#news").innerHTML = items.length ? items.map(n => `<li class="${(n.tickers || []).includes(sec) ? "hit" : ""}"><time>${newsTime(n.time_utc)}</time><span>
      ${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}
      <span class="src"> · ${esc(n.publisher || "")}</span> <span class="tk">${(n.tickers || []).map(esc).join(" ")}</span></span></li>`).join("")
    : '<li class="empty">No headlines available.</li>';
}

/* ---------------- security ---------------- */
async function loadHist(k) { if (!S.hist[k]) S.hist[k] = await getJSON(`t/h/${k}.json`, false); return S.hist[k]; }
async function loadIntra(k) { if (!S.intra[k]) S.intra[k] = await getJSON(`t/i/${k}.json`); return S.intra[k]; }

async function openSec(sym) {
  if (!S.map.has(sym)) return;
  sec = sym;
  history.replaceState(null, "", "#s=" + encodeURIComponent(sym));
  $$("#movers .row, #watch .row").forEach(r => r.classList.toggle("sel", r.dataset.s === sym));
  renderHead(); renderNews();
  const k = shard(sym);
  await Promise.all([loadHist(k).catch(() => null), loadIntra(k).catch(() => null)]);
  if (sym !== sec) return;
  const hasIntra = !!((S.intra[k] || {})[sym] || []).length;
  $('#range-seg [data-r="1D"]').disabled = !hasIntra;
  if (range === "1D" && !hasIntra) setRange("1Y");
  drawChart(); renderDetail();
}

function renderHead() {
  const s = S.map.get(sec), x = q(sec);
  if (!s || !x) return;
  const open = S.qmeta.market === "open";
  const tag = x.live ? `<span class="tag live">${open ? "DELAYED LIVE" : "LAST SESSION"} ${esc(x.t)} IST</span>` : `<span class="tag eod">NSE EOD ${esc(x.d)}</span>`;
  $("#sec-head").innerHTML = `
    <div class="sh-id"><div class="sym">${esc(sec)} <span class="tag">NSE</span><span class="tag">${esc(s.series)}</span>${s.board === "SME" ? '<span class="tag">SME</span>' : ""}${s.etf ? '<span class="tag">ETF</span>' : ""}${s.n500 ? '<span class="tag">NIFTY 500</span>' : ""}</div>
      <div class="nm">${esc(s.n)}${s.ind ? " · " + esc(s.ind) : ""}</div></div>
    <div class="sh-px"><div class="p num ${ud(x.chg)}">₹${inr(x.p)}</div><div class="c num ${ud(x.chg)}">${sg(x.chg)} (${sg(x.pct)}%) ${tag}</div></div>
    <div class="sh-r"><button class="btn" id="add-wl">+ WATCH</button></div>`;
  $("#add-wl").onclick = () => $("#wl-add").click();
  const rngBar = (lo, hi, v) => (lo == null || hi == null || hi <= lo) ? "" : `<div class="rng"><em style="left:0;width:${Math.min(100, (v - lo) / (hi - lo) * 100)}%"></em><i style="left:calc(${Math.min(100, Math.max(0, (v - lo) / (hi - lo) * 100))}% - 1px)"></i></div>`;
  const volx = s.avgv20 ? x.v / s.avgv20 : null;
  const dp = x.p >= 1000 ? 0 : x.p >= 100 ? 1 : 2;       // ranges fit their cell
  $("#sec-stats").innerHTML = `
    <div><span>Open</span><b class="num">${inr(x.o)}</b></div>
    <div><span>Prev close</span><b class="num">${inr(x.pc)}</b></div>
    <div><span>Day range</span><b class="num">${inr(x.l, dp)} – ${inr(x.h, dp)}</b>${rngBar(x.l, x.h, x.p)}</div>
    <div><span>52-wk range</span><b class="num">${inr(s.lo52, dp)} – ${inr(s.hi52, dp)}</b>${rngBar(s.lo52, s.hi52, x.p)}</div>
    <div><span>Volume</span><b class="num">${big(x.v)}</b>${volx ? ` <small class="${volx >= 1.5 ? "up" : "dim"}">${volx.toFixed(1)}× avg</small>` : ""}</div>
    <div><span>Value</span><b class="num">${x.v != null ? cr(x.v * x.p / 1e7) : "--"}</b></div>
    <div><span>Delivery (EOD)</span><b class="num">${s.deliv == null ? "--" : s.deliv.toFixed(1) + "%"}</b></div>
    <div><span>1-yr return</span><b class="num ${ud(s.r1y)}">${s.r1y == null ? "--" : sg(s.r1y, 1) + "%"}</b></div>`;
}

/* ---------------- chart (Lightweight Charts) ---------------- */
let chart = null, sMain = null, sVol = null, s20 = null, s50 = null;
function makeChart() {
  const LC = window.LightweightCharts;
  if (!LC) { $("#chart-msg").textContent = "Chart library could not load (check your connection)."; $("#chart-msg").classList.add("show"); return false; }
  if (chart) { chart.remove(); chart = null; }
  chart = LC.createChart($("#chart"), {
    autoSize: true,
    layout: { background: { type: "solid", color: C.bg }, textColor: C.dim, fontFamily: "Consolas, 'Courier New', monospace", fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: "rgba(181,166,130,0.07)" }, horzLines: { color: "rgba(181,166,130,0.07)" } },
    rightPriceScale: { borderColor: "rgba(181,166,130,0.35)", scaleMargins: { top: 0.08, bottom: ind.vol ? 0.22 : 0.05 } },
    timeScale: { borderColor: "rgba(181,166,130,0.35)", timeVisible: range === "1D", secondsVisible: false, rightOffset: 3 },
    crosshair: { mode: 0, vertLine: { color: "rgba(232,220,195,0.45)", labelBackgroundColor: "#0f3020" }, horzLine: { color: "rgba(232,220,195,0.45)", labelBackgroundColor: "#0f3020" } },
    localization: { priceFormatter: p => inr(p) },
  });
  if (ctype === "candle") sMain = chart.addSeries(LC.CandlestickSeries, { upColor: "rgba(0,255,0,0.85)", downColor: C.down, borderUpColor: C.up, borderDownColor: C.down, wickUpColor: C.up, wickDownColor: C.down, priceLineColor: C.txt });
  else if (ctype === "line") sMain = chart.addSeries(LC.LineSeries, { color: C.up, lineWidth: 2, priceLineColor: C.txt });
  else sMain = chart.addSeries(LC.AreaSeries, { lineColor: C.up, topColor: "rgba(0,255,0,0.28)", bottomColor: "rgba(0,255,0,0.02)", lineWidth: 2, priceLineColor: C.txt });
  sVol = ind.vol ? chart.addSeries(LC.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false }) : null;
  if (sVol) chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  const line = c => chart.addSeries(LC.LineSeries, { color: c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  s20 = ind.sma20 && range !== "1D" ? line(C.sma20) : null;
  s50 = ind.sma50 && range !== "1D" ? line(C.sma50) : null;
  chart.subscribeCrosshairMove(p => legend(p));
  return true;
}
function sma(rows, n) {
  const out = []; let sum = 0;
  rows.forEach((r, i) => { sum += r[4]; if (i >= n) sum -= rows[i - n][4]; if (i >= n - 1) out.push({ time: r[0], value: +(sum / n).toFixed(2) }); });
  return out;
}
let lastBars = [];
function drawChart() {
  const msg = $("#chart-msg"); msg.classList.remove("show");
  const k = shard(sec);
  let rows, times;
  if (range === "1D") {
    rows = (S.intra[k] || {})[sec] || [];
    const day = (S.quotes[sec] || {}).d || S.qmeta.session_date;
    const [y, m, d] = (day || "1970-01-01").split("-").map(Number);
    times = rows.map(r => { const [hh, mm] = r[0].split(":").map(Number); return Date.UTC(y, m - 1, d, hh, mm) / 1000; });
  } else {
    const all = (S.hist[k] || {})[sec] || [];
    const n = { "1M": 22, "3M": 64, "6M": 127, "1Y": 260 }[range];
    rows = all.slice(-n - 60);                                 // extra bars so the averages start on screen
    times = rows.map(r => r[0]);
    // today's live candle on top of NSE's daily history
    const x = q(sec);
    if (x && x.live && rows.length && x.d > rows[rows.length - 1][0] && x.o != null) { rows = [...rows, [x.d, x.o, x.h, x.l, x.p, x.v]]; times.push(x.d); }
  }
  if (!rows.length) { if (chart) { chart.remove(); chart = null; } msg.textContent = range === "1D" ? "No intraday data for this stock (SME stocks have NSE end-of-day data only)." : "No price history available."; msg.classList.add("show"); lastBars = []; legend(); return; }
  if (!makeChart()) return;
  const data = rows.map((r, i) => ctype === "candle" ? { time: times[i], open: r[1], high: r[2], low: r[3], close: r[4] } : { time: times[i], value: r[4] });
  sMain.setData(data);
  if (sVol) sVol.setData(rows.map((r, i) => ({ time: times[i], value: r[5] || 0, color: r[4] >= r[1] ? "rgba(0,255,0,0.28)" : "rgba(224,160,96,0.35)" })));
  if (s20) s20.setData(sma(rows, 20));
  if (s50) s50.setData(sma(rows, 50));
  lastBars = rows.map((r, i) => ({ t: times[i], r }));
  const visible = range === "1D" ? rows.length : { "1M": 22, "3M": 64, "6M": 127, "1Y": 260 }[range];
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, rows.length - visible), to: rows.length + 2 });
  legend();
}
function legend(p) {
  let r;
  if (p && p.time != null) { const f = lastBars.find(b => b.t === p.time); r = f && f.r; }
  if (!r && lastBars.length) r = lastBars[lastBars.length - 1].r;
  const sess = range === "1D" ? (S.qmeta.market === "open" ? '<span class="up">TODAY</span> ' : `<span class="down">LAST SESSION ${esc((S.quotes[sec] || {}).d || "")}</span> `) : "";
  $("#legend").innerHTML = r ? `${sess}<span>${esc(r[0])}</span> O <b>${inr(r[1])}</b> H <b>${inr(r[2])}</b> L <b>${inr(r[3])}</b> C <b class="${ud(r[4] - r[1])}">${inr(r[4])}</b> V <b>${big(r[5])}</b>` : "";
}
function setRange(r) { range = r; $$("#range-seg button").forEach(b => b.classList.toggle("on", b.dataset.r === r)); }
$$("#range-seg button").forEach(b => b.onclick = () => { if (b.disabled) return; setRange(b.dataset.r); drawChart(); });
$$("#type-seg button").forEach(b => b.onclick = () => { ctype = b.dataset.t; $$("#type-seg button").forEach(x => x.classList.toggle("on", x === b)); drawChart(); });
$$("#ind-seg button").forEach(b => b.onclick = () => { ind[b.dataset.i] = !ind[b.dataset.i]; b.classList.toggle("on", ind[b.dataset.i]); drawChart(); });

/* ---------------- detail tabs ---------------- */
const REC = { strong_buy: "STRONG BUY", buy: "BUY", hold: "HOLD", underperform: "UNDERPERFORM", sell: "SELL" };
const kv = (a, b, c = "") => `<div><span>${a}</span><b class="num ${c}">${b}</b></div>`;
function renderDetail() {
  const box = $("#detail"), s = S.map.get(sec), x = q(sec);
  if (!s) return;
  const f = S.fund ? (S.fund[sec] || null) : undefined;       // undefined = still loading, null = not covered
  if (detTab === "DES") {
    const pick = (S.screen.picks || []).find(p => p.symbol === sec);
    box.innerHTML = `
      <div class="h3">Listing</div>
      <div class="kv">${kv("Symbol", esc(sec))}${kv("ISIN", esc(s.isin || "--"))}${kv("Series", esc(s.series))}${kv("Board", esc(s.board))}
        ${kv("Listed", esc(s.listed || "--"))}${kv("Industry", esc(s.ind || f?.industry || "--"))}${kv("Trades (EOD)", s.trades ? s.trades.toLocaleString("en-IN") : "--")}${kv("Avg vol 20d", big(s.avgv20))}</div>
      ${pick ? `<div class="h3">B-Lab screen</div><div class="kv">${kv("Magic rank", "#" + pick.magic_rank + " / " + pick.of, "up")}${kv("F-Score", pick.fscore + "/9")}${kv("Return on cap", pctF(pick.roc))}${kv("Earnings yield", pctF(pick.earnings_yield))}</div>` : ""}
      <div class="h3">Company</div>
      ${f === undefined ? '<p class="note">Loading…</p>' : f ? `<p class="desc">${esc(f.desc || "No description available.")}</p>
        <p class="note" style="margin-top:8px">${[f.sector, f.city, f.emp ? Math.round(f.emp).toLocaleString("en-IN") + " employees" : null, f.web].filter(Boolean).map(esc).join(" · ")}</p>`
        : `<p class="note">${s.etf ? `${esc(sec)} is an exchange-traded fund (ETF), not a company.` : `Company profile and fundamentals are loaded for NIFTY 500 companies. ${esc(sec)} is outside the NIFTY 500`}, so only NSE's official trading data is shown. Nothing is estimated.</p>`}`;
  } else if (detTab === "FA") {
    if (f === undefined) { box.innerHTML = '<p class="note">Loading…</p>'; return; }
    if (!f) { box.innerHTML = `<p class="note">Fundamentals are loaded for NIFTY 500 companies only. ${esc(sec)} is outside the NIFTY 500. Nothing is estimated.</p>`; return; }
    const up = f.tgt && x ? (f.tgt / x.p - 1) * 100 : null;
    const lo = Math.min(f.tgt_lo ?? f.tgt ?? x.p, x.p), hi = Math.max(f.tgt_hi ?? f.tgt ?? x.p, x.p), pos = v => ((v - lo) / ((hi - lo) || 1) * 100).toFixed(1) + "%";
    box.innerHTML = `
      <div class="h3">Valuation</div>
      <div class="kv">${kv("Market cap", f.mcap ? cr(f.mcap / 1e7) : "--")}${kv("Enterprise value", f.ev ? cr(f.ev / 1e7) : "--")}${kv("P/E (TTM)", f.pe ? f.pe.toFixed(1) : "--")}${kv("Forward P/E", f.fpe ? f.fpe.toFixed(1) : "--")}
        ${kv("P/B", f.pb ? f.pb.toFixed(2) : "--")}${kv("EPS (TTM)", f.eps != null ? "₹" + inr(f.eps) : "--")}${kv("Dividend yield", f.dy != null ? f.dy.toFixed(2) + "%" : "--")}${kv("Beta", f.beta != null ? f.beta.toFixed(2) : "--")}</div>
      <div class="h3">Profitability & growth</div>
      <div class="kv">${kv("ROE", pctF(f.roe))}${kv("ROA", pctF(f.roa))}${kv("Profit margin", pctF(f.pm))}${kv("Operating margin", pctF(f.om))}
        ${kv("Revenue (TTM)", f.rev ? cr(f.rev / 1e7) : "--")}${kv("Revenue growth", pctF(f.revg), ud(f.revg))}${kv("Earnings growth", pctF(f.eg), ud(f.eg))}${kv("Debt / equity", f.de != null ? (f.de / 100).toFixed(2) : "--")}</div>
      <div class="h3">Ownership & analysts</div>
      <div class="kv">${kv("Institutions", pctF(f.inst))}${kv("Promoters / insiders", pctF(f.ins))}${kv("Analysts", f.an ?? "--")}${kv("Consensus", f.rec ? REC[f.rec] || f.rec.toUpperCase() : "--", f.rec && /buy/.test(f.rec) ? "up" : "")}</div>
      ${f.tgt ? `<div class="tgt"><div class="ln" style="left:${pos(f.tgt_lo ?? f.tgt)};right:calc(100% - ${pos(f.tgt_hi ?? f.tgt)})"></div>
        <div class="mk" style="left:${pos(f.tgt)};background:var(--up)"></div><div class="now" style="left:${pos(x.p)}" title="Price now"></div></div>
        <div class="tgt-l"><span>LOW ₹${inr(f.tgt_lo, 0)}</span><span class="up">MEAN ₹${inr(f.tgt, 0)} (${sg(up, 1)}%)</span><span>HIGH ₹${inr(f.tgt_hi, 0)}</span></div>
        <p class="note" style="margin-top:6px">Square = price now. 12-month analyst targets; on average analysts are too optimistic.</p>` : ""}
      <p class="note" style="margin-top:10px">Source: Yahoo Finance, updated daily${S.fund ? "" : ""}.</p>`;
  } else if (detTab === "PERF") {
    const keys = [["1 month", "r1m"], ["3 months", "r3m"], ["6 months", "r6m"], ["1 year", "r1y"]];
    const med = k => { const v = S.uni.stocks.map(s => s[k]).filter(v => v != null).sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : null; };
    const rank = (k, v) => { if (v == null) return null; const all = S.uni.stocks.map(s => s[k]).filter(x => x != null); return Math.round(all.filter(x => x <= v).length / all.length * 100); };
    const mx = Math.max(...keys.map(([, k]) => Math.abs(s[k] || 0)), 10);
    box.innerHTML = `<div class="h3">Returns (NSE closing prices)</div><div class="perf">${keys.map(([lbl, k]) => {
      const v = s[k], w = v == null ? 0 : Math.min(50, Math.abs(v) / mx * 50), m = med(k), rk = rank(k, v);
      return `<span class="dim">${lbl}</span><div class="pbar"><i style="${v >= 0 ? `left:50%;width:${w}%` : `left:${50 - w}%;width:${w}%`};background:${v >= 0 ? "var(--up)" : "var(--down)"}"></i></div>
        <b class="num ${ud(v)}" style="font-weight:400">${v == null ? "--" : sg(v, 1) + "%"}</b><span class="dim">${rk == null ? "" : `beats ${rk}% of NSE · median ${sg(m, 1)}%`}</span>`;
    }).join("")}</div><p class="note" style="margin-top:10px">Compared with all ${S.uni.count.toLocaleString("en-IN")} NSE stocks over the same period. Past returns don't predict future returns.</p>`;
  } else {
    const rows = (S.intra[shard(sec)] || {})[sec] || [];
    if (!rows.length) { box.innerHTML = '<p class="note">No intraday prints for this stock (SME stocks have NSE end-of-day data only).</p>'; return; }
    const pc = q(sec)?.pc;
    box.innerHTML = `<table class="qr"><thead><tr><th>Time (IST)</th><th>Last</th><th>Chg</th><th>High</th><th>Low</th><th>Volume</th></tr></thead><tbody>${
      rows.map((r, i) => { const prev = i ? rows[i - 1][4] : pc, ch = prev != null ? r[4] - prev : null;
        return `<tr><td class="dim">${esc(r[0])}</td><td class="num ${ud(ch)}">${inr(r[4])}</td><td class="num ${ud(ch)}">${ch == null ? "--" : (ch > 0 ? "▲" : ch < 0 ? "▼" : "=") + inr(Math.abs(ch))}</td>
          <td class="num">${inr(r[2])}</td><td class="num">${inr(r[3])}</td><td class="num dim">${big(r[5])}</td></tr>`; }).reverse().join("")}</tbody></table>`;
  }
}
$$("#det-tabs button").forEach(b => b.onclick = () => { detTab = b.dataset.d; $$("#det-tabs button").forEach(x => x.classList.toggle("on", x === b)); renderDetail(); });

/* ---------------- command line / search ---------------- */
const FUNCS = { DES: "Security description", FA: "Fundamentals", PERF: "Returns", QR: "Intraday prints", GP: "Graph price",
  MOV: "NSE movers", MAP: "Sector heatmap", WEI: "World indices", TOP: "Top news", WL: "Watchlist", HELP: "Help", BACK: "Back to B-Lab", LOGOFF: "Sign out" };
const input = $("#cli"), sug = $("#suggest");
let opts = [], act = -1;
function search(qs) {
  const Q = qs.trim().toUpperCase(); if (!Q) return [];
  const toks = Q.split(/\s+/), head = toks[0];
  const fnOnly = Object.keys(FUNCS).filter(f => f.startsWith(head) && toks.length === 1).map(f => ({ kind: "fn", code: f, label: FUNCS[f] }));
  const scored = [];
  const words = toks.filter(t => !FUNCS[t] || toks.length === 1);
  const joined = words.join("");
  for (const s of S.uni.stocks) {
    const sym = s.s, nm = s.n.toUpperCase(), nw = nm.split(/[^A-Z0-9&]+/);
    // every typed word must start a word of the company name, or the whole query must match the symbol
    const nameHit = words.every(t => nw.some(w => w.startsWith(t)));
    let sc = sym === joined ? 0 : sym.startsWith(joined) ? 1 : nameHit && nm.startsWith(words[0]) ? 2 : nameHit ? 3 : sym.includes(joined) ? 4 : -1;
    if (sc >= 0) scored.push([sc, -((s.v || 0) * (s.c || 0)), s]);     // ties: most traded first
  }
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const fn = toks.slice(1).find(t => FUNCS[t]);
  return [...fnOnly, ...scored.slice(0, 12).map(([, , s]) => ({ kind: "sec", code: s.s, label: s.n, s, fn }))];
}
function showSug() {
  opts = search(input.value); act = opts.length ? 0 : -1;
  if (!opts.length) { sug.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
  let html = "", lastKind = null;
  opts.forEach((o, i) => {
    if (o.kind !== lastKind) { html += `<li class="grp" aria-hidden="true">${o.kind === "fn" ? "FUNCTIONS" : "NSE SECURITIES · " + S.uni.count.toLocaleString("en-IN")}</li>`; lastKind = o.kind; }
    if (o.kind === "fn") html += `<li role="option" data-i="${i}" aria-selected="${i === act}"><span class="s1">${o.code} &lt;GO&gt;</span><span class="s2">${esc(o.label)}</span><span></span><span></span></li>`;
    else { const x = q(o.code); html += `<li role="option" data-i="${i}" aria-selected="${i === act}"><span class="s1">${esc(o.code)} IN</span><span class="s2">${esc(o.label)}</span><span class="s3">${o.s.board}${o.fn ? " · " + o.fn : ""}</span><span class="num ${ud(x?.pct)}">${inr(x?.p)} ${sg(x?.pct)}%</span></li>`; }
  });
  sug.innerHTML = html; sug.hidden = false; input.setAttribute("aria-expanded", "true");
}
function paint() { $$("#suggest li[role=option]").forEach(li => li.setAttribute("aria-selected", +li.dataset.i === act)); $$("#suggest li[aria-selected=true]")[0]?.scrollIntoView({ block: "nearest" }); }
function focusPanel(id) { $$(".panel").forEach(p => p.classList.toggle("focus", p.id === id)); const el = document.getElementById(id); el?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
function runFn(f) {
  if (f === "BACK") { location.href = "advanced.html#signals"; return; }
  if (f === "LOGOFF") { $("#logout").click(); return; }
  if (f === "HELP") { toast("Type a symbol or company name. Functions: DES FA PERF QR GP MOV MAP WEI TOP WL BACK"); return; }
  if (["DES", "FA", "PERF", "QR"].includes(f)) { $(`#det-tabs [data-d="${f}"]`).click(); focusPanel("p-DES"); return; }
  focusPanel({ GP: "p-GP", MOV: "p-MOV", MAP: "p-MAP", WEI: "p-WEI", TOP: "p-TOP", WL: "p-WL" }[f]);
}
function choose(o) {
  input.value = ""; sug.hidden = true; input.blur();
  if (o.kind === "fn") runFn(o.code); else { openSec(o.code); if (o.fn) runFn(o.fn); }
}
input.addEventListener("input", showSug);
input.addEventListener("keydown", e => {
  if (e.key === "ArrowDown" && opts.length) { act = (act + 1) % opts.length; paint(); e.preventDefault(); }
  else if (e.key === "ArrowUp" && opts.length) { act = (act - 1 + opts.length) % opts.length; paint(); e.preventDefault(); }
  else if (e.key === "Tab" && opts.length) { input.value = opts[act].code + (opts[act].kind === "sec" ? " " : ""); showSug(); e.preventDefault(); }
  else if (e.key === "Enter") { e.preventDefault(); if (act >= 0 && opts[act]) choose(opts[act]); else if (FUNCS[input.value.trim().toUpperCase()]) choose({ kind: "fn", code: input.value.trim().toUpperCase() }); else toast("No match. Type HELP <GO>."); }
});
sug.addEventListener("mousedown", e => { const li = e.target.closest("li[role=option]"); if (li) { e.preventDefault(); choose(opts[+li.dataset.i]); } });
input.addEventListener("blur", () => setTimeout(() => { sug.hidden = true; }, 120));
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { if (!sug.hidden) { sug.hidden = true; return; } if (input.value) { input.value = ""; return; } location.href = "advanced.html#signals"; return; }
  if (document.activeElement === input) return;
  if (e.key === "/") { e.preventDefault(); input.focus(); return; }
  if (e.key.length === 1 && /[a-z0-9]/i.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) input.focus();
});

boot();
