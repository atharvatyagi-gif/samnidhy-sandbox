/* B-LAB DESK (expert-terminal.html). Editorial desk layout (reference: inteldesk.app) in Samnidhy green + beige.
   Real data only:
   t/universe.json  all ~3,500 NSE securities (NSE end-of-day)       t/quotes.json   delayed live prices (~15 min)
   t/h/<k>.json     1 year of NSE daily candles (on demand)           t/i/<k>.json    intraday {d: 5-min latest session, w: 15-min 5 sessions}
   t/fund.json      NIFTY 500 fundamentals                            live.json       world indices, markets, headlines
   screener.json    today's B-Lab screen                              institutional.json  NSE FII/DII history
   t/d/<key>.json   5 years of split-adjusted daily candles (chart; loaded per stock)
   news.json        financial news wire
   Nothing is simulated: values change only when fresh data arrives. */

import { ChartEngine, CHART_TYPES } from "./chart-engine.js";
import { technicals, recommend } from "./chart-indicators.js";
import { LIVE_RELAY_URL } from "./config.js";
import { GlobeMap } from "./globe-map.js";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const IST = "Asia/Kolkata";
const POLL_MS = 60000;
// (chart colours live in chart-engine.js)
const COL_UNUSED = { up: "#00e060", upFill: "rgba(0,224,96,0.9)", down: "#e0a060", ink: "#e8dcc3", ink3: "#83795f", card: "#061a10", acc: "#00e060" };  // dark chart workspace (old terminal palette)
const LS = { get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };

const S = { uni: null, map: new Map(), quotes: {}, qmeta: {}, fund: null, live: {}, screen: {}, inst: {}, hist: {}, intra: {}, prevWei: {}, news: {} };
let sec = null, iv = "D", rg = "1Y", ct = LS.get("blab-ct", "candle"), scaleMode = "auto", view = "brief", side = "details";
let movMode = "gain", board = "All", sector = "", movSort = null, movLimit = 50, movQuery = "", heatSel = null, newsFilter = "all";
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
  if (typeof RP !== "undefined" && RP.on) return S.rq[sym] || null;
  const l = S.quotes[sym];
  if (l && l.d >= e.date) return { live: true, p: l.p, chg: l.chg, pct: l.pct, o: l.o, h: l.h, l: l.l, v: l.v, t: l.t, d: l.d, pc: +(l.p - l.chg).toFixed(2), rt: l.rt, nse: l.nse, grp: l.grp };
  return { live: false, p: e.c, chg: e.chg, pct: e.pct, o: e.o, h: e.h, l: e.l, v: e.v, t: "EOD", d: e.date, pc: e.pc };
}

/* ---------------- auth ---------------- */
function onReady(user) {
  S.user = user; if (S.uni) liveConnect();
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
    S.news = await getJSON("news.json").catch(() => ({}));
    S.uni = uni; uni.stocks.forEach(s => S.map.set(s.s, s)); lastCheck = Date.now();
    S.pred = await getJSON("predict.json").catch(() => null);
    S.globe = await getJSON("globe.json").catch(() => null);
    S.quotes = quotes.quotes || {}; S.qmeta = quotes; S.live = live; S.screen = screen; S.inst = inst;
    S.nseLive = await getJSON("nse_live.json").catch(() => null);
    applyNseLive();
  } catch (e) {
    $("#st-data").textContent = "Data not available: the NSE stock list could not be loaded. Nothing is shown in its place.";
    $("#brief-cards").innerHTML = '<div class="empty">Data not available.</div>'; return;
  }
  const hp = new URLSearchParams(location.hash.slice(1));
  sec = hp.get("s") && S.map.has(hp.get("s")) ? hp.get("s") : (loadWatch()[0] || "RELIANCE");
  $("#search-ph").textContent = `Search ${S.uni.count.toLocaleString("en-IN")} stocks or sections`;
  fillSectorSelect(); updIndCount(); buildTypeMenu(); renderAll();
  go(hp.get("v") || (hp.get("s") ? "terminal" : "brief"), true);
  openSec(sec);
  getJSON("t/fund.json", false).then(f => { S.fund = f.stocks || {}; renderDetails(); }).catch(() => { S.fund = {}; renderDetails(); });
  if (!LS.get("blab-onboarded", false)) openOnboard();
  setInterval(poll, POLL_MS);
  liveConnect();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
}
const NSE_IDX = { "NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK" };
function applyNseLive() {
  const N = S.nseLive; if (!N) return;
  for (const [name, sym] of Object.entries(NSE_IDX)) {
    const row = N.indices && N.indices[name]; if (!row || row.last == null) continue;
    if (!S.idxLive[sym] || !S.idxLive[sym].rt) S.idxLive[sym] = { p: row.last, pc: row.prev_close, pct: row.pct, nse: true };  // an Angel One tick (rt) always wins
  }
  for (const [sym, row] of Object.entries(N.stocks || {})) {
    if (!S.map.has(sym) || row.p == null) continue;
    const cur = S.quotes[sym];
    if (cur && cur.rt) continue;                              // a real-time tick for this stock always wins
    S.quotes[sym] = { p: row.p, chg: row.chg, pct: row.pct, o: row.o, h: row.h, l: row.l, v: row.v, t: row.t ? row.t.slice(11, 19) : "live", d: todayIST(), nse: true, grp: row.grp };
  }
}
function renderAll() { renderAsOf(); renderMast(); renderGlobe(); renderTape(); renderRegime(); renderBrief(); renderWatch(); renderMovers(); renderSectors(); renderWorld(); renderNews(); renderOutlook(); }
/* Auto-update: every minute the desk checks every published file and redraws what changed, so it never needs a
   reload. Prices (t/quotes.json, ~15 min), news (every 15-30 min), world/markets (live.json), FII/DII, the B-Lab
   screen, the model outlook, and, when a new trading day is published, the whole stock list + end-of-day prices. */
let lastCheck = null, checkOk = true;
async function poll() {
  try {
    const [quotes, live, inst, news, screen, uni, pred] = await Promise.all([getJSON("t/quotes.json"), getJSON("live.json"),
      getJSON("institutional.json").catch(() => S.inst), getJSON("news.json").catch(() => null), getJSON("screener.json").catch(() => null),
      getJSON("t/universe.json").catch(() => null), getJSON("predict.json").catch(() => null)]);
    lastCheck = Date.now(); checkOk = true;
    if (news && news.generated_utc !== S.news.generated_utc) S.news = news;
    renderNews();                                            // ages move on even when the wire hasn't changed
    let changed = quotes.generated_utc !== S.qmeta.generated_utc || live.generated_utc !== S.live.generated_utc;
    if (screen && screen.generated_utc !== S.screen.generated_utc) { S.screen = screen; changed = true; }
    if (pred && pred.generated_utc !== (S.pred || {}).generated_utc) { S.pred = pred; changed = true; }
    if (uni && uni.session_date !== S.uni.session_date) {    // a new trading day: refresh everything that is per-day
      S.uni = uni; S.map = new Map(uni.stocks.map(x => [x.s, x]));
      S.hist = {}; S.intra = {}; S.daily = {}; S.arch = {}; S.tech = {}; S.rec = {};
      fillSectorSelect();
      getJSON("t/fund.json").then(f => { S.fund = f.stocks || {}; renderDetails(); }).catch(() => {});
      changed = true;
      await Promise.all([loadHist(shard(sec)).catch(() => null), loadDaily(sec)]);
      toast("New trading day " + uni.session_date + " loaded");
    }
    const rt = Object.fromEntries(Object.entries(S.quotes).filter(([, v]) => v.rt));
    S.quotes = { ...(quotes.quotes || {}), ...rt }; S.qmeta = quotes; S.live = live; S.inst = inst;
    getJSON("nse_live.json").then(nl => { if (nl && nl.generated_utc !== (S.nseLive || {}).generated_utc) { S.nseLive = nl; applyNseLive(); renderTape(); renderRegime(); if (["movers", "brief", "sectors"].includes(view)) renderAll(); renderHead(); } }).catch(() => {});
    getJSON("globe.json").then(g => { if (g && g.generated_utc !== (S.globe || {}).generated_utc) { S.globe = g; renderGlobe(); renderAsOf(); } }).catch(() => {});
    if (!changed) return;
    await loadIntra(shard(sec), true).catch(() => null);
    renderAll(); renderHead(); renderDetails(); if (side === "prints") renderPrints(); if (typeof renderOutlook === "function") renderOutlook(); drawChart(true);
    toast("Desk updated · prices as of " + (quotes.last_bar_ist || "") + " IST");
  } catch (e) { checkOk = false; }
}
/* "As of" dates on every section, and a warning when an update is late */
const dayLbl = iso => iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }) : "--";
const minsAgo = utc => utc ? Math.max(0, Math.round((Date.now() - new Date(utc)) / 60000)) : null;
const agoTxt = m => m == null ? "" : m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.floor(m / 60)} h ${m % 60} min ago` : `${Math.floor(m / 1440)} d ago`;
const istUtc = utc => utc ? new Date(utc).toLocaleString("en-IN", { timeZone: IST, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }) + " IST" : "--";
function marketHoursNow() {
  const n = new Date(new Date().toLocaleString("en-US", { timeZone: IST })), m = n.getHours() * 60 + n.getMinutes();
  return n.getDay() >= 1 && n.getDay() <= 5 && m >= 555 && m <= 930;
}
function renderAsOf() {
  const q = S.qmeta || {}, pm = minsAgo(q.generated_utc), open = marketHoursNow();
  const priceStale = !RP.on && open && !LIVE.ok && pm != null && pm > 30;
  const prices = RP.on ? `<b>REPLAY of ${esc(dayLbl(RP.day))} at ${esc(rpClock(RP.k))} IST</b> · real NSE 1-minute prices played back (NIFTY 50 only) · not live prices`
    : LIVE.ok
    ? `Prices: <b>real-time</b> (NSE via Angel One) · ${esc(dayLbl(new Date().toLocaleDateString("en-CA", { timeZone: IST })))}`
    : q.session_date ? `Prices: <b>${esc(dayLbl(q.session_date))} · ${esc(q.last_bar_ist || "")} IST</b> ${q.market === "open" ? "(market open · delayed about 15 min)" : "(market closed · last trading session)"} · published ${esc(agoTxt(pm))}`
      + (S.uni ? ` · NSE end-of-day files: ${esc(dayLbl(S.uni.session_date))}` : "")
      + (S.nseLive && S.nseLive.stocks ? ` · <span title="nseindia.com's own public site data, unofficial and not a licensed feed">${Object.keys(S.nseLive.stocks).length} stocks tagged NSE carry NSE's own live numbers</span>` : "")
      : "Prices: not available";
  $$('[data-asof="prices"]').forEach(el => { el.innerHTML = (priceStale ? `⚠ Update late: prices were last published ${esc(agoTxt(pm))}. ` : "") + prices; el.classList.toggle("stale", priceStale); });
  const wm = minsAgo(S.live.generated_utc);
  $$('[data-asof="world"]').forEach(el => { const st = wm != null && wm > (open ? 40 : 90); el.innerHTML = `${st ? "⚠ Late: " : ""}Markets, indices &amp; FII/DII updated <b>${esc(istUtc(S.live.generated_utc))}</b> (${esc(agoTxt(wm))})${S.inst && S.inst.updated_ist ? ` · FII/DII report: ${esc(S.inst.updated_ist)}` : ""}`; el.classList.toggle("stale", st); });
  const nm = minsAgo(S.news && S.news.generated_utc);
  $$('[data-asof="news"]').forEach(el => { const st = nm != null && nm > 75; el.innerHTML = S.news && S.news.generated_utc ? `${st ? "⚠ Late: " : ""}News wire updated <b>${esc(istUtc(S.news.generated_utc))}</b> (${esc(agoTxt(nm))}) · refreshed every 15 min in market hours, every 30 min otherwise` : "News wire: not available"; el.classList.toggle("stale", st); });
  const P = S.pred;
  $$('[data-asof="outlook"]').forEach(el => { el.innerHTML = P && P.as_of ? `Model as of the <b>${esc(dayLbl(P.as_of))}</b> close · published ${esc(istUtc(P.generated_utc))} · retrained after every NSE close` : "Model: not published yet"; });
  const gm = minsAgo(S.globe && S.globe.generated_utc);
  $$('[data-asof="globe"]').forEach(el => { const st = gm != null && gm > 90; el.innerHTML = S.globe && S.globe.generated_utc ? `${st ? "⚠ Late: " : ""}Flights &amp; news updated <b>${esc(istUtc(S.globe.generated_utc))}</b> (${esc(agoTxt(gm))}) · refreshed about every hour` : "Globe data: not published yet"; el.classList.toggle("stale", st); });
  const ms = $("#ms-asof");
  if (ms) { ms.textContent = RP.on ? `REPLAY ${rpClock(RP.k).slice(0, 5)}` : LIVE.ok ? "REAL-TIME" : q.session_date ? `${priceStale ? "⚠ " : ""}${dayLbl(q.session_date)} · ${q.last_bar_ist || ""} IST` : "--"; ms.classList.toggle("stale", priceStale);
    ms.title = priceStale ? `Prices were last published ${agoTxt(pm)}: the next update is late` : `Prices as of ${dayLbl(q.session_date)} ${q.last_bar_ist || ""} IST, published ${agoTxt(pm)}`; }
}
setInterval(renderAsOf, 5000);
setInterval(() => {
  const el = $("#st-auto"); if (!el) return;
  const s = lastCheck ? Math.round((Date.now() - lastCheck) / 1000) : null;
  el.textContent = !checkOk ? "● Auto-update: can't reach the site, retrying" : `● Auto-updating${LIVE.ok ? " · real-time feed on" : ""} · checked ${s == null ? "…" : s < 5 ? "just now" : s + "s ago"}`;
  el.classList.toggle("bad", !checkOk);
}, 1000);

