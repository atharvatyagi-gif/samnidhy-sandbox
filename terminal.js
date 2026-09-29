/* B-LAB DESK (expert-terminal.html). Editorial desk layout (reference: inteldesk.app) in Samnidhy green + beige.
   Real data only:
   t/universe.json  all ~3,500 NSE securities (NSE end-of-day)       t/quotes.json   delayed live prices (~15 min)
   t/h/<k>.json     1 year of NSE daily candles (on demand)           t/i/<k>.json    intraday {d: 5-min latest session, w: 15-min 5 sessions}
   t/fund.json      NIFTY 500 fundamentals                            live.json       world indices, markets, headlines
   screener.json    today's B-Lab screen                              institutional.json  NSE FII/DII history
   Nothing is simulated: values change only when fresh data arrives. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const IST = "Asia/Kolkata";
const POLL_MS = 60000;
const COL = { up: "#00e060", upFill: "rgba(0,224,96,0.9)", down: "#e0a060", ink: "#e8dcc3", ink3: "#83795f", card: "#061a10", acc: "#00e060" };  // dark chart workspace (old terminal palette)
const LS = { get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };

const S = { uni: null, map: new Map(), quotes: {}, qmeta: {}, fund: null, live: {}, screen: {}, inst: {}, hist: {}, intra: {}, prevWei: {} };
let sec = null, iv = "D", rg = "1Y", ct = LS.get("blab-ct", "candle"), scaleMode = "auto", view = "brief", side = "details";
let movMode = "gain", board = "All", sector = "", movSort = null, movLimit = 50, movQuery = "", heatSel = null, newsFilter = "all";
let tool = "cross", magnet = LS.get("blab-magnet", false), hideDraw = false, pending = null;

/* ---------------- indicators ---------------- */
const INDS = [
  { id: "vol", name: "Volume", group: "Main", color: "#83795f", def: true },
  { id: "sma20", name: "SMA 20", group: "Moving averages", color: "#e8dcc3", def: true },
  { id: "sma50", name: "SMA 50", group: "Moving averages", color: "#b5a682", def: true },
  { id: "sma200", name: "SMA 200", group: "Moving averages", color: "#6fae7f" },
  { id: "ema20", name: "EMA 20", group: "Moving averages", color: "#4fd1c5" },
  { id: "bb", name: "Bollinger Bands (20, 2)", group: "Bands", color: "#a78bfa" },
  { id: "vwap", name: "VWAP (intraday)", group: "Bands", color: "#f0c674" },
  { id: "rsi", name: "RSI (14)", group: "Oscillators · own pane", color: "#4fd1c5" },
  { id: "macd", name: "MACD (12, 26, 9)", group: "Oscillators · own pane", color: "#e8dcc3" },
];
let inds = new Set(LS.get("blab-inds", INDS.filter(i => i.def).map(i => i.id)));

/* ---------------- formatting ---------------- */
const inr = (v, d = 2) => v == null || isNaN(v) ? "--" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const us = (v, d = 2) => v == null ? "--" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const sg = (v, d = 2) => v == null || isNaN(v) ? "--" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
const ud = v => v == null || v === 0 ? "flat" : v > 0 ? "up" : "down";
const big = v => v == null ? "--" : v >= 1e7 ? (v / 1e7).toFixed(2) + " Cr" : v >= 1e5 ? (v / 1e5).toFixed(2) + " L" : Math.round(v).toLocaleString("en-IN");
const cr = v => v == null ? "--" : "₹" + Math.round(v).toLocaleString("en-IN") + " Cr";
const crS = v => v == null ? "--" : (v >= 0 ? "+" : "−") + "₹" + Math.abs(Math.round(v)).toLocaleString("en-IN") + " Cr";
const pctF = (v, d = 1) => v == null ? "--" : (v * 100).toFixed(d) + "%";
const shard = s => /[A-Z]/i.test(s[0]) ? s[0].toUpperCase() : "0";
const dp = p => p >= 1000 ? 1 : 2;
const dt = (s, o) => s ? new Date(s + "T00:00:00").toLocaleDateString("en-IN", o || { day: "numeric", month: "short" }) : "--";
function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => el.classList.remove("show"), 2400); }

/* quote: live if fresh, else NSE end-of-day */
function q(sym) {
  const e = S.map.get(sym); if (!e) return null;
  const l = S.quotes[sym];
  if (l && l.d >= e.date) return { live: true, p: l.p, chg: l.chg, pct: l.pct, o: l.o, h: l.h, l: l.l, v: l.v, t: l.t, d: l.d, pc: +(l.p - l.chg).toFixed(2) };
  return { live: false, p: e.c, chg: e.chg, pct: e.pct, o: e.o, h: e.h, l: e.l, v: e.v, t: "EOD", d: e.date, pc: e.pc };
}

/* ---------------- auth ---------------- */
function onReady(user) {
  $("#sys-user").textContent = user.email;
  $("#av").textContent = (user.email || "?")[0].toUpperCase();
}
$("#logout").onclick = async () => { try { await window.__expertSignOut?.(); } finally { location.replace("auth.html"); } };
document.addEventListener("expert-ready", e => { window.__expertSignOut = e.detail.signOut; onReady(e.detail.user); });
if (window.expertUser) onReady(window.expertUser);
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString("en-GB", { timeZone: IST, hour12: false }) + " IST"; }, 1000);