/* ================= navigation ================= */
function go(v, quiet) {
  if (!document.getElementById("v-" + v)) v = "brief";
  view = v;
  $$(".view").forEach(el => el.classList.toggle("on", el.id === "v-" + v));
  $(".desk").classList.toggle("on-terminal", v === "terminal");       // dark chart workspace: regime strip folds away
  $$("#tabs [data-go]").forEach(b => b.classList.toggle("on", b.dataset.go === v && !b.dataset.side));
  history.replaceState(null, "", `#v=${v}${sec ? "&s=" + encodeURIComponent(sec) : ""}`);
  if (v === "terminal") requestAnimationFrame(() => { if (!eng.chart) drawChart(); });
  if (v === "globe") { const gm = ensureGlobeMap(); if (gm && S.globe) gm.update(S.globe); requestAnimationFrame(() => gm && gm.resize()); }
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
  $("#livechip").classList.toggle("rt", LIVE.ok);
  $("#live-txt").textContent = RP.on ? `REPLAY · ${dayLbl(RP.day)}` : LIVE.ok ? "REAL-TIME · NSE" : open ? "LIVE · DELAYED" : "MARKET CLOSED";
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
  if (RP.on) { const L = S.idxLive["^NSEI"]; $("#tape").innerHTML = `<span class="chip"><b>REPLAY</b><span class="v">${esc(dayLbl(RP.day))} ${esc(rpClock(RP.k))}</span></span>` + (L ? `<span class="chip"><b>NIFTY 50</b><span class="v">${us(L.p)}</span><em class="${ud(L.pct)}">${sg(L.pct)}%</em></span>` : ""); return; }
  for (const c of ["NIFTY", "SENSEX", "NSEBANK"]) { const L = S.idxLive?.[IDX_OF[c]], r = ix(c); if (L) chips.push([c === "NSEBANK" ? "BANK NIFTY" : c, us(L.p), L.pct]); else if (r) chips.push([c === "NSEBANK" ? "BANK NIFTY" : c, us(r.value), r.pct]); }
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
  $("#regime").innerHTML = `<span class="lbl">Market regime · today</span><span class="verdict ${c.tone}">${esc(c.verdict)}</span><span class="mut">${c.good}/${c.n} favourable</span><span class="rg-scroll">`
    + c.f.map(x => `<span class="f"><i style="background:${x.ok ? "var(--up)" : "var(--down)"}"></i>${esc(x.t)}</span>`).join("")
    + `</span><button class="btn-line sm" data-go="world">Open world →</button>`;
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
    ["15 min", "price refresh"], [`${b.a.toLocaleString("en-IN")}/${b.d.toLocaleString("en-IN")}`, "advancing / declining"],
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

/* ================= CHART (chart-engine.js: TradingView-style engine on Lightweight Charts) ================= */
// Daily history: t/d/<key>.json = 5 years, split-adjusted (Yahoo, checked against NSE's close) for main-board
// stocks, ETFs and the NIFTY / BANK NIFTY / SENSEX indices; SME stocks fall back to NSE's own 1-year files.
const dkey = s => [...s].map(c => /[A-Za-z0-9]/.test(c) ? c : "_" + c.charCodeAt(0).toString(16)).join("");
S.daily = {};
async function loadDaily(sym) {
  if (S.daily[sym] !== undefined) return S.daily[sym];
  try { S.daily[sym] = (await getJSON(`t/d/${dkey(sym)}.json`, false)).d; } catch (e) { S.daily[sym] = null; }
  return S.daily[sym];
}
const dailyOf = sym => S.daily[sym] || histOf(sym);
// Older years (before the 5-year file) live on the repository's "history" branch; fetched when you scroll back.
const ARCHIVE = "https://raw.githubusercontent.com/atharvatyagi-gif/samnidhy-sandbox/history/";
S.arch = {};
async function loadArchive(sym) {
  if (S.arch[sym] !== undefined) return S.arch[sym] === "loading" ? null : S.arch[sym];
  const cur = S.daily[sym]; if (!cur || !cur.length) return null;
  S.arch[sym] = "loading";
  try {
    const r = await fetch(ARCHIVE + dkey(sym) + ".json"); if (!r.ok) throw new Error(r.status);
    const d = (await r.json()).d, first = cur[0][0], ov = d.find(x => x[0] === first);
    const k = ov && ov[4] ? cur[0][4] / ov[4] : 1;              // a split since the archive was made: rescale the old part
    const old = d.filter(x => x[0] < first).map(x => [x[0], +(x[1] * k).toFixed(2), +(x[2] * k).toFixed(2), +(x[3] * k).toFixed(2), +(x[4] * k).toFixed(2), Math.round(x[5] / k)]);
    S.daily[sym] = old.concat(cur); S.arch[sym] = old;
    S.tech[sym] = undefined; S.rec[sym] = undefined;
    return old;
  } catch (e) { S.arch[sym] = null; return null; }
}
const INDEXES = [["^NSEI", "NIFTY 50"], ["^NSEBANK", "BANK NIFTY"], ["^BSESN", "SENSEX"]];
function showMsg(t) { const m = $("#chart-msg"); m.textContent = t || ""; m.classList.toggle("show", !!t); }
const ts = (dateStr, hhmm) => { const [y, m, d] = dateStr.split("-").map(Number), [hh, mm] = hhmm.split(":").map(Number); return Date.UTC(y, m - 1, d, hh, mm) / 1000; };
/* ================= TIMEFRAMES (TradingView's full set) ================= */
// Every timeframe is built from the finest real data available for the stock, never invented:
//   seconds         <- live ticks from the real-time feed (since the page was opened)
//   minutes / hours <- replay: NSE 1-minute candles · real-time feed: Angel One 1-minute / 1-hour candles + ticks
//                      delayed: Yahoo 5-minute (today) and 15-minute (5 sessions) candles
//   1D and up       <- 5 years (and older, on scroll) of split-adjusted daily candles
const IVS = [];
[["Seconds", [["1s", 1], ["5s", 5], ["10s", 10], ["15s", 15], ["30s", 30], ["45s", 45]]],
 ["Minutes", [["1m", 60], ["2m", 120], ["3m", 180], ["5m", 300], ["10m", 600], ["15m", 900], ["30m", 1800], ["45m", 2700]]],
 ["Hours", [["1h", 3600], ["2h", 7200], ["3h", 10800], ["4h", 14400]]],
 ["Days", [["D", 0, "1D"], ["W", 0, "1W"], ["M", 0, "1M"], ["Q", 0, "3M"], ["H", 0, "6M"], ["Y", 0, "12M"]]]]
  .forEach(([g, list]) => list.forEach(([id, s, lbl]) => IVS.push({ id, s, g, lbl: lbl || id })));
const IVSEC = Object.fromEntries(IVS.filter(x => x.s).map(x => [x.id, x.s]));
const ivLabel = id => (IVS.find(x => x.id === id) || { lbl: id }).lbl;
const isIntra = id => !!IVSEC[id];
const INTRA = IVS.filter(x => x.s).map(x => x.id);

// bars must be sorted, times in seconds (IST wall clock stored as UTC); buckets are aligned to the 09:15 open
function aggBars(bars, s) {
  const out = [];
  for (const b of bars) {
    const day0 = Math.floor(b.time / 86400) * 86400, t = day0 + 555 * 60 + Math.floor((b.time - day0 - 555 * 60) / s) * s, last = out[out.length - 1];
    if (last && last.time === t) { last.h = Math.max(last.h, b.h); last.l = Math.min(last.l, b.l); last.c = b.c; last.v += b.v || 0; }
    else { const d = new Date(t * 1000).toISOString(); out.push({ time: t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v || 0, day: d.slice(0, 10), lbl: `${d.slice(0, 10)} ${s < 60 ? d.slice(11, 19) : d.slice(11, 16)}${b.tag || ""}` }); }
  }
  return out;
}
function aggDays(d, id) {
  const out = [];
  for (const b of d) {
    const t0 = new Date(b.time + "T00:00:00Z"), y = b.time.slice(0, 4), mo = +b.time.slice(5, 7);
    let key, lbl;
    if (id === "W") { const m = new Date(t0); m.setUTCDate(t0.getUTCDate() - ((t0.getUTCDay() + 6) % 7)); key = m.toISOString().slice(0, 10); lbl = "Week of " + key; }
    else if (id === "M") { key = b.time.slice(0, 7); lbl = key; }
    else if (id === "Q") { key = `${y}-Q${Math.ceil(mo / 3)}`; lbl = key; }
    else if (id === "H") { key = `${y}-H${mo <= 6 ? 1 : 2}`; lbl = key; }
    else { key = y; lbl = y; }
    const last = out[out.length - 1];
    if (last && last.key === key) { last.h = Math.max(last.h, b.h); last.l = Math.min(last.l, b.l); last.c = b.c; last.v += b.v; }
    else out.push({ key, time: b.time, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, lbl, day: b.time });
  }
  return out;
}
// the finest real intraday data for a stock right now: { bars, s } or { why } when there is none
S.ticks = {};
function tickBars(sym) {                                    // 1-second candles from live ticks
  const T = S.ticks[sym]; if (!T || !T.length) return [];
  const out = []; let pv = null;
  for (const [ms, p, v] of T) {
    const t = Math.floor(ms / 1000) + 19800, dv = pv == null ? 0 : Math.max(0, v - pv); pv = v;
    const last = out[out.length - 1];
    if (last && last.time === t) { last.h = Math.max(last.h, p); last.l = Math.min(last.l, p); last.c = p; last.v += dv; }
    else out.push({ time: t, o: p, h: p, l: p, c: p, v: dv });
  }
  return out;
}
function intraBase(sym, id) {
  const s = IVSEC[id];
  if (RP.on && RP.syms.has(sym)) return s < 60 ? { why: "Second candles need tick-by-tick data, which only the real-time feed provides. Replays are built from real 1-minute candles: pick 1m or longer." } : { bars: rpMinuteBars(sym), s: 60 };
  if (LIVE.ok) {
    if (s < 60) { const b = tickBars(sym); return b.length ? { bars: b, s: 1 } : { why: "Waiting for the first live ticks for " + sym + "… second candles build up from the moment you opened the chart." }; }
    const h = S.rtc[sym + "|1h"], m = S.rtc[sym + "|1m"];
    if (s % 3600 === 0 && h) return { bars: h.bars, s: 3600 };
    if (m) return { bars: m.bars, s: 60 };
  }
  if (s < 60) return { why: "Second candles need tick-by-tick data from the real-time feed (not connected). Try ▶ Replay for NIFTY 50 stocks, or pick 5m or longer." };
  const it = intraOf(sym);
  if (!it) return { why: `No intraday data for ${sym}${(S.map.get(sym) || {}).board === "SME" ? " (SME stocks have NSE end-of-day data only)" : ""}. Switch to 1D.` };
  const w15 = (it.w || []).map(r => { const [d, t] = r[0].split(" "); return { time: ts(d, t), o: r[1], h: r[2], l: r[3], c: r[4], v: r[5] }; });
  const day = (S.quotes[sym] || {}).d || S.qmeta.session_date, d5 = (it.d || []).map(r => ({ time: ts(day, r[0]), o: r[1], h: r[2], l: r[3], c: r[4], v: r[5] }));
  const D = S.deep[sym];
  if (D && s % 3600 === 0 && D.b60.length) return { bars: mergeOlder(D.b60, aggBars(w15, 3600)), s: 3600 };
  if (D && s % 300 === 0 && D.b5.length) return { bars: mergeOlder(D.b5, d5.length ? d5 : w15), s: s % 900 === 0 && !d5.length ? 900 : 300 };
  if (s % 900 === 0) return { bars: w15, s: 900 };
  if (s % 300 === 0) return { bars: d5, s: 300 };
  return { why: `${ivLabel(id)} candles need 1-minute data. The delayed feed comes in 5-minute candles: use ▶ Replay (NIFTY 50, real 1-minute data) or pick 5m, 10m, 15m or longer.` };
}
function dailyCandles(sym) {
  if (RP.on && RP.syms.has(sym)) {
    const st = rpState(sym, RP.k), rows = dailyOf(sym).filter(r => r[0] < RP.day).map(r => ({ time: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: r[0], day: r[0] }));
    if (st) rows.push({ time: RP.day, o: st.o, h: st.h, l: st.l, c: st.p, v: st.v, lbl: RP.day + " (replay)", day: RP.day });
    return rows;
  }
  const x = S.map.has(sym) ? q(sym) : null;
  const d = dailyOf(sym).map(r => ({ time: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: r[0], day: r[0] }));
  if (x && x.live && x.o != null) {                         // today's candle from the latest price
    const live = { time: x.d, o: x.o, h: x.h, l: x.l, c: x.p, v: x.v, lbl: x.d + (x.rt ? " (real-time)" : " (live)"), day: x.d }, last = d[d.length - 1];
    if (!last || x.d > last.time) d.push(live); else if (last.time === x.d) d[d.length - 1] = live;
  }
  return d;
}
let ivWhy = "";
function candlesFor(sym, id) {
  ivWhy = "";
  if (isIntra(id)) {
    const src = intraBase(sym, id);
    if (!src.bars) { ivWhy = src.why; return []; }
    const out = src.s === IVSEC[id] ? src.bars.map(b => ({ ...b, day: b.day || new Date(b.time * 1000).toISOString().slice(0, 10), lbl: b.lbl || new Date(b.time * 1000).toISOString().slice(0, 16).replace("T", " ") })) : aggBars(src.bars, IVSEC[id]);
    if (RP.on) out.forEach(b => { if (!b.lbl.endsWith("(replay)")) b.lbl += " (replay)"; });
    return out;
  }
  const d = dailyCandles(sym);
  return id === "D" ? d : aggDays(d, id);
}
function ivAvailable(id) { if (!sec) return true; candlesFor(sec, id); return !ivWhy; }
function buildIvMenu() {
  let html = "", g = null;
  for (const x of IVS) {
    if (x.g !== g) { g = x.g; html += `<h6>${esc(g)}</h6><div class="iv-row">`; }
    const ok = ivAvailable(x.id);
    html += `<button data-iv="${x.id}" class="${x.id === iv ? "on" : ""}${ok ? "" : " na"}" title="${ok ? ivLabel(x.id) : esc(ivWhy)}">${esc(x.lbl)}</button>`;
    if (IVS[IVS.indexOf(x) + 1]?.g !== g) html += "</div>";
  }
  $("#iv-menu").innerHTML = html;
}

let cmp = [];                                              // [{sym, label, color}]
const CMP_COLORS = ["#6fa8ff", "#f0a0ff", "#f0c674", "#ff6b6b"];
const eng = new ChartEngine($("#chart"), {
  toast, message: showMsg,
  defaultRange: () => applyRange(),
  barSeconds: id => IVSEC[id] || null, ivLabel: id => ivLabel(id),
  marketOpen: () => RP.on || marketHoursNow(), realtime: () => LIVE.ok || RP.on,
  nowIst: () => RP.on ? Date.UTC(+RP.day.slice(0, 4), +RP.day.slice(5, 7) - 1, +RP.day.slice(8, 10)) / 1000 + (555 + Math.floor(RP.k / SUB)) * 60 + (RP.k % SUB) * 15 : null,
  nearStart: () => scrollBack(),
  toolChanged: t => $$("#tools [data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === t)),
  indsChanged: () => updIndCount(),
  compareChanged: list => { cmp = cmp.filter(c => list.some(l => l.sym === c.sym)); },
});
window.blabChart = eng;                                   // handy for checks from the browser console
/* Scroll back = more history, like TradingView: whenever the chart reaches its first candle, the next older
   batch is fetched (daily: older years; intraday: 60 days of 5-minute / 2 years of hourly candles; replay:
   earlier trading days from the library), and the view stays exactly where you are. */
let scrollBusy = false;
function keepView(fn) { const vr = eng.chart && eng.chart.timeScale().getVisibleRange(); fn(); if (vr && eng.chart) eng.chart.timeScale().setVisibleRange(vr); }
async function scrollBack() {
  if (scrollBusy || !sec || !eng.chart) return;
  const sym = sec;
  const done = msg => { scrollBusy = false; if (msg) toast(msg); };
  scrollBusy = true;
  if (RP.on) {                                               // replay: the trading day before the earliest one loaded
    const loaded = Object.keys(RP.data).sort(), days = RP.idx.days, prev = days[days.indexOf(loaded[0]) - 1];
    if (!prev) return done(`Start of the replay library (${dayLbl(loaded[0])})`);
    toast(`Loading ${dayLbl(prev)}…`);
    await rpLoad(prev);
    if (sym === sec) keepView(() => drawChart(true));
    return done();
  }
  if (!isIntra(iv)) {                                         // daily and up: older years from the history branch
    if (!S.daily[sym] || S.arch[sym] !== undefined) return done();
    toast(`Loading ${sym}'s older history…`);
    const old = await loadArchive(sym);
    if (sym !== sec) return done();
    if (!old || !old.length) return done(`No older history for ${sym}: the chart already starts at its first available day`);
    keepView(() => drawChart(true));
    return done(`History loaded back to ${old[0][0]}`);
  }
  if (LIVE.ok) return done();
  if (S.deep[sym] === undefined) {                            // intraday: 60 days of 5-minute + 2 years of hourly candles
    toast(`Loading ${sym}'s older intraday candles…`);
    const d = await loadDeep(sym);
    if (sym !== sec) return done();
    if (!d) return done(`No older intraday candles for ${sym}`);
    keepView(() => drawChart(true));
    return done(`Intraday history loaded: 5-minute from ${dayLbl(d.m5[0]?.[0]?.slice(0, 10))}, hourly from ${dayLbl(d.h1[0]?.[0]?.slice(0, 10))}`);
  }
  return done(IVSEC[iv] >= 3600 ? "Start of the hourly history (about 2 years). Switch to 1D for decades." : "Start of the 5-minute history (about 60 days). Switch to 1h for 2 years, or 1D for decades.");
}
const INTRADAY_DEEP = "https://raw.githubusercontent.com/atharvatyagi-gif/samnidhy-sandbox/intraday/";
S.deep = {};
async function loadDeep(sym) {
  if (S.deep[sym] !== undefined) return S.deep[sym];
  try {
    const r = await fetch(INTRADAY_DEEP + dkey(sym) + ".json"); if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    const conv = rows => rows.map(x => ({ time: ts(x[0].slice(0, 10), x[0].slice(11, 16)), o: x[1], h: x[2], l: x[3], c: x[4], v: x[5] }));
    S.deep[sym] = { m5: d.m5 || [], h1: d.h1 || [], b5: conv(d.m5 || []), b60: conv(d.h1 || []) };
  } catch (e) { S.deep[sym] = null; }
  return S.deep[sym];
}
const mergeOlder = (older, newer) => { if (!newer.length) return older; const t0 = newer[0].time; return older.filter(b => b.time < t0).concat(newer); };
function updIndCount() { const n = eng.inds.length; $("#ind-cnt").textContent = n ? `(${n})` : ""; }
function compareSeries(bars) {
  const intraday = typeof bars[0].time === "number";
  return cmp.map(c => ({ ...c, bars: intraday && c.sym.startsWith("^") ? [] : candlesFor(c.sym, iv) })).filter(c => c.bars.length);
}
function drawChart(keepRange) {
  if (view !== "terminal" && !eng.chart) return;
  if (LIVE.ok && !RP.on && sec && isIntra(iv) && IVSEC[iv] >= 60) {       // real-time: Angel One's own candles as the base
    const base = IVSEC[iv] % 3600 === 0 ? "1h" : "1m";
    if (!S.rtc[sec + "|" + base]) { const sym = sec; showMsg("Loading exchange candles…"); loadRtCandles(sym, base).then(() => { if (sym === sec) { showMsg(""); drawChart(keepRange); } }); if (!intraOf(sec)) return; }
  }
  const bars = sec ? candlesFor(sec, iv) : [];
  syncIv();
  $("#tb-sym").textContent = sec || "—";
  const s = S.map.get(sec);
  if (!bars.length) {
    showMsg(ivWhy || (isIntra(iv) ? `No intraday data for ${sec}. Switch to 1D.` : "No price history available."));
    eng.load({ sym: sec, iv, bars: [], intraday: false }); return;
  }
  showMsg("");
  const intraday = typeof bars[0].time === "number";
  eng.load({ sym: sec, name: s ? s.n : sec, iv, bars, intraday, keepRange, compare: compareSeries(bars) });
  $("#src-note").textContent = RP.on ? `Replay of ${dayLbl(RP.day)} · real NSE 1-minute prices` : intraday ? (LIVE.ok ? (IVSEC[iv] < 60 ? "Live ticks since you opened the chart" : "NSE real-time · Angel One") : "Yahoo Finance, delayed") : S.daily[sec] ? `${bars.length.toLocaleString("en-IN")} bars since ${bars[0].day.slice(0, 4)} · split-adjusted${S.arch[sec] === undefined ? " · scroll back for more" : ""}` : "NSE end-of-day (1 year)";
  updIndCount();
}
function applyRange() {
  const b = eng.bars; if (!b.length) return;
  if (RP.on && typeof b[0].time === "number") {            // replay: a fixed window that fills up as candles form
    const w = Math.max(24, Math.round(7200 / Math.max(IVSEC[iv] || 60, 30)));
    eng.chart.timeScale().setVisibleLogicalRange({ from: -1, to: Math.max(w, b.length + 5) }); return;
  }
  if (typeof b[0].time === "number") { const lastDay = b[b.length - 1].day; eng.showBars(rg === "1D" ? Math.max(0, b.findIndex(x => x.day === lastDay)) : 0); return; }
  const lastD = new Date(b[b.length - 1].time + "T00:00:00Z");
  const back = { "1M": [0, 1], "3M": [0, 3], "6M": [0, 6], "1Y": [1, 0], "5Y": [5, 0] }[rg];
  let cut = null;
  if (rg === "YTD") cut = `${lastD.getUTCFullYear()}-01-01`;
  else if (back) { const d = new Date(lastD); d.setUTCFullYear(d.getUTCFullYear() - back[0]); d.setUTCMonth(d.getUTCMonth() - back[1]); cut = d.toISOString().slice(0, 10); }
  const i = cut ? b.findIndex(x => x.time >= cut) : 0;
  eng.showBars(Math.max(0, i));
}
function renderHead() {
  const s = S.map.get(sec), x = q(sec); if (!s || !x) return;
  const open = S.qmeta.market === "open", pick = (S.screen.picks || []).find(p => p.symbol === sec);
  const when = x.replay ? `Replay · ${dayLbl(x.d)} ${x.t} IST · real 1-minute prices played back` : x.live ? (open ? `${x.rt ? "Real-time" : x.nse ? "NSE live (unofficial)" : "Delayed ~15 min"} · ${dayLbl(x.d)} ${x.t} IST · market open` : `Last session ${dt(x.d, { weekday: "short", day: "numeric", month: "short" })} · last price ${x.t} IST`) : `NSE official end-of-day · ${x.d}`;
  const d = S.dir[sec];
  $("#cc-head").innerHTML = `<span class="sym">${esc(sec)}</span><span class="name">${esc(s.n)}</span><span class="px ${ud(x.chg)}">${d ? `<i class="tick ${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"}</i>` : ""}₹${inr(x.p)}</span><span class="chg ${ud(x.chg)}">${sg(x.chg)} (${sg(x.pct)}%)</span>
    <span class="when"><span class="tag">NSE</span><span class="tag">${esc(s.series)}</span>${s.board === "SME" ? '<span class="tag warn">SME</span>' : ""}${s.etf ? '<span class="tag">ETF</span>' : ""}${s.n500 ? '<span class="tag">NIFTY 500</span>' : ""}${pick ? `<span class="tag acc">B-Lab screen #${pick.magic_rank}</span>` : ""}${x.nse && !x.rt ? '<span class="tag acc" title="NSE\\u2019s own live number, from nseindia.com\\u2019s public site, unofficial and not a licensed feed">NSE live</span>' : ""}<span>${esc(when)}</span></span>`;
  const inW = loadWatch().includes(sec);
  $("#wl-toggle").innerHTML = inW ? '★ <span class="tx wide">On watchlist</span>' : '☆ <span class="tx wide">Watchlist</span>';
  $("#wl-toggle").title = inW ? "Remove from your watchlist" : "Add to your watchlist";
  $("#wl-toggle").classList.toggle("on", inW);
  flash($("#cc-head .px"), "h:" + sec, x.p);
  document.title = `${sec} ₹${inr(x.p)} · B-LAB DESK`;
}

/* ---- chart toolbar ---- */
function syncRange() { $$("#rg-grp button").forEach(b => b.classList.toggle("on", b.dataset.rg === rg)); }
function setIv(id) {
  iv = id;
  const sz = IVSEC[id];
  rg = sz ? (sz <= 300 ? "1D" : "5D") : (["1D", "5D"].includes(rg) ? (id === "D" ? "1Y" : "5Y") : rg);
  syncRange(); $("#iv-menu").hidden = true; drawChart();
}
function syncIv() {
  $$("#iv-grp button[data-iv]").forEach(b => b.classList.toggle("on", b.dataset.iv === iv));
  const fav = [...$$("#iv-grp button[data-iv]")].some(b => b.dataset.iv === iv);
  $("#iv-more").textContent = (fav ? "" : ivLabel(iv) + " ") + "▾"; $("#iv-more").classList.toggle("on", !fav);
}
$$("#iv-grp button[data-iv]").forEach(b => b.onclick = () => setIv(b.dataset.iv));
$("#iv-more").onclick = e => { e.stopPropagation(); const m = $("#iv-menu"); if (m.hidden) buildIvMenu(); m.hidden = !m.hidden; };
$("#iv-menu").onclick = e => { const b = e.target.closest("[data-iv]"); if (b) setIv(b.dataset.iv); };
document.addEventListener("click", e => { if (!e.target.closest("#iv-dd")) $("#iv-menu").hidden = true; });
$$("#rg-grp button").forEach(b => b.onclick = () => {
  if (b.disabled) return;
  rg = b.dataset.rg; syncRange();
  const want = rg === "1D" ? (RP.on || LIVE.ok ? "1m" : "5m") : rg === "5D" ? "15m" : rg === "5Y" ? (iv === "M" ? "M" : "W") : rg === "ALL" ? (INTRA.includes(iv) ? "D" : iv) : (INTRA.includes(iv) ? "D" : iv);
  const ep = ++viewEpoch;
  if (rg === "ALL" && S.daily[sec] && S.arch[sec] === undefined) {
    const sym = sec; toast("Loading the full history…");
    loadArchive(sym).then(() => {
      if (sym !== sec) return;
      if (ep !== viewEpoch) { const vr = eng.chart && eng.chart.timeScale().getVisibleRange(); drawChart(); if (vr) eng.chart.timeScale().setVisibleRange(vr); return; }   // you moved meanwhile: keep your view
      iv = want; drawChart();
    });
    if (want !== iv) { iv = want; drawChart(); } else applyRange();
    return;
  }
  if (want !== iv) { iv = want; drawChart(); } else applyRange();
});
$("#tb-sym").onclick = () => openSearch();
function buildTypeMenu() {
  $("#ct-menu").innerHTML = CHART_TYPES.map(([k, n]) => `<button data-ct="${k}" class="${eng.type === k ? "on" : ""}">${esc(n)}</button>`).join("");
  $("#ct-btn").textContent = (CHART_TYPES.find(t => t[0] === eng.type) || CHART_TYPES[0])[1] + " ▾";
}
$("#ct-btn").onclick = e => { e.stopPropagation(); const m = $("#ct-menu"); buildTypeMenu(); m.hidden = !m.hidden; $("#ct-btn").setAttribute("aria-expanded", String(!m.hidden)); };
$("#ct-menu").onclick = e => { const b = e.target.closest("[data-ct]"); if (!b) return; eng.setType(b.dataset.ct); buildTypeMenu(); $("#ct-menu").hidden = true; };
document.addEventListener("click", e => { if (!e.target.closest("#ct-dd")) $("#ct-menu").hidden = true; });
$("#ind-open").onclick = () => eng.openIndicators();
$$("#sc-grp button").forEach(b => b.onclick = () => { if (cmp.length) { toast("Comparing: the scale stays in %"); return; } $$("#sc-grp button").forEach(x => x.classList.toggle("on", x === b)); eng.setScale(b.dataset.sc); });
$("#snap").onclick = () => {
  const cv = eng.snapshot(); if (!cv) { toast("Open a chart first"); return; }
  const a = document.createElement("a");
  a.href = cv.toDataURL("image/png"); a.download = `${sec}_${iv}_${new Date().toISOString().slice(0, 10)}.png`;
  document.body.appendChild(a); a.click(); a.remove(); toast("Chart image saved");
};
$("#fs").onclick = () => { const on = $(".term").classList.toggle("focus"); $("#fs").classList.toggle("on", on); $("#fs").title = on ? "Show the side panel again" : "Focus: hide the side panel"; $("#fs").querySelector(".tx").textContent = on ? "Exit focus" : "Focus"; };
let viewEpoch = 0;                                          // bumps whenever you navigate, so late-arriving history never undoes it
$("#goto").onchange = e => { if (!e.target.value) return; viewEpoch++; if (INTRA.includes(iv)) { iv = "D"; rg = "ALL"; syncRange(); drawChart(); } eng.goTo(e.target.value); };
$("#wl-toggle").onclick = () => toggleWatch(sec);

/* ---- compare ---- */
$("#cmp-open").onclick = () => {
  const m = document.createElement("div"); m.className = "eng-modal";
  m.innerHTML = `<div class="eng-box" role="dialog" aria-label="Compare"><div class="eng-bh"><b>Compare ${esc(sec)} with…</b><button class="eng-x" aria-label="Close">×</button></div>
    <div class="eng-bb"><div class="cmp-idx">${INDEXES.map(([k, n]) => `<button class="btn-line" data-c="${k}" data-n="${n}">${n}</button>`).join("")}</div>
    <input class="eng-q" type="search" placeholder="…or type a stock (e.g. TCS, HDFC Bank)" aria-label="Compare with a stock"><div class="eng-list cmp-list"></div>
    <p class="eng-note">Both lines are shown as % change from the first bar on screen. Remove a comparison with × in the chart legend.${cmp.length ? " Now comparing: " + cmp.map(c => esc(c.label)).join(", ") + "." : ""}</p></div></div>`;
  const close = () => m.remove();
  m.addEventListener("mousedown", e => { if (e.target === m) close(); });
  m.querySelector(".eng-x").onclick = close;
  m.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
  const list = m.querySelector(".cmp-list"), input = m.querySelector(".eng-q");
  input.oninput = () => {
    const Q = input.value.trim().toUpperCase(); if (!Q) { list.innerHTML = ""; return; }
    const hits = S.uni.stocks.filter(s => s.s !== sec && (s.s.startsWith(Q) || s.n.toUpperCase().split(/\s+/).some(w => w.startsWith(Q)))).sort((a, b) => (b.v || 0) * (b.c || 0) - (a.v || 0) * (a.c || 0)).slice(0, 8);
    list.innerHTML = hits.map(s => `<button class="eng-ind" data-c="${esc(s.s)}" data-n="${esc(s.s)}"><span>${esc(s.s)}</span><small>${esc(s.n)}</small></button>`).join("") || '<p class="eng-empty">No match.</p>';
  };
  m.addEventListener("click", async e => {
    const b = e.target.closest("[data-c]"); if (!b) return;
    if (cmp.some(c => c.sym === b.dataset.c)) { toast("Already comparing " + b.dataset.n); return; }
    if (cmp.length >= 4) { toast("Up to 4 comparisons"); return; }
    await loadDaily(b.dataset.c); if (!b.dataset.c.startsWith("^")) { await loadHist(shard(b.dataset.c)).catch(() => null); await loadIntra(shard(b.dataset.c)).catch(() => null); }
    if (!dailyOf(b.dataset.c).length) { toast("No price history for " + b.dataset.n); return; }
    cmp.push({ sym: b.dataset.c, label: b.dataset.n, color: CMP_COLORS[cmp.length % CMP_COLORS.length] });
    close(); $$("#sc-grp button").forEach(x => x.classList.toggle("on", x.dataset.sc === "pct")); drawChart(true); toast("Comparing with " + b.dataset.n);
  });
  document.body.appendChild(m); input.focus();
};

/* ---- drawing tools ---- */
let stay = false;
$$("#tools [data-tool]").forEach(b => b.onclick = () => eng.setTool(b.dataset.tool, stay));
$("#magnet").classList.toggle("on", eng.magnet);
$$("#tools [data-act]").forEach(b => b.onclick = () => {
  const a = b.dataset.act;
  if (a === "magnet") { eng.setMagnet(!eng.magnet); b.classList.toggle("on", eng.magnet); toast(eng.magnet ? "Magnet on: points snap to open/high/low/close" : "Magnet off"); }
  else if (a === "stay") { stay = !stay; b.classList.toggle("on", stay); if (eng.tool !== "cursor") eng.setTool(eng.tool, stay); toast(stay ? "Stay in drawing mode: on" : "Stay in drawing mode: off"); }
  else if (a === "hide") { const h = eng.toggleHidden(); b.classList.toggle("on", h); toast(h ? "Drawings hidden" : "Drawings shown"); }
  else if (a === "undo") eng.undo();
  else if (a === "clear") eng.clearDrawings();
  else if (a === "fit") eng.fit();
  else eng.zoom(a === "zoomin" ? 0.7 : 1.4);
});

/* ================= REAL-TIME (relay/relay.py: Angel One SmartAPI -> this page) ================= */
// After sign-in the page opens a WebSocket to the relay, proves who it is with the Firebase ID token, and then
// receives every price change: the stocks on screen every 250 ms, the rest of the market every 2 s. Candles for
// 1m / 5m / 15m / 1h charts come from Angel One's exchange candles. Without a relay the page keeps the delayed prices.
const LIVE = { ws: null, ok: false, tries: 0, id: 0, pend: new Map(), since: null };
S.idxLive = {}; S.rtc = {};
const IDX_OF = { NIFTY: "^NSEI", SENSEX: "^BSESN", NSEBANK: "^NSEBANK" };
const todayIST = () => new Date().toLocaleDateString("en-CA", { timeZone: IST });
function liveConnect() {
  if (!LIVE_RELAY_URL || !S.user || typeof S.user.getIdToken !== "function" || LIVE.ws) return;
  const open = async () => {
    const tok = await S.user.getIdToken().catch(() => null);
    if (!tok) { LIVE.ws = null; return; }
    let ws;
    try { ws = new WebSocket(LIVE_RELAY_URL); } catch (e) { LIVE.ws = null; return; }
    LIVE.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", idToken: tok }));
    ws.onmessage = e => { try { onLive(JSON.parse(e.data)); } catch (err) {} };
    ws.onclose = () => {
      const was = LIVE.ok; LIVE.ok = false; LIVE.ws = null; renderMast(); markIntraday();
      if (was) toast("Real-time feed disconnected: reconnecting… (showing delayed prices meanwhile)");
      setTimeout(liveConnect, Math.min(30000, 1500 * 2 ** LIVE.tries++));
    };
  };
  open();
}
function onLive(m) {
  if (m.type === "hello") {
    LIVE.ok = !!m.ok;
    if (m.ok) { LIVE.tries = 0; LIVE.since = new Date(); sendFocus(); toast("Real-time NSE prices connected"); markIntraday(); if (["5m", "15m", "1h", "1m"].includes(iv)) drawChart(true); }
    else toast("Real-time feed: " + (m.reason || "not allowed"));
    renderMast();
  } else if (m.type === "snap" || m.type === "ticks") applyTicks(m.q);
  else if (m.type === "candles") { const cb = LIVE.pend.get(m.id); if (cb) { LIVE.pend.delete(m.id); cb(m.bars); } }
}
function sendFocus() {
  if (!LIVE.ok) return;
  const syms = [...new Set([sec, ...loadWatch(), ...cmp.map(c => c.sym)].filter(Boolean))].slice(0, 50);
  LIVE.ws.send(JSON.stringify({ type: "focus", syms }));
}
function liveCandles(sym, interval) {
  return new Promise(res => {
    if (!LIVE.ok) return res(null);
    const id = ++LIVE.id; LIVE.pend.set(id, res);
    LIVE.ws.send(JSON.stringify({ type: "candles", id, sym, iv: interval }));
    setTimeout(() => { if (LIVE.pend.has(id)) { LIVE.pend.delete(id); res(null); } }, 15000);
  });
}
function applyTicks(qmap) {
  const day = todayIST();
  let mine = null;
  for (const [sym, r] of Object.entries(qmap)) {
    const [p, o, h, l, pc, v, ms] = r;
    if (sym.startsWith("^")) { S.idxLive[sym] = { p, pc, pct: pc ? (p / pc - 1) * 100 : null, rt: true }; continue; }
    const t = ms ? new Date(ms).toLocaleTimeString("en-GB", { timeZone: IST, hour12: false }) : "";
    S.quotes[sym] = { p, chg: +(p - pc).toFixed(2), pct: pc ? +((p / pc - 1) * 100).toFixed(2) : null, o, h, l, v, t, d: day, rt: true };
    if (ms && (sym === sec || S.ticks[sym])) { const T = (S.ticks[sym] ||= []); if (!T.length || T[T.length - 1][0] <= ms) T.push([ms, p, v]); if (T.length > 30000) T.splice(0, 5000); feedRtc(sym, p, v, ms); }
    if (sym === sec) mine = { p, o, h, l, v, ms };
  }
  if (mine) liveBar(mine);
  scheduleLive();
}
function feedRtc(sym, p, v, ms) {                          // keep Angel One's 1m / 1h candles moving with each tick
  const t0 = Math.floor(ms / 1000) + 19800;
  for (const [base, sz] of [["1m", 60], ["1h", 3600]]) {
    const R = S.rtc[sym + "|" + base]; if (!R || !R.bars.length) continue;
    const day0 = Math.floor(t0 / 86400) * 86400, t = day0 + 555 * 60 + Math.floor((t0 - day0 - 555 * 60) / sz) * sz, last = R.bars[R.bars.length - 1];
    const dv = R.lastV != null ? Math.max(0, v - R.lastV) : 0; R.lastV = v;
    if (last.time === t) { last.h = Math.max(last.h, p); last.l = Math.min(last.l, p); last.c = p; last.v += dv; }
    else if (t > last.time) R.bars.push({ time: t, o: p, h: p, l: p, c: p, v: dv });
  }
}
function liveBar() {                                        // move the chart's last candle with the tick
  if (!eng.bars.length || RP.on) return;
  const bs = candlesFor(sec, iv); if (bs.length) eng.upsertBar(bs[bs.length - 1]);
}
let liveTimer = null, liveSlow = 0;
function scheduleLive() {
  if (liveTimer) return;
  liveTimer = setTimeout(() => {
    liveTimer = null;
    renderHead(); renderWatch();
    if (Date.now() - liveSlow > 2000) {                    // the heavier panels at most every 2 s
      liveSlow = Date.now();
      renderMast(); renderTape();
      if (view === "movers") renderMovers(); else if (view === "sectors") renderSectors(); else if (view === "brief") renderBrief();
      if (side === "details") renderDetails();
    }
  }, 200);
}
function markIntraday() {                                   // after the feed connects / drops, keep the timeframe if it still has data
  if (!sec || !isIntra(iv) || RP.on) return;
  candlesFor(sec, iv); if (ivWhy && !LIVE.ok) { iv = "5m"; drawChart(); }
}
async function loadRtCandles(sym, interval) {               // Angel One's own candles -> chart bars
  const key = sym + "|" + interval;
  if (S.rtc[key] && Date.now() - S.rtc[key].at < 60000) return S.rtc[key].bars;
  const rows = await liveCandles(sym, interval); if (!rows || !rows.length) return null;
  const bars = rows.map(r => { const d = r[0].slice(0, 10), hm = r[0].slice(11, 16); return { time: ts(d, hm), o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: `${d} ${hm}`, day: d }; });
  S.rtc[key] = { at: Date.now(), bars };
  LIVE.dayVol = (S.quotes[sym] || {}).v;
  return bars;
}

/* ================= REPLAY (t/r/<day>.json: scripts/replay_data.py) ================= */
// Bar replay, like TradingView's: real NSE 1-minute candles for the NIFTY 50 are played back minute by minute.
// Inside each minute the price steps open -> first extreme -> second extreme -> close (the usual bar-replay
// convention; the true order of ticks inside a minute isn't in 1-minute data). It never stops by itself: at the
// 15:30 close it rolls into the next trading day, and after the newest day it starts again from the oldest.
// While replay is on, every price in the desk is the replay's, and the desk says REPLAY everywhere.
const SUB = 4, RP = { on: false, idx: null, day: null, data: {}, k: 0, speed: 60, playing: false, timer: null, syms: new Set(), loop: true, busy: false };
S.rq = {};
const RP_MAX = 375 * SUB - 1;
const rpMinute = hm => (+hm.slice(0, 2)) * 60 + (+hm.slice(3, 5)) - 555;
const rpClock = k => { const m = Math.floor(k / SUB), s = (k % SUB) * 15, t = 555 + m; return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`; };
const rpCur = () => RP.data[RP.day] || { at: {}, pc: {} };
function rpPrice(b, sub) { return sub === 0 ? b[1] : sub === 3 ? b[4] : (b[4] >= b[1]) === (sub === 1) ? b[3] : b[2]; }   // up bar: O,L,H,C  down bar: O,H,L,C
function rpState(sym, k) {                                   // price, open, high, low, volume at step k of the current day
  const A = rpCur().at[sym]; if (!A) return null;
  const m = Math.floor(k / SUB), sub = k % SUB;
  let o = null, h = -Infinity, l = Infinity, v = 0, p = null;
  for (let i = 0; i <= m && i < 375; i++) {
    const b = A[i]; if (!b) continue;
    if (o === null) o = b[1];
    if (i < m) { h = Math.max(h, b[2]); l = Math.min(l, b[3]); v += b[5]; p = b[4]; continue; }
    for (let s = 0; s <= sub; s++) { const x = rpPrice(b, s); h = Math.max(h, x); l = Math.min(l, x); p = x; }
    if (sub === 3) v += b[5];
  }
  return p === null ? null : { p, o, h, l, v };
}
function rpMinuteBars(sym) {                                 // 1-minute bars: earlier loaded days in full + today up to the clock
  const out = [], m = Math.floor(RP.k / SUB), sub = RP.k % SUB;
  for (const d of Object.keys(RP.data).sort()) {
    if (d > RP.day) continue;
    const A = RP.data[d].at[sym]; if (!A) continue;
    for (let i = 0; i < 375; i++) {
      const b = A[i]; if (!b) continue;
      if (d === RP.day && i > m) break;
      let bar = { o: b[1], h: b[2], l: b[3], c: b[4], v: b[5] };
      if (d === RP.day && i === m) { let h = -Infinity, l = Infinity, c = b[1]; for (let s = 0; s <= sub; s++) { const x = rpPrice(b, s); h = Math.max(h, x); l = Math.min(l, x); c = x; } bar = { o: b[1], h, l, c, v: sub === 3 ? b[5] : Math.round(b[5] * (sub + 1) / SUB) }; }
      out.push({ time: ts(d, b[0]), ...bar, day: d, lbl: `${d} ${b[0]} (replay)` });
    }
  }
  return out;
}
function rpApply() {
  const k = RP.k, t = rpClock(k), pc = rpCur().pc;
  S.rq = {};
  for (const sym of RP.syms) {
    const st = rpState(sym, k); if (!st) continue;
    const c = pc[sym];
    if (sym === "^NSEI") { S.idxLive["^NSEI"] = { p: st.p, pc: c, pct: c ? (st.p / c - 1) * 100 : null }; continue; }
    S.rq[sym] = { p: st.p, chg: c ? +(st.p - c).toFixed(2) : null, pct: c ? +((st.p / c - 1) * 100).toFixed(2) : null, o: st.o, h: st.h, l: st.l, v: st.v, t, d: RP.day, rt: true, replay: true, live: true };
  }
  $("#rp-time").textContent = t; $("#rp-slider").value = k;
  if ($("#rp-day").value !== RP.day) $("#rp-day").value = RP.day;
}
async function rpLoad(day) {
  if (RP.data[day]) return true;
  const d = await getJSON(`t/r/${day}.json`, false).catch(() => null);
  if (!d) return false;
  const at = {};
  for (const [sym, rows] of Object.entries(d.bars)) { const A = new Array(375); for (const r of rows) { const m = rpMinute(r[0]); if (m >= 0 && m < 375) A[m] = r; } at[sym] = A; }
  RP.data[day] = { at, pc: d.pc || {} };
  return true;
}
async function rpSetDay(day, context = true) {               // load a day (+ the two before it, so charts have history)
  RP.busy = true;
  const days = RP.idx.days, i = days.indexOf(day);
  if (context) { RP.data = {}; for (const d of days.slice(Math.max(0, i - 2), i)) await rpLoad(d); }
  const ok = await rpLoad(day);
  RP.busy = false;
  if (!ok) { toast("Couldn't load that day's replay data"); return false; }
  RP.day = day; RP.syms = new Set(Object.keys(RP.data[day].at)); RP.k = 0;
  return true;
}
async function rpNextDay() {                                 // endless: next trading day, or back to the oldest
  const days = RP.idx.days, i = days.indexOf(RP.day), next = days[i + 1];
  rpPlay(false);
  if (next) { if (!(await rpSetDay(next, false))) return; toast(`Next trading day: ${dayLbl(next)}`); }
  else { if (!(await rpSetDay(days[0], true))) return; toast(`End of the library: starting again from ${dayLbl(days[0])}`); }
  rpApply(); drawChart(true); renderAll(); renderHead(); rpPlay(true);
}
function rpStep() {
  if (RP.busy) return;
  if (RP.k >= RP_MAX) { if (RP.loop) rpNextDay(); else { rpPlay(false); toast("Replay reached the 15:30 close"); } return; }
  RP.k++; rpApply();
  if (RP.syms.has(sec)) { const bs = candlesFor(sec, iv); if (bs.length) eng.upsertBar(bs[bs.length - 1]); }
  scheduleLive();
}
function rpPlay(on) {
  RP.playing = on; clearInterval(RP.timer);
  $("#rp-play").textContent = on ? "❚❚" : "▶";
  if (on) RP.timer = setInterval(rpStep, Math.max(20, 60000 / (SUB * RP.speed)));
}
function rpJump(k) { RP.k = Math.max(0, Math.min(RP_MAX, k)); rpApply(); drawChart(); renderAll(); renderHead(); }
async function startReplay(day) {
  RP.idx = RP.idx || await getJSON("t/r/index.json").catch(() => null);
  if (!RP.idx || !RP.idx.days || !RP.idx.days.length) { toast("The replay library hasn't been published yet: it's built after each market close"); return; }
  $("#rp-day").innerHTML = [...RP.idx.days].reverse().map(d => `<option value="${d}">${esc(dayLbl(d))}</option>`).join("");
  day = day || RP.idx.days[RP.idx.days.length - 1];
  if (!(await rpSetDay(day))) return;
  RP.on = true;
  $("#rp-bar").hidden = false; $(".desk").classList.add("replaying");
  if (!RP.syms.has(sec)) { const first = [...RP.syms].filter(s => s !== "^NSEI").sort()[0]; toast(`Replay covers the NIFTY 50: opening ${first}`); await openSec(first); }
  if (!isIntra(iv) || IVSEC[iv] < 60) { iv = "1m"; rg = "1D"; syncRange(); }
  go("terminal"); rpApply(); drawChart(); renderAll(); renderHead(); rpPlay(true);
}
function exitReplay() {
  rpPlay(false); RP.on = false; S.rq = {}; delete S.idxLive["^NSEI"];
  $("#rp-bar").hidden = true; $(".desk").classList.remove("replaying");
  if (isIntra(iv)) { candlesFor(sec, iv); if (ivWhy) iv = "5m"; }
  drawChart(); renderAll(); renderHead(); toast("Back to current prices");
}
$("#rp-open").onclick = () => RP.on ? toast("Replay is already on: use the bar at the bottom") : startReplay();
$("#rp-exit").onclick = exitReplay;
$("#rp-play").onclick = () => rpPlay(!RP.playing);
$("#rp-restart").onclick = () => rpJump(0);
$("#rp-loop").onclick = () => { RP.loop = !RP.loop; $("#rp-loop").classList.toggle("on", RP.loop); toast(RP.loop ? "Endless: rolls into the next trading day at the close" : "Stops at the 15:30 close"); };
$("#rp-slider").oninput = e => rpJump(+e.target.value);
$("#rp-day").onchange = async e => { rpPlay(false); if (await rpSetDay(e.target.value)) { rpJump(0); rpPlay(true); } };
$$("#rp-speed button").forEach(b => b.onclick = () => { RP.speed = +b.dataset.sp; $$("#rp-speed button").forEach(x => x.classList.toggle("on", x === b)); if (RP.playing) rpPlay(true); });

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
  renderWatch(); renderHead(); renderMast(); renderMovers(); sendFocus();
}
/* TradingView-style price flashes: green when a price ticks up, red when it ticks down */
S.shown = {}; S.dir = {};
function flash(el, key, price) {
  if (!el || price == null) return;
  const prev = S.shown[key];
  S.shown[key] = price;
  if (prev == null || prev === price) return;
  const up = price > prev; S.dir[key.split(":")[1]] = up ? 1 : -1;
  el.classList.remove("fl-up", "fl-dn"); void el.offsetWidth; el.classList.add(up ? "fl-up" : "fl-dn");
}
function renderWatch() {
  const w = loadWatch();
  $("#wl-count").textContent = w.length;
  $("#watch").innerHTML = w.length ? w.map(sym => { const x = q(sym), s = S.map.get(sym);
    const out = RP.on && !RP.syms.has(sym);
    return `<div class="wl-row ${sym === sec ? "sel" : ""}${out ? " off" : ""}" data-s="${esc(sym)}"><span class="s">${esc(sym)}<small>${esc(s.n)}</small></span><span class="p">${out ? '<small class="mut">not in replay</small>' : inr(x?.p)}</span>
      <span class="c ${ud(x?.pct)}">${out ? "" : sg(x?.pct) + "%"}</span><button class="x" data-rm="${esc(sym)}" title="Remove ${esc(sym)}">×</button></div>`; }).join("")
    : '<div class="empty">Your watchlist is empty. Open any stock and press + Watchlist, or use Set up desk.</div>';
  $$("#watch .wl-row").forEach(r => { flash(r.querySelector(".p"), "w:" + r.dataset.s, q(r.dataset.s)?.p); r.onclick = e => { if (e.target.dataset.rm) { toggleWatch(e.target.dataset.rm); return; } openSec(r.dataset.s); }; });
}
const REC = { strong_buy: "Strong buy", buy: "Buy", hold: "Hold", underperform: "Underperform", sell: "Sell" };
function perfFrom(sym) {
  const x = q(sym); if (!x) return null;
  const h = dailyOf(sym).filter(r => r[0] < x.d); if (!h.length) return null;          // history before today
  const back = n => h.length >= n ? h[h.length - n][4] : null;
  const y = x.d.slice(0, 4) + "-01-01", before = h.filter(r => r[0] < y), ytd = before.length ? before[before.length - 1][4] : null;
  const f = b => b ? (x.p / b - 1) * 100 : null;
  return [["1W", f(back(5))], ["1M", f(back(21))], ["3M", f(back(63))], ["6M", f(back(126))], ["YTD", f(ytd)], ["1Y", f(back(250))], ["3Y", f(back(745))], ["5Y", f(back(1240))]];
}
S.tech = {}; S.rec = {};
const dailyBars = sym => dailyOf(sym).map(r => ({ time: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], day: r[0] }));
const pctS = v => v == null ? "--" : (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(1) + "%";
function analysisHtml(sym) {
  if (S.daily[sym] === undefined) return `<div class="sec-t">Technicals &amp; recommended indicators</div><p class="note">Loading ${esc(sym)}'s price history…</p>`;
  const bars = dailyBars(sym);
  const T = S.tech[sym] !== undefined ? S.tech[sym] : (S.tech[sym] = technicals(bars));
  const R = S.rec[sym] !== undefined ? S.rec[sym] : (S.rec[sym] = recommend(bars));
  eng.recommended = R ? R.top.map(r => ({ name: r.name, add: r.add })) : [];
  const gauge = (lbl, sc) => `<div class="tg"><div class="tg-top"><span class="mut">${lbl}</span><b class="${sc.score > 0.1 ? "up" : sc.score < -0.1 ? "down" : ""}">${sc.label}</b></div>
    <div class="tg-bar"><i style="left:calc(${((sc.score + 1) / 2 * 100).toFixed(1)}% - 2px)"></i></div><div class="tg-n">${sc.sell} sell · ${sc.neutral} neutral · ${sc.buy} buy</div></div>`;
  let h = `<div class="sec-t">Technicals · daily</div>`;
  h += T ? gauge("Summary", T.all) + `<div class="tg2">${gauge("Moving averages", T.ma)}${gauge("Oscillators", T.osc)}</div>
    <details class="tg-rows"><summary>All ${T.rows.length} signals</summary><table class="prints"><tbody>${T.rows.map(r => `<tr><td>${esc(r.name)}</td><td class="num">${inr(r.value)}</td><td class="${r.sig > 0 ? "up" : r.sig < 0 ? "down" : "mut"}">${r.sig > 0 ? "Buy" : r.sig < 0 ? "Sell" : "Neutral"}</td></tr>`).join("")}</tbody></table></details>
    <p class="note">Counts simple rules (price vs 12 moving averages; RSI, Stochastic, CCI, ADX, Momentum, MACD, Williams %R), the way TradingView's Technicals gauge does. Not advice.</p>`
    : `<p class="note">Needs at least 60 days of history.</p>`;
  h += `<div class="sec-t">Recommended indicators for ${esc(sym)}</div>`;
  if (!R) h += `<p class="note">Needs about 1.6 years of daily history to test indicators on this stock.</p>`;
  else if (!R.top.length) h += `<p class="note">None of the ${R.list.length} indicator rules tested held up on ${esc(sym)}: none made money after costs in both the earlier years and the recent test period. For this stock, no indicator has had a reliable edge.</p>`;
  else h += R.top.map((r, k) => `<div class="rec"><div class="rec-h"><b>${k + 1}. ${esc(r.name)}</b></div>
      <div class="rec-t"><span class="tag">${esc(r.family)}</span>${r.now ? '<span class="tag acc">rule says: in</span>' : '<span class="tag">rule says: out</span>'}</div>
      <div class="rec-s">Unseen test period: <b class="${ud(r.te.ret)}">${pctS(r.te.ret)}</b> vs buy &amp; hold <b class="${ud(R.buyHold.te.ret)}">${pctS(R.buyHold.te.ret)}</b><br>
        Whole period: ${pctS(r.all.ret)} (buy &amp; hold ${pctS(R.buyHold.all.ret)}) · worst drop ${pctS(r.all.dd)} · ${r.all.trades} trades${r.all.win != null ? ` · ${Math.round(r.all.win * 100)}% profitable` : ""} · in the market ${Math.round(r.all.exposure * 100)}% of days</div>
      <button class="btn-line sm" data-rec="${k}">+ Add to chart</button></div>`).join("")
    + `<p class="note">How it works: each indicator is turned into its usual buy/sell rule and tested on ${esc(sym)}'s own daily prices from ${esc(R.from)} to ${esc(R.to)} (acted on the next day, 0.1% cost per trade).
      Rules are ranked on the first 70% of that history and checked on the last 30% (from ${esc(R.testFrom)}), which the ranking never saw. ${R.style ? `On this stock, <b>${esc(R.style.toLowerCase())}</b> rules have worked best.` : ""} Past results are not a forecast. Educational only, not advice.</p>`;
  return h;
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
  let html = `<div class="sec-t">Ranges</div>${rangeBar("Day's range", x.l, x.h, x.p)}${rangeBar("52-week range", s.lo52, s.hi52, x.p)}${outlookHtml(sec)}${analysisHtml(sec)}
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
  $$("#details [data-rec]").forEach(bt => bt.onclick = () => { const r = eng.recommended[+bt.dataset.rec]; if (!r) return; r.add.forEach(([id, p]) => eng.addIndicator(id, p)); go("terminal"); });
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
    const [k, dir] = movSort, get = r => ({ s: r.s.s, n: r.s.n, p: r.x.p, chg: r.x.chg, pct: r.x.pct, v: r.x.v, val: r.val, deliv: r.s.deliv, grp: r.x.grp && r.x.grp[0] }[k]);
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
      <td class="mov-grp">${r.x.nse && r.x.grp && r.x.grp.length ? `<span class="tag acc" title="NSE's own live lists this price came from: ${esc(r.x.grp.join(", "))}">${esc(r.x.grp[0])}${r.x.grp.length > 1 ? ` +${r.x.grp.length - 1}` : ""}</span>` : '<span class="mut">–</span>'}</td>
      <td><button class="icon-btn ${on ? "on" : ""}" data-wl="${esc(r.s.s)}" title="${on ? "Remove from" : "Add to"} watchlist">${on ? "✓" : "+"}</button></td></tr>`;
  }).join("") : '<tr><td colspan="11" class="empty">No stocks match these filters.</td></tr>';
  $("#mov-count").textContent = `Showing ${show.length.toLocaleString("en-IN")} of ${rows.length.toLocaleString("en-IN")} stocks`;
  $("#mov-more").hidden = rows.length <= movLimit;
  $$("#mov-table tbody tr[data-s]").forEach(tr => flash(tr.children[2], "m:" + tr.dataset.s, q(tr.dataset.s)?.p));
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

/* ================= NEWS: brutalist.report-style financial wire ================= */
// news.json (scripts/news_wire.py): India markets RSS (ET, Business Standard, Mint) + brutalist.report's
// Business topic, WSJ, Quartz and Coindesk. live.json adds Yahoo headlines tagged with the screened stocks.
let newsHours = 24, newsWatchOnly = false, newsQuery = "";
const NEWS_STOP = new Set(["THE", "INDIA", "INDIAN", "BANK", "LIMITED", "LTD", "COMPANY", "CORPORATION", "INDUSTRIES", "FINANCE", "FINANCIAL", "NATIONAL", "GLOBAL", "INTERNATIONAL", "POWER", "CAPITAL", "SERVICES", "GROUP", "UNITED", "HOLDINGS", "NEW", "FIRST", "STATE", "GENERAL", "HOUSING", "MOTORS", "STEEL"]);
function watchTerms() {                                   // symbol + distinctive first word of each watchlist company
  const t = new Set();
  for (const sym of loadWatch()) {
    if (sym.length >= 3) t.add(sym);
    const w = ((S.map.get(sym) || {}).n || "").toUpperCase().replace(/[^A-Z0-9& ]/g, " ").split(/\s+/).filter(Boolean)[0];
    if (w && w.length >= 4 && !NEWS_STOP.has(w)) t.add(w);
  }
  return [...t];
}
const ageLabel = m => m == null ? "" : m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m / 60)}h` : `${Math.floor(m / 1440)}d`;
function newsSources() {
  const since = S.news.generated_utc ? Math.max(0, Math.round((Date.now() - new Date(S.news.generated_utc)) / 60000)) : 0;
  const groups = (S.news.groups || []).map(g => ({ id: g.id, name: g.name, sources: g.sources.map(s => ({ ...s,
    items: (s.items || []).map(i => ({ ...i, mins: i.age_min == null ? null : i.age_min + since })) })) }));
  const yahoo = (S.live.news || []).map(n => ({ t: n.title, u: n.url, pub: n.publisher, tickers: (n.tickers || []).filter(t => S.map.has(t)),
    mins: n.time_utc ? Math.max(0, Math.round((Date.now() - new Date(n.time_utc)) / 60000)) : null }));
  if (yahoo.length) {
    const india = groups.find(g => g.id === "india") || (groups.unshift({ id: "india", name: "India markets", sources: [] }), groups[0]);
    india.sources.push({ name: "Yahoo Finance · B-Lab stocks", home: "https://finance.yahoo.com/", via: "Yahoo Finance", items: yahoo });
  }
  return groups;
}
function renderNews() {
  const groups = newsSources();
  const terms = newsWatchOnly ? watchTerms() : [], Q = newsQuery.trim().toLowerCase();
  const reEsc = t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = terms.length ? new RegExp(`\\b(${terms.map(reEsc).join("|")})\\b`, "i") : null;
  const keep = i => (i.mins == null || i.mins <= newsHours * 60) && (!Q || i.t.toLowerCase().includes(Q))
    && (!newsWatchOnly || (re && re.test(i.t)) || (i.tickers || []).some(t => loadWatch().includes(t)));
  const mark = t => { let h = esc(t); if (Q) h = h.replace(new RegExp(reEsc(esc(Q)), "gi"), m => `<mark>${m}</mark>`); return h; };
  let shown = 0, sources = 0, html = "";
  for (const g of groups) {
    if (newsFilter !== "all" && g.id !== newsFilter) continue;
    const cols = g.sources.map(s => {
      const items = s.items.filter(keep); shown += items.length; if (s.items.length) sources++;
      if (!items.length && (Q || newsWatchOnly)) return "";          // filtering: hide sources with no match
      return `<div><h3><a href="${esc(s.home)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a><small>via ${esc(s.via)}${s.stale ? " · last good copy" : ""}</small></h3><ul>${
        items.length ? items.map(i => `<li><a href="${esc(i.u)}" target="_blank" rel="noopener noreferrer">${mark(i.t)}</a> <span class="age">[${ageLabel(i.mins) || "–"}]</span>${
          (i.tickers || []).map(t => `<button class="tk" data-open="${esc(t)}">${esc(t)}</button>`).join("")}</li>`).join("")
        : `<li class="none">No new articles in the past ${newsHours}h.</li>`}</ul></div>`;
    }).join("");
    if (cols) html += (newsFilter === "all" ? `<div class="grp">${esc(g.name)}</div>` : "") + cols;
  }
  $("#news").innerHTML = html || `<div><ul><li class="none">${groups.length ? "No headlines match these filters." : "The news wire isn't available right now. Nothing is shown in its place."}</li></ul></div>`;
  $("#news-meta").textContent = S.news.generated_ist
    ? `${shown.toLocaleString("en-IN")} headlines · ${sources} sources · wire updated ${S.news.generated_ist.replace(/^.*?, /, "")} · links open the original articles`
    : "Wire not loaded yet.";
  $$("#news [data-open]").forEach(b => b.onclick = () => { openSec(b.dataset.open); go("terminal"); });
}
$$("#news-filter button").forEach(b => b.onclick = () => { newsFilter = b.dataset.nf; $$("#news-filter button").forEach(x => x.classList.toggle("on", x === b)); renderNews(); });
$$("#news-time button").forEach(b => b.onclick = () => { newsHours = +b.dataset.h; $$("#news-time button").forEach(x => x.classList.toggle("on", x === b)); renderNews(); });
$("#news-watch").onclick = () => { newsWatchOnly = !newsWatchOnly; $("#news-watch").setAttribute("aria-pressed", String(newsWatchOnly)); renderNews(); };
$("#news-q").oninput = e => { newsQuery = e.target.value; renderNews(); };

/* ================= OUTLOOK (predict.json: scripts/predict_model.py) ================= */
// Probability that each NIFTY 500 stock beats the NIFTY 50 over the next 20 trading days, from a LightGBM
// ensemble tested walk-forward on years it never saw. Every accuracy number shown comes from those unseen years.
let olMode = "top", olSector = "", olQuery = "";
const pct0 = v => v == null ? "--" : Math.round(v * 100) + "%";
const pct1 = v => v == null ? "--" : (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(1) + "%";
function probBar(p) {
  const w = Math.round(p * 100), cls = p >= 0.55 ? "up" : p <= 0.45 ? "down" : "flat";
  return `<span class="pbar ${cls}"><i style="width:${w}%"></i><b>${w}%</b></span>`;
}
function driversHtml(d, n = 3) {
  return (d || []).slice(0, n).map(([name, v]) => `<span class="drv ${v > 0 ? "up" : "down"}">${v > 0 ? "▲" : "▼"} ${esc(name)}</span>`).join(" ");
}
function renderOutlook() {
  const P = S.pred;
  if (!P || !P.stocks) {
    $("#ol-lede").textContent = "The model hasn't been published yet. It runs every evening after the NSE close; nothing is shown in its place.";
    $("#ol-card").innerHTML = ""; $("#ol-table tbody").innerHTML = ""; return;
  }
  const M = P.oos.metrics, L = P.live || {};
  $("#ol-lede").innerHTML = `For each stock: the chance it does better than the NIFTY 50 over the next <b>${P.horizon_days} trading days</b>, as of the <b>${esc(dt(P.as_of, { day: "numeric", month: "short", year: "numeric" }))}</b> close.
    50% = no edge. The model is right more often than a coin flip, but far from always: read the card below before using any number.`;
  const yrs = (P.oos.years || []).map(y => `<tr><td>${y.year}</td><td class="num">${y.auc.toFixed(3)}</td><td class="num">${pct0(y.top_hit)}</td><td class="num ${ud(y.top_excess)}">${pct1(y.top_excess)}</td><td class="num ${ud(y.bottom_excess)}">${pct1(y.bottom_excess)}</td></tr>`).join("");
  const cal = (P.oos.calibration || []).map(c => `<div class="cal-b" title="Predicted ${pct0(c.pred)} → actually ${pct0(c.actual)} (${c.n.toLocaleString("en-IN")} cases)"><i class="pr" style="height:${Math.round(c.pred * 100)}%"></i><i class="ac" style="height:${Math.round(c.actual * 100)}%"></i><span>${pct0(c.pred)}</span></div>`).join("");
  $("#ol-card").innerHTML = `
    <div class="ol-grid">
      <div class="ol-stat"><b>${pct0(M.accuracy)}</b><span>right on unseen years<br><small>coin flip / base rate: ${pct0(M.base_rate)}</small></span></div>
      <div class="ol-stat"><b>${M.auc.toFixed(3)}</b><span>AUC out of sample<br><small>0.500 = no skill</small></span></div>
      <div class="ol-stat"><b>${pct0(M.top_decile_hit)}</b><span>top 10% beat NIFTY<br><small>bottom 10%: ${pct0(M.bottom_decile_hit)}</small></span></div>
      <div class="ol-stat"><b class="${ud(M.top_decile_excess - M.bottom_decile_excess)}">${pct1(M.top_decile_excess - M.bottom_decile_excess)}</b><span>top vs bottom 10%<br><small>average 20-day excess return gap</small></span></div>
      <div class="ol-stat"><b>${L.matured_days ? pct0(L.accuracy) : "—"}</b><span>live track record<br><small>${L.matured_days ? `${L.matured_days} days scored, ${(L.n || 0).toLocaleString("en-IN")} predictions` : "first results about a month after launch"}</small></span></div>
    </div>
    <details class="ol-more"><summary>How good is this model? (tested on ${esc(M.from)} → ${esc(M.to)}, ${M.n.toLocaleString("en-IN")} predictions it never saw)</summary>
      <div class="ol-two">
        <div><h6>By year (each year predicted by models trained only on earlier years)</h6>
          <table class="tbl sm"><thead><tr><th>Year</th><th class="r">AUC</th><th class="r">Top 10% beat NIFTY</th><th class="r">Top 10% excess</th><th class="r">Bottom 10% excess</th></tr></thead><tbody>${yrs}</tbody></table></div>
        <div><h6>Calibration: 10 equal groups from lowest to highest score. Predicted chance (dark) vs what actually happened (bright)</h6><div class="cal">${cal}</div>
          <p class="note">When bars match, the percentages can be taken at face value. (This matching was fitted on these same test years; the live track record above is the check on new data.)${M.confident_accuracy != null ? ` When the model is confident (below 40% or above 60%, ${pct0(M.confident_share)} of cases) it was right ${pct0(M.confident_accuracy)} of the time.` : ""}</p></div>
      </div>
      <p class="note"><b>Method:</b> ${esc(P.model.type)}; ${P.model.inputs} inputs per stock per day (price trend, momentum, RSI, ADX, MACD, Bollinger, volatility, 52-week high/low, volume, beta to NIFTY, sector-relative returns, market breadth and regime).
        Walk-forward: every year was predicted by models trained only on earlier data with a 25-day gap, so no future information leaks in. Today's model was trained on ${P.model.train_rows_final.toLocaleString("en-IN")} examples up to ${esc(P.model.train_to)}.
        Most influential inputs: ${P.model.top_inputs.slice(0, 6).map(t => esc(t[0])).join(", ")}.</p>
      <p class="note"><b>Limits:</b> markets are mostly noise over 20 days; a 55% chance still fails 45% of the time. Results before costs and taxes. Past accuracy does not guarantee future accuracy. Educational only, not investment advice.</p>
    </details>`;
  const secs = [...new Set(Object.keys(P.stocks).map(s => (S.map.get(s) || {}).ind).filter(Boolean))].sort();
  const sel = $("#ol-sector"); if (sel.options.length <= 1) sel.innerHTML = `<option value="">All sectors</option>` + secs.map(x => `<option>${esc(x)}</option>`).join("");
  let rows = Object.entries(P.stocks).map(([sym, v]) => ({ sym, ...v, st: S.map.get(sym) || { n: sym } }));
  if (olSector) rows = rows.filter(r => r.st.ind === olSector);
  const Q = olQuery.trim().toUpperCase(); if (Q) rows = rows.filter(r => r.sym.includes(Q) || (r.st.n || "").toUpperCase().includes(Q));
  rows.sort((a, b) => olMode === "bottom" ? (a.s ?? a.p) - (b.s ?? b.p) : (b.s ?? b.p) - (a.s ?? a.p));
  if (olMode !== "all") rows = rows.slice(0, 25);
  $("#ol-table tbody").innerHTML = rows.map((r, i) => `<tr data-s="${esc(r.sym)}"><td class="mut">${i + 1}</td><td class="sym">${esc(r.sym)}</td><td class="co">${esc(r.st.n || "")}</td><td class="mut">${esc(r.st.ind || "")}</td>
    <td class="num">${probBar(r.p)}</td><td class="num">${r.dec}/10</td><td class="num ${ud(r.er)}">${pct1(r.er)}</td><td class="rs">${driversHtml(r.drivers, 2)}</td></tr>`).join("") || '<tr><td colspan="8" class="empty">No stocks match.</td></tr>';
  $$("#ol-table tbody tr[data-s]").forEach(tr => tr.onclick = () => { openSec(tr.dataset.s); go("terminal"); setSide("details"); });
  $("#ol-foot").innerHTML = `* Past excess: what stocks in the same score decile actually did vs NIFTY, on average over 20 trading days, in the unseen test years. Not a forecast of this stock's return. Updated every evening after the NSE close (${esc(P.as_of)}).`;
}
$$("#ol-mode button").forEach(b => b.onclick = () => { olMode = b.dataset.om; $$("#ol-mode button").forEach(x => x.classList.toggle("on", x === b)); renderOutlook(); });
$("#ol-sector").onchange = e => { olSector = e.target.value; renderOutlook(); };
$("#ol-q").oninput = e => { olQuery = e.target.value; renderOutlook(); };
function outlookHtml(sym) {
  const P = S.pred, v = P && P.stocks ? P.stocks[sym] : null;
  let h = `<div class="sec-t">Model outlook · next ${P ? P.horizon_days : 20} trading days</div>`;
  if (!P || !P.stocks) return h + `<p class="note">The model hasn't been published yet.</p>`;
  if (!v) return h + `<p class="note">${esc(sym)} is outside the NIFTY 500 (or lacks enough history), so the model doesn't cover it.</p>`;
  const M = P.oos.metrics;
  return h + `<div class="ol-mini"><div class="tg-top"><span class="mut">Chance it beats NIFTY 50</span><b class="${v.p >= 0.55 ? "up" : v.p <= 0.45 ? "down" : ""}">${pct0(v.p)}</b></div>
      <div class="tg-bar"><i style="left:calc(${Math.round(v.p * 100)}% - 2px)"></i></div>
      <div class="tg-n">Decile ${v.dec}/10 · stocks in this decile did ${pct1(v.er)} vs NIFTY on average (unseen years)</div>
      <div class="ol-drv">${driversHtml(v.drivers, 5)}</div>
      <p class="note">Model right ${pct0(M.accuracy)} of the time on unseen years (coin flip ${pct0(M.base_rate)}). As of ${esc(P.as_of)} close. <a href="#" data-go="outlook">How good is it? →</a></p></div>`;
}