/* ---------------- data ---------------- */
async function getJSON(url, bust = true) {
  const r = await fetch(url + (bust ? "?t=" + Date.now() : ""), { cache: bust ? "no-store" : "default" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}
async function loadHist(k) { if (!S.hist[k]) S.hist[k] = await getJSON(`t/h/${k}.json`, false); return S.hist[k]; }
async function loadIntra(k, force) { if (!S.intra[k] || force) S.intra[k] = await getJSON(`t/i/${k}.json`); return S.intra[k]; }
const intraOf = sym => ((S.intra[shard(sym)] || {})[sym]) || null;
const histOf = sym => ((S.hist[shard(sym)] || {})[sym]) || [];

async function boot() {
  try {
    const [uni, quotes, live, screen, inst] = await Promise.all([getJSON("t/universe.json"), getJSON("t/quotes.json").catch(() => ({})),
      getJSON("live.json").catch(() => ({})), getJSON("screener.json").catch(() => ({})), getJSON("institutional.json").catch(() => ({}))]);
    S.uni = uni; uni.stocks.forEach(s => S.map.set(s.s, s));
    S.quotes = quotes.quotes || {}; S.qmeta = quotes; S.live = live; S.screen = screen; S.inst = inst;
  } catch (e) {
    $("#st-data").textContent = "Data not available: the NSE stock list could not be loaded. Nothing is shown in its place.";
    $("#brief-cards").innerHTML = '<div class="empty">Data not available.</div>'; return;
  }
  const hp = new URLSearchParams(location.hash.slice(1));
  sec = hp.get("s") && S.map.has(hp.get("s")) ? hp.get("s") : (loadWatch()[0] || "RELIANCE");
  $("#search-ph").textContent = `Search ${S.uni.count.toLocaleString("en-IN")} NSE stocks, or press / to jump`;
  fillSectorSelect(); buildIndMenu(); renderAll();
  go(hp.get("v") || (hp.get("s") ? "terminal" : "brief"), true);
  openSec(sec);
  getJSON("t/fund.json", false).then(f => { S.fund = f.stocks || {}; renderDetails(); }).catch(() => { S.fund = {}; renderDetails(); });
  if (!LS.get("blab-onboarded", false)) openOnboard();
  setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
}
function renderAll() { renderMast(); renderTape(); renderRegime(); renderBrief(); renderWatch(); renderMovers(); renderSectors(); renderWorld(); renderNews(); }
async function poll() {
  try {
    const [quotes, live, inst] = await Promise.all([getJSON("t/quotes.json"), getJSON("live.json"), getJSON("institutional.json").catch(() => S.inst)]);
    const changed = quotes.generated_utc !== S.qmeta.generated_utc || live.generated_utc !== S.live.generated_utc;
    S.quotes = quotes.quotes || {}; S.qmeta = quotes; S.live = live; S.inst = inst;
    if (!changed) return;
    await loadIntra(shard(sec), true).catch(() => null);
    renderAll(); renderHead(); renderDetails(); if (side === "prints") renderPrints(); drawChart(true);
    toast("Desk updated · prices as of " + (quotes.last_bar_ist || "") + " IST");
  } catch (e) { /* keep showing the last values */ }
}

/* ================= navigation ================= */
function go(v, quiet) {
  if (!document.getElementById("v-" + v)) v = "brief";
  view = v;
  $$(".view").forEach(el => el.classList.toggle("on", el.id === "v-" + v));
  $(".desk").classList.toggle("on-terminal", v === "terminal");       // dark chart workspace: regime strip folds away
  $$("#tabs [data-go]").forEach(b => b.classList.toggle("on", b.dataset.go === v && !b.dataset.side));
  history.replaceState(null, "", `#v=${v}${sec ? "&s=" + encodeURIComponent(sec) : ""}`);
  if (v === "terminal") requestAnimationFrame(() => { if (chart) chart.timeScale().applyOptions({}); else drawChart(); });
  if (!quiet) $("#v-" + v).scrollTop = 0;
}
document.addEventListener("click", e => {
  const g = e.target.closest("[data-go]");
  if (g) { e.preventDefault(); go(g.dataset.go); if (g.dataset.side) setSide(g.dataset.side); }
});

/* ================= masthead, tape, regime ================= */
function breadthNow() {
  let a = 0, d = 0, u = 0;
  for (const s of S.uni.stocks) { const x = q(s.s); if (!x || x.pct == null) continue; x.pct > 0 ? a++ : x.pct < 0 ? d++ : u++; }
  return { a, d, u };
}
function renderMast() {
  const open = S.qmeta.market === "open", b = breadthNow();
  $("#livechip").classList.toggle("on", open);
  $("#live-txt").textContent = open ? "LIVE · DELAYED" : "MARKET CLOSED";
  $("#ms-stocks").textContent = S.uni.count.toLocaleString("en-IN");
  $("#ms-live").textContent = (S.qmeta.covered || 0).toLocaleString("en-IN");
  $("#ms-ad").textContent = `${b.a.toLocaleString("en-IN")} / ${b.d.toLocaleString("en-IN")}`;
  $("#wl-count").textContent = loadWatch().length;
  $("#st-data").textContent = `Prices ${S.qmeta.session_date || "--"} ${S.qmeta.last_bar_ist || ""} IST · updated ${S.qmeta.generated_ist || "--"} · NSE end-of-day ${S.uni.session_date}`;
  $("#st-cover").textContent = `${S.uni.count.toLocaleString("en-IN")} NSE securities · ${(S.qmeta.covered || 0).toLocaleString("en-IN")} with delayed live prices · SME = NSE end-of-day`;
}
const mk = t => (S.live.markets || []).find(m => m.ticker === t) || null;
const ix = c => (S.live.indices || []).find(r => r.code === c && !r.error) || null;
function renderTape() {
  const chips = [];
  for (const c of ["NIFTY", "SENSEX", "NSEBANK"]) { const r = ix(c); if (r) chips.push([c === "NSEBANK" ? "BANK NIFTY" : c, us(r.value), r.pct]); }
  for (const [t, name, fmt] of [["^INDIAVIX", "INDIA VIX", v => v.toFixed(2)], ["INR=X", "USD/INR", v => "₹" + v.toFixed(2)], ["BZ=F", "BRENT", v => "$" + v.toFixed(2)],
    ["GC=F", "GOLD", v => "$" + us(v, 0)], ["^TNX", "US10Y", v => v.toFixed(2) + "%"]]) { const m = mk(t); if (m && !m.error) chips.push([name, fmt(m.value), m.change_pct]); }
  for (const c of ["SPX", "NKY", "HSI", "DAX"]) { const r = ix(c); if (r) chips.push([c, us(r.value), r.pct]); }
  $("#tape").innerHTML = chips.map(([n, v, p]) => `<button class="chip" data-go="world" title="Open World"><b>${esc(n)}</b><span class="v">${esc(v)}</span><em class="${ud(p)}">${sg(p)}%</em></button>`).join("")
    || '<span class="chip">Market tape not available</span>';
}
function climate() {
  const f = [], nifty = mk("^NSEI"), vix = mk("^INDIAVIX"), br = (S.screen.universe_stats || {}).breadth_above_200dma, days = S.inst.days || [];
  if (nifty && nifty.sma200 != null) f.push({ k: "Nifty trend", ok: nifty.above_200, t: `Nifty ${nifty.above_200 ? "above" : "below"} its 200-day avg (${us(nifty.value, 0)} vs ${us(nifty.sma200, 0)})` });
  if (br != null) f.push({ k: "Breadth", ok: br >= 0.5, t: `${Math.round(br * 100)}% of NIFTY 500 above their 200-day avg` });
  if (vix && vix.value != null) f.push({ k: "VIX", ok: vix.value < 18, t: `India VIX ${vix.value.toFixed(2)} (${vix.value < 13 ? "calm" : vix.value < 18 ? "normal" : vix.value < 25 ? "nervous" : "fearful"})` });
  if (days.length) { const l = days[days.length - 1]; f.push({ k: "FII", ok: l.fii.net_cr > 0, t: `FII ${crS(l.fii.net_cr)} · DII ${crS(l.dii.net_cr)} (${dt(l.date)})` }); }
  const good = f.filter(x => x.ok).length, n = f.length;
  const verdict = !n ? "Unknown" : good === n ? "Supportive" : good >= n - 1 ? "Mostly supportive" : good >= n / 2 ? "Mixed" : "Cautious";
  return { f, good, n, verdict, tone: !n ? "flat" : good >= n - 1 ? "up" : good >= n / 2 ? "flat" : "down" };
}
function renderRegime() {
  const c = climate();
  $("#regime").innerHTML = `<span class="lbl">Market regime · today</span><span class="verdict ${c.tone}">${esc(c.verdict)}</span><span class="mut">${c.good}/${c.n} favourable</span>`
    + c.f.map(x => `<span class="f"><i style="background:${x.ok ? "var(--up)" : "var(--down)"}"></i>${esc(x.t)}</span>`).join("")
    + `<button class="btn-line sm" data-go="world" style="margin-left:auto">Open world →</button>`;
}

/* ================= BRIEF ================= */
function topBy(fn, filter = () => true) {
  let best = null;
  for (const s of S.uni.stocks) { if (!filter(s)) continue; const x = q(s.s); if (!x || x.p == null) continue; const v = fn(s, x); if (v == null) continue; if (!best || v > best.v) best = { s, x, v }; }
  return best;
}
function renderBrief() {
  const b = breadthNow(), c = climate(), vix = mk("^INDIAVIX");
  const liquid = s => s.board === "Main" && !s.etf && (s.avgv20 || 0) * (s.c || 0) > 5e7;     // avoids tiny illiquid spikes
  const gain = topBy((s, x) => x.pct, liquid), lose = topBy((s, x) => -x.pct, liquid), act = topBy((s, x) => (x.v || 0) * x.p, s => !s.etf);
  const secs = sectorStats(), lead = secs[0], lag = secs[secs.length - 1];
  const pick = (S.screen.picks || [])[0], days = S.inst.days || [], fl = days[days.length - 1];
  const wl = loadWatch().map(sym => ({ sym, x: q(sym) })).filter(r => r.x && r.x.pct != null).sort((a, b2) => b2.x.pct - a.x.pct);
  $("#brief-stats").innerHTML = [
    [S.uni.count.toLocaleString("en-IN"), "NSE securities"], [(S.qmeta.covered || 0).toLocaleString("en-IN"), "delayed live prices"],
    ["15m", "refresh cycle, market hours"], [`${b.a.toLocaleString("en-IN")}/${b.d.toLocaleString("en-IN")}`, "advancing / declining"],
    [(S.screen.universe_stats || {}).breadth_above_200dma != null ? Math.round(S.screen.universe_stats.breadth_above_200dma * 100) + "%" : "--", "above 200-day avg"],
    [vix && vix.value != null ? vix.value.toFixed(1) : "--", "India VIX"],
  ].map(([v, l]) => `<div><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
  const card = (cls, lbl, ttl, sub, btn, attrs) => `<button class="bcard ${cls}" ${attrs}><span class="lbl">${esc(lbl)}</span><span class="ttl">${ttl}</span><span class="sub">${sub}</span><span class="go">${esc(btn)} →</span></button>`;
  const cards = [];
  cards.push(card(c.tone === "up" ? "pos" : c.tone === "down" ? "neg" : "neutral", "Market climate", `${esc(c.verdict)}: ${c.good} of ${c.n} conditions favourable`, c.f.map(x => esc(x.t)).join(" · ") || "Market data not available.", "Open world", 'data-go="world"'));
  if (gain) cards.push(card("pos", "Biggest liquid gainer", `${esc(gain.s.s)} <span class="up">${sg(gain.x.pct)}%</span> at ₹${inr(gain.x.p)}`, esc(gain.s.n) + (gain.s.ind ? " · " + esc(gain.s.ind) : ""), "Open chart", `data-open="${esc(gain.s.s)}"`));
  if (lose) cards.push(card("neg", "Biggest liquid loser", `${esc(lose.s.s)} <span class="down">${sg(lose.x.pct)}%</span> at ₹${inr(lose.x.p)}`, esc(lose.s.n) + (lose.s.ind ? " · " + esc(lose.s.ind) : ""), "Open chart", `data-open="${esc(lose.s.s)}"`));
  if (act) cards.push(card("neutral", "Most traded (value)", `${esc(act.s.s)} · ₹${big(act.v)} traded`, `${esc(act.s.n)} · ${sg(act.x.pct)}% today`, "Open chart", `data-open="${esc(act.s.s)}"`));
  if (lead) cards.push(card(lead.avg >= 0 ? "pos" : "neg", "Sectors · NIFTY 500", `${esc(lead.k)} leads (${sg(lead.avg)}%), ${esc(lag.k)} lags (${sg(lag.avg)}%)`, `${secs.filter(s2 => s2.avg > 0).length} of ${secs.length} sectors up on average today.`, "Open sectors", 'data-go="sectors"'));
  if (fl) cards.push(card(fl.fii.net_cr >= 0 ? "pos" : "neg", "Institutional flows · NSE", `FII ${crS(fl.fii.net_cr)}, DII ${crS(fl.dii.net_cr)}`, `Cash market, provisional, ${dt(fl.date, { weekday: "short", day: "numeric", month: "short" })}.`, "Open world", 'data-go="world"'));
  if (pick) { const x = q(pick.symbol); cards.push(card("pos", "B-Lab screen · rank #1", `${esc(pick.symbol)} · F-Score ${pick.fscore}/9`, `Return on capital ${pctF(pick.roc, 0)}, earnings yield ${pctF(pick.earnings_yield)}${x ? ` · ₹${inr(x.p)} (${sg(x.pct)}%)` : ""}`, "Open chart", `data-open="${esc(pick.symbol)}"`)); }
  if (wl.length) cards.push(card(wl[0].x.pct >= 0 ? "pos" : "neg", "Your watchlist", `Best ${esc(wl[0].sym)} ${sg(wl[0].x.pct)}% · worst ${esc(wl[wl.length - 1].sym)} ${sg(wl[wl.length - 1].x.pct)}%`, `${wl.filter(r => r.x.pct > 0).length} of ${wl.length} up today.`, "Open watchlist", 'data-go="terminal" data-side="watch"'));
  $("#brief-cards").innerHTML = cards.join("");
  $$("#brief-cards [data-open]").forEach(bt => bt.onclick = () => { openSec(bt.dataset.open); go("terminal"); });
}

/* ================= CHART ================= */
let chart = null, sMain = null, extra = {}, bars = [], drawSeries = [], priceLines = [], measureSeries = null, measureShown = false;
const LC = () => window.LightweightCharts;
function showMsg(t) { const m = $("#chart-msg"); m.textContent = t || ""; m.classList.toggle("show", !!t); }
const ts = (dateStr, hhmm) => { const [y, m, d] = dateStr.split("-").map(Number), [hh, mm] = hhmm.split(":").map(Number); return Date.UTC(y, m - 1, d, hh, mm) / 1000; };
function candlesFor(sym, interval) {
  const x = q(sym);
  if (["5m", "15m", "1h"].includes(interval)) {
    const it = intraOf(sym); if (!it) return [];
    if (interval === "5m") { const day = (S.quotes[sym] || {}).d || S.qmeta.session_date; return (it.d || []).map(r => ({ time: ts(day, r[0]), o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: day + " " + r[0] })); }
    const w = (it.w || []).map(r => { const [d, t] = r[0].split(" "); return { time: ts(d, t), o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: r[0], d, t }; });
    if (interval === "15m") return w;
    const out = [];
    for (const b of w) {
      const [hh, mm] = b.t.split(":").map(Number), k = Math.floor(((hh * 60 + mm) - 555) / 60), start = 555 + k * 60;
      const hm = String(Math.floor(start / 60)).padStart(2, "0") + ":" + String(start % 60).padStart(2, "0"), key = b.d + " " + hm, last = out[out.length - 1];
      if (last && last.lbl === key) { last.h = Math.max(last.h, b.h); last.l = Math.min(last.l, b.l); last.c = b.c; last.v += b.v; }
      else out.push({ time: ts(b.d, hm), o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, lbl: key });
    }
    return out;
  }
  const d = histOf(sym).map(r => ({ time: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: r[0] }));
  if (x && x.live && x.o != null && (!d.length || x.d > d[d.length - 1].time)) d.push({ time: x.d, o: x.o, h: x.h, l: x.l, c: x.p, v: x.v, lbl: x.d + " (live)" });
  if (interval === "D") return d;
  const out = [];
  for (const b of d) {
    const t0 = new Date(b.time + "T00:00:00Z");
    let key;
    if (interval === "W") { const m = new Date(t0); m.setUTCDate(t0.getUTCDate() - ((t0.getUTCDay() + 6) % 7)); key = m.toISOString().slice(0, 10); }
    else key = b.time.slice(0, 7);
    const last = out[out.length - 1];
    if (last && last.key === key) { last.h = Math.max(last.h, b.h); last.l = Math.min(last.l, b.l); last.c = b.c; last.v += b.v; }
    else out.push({ key, time: b.time, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, lbl: interval === "W" ? "Week of " + b.time : b.time.slice(0, 7) });
  }
  return out;
}
const smaA = (c, n) => c.map((_, i) => i < n - 1 ? null : c.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n);
function emaA(c, n) { const k = 2 / (n + 1), o = []; let e = null; c.forEach((v, i) => { if (i < n - 1) { o.push(null); return; } e = e == null ? c.slice(0, n).reduce((a, b) => a + b, 0) / n : v * k + e * (1 - k); o.push(e); }); return o; }
function rsiA(c, n = 14) {
  const o = []; let g = 0, l = 0;
  c.forEach((v, i) => {
    if (!i) { o.push(null); return; }
    const d = v - c[i - 1];
    if (i <= n) { g += Math.max(d, 0); l += Math.max(-d, 0); if (i === n) { g /= n; l /= n; o.push(l ? 100 - 100 / (1 + g / l) : 100); } else o.push(null); }
    else { g = (g * (n - 1) + Math.max(d, 0)) / n; l = (l * (n - 1) + Math.max(-d, 0)) / n; o.push(l ? 100 - 100 / (1 + g / l) : 100); }
  });
  return o;
}
function bbA(c, n = 20, k = 2) { const m = smaA(c, n); return c.map((_, i) => { if (m[i] == null) return null; const s = c.slice(i - n + 1, i + 1), sd = Math.sqrt(s.reduce((a, b) => a + (b - m[i]) ** 2, 0) / n); return [m[i] + k * sd, m[i], m[i] - k * sd]; }); }
function vwapA(b) { const o = []; let pv = 0, vv = 0, day = null; b.forEach(x => { const d = String(x.lbl).slice(0, 10); if (d !== day) { pv = 0; vv = 0; day = d; } pv += (x.h + x.l + x.c) / 3 * (x.v || 0); vv += x.v || 0; o.push(vv ? pv / vv : null); }); return o; }
function macdA(c) {
  const e12 = emaA(c, 12), e26 = emaA(c, 26), m = c.map((_, i) => e12[i] != null && e26[i] != null ? e12[i] - e26[i] : null);
  const first = m.findIndex(v => v != null), sig = Array(c.length).fill(null);
  if (first >= 0) emaA(m.slice(first), 9).forEach((v, j) => sig[first + j] = v);
  return m.map((v, i) => [v, sig[i], v != null && sig[i] != null ? v - sig[i] : null]);
}
function drawChart(keepRange) {
  if (view !== "terminal" && !chart) return;                   // draw when the terminal is visible
  const L = LC();
  if (!L) { showMsg("The chart library could not load. Check your connection and reload."); return; }
  const prevRange = keepRange && chart ? chart.timeScale().getVisibleLogicalRange() : null;
  if (chart) { chart.remove(); chart = null; }
  extra = {}; drawSeries = []; priceLines = []; measureSeries = null; $("#measure").hidden = true; measureShown = false;
  bars = sec ? candlesFor(sec, iv) : [];
  $$("#iv-grp button").forEach(b => b.classList.toggle("on", b.dataset.iv === iv));
  if (!bars.length) {
    const s = S.map.get(sec);
    showMsg(["5m", "15m", "1h"].includes(iv) ? `No intraday data for ${sec}${s && s.board === "SME" ? " (SME stocks have NSE end-of-day data only)" : ""}. Switch to D.` : "No price history available.");
    legend(); return;
  }
  showMsg("");
  const intraday = typeof bars[0].time === "number";
  chart = L.createChart($("#chart"), {
    autoSize: true,
    layout: { background: { type: "solid", color: COL.card }, textColor: COL.ink3, fontFamily: "'IBM Plex Mono', Consolas, monospace", fontSize: 11, attributionLogo: false,
      panes: { separatorColor: "rgba(181,166,130,0.22)", separatorHoverColor: "rgba(181,166,130,0.45)", enableResize: true } },
    grid: { vertLines: { color: "rgba(181,166,130,0.07)" }, horzLines: { color: "rgba(181,166,130,0.07)" } },
    rightPriceScale: { borderColor: "rgba(181,166,130,0.25)", scaleMargins: { top: 0.14, bottom: inds.has("vol") ? 0.2 : 0.06 }, mode: { auto: 0, log: 1, pct: 2 }[scaleMode] },
    timeScale: { borderColor: "rgba(181,166,130,0.25)", timeVisible: intraday, secondsVisible: false, rightOffset: 6, barSpacing: intraday ? 7 : 6 },
    crosshair: { mode: magnet ? 1 : 0, vertLine: { color: "rgba(181,166,130,0.45)", style: 3, labelBackgroundColor: "#11352a" }, horzLine: { color: "rgba(181,166,130,0.45)", style: 3, labelBackgroundColor: "#11352a" } },
    localization: { priceFormatter: p => inr(p, dp(Math.abs(p))) },
  });
  try { L.createTextWatermark(chart.panes()[0], { horzAlign: "center", vertAlign: "center", lines: [{ text: sec, color: "rgba(181,166,130,0.07)", fontSize: 64, fontStyle: "bold" }, { text: `${iv} · NSE`, color: "rgba(232,220,195,0.06)", fontSize: 16 }] }); } catch (e) {}
  if (ct === "candle") sMain = chart.addSeries(L.CandlestickSeries, { upColor: COL.upFill, downColor: COL.down, borderUpColor: COL.up, borderDownColor: COL.down, wickUpColor: COL.up, wickDownColor: COL.down, priceLineColor: COL.ink, priceLineStyle: 2 });
  else if (ct === "bars") sMain = chart.addSeries(L.BarSeries, { upColor: COL.up, downColor: COL.down, thinBars: false, priceLineColor: COL.ink });
  else if (ct === "line") sMain = chart.addSeries(L.LineSeries, { color: COL.acc, lineWidth: 2, priceLineColor: COL.ink });
  else sMain = chart.addSeries(L.AreaSeries, { lineColor: COL.acc, topColor: "rgba(0,224,96,0.22)", bottomColor: "rgba(0,224,96,0.02)", lineWidth: 2, priceLineColor: COL.ink });
  sMain.setData(bars.map(b => ["candle", "bars"].includes(ct) ? { time: b.time, open: b.o, high: b.h, low: b.l, close: b.c } : { time: b.time, value: b.c }));
  const c = bars.map(b => b.c), colorOf = id => INDS.find(i => i.id === id).color;
  const line = (vals, color, pane = 0, w = 1.5, more = {}) => {
    const s = chart.addSeries(L.LineSeries, { color, lineWidth: w, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...more }, pane);
    s.setData(vals.map((v, i) => v == null ? { time: bars[i].time } : { time: bars[i].time, value: +v.toFixed(2) })); return s;
  };
  if (inds.has("vol")) {
    extra.vol = chart.addSeries(L.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    extra.vol.setData(bars.map(b => ({ time: b.time, value: b.v || 0, color: b.c >= b.o ? "rgba(0,224,96,0.25)" : "rgba(224,160,96,0.28)" })));
  }
  for (const [id, n] of [["sma20", 20], ["sma50", 50], ["sma200", 200]]) if (inds.has(id)) { const v = smaA(c, n); extra[id] = [line(v, colorOf(id)), v]; }
  if (inds.has("ema20")) { const v = emaA(c, 20); extra.ema20 = [line(v, colorOf("ema20")), v]; }
  if (inds.has("bb")) { const b = bbA(c), col = colorOf("bb"); extra.bb = [[line(b.map(x => x && x[0]), col, 0, 1), line(b.map(x => x && x[1]), col, 0, 1, { lineStyle: 2 }), line(b.map(x => x && x[2]), col, 0, 1)], b]; }
  if (inds.has("vwap") && intraday) { const v = vwapA(bars); extra.vwap = [line(v, colorOf("vwap"), 0, 1.6), v]; }
  let pane = 1;
  if (inds.has("rsi")) {
    const r = rsiA(c), s = line(r, colorOf("rsi"), pane, 1.5);
    s.createPriceLine({ price: 70, color: "rgba(224,160,96,0.55)", lineStyle: 2, axisLabelVisible: false });
    s.createPriceLine({ price: 30, color: "rgba(0,224,96,0.5)", lineStyle: 2, axisLabelVisible: false });
    extra.rsi = [s, r]; pane++;
  }
  if (inds.has("macd")) {
    const m = macdA(c), h = chart.addSeries(L.HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
    h.setData(m.map((x, i) => x[2] == null ? { time: bars[i].time } : { time: bars[i].time, value: +x[2].toFixed(3), color: x[2] >= 0 ? "rgba(0,224,96,0.45)" : "rgba(224,160,96,0.45)" }));
    extra.macd = [[h, line(m.map(x => x[0]), "#e8dcc3", pane, 1.3), line(m.map(x => x[1]), "#e0a060", pane, 1.3)], m]; pane++;
  }
  const sizePanes = () => { try { chart && chart.panes().forEach((p, i) => { if (p.setStretchFactor) p.setStretchFactor(i === 0 ? 4 : 1); else if (i > 0) p.setHeight(120); }); } catch (e) {} };
  sizePanes(); requestAnimationFrame(sizePanes);
  applyDrawings();
  chart.subscribeCrosshairMove(p => legend(p));
  if (prevRange) chart.timeScale().setVisibleLogicalRange(prevRange); else applyRange();
  legend();
}
function applyRange() {
  if (!chart || !bars.length) return;
  const n = bars.length; let from = 0;
  if (iv === "D") {
    if (rg === "YTD") { const y = new Date().getFullYear() + "-01-01"; const i = bars.findIndex(b => String(b.time) >= y); from = i < 0 ? 0 : i; }
    else { const d = { "1M": 22, "3M": 64, "6M": 127 }[rg]; if (d) from = Math.max(0, n - d); }
  }
  chart.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: n + 5 });
}
function legend(p) {
  const s = S.map.get(sec), x = q(sec); if (!s) return;
  let i = bars.length - 1;
  if (p && p.time != null) { const j = bars.findIndex(b => b.time === p.time); if (j >= 0) i = j; }
  const b = bars[i], prev = i > 0 ? bars[i - 1].c : (x && x.pc), ch = b && prev ? b.c - prev : null, chp = b && prev ? ch / prev * 100 : null;
  let html = `<div class="lg-main"><b>${esc(sec)} · ${esc(iv)} · NSE</b>`;
  if (b) html += `<span>O <b class="${ud(ch)}">${inr(b.o)}</b> H <b class="${ud(ch)}">${inr(b.h)}</b> L <b class="${ud(ch)}">${inr(b.l)}</b> C <b class="${ud(ch)}">${inr(b.c)}</b> <b class="${ud(ch)}">${sg(ch)} (${sg(chp)}%)</b>${b.v != null ? ` · Vol <b>${big(b.v)}</b>` : ""} · <span class="mut">${esc(b.lbl)}</span></span>`;
  html += `</div><div class="lg-ind">`;
  for (const d of INDS) {
    if (d.id === "vol" || !extra[d.id]) continue;
    const e = extra[d.id][1][i];
    let v = "--";
    if (d.id === "bb") v = e ? `${inr(e[0])} ${inr(e[1])} ${inr(e[2])}` : "--";
    else if (d.id === "rsi") v = e != null ? e.toFixed(1) : "--";
    else if (d.id === "macd") v = e && e[0] != null ? `${e[0].toFixed(2)} ${e[1] != null ? e[1].toFixed(2) : "--"} ${e[2] != null ? e[2].toFixed(2) : ""}` : "--";
    else v = e != null ? inr(e) : "--";
    html += `<span style="color:${d.color}">■ ${esc(d.name)} <b>${v}</b></span>`;
  }
  $("#legend").innerHTML = html + "</div>";
}
function renderHead() {
  const s = S.map.get(sec), x = q(sec); if (!s || !x) return;
  const open = S.qmeta.market === "open", pick = (S.screen.picks || []).find(p => p.symbol === sec);
  const when = x.live ? (open ? `Delayed live · ${x.t} IST · market open` : `Last session ${dt(x.d, { weekday: "short", day: "numeric", month: "short" })} · last price ${x.t} IST`) : `NSE official end-of-day · ${x.d}`;
  $("#cc-head").innerHTML = `<span class="sym">${esc(sec)}</span><span class="name">${esc(s.n)}</span><span class="px ${ud(x.chg)}">₹${inr(x.p)}</span><span class="chg ${ud(x.chg)}">${sg(x.chg)} (${sg(x.pct)}%)</span>
    <span class="when"><span class="tag">NSE</span><span class="tag">${esc(s.series)}</span>${s.board === "SME" ? '<span class="tag warn">SME</span>' : ""}${s.etf ? '<span class="tag">ETF</span>' : ""}${s.n500 ? '<span class="tag">NIFTY 500</span>' : ""}${pick ? `<span class="tag acc">B-Lab screen #${pick.magic_rank}</span>` : ""}<span>${esc(when)}</span></span>`;
  const inW = loadWatch().includes(sec);
  $("#wl-toggle").textContent = inW ? "✓ On watchlist" : "+ Watchlist";
  $("#wl-toggle").classList.toggle("on", inW);
  document.title = `${sec} ₹${inr(x.p)} · B-LAB DESK`;
}

/* ---- chart toolbar ---- */
function syncRange() { $$("#rg-grp button").forEach(b => b.classList.toggle("on", b.dataset.rg === rg)); }
$$("#iv-grp button").forEach(b => b.onclick = () => {
  if (b.disabled) return;
  iv = b.dataset.iv; rg = { "5m": "1D", "15m": "5D", "1h": "5D" }[iv] || (["1D", "5D"].includes(rg) ? "1Y" : rg);
  syncRange(); drawChart();
});
$$("#rg-grp button").forEach(b => b.onclick = () => {
  if (b.disabled) return;
  rg = b.dataset.rg; syncRange();
  const want = rg === "1D" ? "5m" : rg === "5D" ? "15m" : "D";
  if (want !== iv) { iv = want; drawChart(); } else applyRange();
});
$$("#ct-grp button").forEach(b => { b.classList.toggle("on", b.dataset.ct === ct); b.onclick = () => { ct = b.dataset.ct; LS.set("blab-ct", ct); $$("#ct-grp button").forEach(x => x.classList.toggle("on", x === b)); drawChart(true); }; });
$$("#sc-grp button").forEach(b => b.onclick = () => { scaleMode = b.dataset.sc; $$("#sc-grp button").forEach(x => x.classList.toggle("on", x === b)); chart?.priceScale("right").applyOptions({ mode: { auto: 0, log: 1, pct: 2 }[scaleMode] }); });
$("#snap").onclick = () => {
  if (!chart) { toast("Open a chart first"); return; }
  const a = document.createElement("a");
  a.href = chart.takeScreenshot().toDataURL("image/png"); a.download = `${sec}_${iv}_${new Date().toISOString().slice(0, 10)}.png`;
  document.body.appendChild(a); a.click(); a.remove(); toast("Chart image saved");
};
$("#wl-toggle").onclick = () => toggleWatch(sec);
function buildIndMenu() {
  let html = "", g = null;
  for (const d of INDS) {
    if (d.group !== g) { g = d.group; html += `<h6>${esc(g)}</h6>`; }
    html += `<label><input type="checkbox" data-ind="${d.id}" ${inds.has(d.id) ? "checked" : ""}><i style="background:${d.color}"></i><span>${esc(d.name)}</span>${d.id === "vwap" ? "<small>5m · 15m · 1h</small>" : ""}</label>`;
  }
  $("#ind-menu").innerHTML = html;
  $("#ind-cnt").textContent = inds.size ? `(${inds.size})` : "";
  $$("#ind-menu input").forEach(i => i.onchange = () => { i.checked ? inds.add(i.dataset.ind) : inds.delete(i.dataset.ind); LS.set("blab-inds", [...inds]); $("#ind-cnt").textContent = inds.size ? `(${inds.size})` : ""; drawChart(true); });
}
$("#ind-btn").onclick = e => { e.stopPropagation(); const m = $("#ind-menu"); m.hidden = !m.hidden; $("#ind-btn").setAttribute("aria-expanded", String(!m.hidden)); };
document.addEventListener("click", e => { if (!e.target.closest("#ind-dd")) $("#ind-menu").hidden = true; });

/* ---- drawing tools (saved in this browser, per stock) ---- */
const DKEY = "blab-draw";
const drawingsOf = sym => (LS.get(DKEY, {})[sym] || []);
function saveDrawings(sym, list) { const all = LS.get(DKEY, {}); all[sym] = list; LS.set(DKEY, all); }
function clearMeasure() { if (measureSeries && chart) { try { chart.removeSeries(measureSeries); } catch (e) {} } measureSeries = null; $("#measure").hidden = true; measureShown = false; }
function setTool(t) {
  tool = t; pending = null;
  $$("#tools [data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === t));
  $(".stage").classList.toggle("tool-active", t !== "cross");
  const hint = { trend: "Trend line: click the first point", hline: "Horizontal line: click a price", measure: "Measure: click the start point" }[t];
  $("#tool-hint").hidden = !hint; $("#tool-hint").textContent = hint || "";
}
$$("#tools [data-tool]").forEach(b => b.onclick = () => { clearMeasure(); setTool(b.dataset.tool); });
$("#magnet").classList.toggle("on", magnet);
$$("#tools [data-act]").forEach(b => b.onclick = () => {
  const a = b.dataset.act;
  if (a === "magnet") { magnet = !magnet; LS.set("blab-magnet", magnet); b.classList.toggle("on", magnet); chart?.applyOptions({ crosshair: { mode: magnet ? 1 : 0 } }); toast(magnet ? "Magnet on: snaps to candle prices" : "Magnet off"); }
  else if (a === "hide") { hideDraw = !hideDraw; b.classList.toggle("on", hideDraw); applyDrawings(); toast(hideDraw ? "Drawings hidden" : "Drawings shown"); }
  else if (a === "clear") { const n = drawingsOf(sec).length; saveDrawings(sec, []); clearMeasure(); applyDrawings(); toast(n ? `Removed ${n} drawing${n > 1 ? "s" : ""} on ${sec}` : "No drawings on " + sec); }
  else if (a === "fit") chart?.timeScale().fitContent();
  else {
    const r = chart?.timeScale().getVisibleLogicalRange(); if (!r) return;
    const mid = (r.from + r.to) / 2, half = (r.to - r.from) / 2 * (a === "zoomin" ? 0.7 : 1.4);
    chart.timeScale().setVisibleLogicalRange({ from: mid - half, to: mid + half });
  }
});
function applyDrawings() {
  if (!chart || !sMain) return;
  drawSeries.forEach(s => { try { chart.removeSeries(s); } catch (e) {} }); drawSeries = [];
  priceLines.forEach(l => { try { sMain.removePriceLine(l); } catch (e) {} }); priceLines = [];
  if (hideDraw) return;
  for (const d of drawingsOf(sec)) {
    if (d.type === "h") priceLines.push(sMain.createPriceLine({ price: d.price, color: COL.acc, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "" }));
    else if (d.type === "t" && d.iv === iv && d.a.time !== d.b.time) {
      const s = chart.addSeries(LC().LineSeries, { color: COL.acc, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData([d.a, d.b].sort((m, n) => (m.time > n.time ? 1 : -1))); drawSeries.push(s);
    }
  }
}
function pointAt(p) {
  if (!p || p.time == null || !p.point) return null;
  let price = sMain.coordinateToPrice(p.point.y); if (price == null) return null;
  if (magnet) { const b = bars.find(x => x.time === p.time); if (b) price = [b.o, b.h, b.l, b.c].reduce((a, v) => Math.abs(v - price) < Math.abs(a - price) ? v : a, b.c); }
  return { time: p.time, value: +price.toFixed(2) };
}
/* Drawing clicks are read from the raw mouse event: the chart library's own click event is skipped
   when two clicks come close together, which made the second point of a line get lost. */
$("#chart").addEventListener("click", e => {
  if (tool === "cross" || !chart || !sMain) return;
  const r = $("#chart").getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  if (x > chart.timeScale().width() || y > chart.panes()[0].getHeight()) return;   // price axis or a lower pane
  const time = chart.timeScale().coordinateToTime(x);
  if (time == null) return;
  onChartClick({ time, point: { x, y } });
});
function onChartClick(p) {
  if (tool === "cross") return;
  const pt = pointAt(p); if (!pt) return;
  if (tool === "hline") { saveDrawings(sec, [...drawingsOf(sec), { type: "h", price: pt.value }]); applyDrawings(); setTool("cross"); toast(`Horizontal line at ₹${inr(pt.value)}`); return; }
  if (!pending) { pending = pt; $("#tool-hint").textContent = tool === "trend" ? "Trend line: click the second point" : "Measure: click the end point"; return; }
  if (tool === "trend") { saveDrawings(sec, [...drawingsOf(sec), { type: "t", iv, a: pending, b: pt }]); applyDrawings(); setTool("cross"); toast("Trend line saved"); return; }
  const a = pending, b = pt, ia = bars.findIndex(x => x.time === a.time), ib = bars.findIndex(x => x.time === b.time);
  const d = b.value - a.value, pc = d / a.value * 100, n = Math.abs(ib - ia);
  clearMeasure();
  measureSeries = chart.addSeries(LC().LineSeries, { color: d >= 0 ? COL.up : COL.down, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  if (a.time !== b.time) measureSeries.setData([a, b].sort((m, k) => (m.time > k.time ? 1 : -1)));
  const box = $("#measure"), x = chart.timeScale().timeToCoordinate(b.time), y = sMain.priceToCoordinate(b.value);
  box.innerHTML = `${sg(d)} (${sg(pc)}%)<br>${n} bar${n === 1 ? "" : "s"} · ${esc(iv)}`;
  box.style.left = Math.max(0, Math.min((x ?? 0) + 14, $("#chart").clientWidth - 160)) + "px"; box.style.top = Math.max(0, (y ?? 0) - 20) + "px";
  box.style.color = box.style.borderColor = d >= 0 ? COL.up : COL.down; box.hidden = false; measureShown = true;
  setTool("cross");
}

/* ================= RAIL: watchlist, details, prints ================= */
function setSide(v) {
  if (v === "watch") {                                   // the watchlist is always shown at the top of the rail
    const h = $("#watch-h"); h.classList.remove("flash"); void h.offsetWidth; h.classList.add("flash"); return;
  }
  side = v;
  $$("#rail-tabs button").forEach(b => b.classList.toggle("on", b.dataset.side === v));
  $$(".rail-view").forEach(el => el.hidden = el.dataset.side !== v);
  if (v === "prints") renderPrints();
  if (v === "details") renderDetails();
}
$$("#rail-tabs button").forEach(b => b.onclick = () => setSide(b.dataset.side));
function loadWatch() {
  const w = LS.get("blab-watch", null);
  if (Array.isArray(w)) return w.filter(s => S.map.has(s));
  return (S.screen.picks || []).map(p => p.symbol).filter(s => S.map.has(s));
}
function toggleWatch(sym) {
  const w = loadWatch();
  if (w.includes(sym)) { LS.set("blab-watch", w.filter(s => s !== sym)); toast(sym + " removed from watchlist"); }
  else { LS.set("blab-watch", [sym, ...w].slice(0, 60)); toast(sym + " added to watchlist"); }
  renderWatch(); renderHead(); renderMast(); renderMovers();
}
function renderWatch() {
  const w = loadWatch();
  $("#wl-count").textContent = w.length;
  $("#watch").innerHTML = w.length ? w.map(sym => { const x = q(sym), s = S.map.get(sym);
    return `<div class="wl-row ${sym === sec ? "sel" : ""}" data-s="${esc(sym)}"><span class="s">${esc(sym)}<small>${esc(s.n)}</small></span><span class="p">${inr(x?.p)}</span>
      <span class="c ${ud(x?.pct)}">${sg(x?.pct)}%</span><button class="x" data-rm="${esc(sym)}" title="Remove ${esc(sym)}">×</button></div>`; }).join("")
    : '<div class="empty">Your watchlist is empty. Open any stock and press + Watchlist, or use Set up desk.</div>';
  $$("#watch .wl-row").forEach(r => r.onclick = e => { if (e.target.dataset.rm) { toggleWatch(e.target.dataset.rm); return; } openSec(r.dataset.s); });
}
const REC = { strong_buy: "Strong buy", buy: "Buy", hold: "Hold", underperform: "Underperform", sell: "Sell" };
function perfFrom(sym) {
  const h = histOf(sym), x = q(sym); if (!h.length || !x) return null;
  const closes = h.map(r => r[4]);
  if (!(x.live && x.d > h[h.length - 1][0])) closes.pop();
  const back = n => closes.length >= n ? closes[closes.length - n] : null;
  const y = new Date().getFullYear() + "-01-01", before = h.filter(r => r[0] < y), ytd = before.length ? before[before.length - 1][4] : null;
  const f = b => b ? (x.p / b - 1) * 100 : null;
  return [["1W", f(back(5))], ["1M", f(back(21))], ["3M", f(back(63))], ["6M", f(back(126))], ["YTD", f(ytd)], ["1Y", f(h[0][4])]];
}
function rangeBar(lbl, lo, hi, v) {
  if (lo == null || hi == null || hi <= lo) return "";
  const pos = Math.max(0, Math.min(100, (v - lo) / (hi - lo) * 100));
  return `<div class="rbar"><div class="lbl"><span>${lbl}</span></div><div class="trk"><em style="width:${pos}%"></em><i style="left:calc(${pos}% - 1px)"></i></div><div class="lbl"><span>${inr(lo, dp(lo))}</span><span>${inr(hi, dp(hi))}</span></div></div>`;
}
let descOpen = false;
function renderDetails() {
  const s = S.map.get(sec), x = q(sec); if (!s || !x || side !== "details") return;
  const f = S.fund ? (S.fund[sec] || null) : undefined, pick = (S.screen.picks || []).find(p => p.symbol === sec);
  const stat = (k, v) => `<div><span>${k}</span><b>${v}</b></div>`, perf = perfFrom(sec);
  let html = `<div class="sec-t">Ranges</div>${rangeBar("Day's range", x.l, x.h, x.p)}${rangeBar("52-week range", s.lo52, s.hi52, x.p)}
    <div class="sec-t">Key stats</div><div class="stats">${stat("Open", inr(x.o))}${stat("Prev close", inr(x.pc))}${stat("Volume", big(x.v))}${stat("Avg vol 20D", big(s.avgv20))}
      ${stat("Value", x.v != null ? cr(x.v * x.p / 1e7) : "--")}${stat("Delivery", s.deliv == null ? "--" : s.deliv.toFixed(1) + "%")}
      ${f ? stat("Market cap", f.mcap ? cr(f.mcap / 1e7) : "--") + stat("P/E", f.pe ? f.pe.toFixed(1) : "--") + stat("EPS", f.eps != null ? "₹" + inr(f.eps) : "--") + stat("Div yield", f.dy != null ? f.dy.toFixed(2) + "%" : "--")
        + stat("P/B", f.pb ? f.pb.toFixed(2) : "--") + stat("Beta", f.beta != null ? f.beta.toFixed(2) : "--") + stat("ROE", pctF(f.roe)) + stat("Debt/eq", f.de != null ? (f.de / 100).toFixed(2) : "--") : ""}</div>`;
  if (perf) html += `<div class="sec-t">Performance</div><div class="perf">${perf.map(([k, v]) => `<div class="${v == null ? "" : v >= 0 ? "pu" : "pd"}"><span>${k}</span><b class="${ud(v)}">${v == null ? "--" : sg(v, 1) + "%"}</b></div>`).join("")}</div>`;
  if (f && (f.rec || f.tgt)) {
    const pos = { strong_buy: 95, buy: 75, hold: 50, underperform: 25, sell: 5 }[f.rec] ?? 50, up = f.tgt ? (f.tgt / x.p - 1) * 100 : null;
    html += `<div class="sec-t">Analyst view</div><div class="gauge"><i style="left:calc(${pos}% - 2px)"></i></div><div class="g-l"><span>Sell</span><span>Hold</span><span>Buy</span></div>
      <div class="stats" style="margin-top:10px">${stat("Consensus", f.rec ? REC[f.rec] || f.rec : "--")}${stat("Analysts", f.an ?? "--")}${stat("Target", f.tgt ? "₹" + inr(f.tgt, 0) : "--")}${stat("Upside", up == null ? "--" : `<span class="${ud(up)}">${sg(up, 1)}%</span>`)}</div>
      <p class="note">12-month brokerage targets (Yahoo Finance). On average analysts are too optimistic.</p>`;
  }
  if (pick) html += `<div class="sec-t">B-Lab screen</div><div class="stats">${stat("Magic rank", "#" + pick.magic_rank + " of " + pick.of)}${stat("F-Score", pick.fscore + "/9")}${stat("Ret. on capital", pctF(pick.roc))}${stat("Earn. yield", pctF(pick.earnings_yield))}</div>`;
  html += `<div class="sec-t">Profile</div>`;
  if (f === undefined) html += `<p class="note">Loading…</p>`;
  else if (f) html += `<div class="stats">${stat("Sector", esc(f.sector || "--"))}${stat("Employees", f.emp ? Math.round(f.emp).toLocaleString("en-IN") : "--")}${stat("ISIN", esc(s.isin || "--"))}${stat("Listed", esc(s.listed || "--"))}</div>
      ${f.desc ? `<p class="desc ${descOpen ? "" : "clamp"}">${esc(f.desc)}</p><button class="more" id="more">${descOpen ? "Show less" : "Show more"}</button>` : ""}${f.web ? `<p class="note">${esc(f.web)}</p>` : ""}`;
  else html += `<div class="stats">${stat("ISIN", esc(s.isin || "--"))}${stat("Listed", esc(s.listed || "--"))}${stat("Series", esc(s.series))}${stat("Board", esc(s.board))}</div>
      <p class="note">${s.etf ? `${esc(sec)} is an exchange-traded fund, not a company.` : `Company fundamentals are loaded for NIFTY 500 companies; ${esc(sec)} is outside it.`} Only NSE's official trading data is shown. Nothing is estimated.</p>`;
  $("#details").innerHTML = html;
  const more = $("#more"); if (more) more.onclick = () => { descOpen = !descOpen; renderDetails(); };
}
function renderPrints() {
  const it = intraOf(sec), rows = it ? (it.d || []) : [];
  if (!rows.length) { $("#prints").innerHTML = `<div class="empty">No intraday prints for ${esc(sec)} (SME stocks have NSE end-of-day data only).</div>`; return; }
  const pc = q(sec)?.pc;
  $("#prints").innerHTML = `<table class="prints"><thead><tr><th>Time</th><th>Last</th><th>Chg</th><th>Vol</th></tr></thead><tbody>${rows.map((r, i) => {
    const prev = i ? rows[i - 1][4] : pc, ch = prev != null ? r[4] - prev : null;
    return `<tr><td>${esc(r[0])}</td><td class="${ud(ch)}">${inr(r[4])}</td><td class="${ud(ch)}">${ch == null ? "--" : (ch > 0 ? "▲" : ch < 0 ? "▼" : "=") + inr(Math.abs(ch))}</td><td class="mut">${big(r[5])}</td></tr>`;
  }).reverse().join("")}</tbody></table>`;
}

/* ================= MOVERS ================= */
function fillSectorSelect() {
  const inds2 = [...new Set(S.uni.stocks.map(s => s.ind).filter(Boolean))].sort();
  $("#sector-sel").innerHTML = `<option value="">All sectors (NIFTY 500 only when chosen)</option>` + inds2.map(i => `<option>${esc(i)}</option>`).join("");
}
function moverRows() {
  const Qy = movQuery.trim().toUpperCase();
  let rows = S.uni.stocks.filter(s => (board === "All" || (board === "ETF" ? s.etf : s.board === board && !s.etf)) && (!sector || s.ind === sector)
    && (!Qy || s.s.includes(Qy) || s.n.toUpperCase().includes(Qy))).map(s => { const x = q(s.s); return x && x.p != null ? { s, x, val: (x.v || 0) * x.p } : null; }).filter(Boolean);
  if (movMode === "gain") rows = rows.filter(r => r.x.pct != null && r.s.v > 0).sort((a, b) => b.x.pct - a.x.pct);
  else if (movMode === "lose") rows = rows.filter(r => r.x.pct != null && r.s.v > 0).sort((a, b) => a.x.pct - b.x.pct);
  else if (movMode === "val") rows.sort((a, b) => b.val - a.val);
  else if (movMode === "hi") rows = rows.filter(r => r.s.hi52 && r.x.h >= r.s.hi52 * 0.999).sort((a, b) => b.x.pct - a.x.pct);
  else rows = rows.filter(r => r.s.lo52 && r.x.l <= r.s.lo52 * 1.001).sort((a, b) => a.x.pct - b.x.pct);
  if (movSort) {
    const [k, dir] = movSort, get = r => ({ s: r.s.s, n: r.s.n, p: r.x.p, chg: r.x.chg, pct: r.x.pct, v: r.x.v, val: r.val, deliv: r.s.deliv }[k]);
    rows.sort((a, b) => { const A = get(a), B = get(b); if (A == null) return 1; if (B == null) return -1; return (typeof A === "string" ? A.localeCompare(B) : A - B) * dir; });
  }
  return rows;
}
function renderMovers() {
  const rows = moverRows(), show = rows.slice(0, movLimit), wl = loadWatch();
  $("#mov-table tbody").innerHTML = show.length ? show.map(r => {
    const lo = r.s.lo52, hi = r.s.hi52, pos = lo != null && hi > lo ? Math.max(0, Math.min(100, (r.x.p - lo) / (hi - lo) * 100)) : null, on = wl.includes(r.s.s);
    return `<tr data-s="${esc(r.s.s)}"><td class="sym">${esc(r.s.s)} ${r.s.board === "SME" ? '<span class="tag warn">SME</span>' : ""}${r.s.etf ? '<span class="tag">ETF</span>' : ""}</td><td class="co">${esc(r.s.n)}</td>
      <td class="num">${inr(r.x.p)}</td><td class="num ${ud(r.x.chg)}">${sg(r.x.chg)}</td><td class="num ${ud(r.x.pct)}">${sg(r.x.pct)}%</td><td class="num">${big(r.x.v)}</td><td class="num">₹${big(r.val)}</td>
      <td class="num">${r.s.deliv == null ? "--" : r.s.deliv.toFixed(0) + "%"}</td><td>${pos == null ? "--" : `<div class="rng" title="₹${inr(lo)} – ₹${inr(hi)}"><i style="left:calc(${pos}% - 1px)"></i></div>`}</td>
      <td><button class="icon-btn ${on ? "on" : ""}" data-wl="${esc(r.s.s)}" title="${on ? "Remove from" : "Add to"} watchlist">${on ? "✓" : "+"}</button></td></tr>`;
  }).join("") : '<tr><td colspan="10" class="empty">No stocks match these filters.</td></tr>';
  $("#mov-count").textContent = `Showing ${show.length.toLocaleString("en-IN")} of ${rows.length.toLocaleString("en-IN")} stocks`;
  $("#mov-more").hidden = rows.length <= movLimit;
  $$("#mov-table tbody tr[data-s]").forEach(tr => tr.onclick = e => { const w = e.target.closest("[data-wl]"); if (w) { e.stopPropagation(); toggleWatch(w.dataset.wl); return; } openSec(tr.dataset.s); go("terminal"); });
  $$("#mov-table th[data-sort]").forEach(th => th.classList.toggle("sorted", movSort && movSort[0] === th.dataset.sort));
}
$$("#mov-tabs button").forEach(b => b.onclick = () => { movMode = b.dataset.m; movSort = null; movLimit = 50; $$("#mov-tabs button").forEach(x => x.classList.toggle("on", x === b)); renderMovers(); });
$$("#board-grp button").forEach(b => b.onclick = () => { board = b.dataset.b; movLimit = 50; $$("#board-grp button").forEach(x => x.classList.toggle("on", x === b)); renderMovers(); });
$("#sector-sel").onchange = e => { sector = e.target.value; movLimit = 50; renderMovers(); };
$("#mov-filter").oninput = e => { movQuery = e.target.value; movLimit = 50; renderMovers(); };
$("#mov-more").onclick = () => { movLimit += 50; renderMovers(); };
$$("#mov-table th[data-sort]").forEach(th => th.onclick = () => { const k = th.dataset.sort; movSort = movSort && movSort[0] === k ? [k, -movSort[1]] : [k, ["s", "n"].includes(k) ? 1 : -1]; renderMovers(); });

/* ================= SECTORS ================= */
function sectorStats() {
  const g = {};
  for (const s of S.uni.stocks) { if (!s.ind) continue; const x = q(s.s); if (!x || x.pct == null) continue; (g[s.ind] = g[s.ind] || []).push({ s, x }); }
  return Object.entries(g).map(([k, v]) => ({ k, rows: v, n: v.length, avg: v.reduce((a, r) => a + r.x.pct, 0) / v.length, up: v.filter(r => r.x.pct > 0).length })).sort((a, b) => b.avg - a.avg);
}
function renderSectors() {
  const b = breadthNow(), t = b.a + b.d + b.u || 1;
  $("#breadth").innerHTML = `<div class="kick" style="margin-bottom:8px">Market breadth · all ${S.uni.count.toLocaleString("en-IN")} NSE securities</div>
    <div class="b-bar"><i style="width:${b.a / t * 100}%;background:var(--up)"></i><i style="width:${b.u / t * 100}%;background:var(--ink-4)"></i><i style="width:${b.d / t * 100}%;background:var(--down)"></i></div>
    <div class="b-leg"><span class="up">▲ ${b.a.toLocaleString("en-IN")} advancing</span><span class="mut">${b.u} unchanged</span><span class="down">▼ ${b.d.toLocaleString("en-IN")} declining</span></div>`;
  const secs = sectorStats();
  if (!heatSel && secs.length) heatSel = secs[0].k;
  $("#heat").innerHTML = secs.map(s => { const a = Math.min(1, Math.abs(s.avg) / 2.5), bg = s.avg >= 0 ? `rgba(47,111,46,${0.08 + a * 0.4})` : `rgba(168,69,42,${0.08 + a * 0.4})`;
    return `<button class="${heatSel === s.k ? "on" : ""}" style="background:${bg}" data-k="${esc(s.k)}"><span class="n">${esc(s.k)}</span><span class="v ${ud(s.avg)}">${sg(s.avg)}%</span><span class="c">${s.up} of ${s.n} up</span></button>`; }).join("")
    || '<div class="empty">No sector data.</div>';
  $$("#heat button").forEach(bt => bt.onclick = () => { heatSel = bt.dataset.k; renderSectors(); });
  const cur = secs.find(s => s.k === heatSel);
  $("#sec-detail").innerHTML = cur ? `<div class="card-bar">${esc(cur.k)} <span class="mut">${cur.n} stocks · avg ${sg(cur.avg)}%</span></div>
    <table class="tbl"><thead><tr><th>Symbol</th><th class="r">Last</th><th class="r">Chg %</th><th class="r">Value</th></tr></thead><tbody>${[...cur.rows].sort((a, b2) => b2.x.pct - a.x.pct).map(r =>
      `<tr data-s="${esc(r.s.s)}"><td><span class="sym">${esc(r.s.s)}</span><div class="mut">${esc(r.s.n)}</div></td><td class="num">${inr(r.x.p)}</td><td class="num ${ud(r.x.pct)}">${sg(r.x.pct)}%</td><td class="num">₹${big((r.x.v || 0) * r.x.p)}</td></tr>`).join("")}</tbody></table>
    <div class="more-row" style="padding:10px 14px"><button class="btn-line sm" id="sec-to-movers">Show in movers →</button></div>` : '<div class="empty">Choose a sector.</div>';
  $$("#sec-detail tr[data-s]").forEach(tr => tr.onclick = () => { openSec(tr.dataset.s); go("terminal"); });
  const tm = $("#sec-to-movers"); if (tm) tm.onclick = () => { sector = heatSel; $("#sector-sel").value = heatSel; movLimit = 50; renderMovers(); go("movers"); };
}

/* ================= WORLD ================= */
function renderWorld() {
  const rows = S.live.indices || [];
  let html = "", rgn = null;
  for (const r of rows) {
    if (r.region !== rgn) { rgn = r.region; html += `<tr class="grp"><td colspan="6">${esc(rgn.toUpperCase())}</td></tr>`; }
    if (r.error) { html += `<tr><td><span class="sym">${esc(r.code)}</span> <span class="mut">${esc(r.name)}</span></td><td class="num mut" colspan="5">Not available</td></tr>`; continue; }
    html += `<tr><td><span class="sym">${esc(r.code)}</span> <span class="mut">${esc(r.name)}</span></td><td class="num">${us(r.value)}</td><td class="num ${ud(r.net)}">${sg(r.net)}</td><td class="num ${ud(r.pct)}">${sg(r.pct)}%</td><td class="num ${ud(r.ytd)}">${r.ytd == null ? "--" : sg(r.ytd, 1) + "%"}</td><td class="num mut">${esc(r.time)}</td></tr>`;
  }
  $("#wei tbody").innerHTML = html || '<tr><td colspan="6" class="empty">Index data not available.</td></tr>';
  $("#wei-asof").textContent = S.live.generated_ist ? "updated " + S.live.generated_ist.replace(/^.*?, /, "") : "";
  const fmt = m => m.unit === "Rs" ? "₹" + m.value.toFixed(2) : m.unit === "%" ? m.value.toFixed(2) + "%" : m.unit.startsWith("$") ? "$" + us(m.value, 2) : us(m.value, 2);
  $("#macro tbody").innerHTML = (S.live.markets || []).map(m => m.error ? `<tr><td>${esc(m.name)}</td><td class="num mut" colspan="3">Not available</td></tr>`
    : `<tr><td>${esc(m.name)}</td><td class="num">${fmt(m)}</td><td class="num ${ud(m.change_pct)}">${sg(m.change_pct)}%</td><td class="num mut">${m.above_200 == null ? "" : m.above_200 ? "above 200-DMA" : "below 200-DMA"}</td></tr>`).join("")
    || '<tr><td class="empty">Market data not available.</td></tr>';
  const days = (S.inst.days || []).slice(-10).reverse();
  if (!days.length) { $("#fii").innerHTML = '<div class="empty">NSE\'s FII/DII report could not be loaded yet. Nothing is estimated.</div>'; $("#fii-asof").textContent = ""; return; }
  const mx = Math.max(...days.flatMap(d => [Math.abs(d.fii.net_cr), Math.abs(d.dii.net_cr)]), 1);
  const bar = (v, col) => `<div class="bar"><i style="${v >= 0 ? "left:50%" : `left:${50 - Math.abs(v) / mx * 50}%`};width:${Math.abs(v) / mx * 50}%;background:${col}"></i></div>`;
  $("#fii-asof").textContent = `${days.length} day${days.length > 1 ? "s" : ""} saved`;
  $("#fii").innerHTML = days.map(d => `<div class="flow"><span>${dt(d.date, { day: "numeric", month: "short" })} FII</span>${bar(d.fii.net_cr, "var(--acc)")}<b class="${ud(d.fii.net_cr)}" style="text-align:right">${crS(d.fii.net_cr)}</b></div>
    <div class="flow"><span class="mut">${dt(d.date, { day: "numeric", month: "short" })} DII</span>${bar(d.dii.net_cr, "var(--gold)")}<b class="${ud(d.dii.net_cr)}" style="text-align:right">${crS(d.dii.net_cr)}</b></div>`).join("");
}

/* ================= NEWS ================= */
function newsTime(iso) {
  const d = new Date(iso), same = d.toLocaleDateString("en-CA", { timeZone: IST }) === new Date().toLocaleDateString("en-CA", { timeZone: IST });
  return same ? d.toLocaleTimeString("en-GB", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false }) + " IST" : d.toLocaleDateString("en-GB", { timeZone: IST, day: "numeric", month: "short" });
}
function renderNews() {
  const wl = loadWatch(), all = S.live.news || [];
  const items = all.filter(n => {
    const tk = n.tickers || [];
    if (newsFilter === "watch") return tk.some(t => wl.includes(t));
    if (newsFilter === "india") return tk.some(t => S.map.has(t) || t === "NIFTY");
    if (newsFilter === "global") return tk.includes("SPX");
    return true;
  });
  $("#news").innerHTML = items.length ? items.map(n => `<li><span class="t">${newsTime(n.time_utc)}</span><div>${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}
      <div class="meta"><span>${esc(n.publisher || "")}</span>${(n.tickers || []).map(t => S.map.has(t) ? `<button class="tk" data-open="${esc(t)}">${esc(t)}</button>` : `<span class="tag">${esc(t)}</span>`).join("")}</div></div></li>`).join("")
    : `<li class="empty">${all.length ? "No headlines match this filter." : "No headlines available right now."}</li>`;
  $$("#news [data-open]").forEach(b => b.onclick = () => { openSec(b.dataset.open); go("terminal"); });
}
$$("#news-filter button").forEach(b => b.onclick = () => { newsFilter = b.dataset.nf; $$("#news-filter button").forEach(x => x.classList.toggle("on", x === b)); renderNews(); });

/* ================= open a security ================= */
async function openSec(sym) {
  if (!S.map.has(sym)) return;
  sec = sym; pending = null; clearMeasure(); descOpen = false;
  history.replaceState(null, "", `#v=${view}&s=${encodeURIComponent(sym)}`);
  $$("#watch .wl-row").forEach(r => r.classList.toggle("sel", r.dataset.s === sym));
  renderHead(); renderDetails();
  const k = shard(sym);
  await Promise.all([loadHist(k).catch(() => null), loadIntra(k).catch(() => null)]);
  if (sym !== sec) return;
  const hasIntra = !!(intraOf(sym) && (intraOf(sym).d || []).length);
  $$('#iv-grp [data-iv="5m"], #iv-grp [data-iv="15m"], #iv-grp [data-iv="1h"], #rg-grp [data-rg="1D"], #rg-grp [data-rg="5D"]').forEach(b => { b.disabled = !hasIntra; b.title = hasIntra ? "" : "No intraday data for this stock (SME stocks: NSE end-of-day only)"; });
  if (!hasIntra && ["5m", "15m", "1h"].includes(iv)) { iv = "D"; rg = "1Y"; syncRange(); }
  if (view === "terminal") drawChart(); else if (chart) { chart.remove(); chart = null; }
  renderDetails(); if (side === "prints") renderPrints();
}

/* ================= search ================= */
const FUNCS = { BRIEF: "Brief", TERMINAL: "Terminal", MOVERS: "Movers", SECTORS: "Sectors", WORLD: "World", NEWS: "News", WATCHLIST: "Watchlist", SETUP: "Set up desk", BACK: "Back to B-Lab", LOGOFF: "Log off" };
let qFilter = "all", qOpts = [], qAct = 0;
let qAdd = false;                                       // search opened from "+ Add": the pick goes on the watchlist
function openSearch(initial = "", add = false) { qAdd = add; $("#q").placeholder = add ? "Add a stock to your watchlist…" : "Symbol, company name, or a section (MOVERS, NEWS…)"; $("#search").hidden = false; const i = $("#q"); i.value = initial; i.focus(); runSearch(); }
function closeSearch() { $("#search").hidden = true; }
function runSearch() {
  const Q = $("#q").value.trim().toUpperCase(), words = Q.split(/\s+/).filter(Boolean), joined = words.join("");
  const fns = words.length === 1 && Q.length >= 2 ? Object.keys(FUNCS).filter(f => f.startsWith(Q)).map(f => ({ fn: f })) : [];
  const out = [];
  for (const s of S.uni.stocks) {
    if (qFilter === "Main" && (s.board !== "Main" || s.etf)) continue;
    if (qFilter === "SME" && s.board !== "SME") continue;
    if (qFilter === "etf" && !s.etf) continue;
    if (qFilter === "n500" && !s.n500) continue;
    let sc;
    if (!Q) sc = 5;
    else { const nw = s.n.toUpperCase().split(/[^A-Z0-9&]+/), hit = words.every(t => nw.some(w => w.startsWith(t)));
      sc = s.s === joined ? 0 : s.s.startsWith(joined) ? 1 : hit && nw[0].startsWith(words[0]) ? 2 : hit ? 3 : s.s.includes(joined) ? 4 : 9; }
    if (sc < 9) out.push([sc, -((s.v || 0) * (s.c || 0)), s]);
  }
  out.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  qOpts = [...fns, ...out.slice(0, 50).map(r => ({ s: r[2] }))]; qAct = 0;
  $("#q-list").innerHTML = qOpts.map((o, i) => {
    if (o.fn) return `<li role="option" data-i="${i}" aria-selected="${i === qAct}"><span class="lg">→</span><span class="fn">${o.fn}</span><span class="n">${esc(FUNCS[o.fn])}</span><span class="t">section</span><span></span></li>`;
    const x = q(o.s.s);
    return `<li role="option" data-i="${i}" aria-selected="${i === qAct}"><span class="lg">${esc(o.s.s[0])}</span><span class="s">${esc(o.s.s)}</span><span class="n">${esc(o.s.n)}</span><span class="t">${o.s.etf ? "ETF" : o.s.board === "SME" ? "SME" : "STOCK"} · NSE</span><span class="q">${inr(x?.p)} <span class="${ud(x?.pct)}">${sg(x?.pct)}%</span></span></li>`;
  }).join("") || '<li class="empty">No matches.</li>';
  $("#q-foot").textContent = `${S.uni.count.toLocaleString("en-IN")} NSE securities · ↑ ↓ to move · Enter to open · Esc to close`;
}
function paintQ() { $$("#q-list li[role=option]").forEach(li => li.setAttribute("aria-selected", String(+li.dataset.i === qAct))); $("#q-list li[aria-selected=true]")?.scrollIntoView({ block: "nearest" }); }
function chooseQ(o) {
  closeSearch(); if (!o) return;
  if (o.s) { if (qAdd && !loadWatch().includes(o.s.s)) toggleWatch(o.s.s); openSec(o.s.s); go("terminal"); return; }
  const f = o.fn;
  if (f === "BACK") location.href = "advanced.html#signals";
  else if (f === "LOGOFF") $("#logout").click();
  else if (f === "SETUP") openOnboard();
  else if (f === "WATCHLIST") { go("terminal"); setSide("watch"); }
  else go(f.toLowerCase());
}
$("#q").addEventListener("input", runSearch);
$("#q").addEventListener("keydown", e => {
  if (e.key === "ArrowDown") { qAct = Math.min(qOpts.length - 1, qAct + 1); paintQ(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { qAct = Math.max(0, qAct - 1); paintQ(); e.preventDefault(); }
  else if (e.key === "Enter") { chooseQ(qOpts[qAct]); e.preventDefault(); }
});
$("#q-list").addEventListener("click", e => { const li = e.target.closest("li[role=option]"); if (li) chooseQ(qOpts[+li.dataset.i]); });
$$("#q-tabs button").forEach(b => b.onclick = () => { qFilter = b.dataset.f; $$("#q-tabs button").forEach(x => x.classList.toggle("on", x === b)); runSearch(); $("#q").focus(); });
$("#search").addEventListener("mousedown", e => { if (e.target.id === "search") closeSearch(); });
$("#open-search").onclick = () => openSearch();
$("#wl-add").onclick = () => openSearch("", true);

/* ================= desk setup (first visit) ================= */
const LANES = [
  { id: "screen", name: "B-Lab screen", sub: "Today's 10 screened stocks", pick: () => (S.screen.picks || []).map(p => p.symbol) },
  { id: "large", name: "Largest companies", sub: "NIFTY 500 by market value", pick: () => Object.entries(S.fund || {}).filter(([, f]) => f.mcap).sort((a, b) => b[1].mcap - a[1].mcap).map(([s]) => s) },
  { id: "fin", name: "Banks & finance", sub: "Financial services", ind: "Financial Services" },
  { id: "it", name: "Technology", sub: "Information technology", ind: "Information Technology" },
  { id: "energy", name: "Energy", sub: "Oil, gas & power", ind: ["Oil Gas & Consumable Fuels", "Power"] },
  { id: "auto", name: "Autos", sub: "Automobile & components", ind: "Automobile and Auto Components" },
  { id: "pharma", name: "Healthcare", sub: "Pharma & hospitals", ind: "Healthcare" },
  { id: "sme", name: "SME board", sub: "Most-traded SME stocks", pick: () => S.uni.stocks.filter(s => s.board === "SME").sort((a, b) => (b.v || 0) * (b.c || 0) - (a.v || 0) * (a.c || 0)).map(s => s.s) },
];
let lane = "screen";
function lanePicks(l) {
  const L = LANES.find(x => x.id === l);
  let list = L.pick ? L.pick() : S.uni.stocks.filter(s => [].concat(L.ind).includes(s.ind)).sort((a, b) => (b.v || 0) * (b.c || 0) - (a.v || 0) * (a.c || 0)).map(s => s.s);
  return list.filter(s => S.map.has(s)).slice(0, 10);
}
function openOnboard() {
  $("#lanes").innerHTML = LANES.map(l => `<button data-lane="${l.id}" class="${l.id === lane ? "on" : ""}"><b>${esc(l.name)}</b><span>${esc(l.sub)}</span></button>`).join("");
  $$("#lanes button").forEach(b => b.onclick = () => { lane = b.dataset.lane; $$("#lanes button").forEach(x => x.classList.toggle("on", x === b)); previewLane(); });
  previewLane(); $("#onboard").hidden = false;
}
function previewLane() {
  const p = lanePicks(lane), L = LANES.find(x => x.id === lane);
  $("#lane-preview").innerHTML = p.length ? `<b>${esc(L.name.toUpperCase())} · ${p.length} STOCKS</b><br>${p.map(esc).join(" / ")}` : "No stocks available for this lane right now.";
}
$("#ob-skip").onclick = () => { LS.set("blab-onboarded", true); $("#onboard").hidden = true; go("brief"); };
$("#ob-open").onclick = () => {
  const p = lanePicks(lane);
  if (p.length) { LS.set("blab-watch", p); openSec(p[0]); }
  LS.set("blab-onboarded", true); $("#onboard").hidden = true; renderWatch(); renderMast(); renderBrief(); renderMovers(); go("terminal"); setSide("watch");
  toast(`${p.length} stocks on your watchlist`);
};
$("#setup-btn").onclick = openOnboard;

/* ================= keyboard ================= */
document.addEventListener("keydown", e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  if (e.key === "Escape") {
    if (!$("#search").hidden) { closeSearch(); return; }
    if (!$("#onboard").hidden) { $("#ob-skip").click(); return; }
    if (tool !== "cross" || pending) { setTool("cross"); return; }
    if (measureShown) { clearMeasure(); return; }
    if (!$("#ind-menu").hidden) { $("#ind-menu").hidden = true; return; }
    if (typing) { document.activeElement.blur(); return; }
    location.href = "advanced.html#signals"; return;
  }
  if (e.altKey && !typing) { const t = { t: "trend", h: "hline", m: "measure", c: "cross" }[e.key.toLowerCase()]; if (t) { go("terminal"); clearMeasure(); setTool(t); e.preventDefault(); } return; }
  if (typing || e.ctrlKey || e.metaKey || !$("#onboard").hidden) return;
  if (e.key === "/") { e.preventDefault(); openSearch(); return; }
  if (e.key.length === 1 && /[a-z0-9]/i.test(e.key)) { e.preventDefault(); openSearch(e.key); }
});

boot();