/* ================= GLOBE (globe.json: scripts/globe_data.py) ================= */
// Real live flight positions (OpenSky) near 7 shipping/oil chokepoints, real news about each (GDELT), and a
// general world-events feed (GDELT). No live cargo-ship positions exist for free anywhere, so ships aren't
// drawn; each chokepoint's real news stands in for that. "Why it matters" lines are static reference facts.
let globeMap = null, globeSel = null;
function ensureGlobeMap() {
  if (globeMap) return globeMap;
  const host = $("#globe-map"); if (!host) return null;
  globeMap = new GlobeMap(host, { onSelect: id => { globeSel = id; renderGlobeCards(); } });
  return globeMap;
}
function selectChoke(id) {                                // one entry point: the map and the cards both go through this
  if (globeMap) globeMap.select(id);                       // GlobeMap owns the toggle and fires onSelect -> updates globeSel + cards
  else { globeSel = globeSel === id ? null : id; renderGlobeCards(); }
}
function newsTimeAgo(iso) {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`;
}
// "Active"/"Quiet": each chokepoint's live flight count against this run's own average across all 7 - a same-run
// comparison, not a historical trend (no baseline is stored). Not a claim about trade or oil activity, just aircraft.
function activityFlag(pts) {
  const counts = (pts || []).map(p => (p.flights && p.flights.count) || 0);
  const avg = counts.reduce((a, b) => a + b, 0) / (counts.length || 1);
  return n => avg <= 0 ? null : n >= avg * 1.5 ? "active" : n <= avg * 0.3 ? "quiet" : null;
}
function renderGlobe() {
  const G = S.globe;
  // The Leaflet map sizes itself from its container when built; while the Globe tab is hidden that container is
  // 0x0 (display:none), which leaves the map broken (one tile, pins bunched in a corner) until resize() runs.
  // So it's only touched while the tab is actually visible - go() builds/updates/resizes it on switching in.
  if (view === "globe") { const gm = ensureGlobeMap(); if (gm && G) gm.update(G); }
  renderGlobeCards();
  const el = $("#globe-events");
  if (el) el.innerHTML = G && (G.events || []).length ? G.events.map(n => `<li><span class="t">${esc(newsTimeAgo(n.seen_utc))}</span><div>${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title || "")}
      <div class="meta"><span>${esc(n.source || "")}</span>${n.country ? `<span class="tag">${esc(n.country)}</span>` : ""}</div></div></li>`).join("")
    : `<li class="empty">${G ? "No world-events headlines matched right now." : "The globe data hasn't been published yet."}</li>`;
}
// Real NSE sector(s) each chokepoint is structurally exposed to (well-documented supply-chain facts, not a
// forecast) - only mapped where the link is genuinely strong; left out where it would be a stretch (Malacca,
// Panama carry broad general trade, not one identifiable NSE sector). Names must match S.uni.stocks[].ind exactly.
const CHOKE_SECTORS = {
  hormuz: [["Oil Gas & Consumable Fuels", "oil tankers from the Gulf transit here"]],
  bab_el_mandeb: [["Oil Gas & Consumable Fuels", "Red Sea oil and gas route"]],
  suez: [["Oil Gas & Consumable Fuels", "Mediterranean-Red Sea oil route"]],
  taiwan: [["Automobile and Auto Components", "the auto industry's 2021-22 chip shortage traced back to Taiwan"], ["Consumer Durables", "electronics assembly depends on Taiwan-made chips"]],
  bosphorus: [["Oil Gas & Consumable Fuels", "Black Sea oil route"]],
};
function renderGlobeCards() {
  const el = $("#globe-cards"); if (!el) return;
  const G = S.globe;
  if (!G) { el.innerHTML = '<p class="empty">The globe data hasn\'t been published yet; it refreshes about every hour.</p>'; return; }
  const pts = G.chokepoints || [];
  const flag = activityFlag(pts);
  const secs = sectorStats();                                // real, live sector moves already computed for the Sectors tab
  el.innerHTML = pts.map(p => {
    const n = (p.flights && p.flights.count) || 0, news = p.news || [];
    const fl = flag(n);
    const badge = fl ? `<span class="gc-act ${fl}" title="${fl === "active" ? "More aircraft over this chokepoint right now than most of the other 6" : "Fewer aircraft over this chokepoint right now than most of the other 6"}">${fl === "active" ? "Active" : "Quiet"}</span>` : "";
    const secTags = (CHOKE_SECTORS[p.id] || []).map(([name, why]) => {
      const s = secs.find(x => x.k === name); if (!s) return "";
      return `<span class="gc-sec ${ud(s.avg)}" title="${esc(name)}: ${esc(why)}">${esc(name)} ${sg(s.avg)}%</span>`;
    }).filter(Boolean).join("");
    return `<div class="gc-card${globeSel === p.id ? " on" : ""}" data-id="${esc(p.id)}">
      <h4>${esc(p.name)}<span class="gc-r"><b>${n} flight${n === 1 ? "" : "s"} now</b>${badge}</span></h4>
      <p class="why">${esc(p.why)}</p>
      ${secTags ? `<div class="gc-secs"><span class="lbl">Exposed NSE sectors, real move today</span>${secTags}</div>` : ""}
      ${news.length ? `<ul>${news.slice(0, 3).map(a => `<li><a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a> <span class="src">· ${esc(a.source || "")} · ${esc(newsTimeAgo(a.seen_utc))}</span></li>`).join("")}</ul>`
        : '<p class="none">No recent news matched this chokepoint.</p>'}
    </div>`;
  }).join("");
  $$("#globe-cards .gc-card").forEach(c => c.onclick = () => selectChoke(c.dataset.id));
}

/* ================= open a security ================= */
async function openSec(sym) {
  if (!S.map.has(sym)) return;
  if (RP.on && !RP.syms.has(sym)) { toast(`Replay covers the NIFTY 50 only: exit replay to open ${sym}`); return; }
  sec = sym; eng.cancel(); descOpen = false; LIVE.dayVol = null; sendFocus();
  history.replaceState(null, "", `#v=${view}&s=${encodeURIComponent(sym)}`);
  $$("#watch .wl-row").forEach(r => r.classList.toggle("sel", r.dataset.s === sym));
  renderHead(); renderDetails();
  const k = shard(sym);
  await Promise.all([loadHist(k).catch(() => null), loadIntra(k).catch(() => null), loadDaily(sym)]);
  if (sym !== sec) return;
  const hasIntra = !!(intraOf(sym) && (intraOf(sym).d || []).length);
  if (!hasIntra && isIntra(iv) && !RP.on && !LIVE.ok) { iv = "D"; rg = "1Y"; syncRange(); }
  if (view === "terminal") drawChart(); else eng.load({ sym, iv, bars: [], intraday: false });
  renderDetails(); if (side === "prints") renderPrints();
}

/* ================= search ================= */
const FUNCS = { BRIEF: "Brief", TERMINAL: "Terminal", MOVERS: "Movers", SECTORS: "Sectors", WORLD: "World", OUTLOOK: "Outlook", NEWS: "News", WATCHLIST: "Watchlist", SETUP: "Set up desk", BACK: "Back to B-Lab", LOGOFF: "Log off" };
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
    if (document.querySelector(".eng-modal")) return;
    if (eng.cancel()) return;
    if (!$("#ct-menu").hidden) { $("#ct-menu").hidden = true; return; }
    if (!$("#iv-menu").hidden) { $("#iv-menu").hidden = true; return; }
    if (typing) { document.activeElement.blur(); return; }
    location.href = "advanced.html#signals"; return;
  }
  if (e.altKey && !typing) { const t = { t: "trend", h: "hline", v: "vline", f: "fib", r: "rect", m: "range", c: "cursor" }[e.key.toLowerCase()]; if (t) { go("terminal"); eng.setTool(t, stay); e.preventDefault(); } return; }
  if (!typing && view === "terminal" && (e.key === "Delete" || e.key === "Backspace") && eng.deleteSelected()) { e.preventDefault(); return; }
  if (!typing && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && view === "terminal") { e.preventDefault(); eng.undo(); return; }
  if (typing || e.ctrlKey || e.metaKey || !$("#onboard").hidden) return;
  if (e.key === " " && RP.on) { e.preventDefault(); $("#rp-play").click(); return; }
  if (e.key === "/") { e.preventDefault(); openSearch(); return; }
  if (e.key.length === 1 && /[a-z0-9]/i.test(e.key)) { e.preventDefault(); openSearch(e.key); }
});

boot();
