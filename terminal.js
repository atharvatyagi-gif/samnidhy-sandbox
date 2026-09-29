/* B-LAB TERMINAL (expert-terminal.html): a TradingView-style workspace for every NSE stock. Real data only.
   t/universe.json  all ~3,500 NSE securities (NSE end-of-day)        t/quotes.json  delayed live prices (~15 min)
   t/h/<k>.json     1 year of NSE daily candles (on demand)            t/i/<k>.json   intraday: {d: 5-min today, w: 15-min 5 days}
   t/fund.json      NIFTY 500 fundamentals                             live.json      world indices + news; screener.json today's screen
   Nothing is simulated: values change only when fresh data arrives. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const IST = "Asia/Kolkata";
const POLL_MS = 60000;
const COL = { up: "#00e060", upFill: "rgba(0,224,96,0.9)", down: "#e0a060", txt: "#e8dcc3", dim: "#83795f", bg: "#061a10", beige: "#b5a682" };
const LS = { get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };

const S = { uni: null, map: new Map(), quotes: {}, qmeta: {}, fund: null, live: {}, screen: {}, hist: {}, intra: {}, prevWei: {} };
let sec = null, iv = "D", rg = "1Y", ct = LS.get("blab-ct", "candle"), scaleMode = "auto", view = "wl";
let movMode = "gain", board = "All", sector = null;
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
const pctF = (v, d = 1) => v == null ? "--" : (v * 100).toFixed(d) + "%";
const shard = s => /[A-Z]/i.test(s[0]) ? s[0].toUpperCase() : "0";
const dp = p => p >= 1000 ? 1 : 2;
function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => el.classList.remove("show"), 2400); }

/* ---------------- quote: live if fresh, else NSE end-of-day ---------------- */
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
  $("#logout").onclick = async () => { try { await window.__expertSignOut?.(); } finally { location.replace("auth.html"); } };
}
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
    const [uni, quotes, live, screen] = await Promise.all([getJSON("t/universe.json"), getJSON("t/quotes.json").catch(() => ({})),
      getJSON("live.json").catch(() => ({})), getJSON("screener.json").catch(() => ({}))]);
    S.uni = uni; uni.stocks.forEach(s => S.map.set(s.s, s));
    S.quotes = quotes.quotes || {}; S.qmeta = quotes; S.live = live; S.screen = screen;
  } catch (e) {
    $("#st-data").textContent = "Data not available: the NSE stock list could not be loaded. Nothing is shown in its place.";
    showMsg("Data not available."); return;
  }
  const h = new URLSearchParams(location.hash.slice(1)).get("s");
  sec = h && S.map.has(h) ? h : (loadWatch()[0] || "RELIANCE");
  buildIndMenu(); renderStatus(); renderWatch(); renderMovers(); renderHeat(); renderWei(false); renderNews();
  await openSec(sec);
  getJSON("t/fund.json", false).then(f => { S.fund = f.stocks || {}; renderDetails(); }).catch(() => { S.fund = {}; renderDetails(); });
  setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
}
async function poll() {
  try {
    const [quotes, live] = await Promise.all([getJSON("t/quotes.json"), getJSON("live.json")]);
    if (quotes.generated_utc === S.qmeta.generated_utc) { S.live = live; return; }
    S.quotes = quotes.quotes || {}; S.qmeta = quotes; S.live = live;
    await loadIntra(shard(sec), true).catch(() => null);
    renderStatus(); renderWatch(); renderMovers(); renderHeat(); renderWei(true); renderNews(); renderDetails(); drawChart(true);
    if (view === "qr") renderPrints();
    toast("Prices updated · " + (quotes.last_bar_ist || "") + " IST");
  } catch (e) { /* keep last values */ }
}

function renderStatus() {
  const open = S.qmeta.market === "open", m = $("#mkt");
  m.className = "mkt" + (open ? " open" : "");
  m.querySelector("span").textContent = open ? "Market open · delayed" : "Market closed";
  $("#st-data").textContent = `Live ${S.qmeta.session_date || "--"} ${S.qmeta.last_bar_ist || ""} IST · updated ${S.qmeta.generated_ist || "--"} · NSE end-of-day ${S.uni.session_date}`;
  $("#st-cover").textContent = `${S.uni.count.toLocaleString("en-IN")} NSE securities · ${(S.qmeta.covered || 0).toLocaleString("en-IN")} with delayed live prices · SME = NSE end-of-day`;
}

/* ================= CHART ================= */
let chart = null, sMain = null, extra = {}, bars = [], drawSeries = [], priceLines = [];
const LC = () => window.LightweightCharts;
function showMsg(t) { const m = $("#chart-msg"); m.textContent = t || ""; m.classList.toggle("show", !!t); }

// intraday "HH:MM" on a date -> a timestamp the chart shows as IST
const ts = (dateStr, hhmm) => { const [y, m, d] = dateStr.split("-").map(Number), [hh, mm] = hhmm.split(":").map(Number); return Date.UTC(y, m - 1, d, hh, mm) / 1000; };
function candlesFor(sym, interval) {
  const x = q(sym);
  if (["5m", "15m", "1h"].includes(interval)) {
    const it = intraOf(sym); if (!it) return [];
    if (interval === "5m") { const day = (S.quotes[sym] || {}).d || S.qmeta.session_date; return it.d.map(r => ({ time: ts(day, r[0]), o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: day + " " + r[0] })); }
    const w = (it.w || []).map(r => { const [d, t] = r[0].split(" "); return { time: ts(d, t), o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], lbl: r[0], d, t }; });
    if (interval === "15m") return w;
    const out = [];                                            // 1h buckets anchored at 09:15 IST, like NSE charts
    for (const b of w) {
      const [hh, mm] = b.t.split(":").map(Number), k = Math.floor(((hh * 60 + mm) - 555) / 60), start = 555 + k * 60;
      const hm = String(Math.floor(start / 60)).padStart(2, "0") + ":" + String(start % 60).padStart(2, "0"), key = b.d + " " + hm;
      const last = out[out.length - 1];
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
    const dt = new Date(b.time + "T00:00:00Z");
    let key;
    if (interval === "W") { const m = new Date(dt); m.setUTCDate(dt.getUTCDate() - ((dt.getUTCDay() + 6) % 7)); key = m.toISOString().slice(0, 10); }
    else key = b.time.slice(0, 7);
    const last = out[out.length - 1];
    if (last && last.key === key) { last.h = Math.max(last.h, b.h); last.l = Math.min(last.l, b.l); last.c = b.c; last.v += b.v; }
    else out.push({ key, time: b.time, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, lbl: interval === "W" ? "Week of " + b.time : b.time.slice(0, 7) });
  }
  return out;
}
// ---- indicator maths ----
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
  const L = LC();
  if (!L) { showMsg("The chart library could not load. Check your connection and reload."); return; }
  const prevRange = keepRange && chart ? chart.timeScale().getVisibleLogicalRange() : null;
  if (chart) { chart.remove(); chart = null; }
  extra = {}; drawSeries = []; priceLines = []; measureSeries = null;
  bars = candlesFor(sec, iv);
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
    layout: { background: { type: "solid", color: COL.bg }, textColor: COL.dim, fontFamily: "Consolas, 'Cascadia Mono', monospace", fontSize: 11, attributionLogo: false,
      panes: { separatorColor: "rgba(181,166,130,0.3)", separatorHoverColor: "rgba(181,166,130,0.5)", enableResize: true } },
    grid: { vertLines: { color: "rgba(181,166,130,0.06)" }, horzLines: { color: "rgba(181,166,130,0.06)" } },
    rightPriceScale: { borderColor: "rgba(181,166,130,0.3)", scaleMargins: { top: 0.14, bottom: inds.has("vol") ? 0.2 : 0.06 }, mode: { auto: 0, log: 1, pct: 2 }[scaleMode] },
    timeScale: { borderColor: "rgba(181,166,130,0.3)", timeVisible: intraday, secondsVisible: false, rightOffset: 6, barSpacing: intraday ? 7 : 6 },
    crosshair: { mode: magnet ? 1 : 0, vertLine: { color: "rgba(232,220,195,0.4)", style: 3, labelBackgroundColor: "#11352a" }, horzLine: { color: "rgba(232,220,195,0.4)", style: 3, labelBackgroundColor: "#11352a" } },
    localization: { priceFormatter: p => inr(p, dp(Math.abs(p))) },
  });
  try { L.createTextWatermark(chart.panes()[0], { horzAlign: "center", vertAlign: "center", lines: [{ text: sec, color: "rgba(181,166,130,0.08)", fontSize: 64, fontStyle: "bold" }, { text: `${iv} · NSE`, color: "rgba(181,166,130,0.08)", fontSize: 18 }] }); } catch (e) {}

  const cs = { upColor: COL.upFill, downColor: COL.down, borderUpColor: COL.up, borderDownColor: COL.down, wickUpColor: COL.up, wickDownColor: COL.down, priceLineColor: COL.txt, priceLineStyle: 2 };
  if (ct === "candle") sMain = chart.addSeries(L.CandlestickSeries, cs);
  else if (ct === "bars") sMain = chart.addSeries(L.BarSeries, { upColor: COL.up, downColor: COL.down, thinBars: false, priceLineColor: COL.txt });
  else if (ct === "line") sMain = chart.addSeries(L.LineSeries, { color: COL.up, lineWidth: 2, priceLineColor: COL.txt });
  else sMain = chart.addSeries(L.AreaSeries, { lineColor: COL.up, topColor: "rgba(0,224,96,0.3)", bottomColor: "rgba(0,224,96,0.02)", lineWidth: 2, priceLineColor: COL.txt });
  sMain.setData(bars.map(b => ["candle", "bars"].includes(ct) ? { time: b.time, open: b.o, high: b.h, low: b.l, close: b.c } : { time: b.time, value: b.c }));

  const c = bars.map(b => b.c);
  const line = (vals, color, pane = 0, w = 1.5, more = {}) => {
    const s = chart.addSeries(L.LineSeries, { color, lineWidth: w, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...more }, pane);
    s.setData(vals.map((v, i) => v == null ? { time: bars[i].time } : { time: bars[i].time, value: +v.toFixed(2) })); return s;
  };
  const colorOf = id => INDS.find(i => i.id === id).color;
  if (inds.has("vol")) {
    extra.vol = chart.addSeries(L.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    extra.vol.setData(bars.map(b => ({ time: b.time, value: b.v || 0, color: b.c >= b.o ? "rgba(0,224,96,0.28)" : "rgba(224,160,96,0.32)" })));
  }
  for (const [id, n] of [["sma20", 20], ["sma50", 50], ["sma200", 200]]) if (inds.has(id)) { const v = smaA(c, n); extra[id] = [line(v, colorOf(id)), v]; }
  if (inds.has("ema20")) { const v = emaA(c, 20); extra.ema20 = [line(v, colorOf("ema20")), v]; }
  if (inds.has("bb")) { const b = bbA(c), col = colorOf("bb"); extra.bb = [[line(b.map(x => x && x[0]), col, 0, 1), line(b.map(x => x && x[1]), col, 0, 1, { lineStyle: 2 }), line(b.map(x => x && x[2]), col, 0, 1)], b]; }
  if (inds.has("vwap") && intraday) { const v = vwapA(bars); extra.vwap = [line(v, colorOf("vwap"), 0, 1.6), v]; }
  let pane = 1;
  if (inds.has("rsi")) {
    const r = rsiA(c), s = line(r, colorOf("rsi"), pane, 1.5);
    s.createPriceLine({ price: 70, color: "rgba(224,160,96,0.55)", lineStyle: 2, axisLabelVisible: false });
    s.createPriceLine({ price: 30, color: "rgba(0,224,96,0.55)", lineStyle: 2, axisLabelVisible: false });
    extra.rsi = [s, r]; pane++;
  }
  if (inds.has("macd")) {
    const m = macdA(c), h = chart.addSeries(L.HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
    h.setData(m.map((x, i) => x[2] == null ? { time: bars[i].time } : { time: bars[i].time, value: +x[2].toFixed(3), color: x[2] >= 0 ? "rgba(0,224,96,0.5)" : "rgba(224,160,96,0.55)" }));
    extra.macd = [[h, line(m.map(x => x[0]), "#e8dcc3", pane, 1.3), line(m.map(x => x[1]), "#e0a060", pane, 1.3)], m]; pane++;
  }
  const sizePanes = () => { try { chart.panes().forEach((p, i) => { if (p.setStretchFactor) p.setStretchFactor(i === 0 ? 4 : 1); else if (i > 0) p.setHeight(120); }); } catch (e) {} };
  sizePanes(); requestAnimationFrame(sizePanes);

  applyDrawings();
  chart.subscribeCrosshairMove(p => legend(p));
  chart.subscribeClick(onChartClick);
  if (prevRange) chart.timeScale().setVisibleLogicalRange(prevRange); else applyRange();
  legend();
}
function applyRange() {
  if (!chart || !bars.length) return;
  const n = bars.length; let from = 0;
  if (iv === "D") {
    if (rg === "YTD") { const y = new Date().getFullYear() + "-01-01"; from = Math.max(0, bars.findIndex(b => String(b.time) >= y)); }
    else { const days = { "1M": 22, "3M": 64, "6M": 127 }[rg]; if (days) from = Math.max(0, n - days); }
  }
  chart.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: n + 5 });
}

/* ---------------- legend (follows the crosshair) ---------------- */
function legend(p) {
  const s = S.map.get(sec), x = q(sec); if (!s) return;
  let i = bars.length - 1;
  if (p && p.time != null) { const j = bars.findIndex(b => b.time === p.time); if (j >= 0) i = j; }
  const b = bars[i], prev = i > 0 ? bars[i - 1].c : (x && x.pc);
  const ch = b && prev ? b.c - prev : null, chp = b && prev ? ch / prev * 100 : null;
  const live = x && x.live, open = S.qmeta.market === "open";
  let html = `<div class="lg-main"><span class="lg-title">${esc(sec)} <small>· ${esc(iv)} · NSE${s.board === "SME" ? " SME" : ""}</small></span>
    <span class="lg-dot" style="background:${live && open ? "var(--accent)" : live ? "var(--beige)" : "var(--down)"}" title="${live && open ? "Market open, delayed" : live ? "Last session" : "NSE end-of-day"}"></span>`;
  if (b) html += `<span class="lg-ohlc">O<b class="${ud(ch)}">${inr(b.o)}</b> H<b class="${ud(ch)}">${inr(b.h)}</b> L<b class="${ud(ch)}">${inr(b.l)}</b> C<b class="${ud(ch)}">${inr(b.c)}</b>
      <b class="${ud(ch)}">${sg(ch)} (${sg(chp)}%)</b>${b.v != null ? ` &nbsp;Vol<b>${big(b.v)}</b>` : ""} &nbsp;<span class="dim">${esc(b.lbl)}</span></span>`;
  html += `</div><div class="lg-ind">`;
  for (const d of INDS) {
    if (d.id === "vol" || !extra[d.id]) continue;
    const e = extra[d.id][1][i];
    let v = "--";
    if (d.id === "bb") v = e ? `${inr(e[0])} ${inr(e[1])} ${inr(e[2])}` : "--";
    else if (d.id === "rsi") v = e != null ? e.toFixed(1) : "--";
    else if (d.id === "macd") v = e && e[0] != null ? `${e[0].toFixed(2)} ${e[1] != null ? e[1].toFixed(2) : "--"} ${e[2] != null ? e[2].toFixed(2) : ""}` : "--";
    else v = e != null ? inr(e) : "--";
    html += `<span><i style="color:${d.color}">■</i> ${esc(d.name)} <b style="color:${d.color}">${v}</b></span>`;
  }
  $("#legend").innerHTML = html + "</div>";
}

/* ---------------- toolbar ---------------- */
function syncRangeButtons() { $$("#rg-grp button").forEach(b => b.classList.toggle("on", b.dataset.rg === rg)); }
$$("#iv-grp button").forEach(b => b.onclick = () => {
  if (b.disabled) return;
  iv = b.dataset.iv;
  rg = { "5m": "1D", "15m": "5D", "1h": "5D" }[iv] || (["1D", "5D"].includes(rg) ? "1Y" : rg);
  syncRangeButtons(); drawChart();
});
$$("#rg-grp button").forEach(b => b.onclick = () => {
  if (b.disabled) return;
  rg = b.dataset.rg; syncRangeButtons();
  const want = rg === "1D" ? "5m" : rg === "5D" ? "15m" : (["5m", "15m", "1h"].includes(iv) || ["W", "M"].includes(iv) ? "D" : iv);
  if (want !== iv) { iv = want; drawChart(); } else applyRange();
});
$$("#ct-grp button").forEach(b => { b.classList.toggle("on", b.dataset.ct === ct); b.onclick = () => { ct = b.dataset.ct; LS.set("blab-ct", ct); $$("#ct-grp button").forEach(x => x.classList.toggle("on", x === b)); drawChart(true); }; });
$$("#sc-grp button").forEach(b => b.onclick = () => { scaleMode = b.dataset.sc; $$("#sc-grp button").forEach(x => x.classList.toggle("on", x === b)); chart?.priceScale("right").applyOptions({ mode: { auto: 0, log: 1, pct: 2 }[scaleMode] }); });
$("#snap").onclick = () => {
  if (!chart) return;
  const a = document.createElement("a");
  a.href = chart.takeScreenshot().toDataURL("image/png"); a.download = `${sec}_${iv}_${new Date().toISOString().slice(0, 10)}.png`; a.click(); toast("Chart image saved");
};
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

/* ---------------- drawing tools (saved in this browser, per stock) ---------------- */
const DKEY = "blab-draw";
const drawingsOf = sym => (LS.get(DKEY, {})[sym] || []);
function saveDrawings(sym, list) { const all = LS.get(DKEY, {}); all[sym] = list; LS.set(DKEY, all); }
let measureSeries = null, measureShown = false;
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
  else if (a === "hide") { hideDraw = !hideDraw; b.classList.toggle("on", hideDraw); applyDrawings(); }
  else if (a === "clear") { saveDrawings(sec, []); clearMeasure(); applyDrawings(); toast("Drawings removed for " + sec); }
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
    if (d.type === "h") priceLines.push(sMain.createPriceLine({ price: d.price, color: COL.beige, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "" }));
    else if (d.type === "t" && d.iv === iv && d.a.time !== d.b.time) {
      const s = chart.addSeries(LC().LineSeries, { color: COL.txt, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData([d.a, d.b].sort((m, n) => (m.time > n.time ? 1 : -1))); drawSeries.push(s);
    }
  }
}
function pointAt(p) {
  if (!p || p.time == null || !p.point) return null;
  let price = sMain.coordinateToPrice(p.point.y);
  if (price == null) return null;
  if (magnet) { const b = bars.find(x => x.time === p.time); if (b) price = [b.o, b.h, b.l, b.c].reduce((a, v) => Math.abs(v - price) < Math.abs(a - price) ? v : a, b.c); }
  return { time: p.time, value: +price.toFixed(2) };
}
function onChartClick(p) {
  if (tool === "cross") return;
  const pt = pointAt(p); if (!pt) return;
  if (tool === "hline") { saveDrawings(sec, [...drawingsOf(sec), { type: "h", price: pt.value }]); applyDrawings(); setTool("cross"); toast(`Horizontal line at ₹${inr(pt.value)}`); return; }
  if (!pending) { pending = pt; $("#tool-hint").textContent = tool === "trend" ? "Trend line: click the second point" : "Measure: click the end point"; return; }
  if (tool === "trend") { saveDrawings(sec, [...drawingsOf(sec), { type: "t", iv, a: pending, b: pt }]); applyDrawings(); setTool("cross"); return; }
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

/* ================= SIDEBAR ================= */
$$("#rail button").forEach(b => b.onclick = () => setView(b.dataset.view));
function setView(v) {
  view = v;
  $$("#rail button").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  $$(".side-view").forEach(el => el.hidden = el.dataset.view !== v);
  if (v === "qr") renderPrints();
}

/* ---- watchlist + details ---- */
function loadWatch() {
  const w = LS.get("blab-watch", null);
  if (Array.isArray(w) && w.length) return w.filter(s => S.map.has(s));
  return (S.screen.picks || []).map(p => p.symbol).filter(s => S.map.has(s));
}
function renderWatch() {
  const w = loadWatch();
  $("#watch").innerHTML = w.length ? w.map(sym => { const x = q(sym);
    return `<div class="wl-row ${sym === sec ? "sel" : ""}" data-s="${esc(sym)}"><span class="s">${esc(sym)}</span><span>${inr(x?.p)}</span>
      <span class="${ud(x?.chg)}">${sg(x?.chg)}</span><span class="${ud(x?.pct)}">${sg(x?.pct)}%</span><button class="x" data-rm="${esc(sym)}" title="Remove">×</button></div>`; }).join("")
    : '<div class="empty">Your watchlist is empty. Open a stock and press + Add.</div>';
  $$("#watch .wl-row").forEach(r => r.onclick = e => {
    if (e.target.dataset.rm) { LS.set("blab-watch", loadWatch().filter(s => s !== e.target.dataset.rm)); renderWatch(); return; }
    openSec(r.dataset.s);
  });
}
$("#wl-add").onclick = () => { const w = loadWatch(); if (w.includes(sec)) { toast(sec + " is already on your watchlist"); return; } LS.set("blab-watch", [sec, ...w].slice(0, 50)); renderWatch(); toast(sec + " added to watchlist"); };

const REC = { strong_buy: "Strong buy", buy: "Buy", hold: "Hold", underperform: "Underperform", sell: "Sell" };
function perfFrom(sym) {
  const h = histOf(sym), x = q(sym); if (!h.length || !x) return null;
  const last = x.p, closes = h.map(r => r[4]);
  if (!(x.live && x.d > h[h.length - 1][0])) closes.pop();         // history already includes today: measure from the bar before
  const back = n => closes.length >= n ? closes[closes.length - n] : null;
  const y = new Date().getFullYear() + "-01-01", before = h.filter(r => r[0] < y), ytdBase = before.length ? before[before.length - 1][4] : null;
  const f = b => b ? (last / b - 1) * 100 : null;
  return [["1W", f(back(5))], ["1M", f(back(21))], ["3M", f(back(63))], ["6M", f(back(126))], ["YTD", f(ytdBase)], ["1Y", f(h[0][4])]];
}
function rangeBar(lbl, lo, hi, v) {
  if (lo == null || hi == null || hi <= lo) return "";
  const pos = Math.max(0, Math.min(100, (v - lo) / (hi - lo) * 100));
  return `<div class="rbar"><div class="lbl"><span>${lbl}</span></div><div class="trk"><em style="width:${pos}%"></em><i style="left:calc(${pos}% - 1px)"></i></div>
    <div class="lbl"><span>${inr(lo, dp(lo))}</span><span>${inr(hi, dp(hi))}</span></div></div>`;
}
let descOpen = false;
function renderDetails() {
  const s = S.map.get(sec), x = q(sec); if (!s || !x) return;
  const f = S.fund ? (S.fund[sec] || null) : undefined, pick = (S.screen.picks || []).find(p => p.symbol === sec);
  const open = S.qmeta.market === "open";
  const when = x.live ? (open ? `Delayed live price · ${x.t} IST · market open` : `Last session ${x.d} · last price ${x.t} IST`) : `NSE official end-of-day · ${x.d}`;
  const stat = (k, v) => `<div><span>${k}</span><b>${v}</b></div>`;
  const perf = perfFrom(sec);
  let html = `<div class="d-top"><span class="d-logo">${esc(sec[0])}</span><div><div class="d-sym">${esc(sec)}</div><div class="d-name">${esc(s.n)}</div></div></div>
    <div class="tagrow"><span class="tag">NSE</span><span class="tag">${esc(s.series)}</span>${s.board === "SME" ? '<span class="tag o">SME</span>' : ""}${s.etf ? '<span class="tag">ETF</span>' : ""}
      ${s.n500 ? '<span class="tag">NIFTY 500</span>' : ""}${pick ? `<span class="tag g">B-Lab screen #${pick.magic_rank}</span>` : ""}${s.ind ? `<span class="tag">${esc(s.ind)}</span>` : ""}</div>
    <div class="d-px"><span class="p ${ud(x.chg)}">₹${inr(x.p)}</span><span class="c ${ud(x.chg)}">${sg(x.chg)} (${sg(x.pct)}%)</span></div>
    <div class="d-when">${esc(when)}</div>
    ${rangeBar("Day's range", x.l, x.h, x.p)}${rangeBar("52-week range", s.lo52, s.hi52, x.p)}
    <div class="sec-t">Key stats</div>
    <div class="stats">${stat("Open", inr(x.o))}${stat("Prev close", inr(x.pc))}${stat("Volume", big(x.v))}${stat("Avg vol (20D)", big(s.avgv20))}
      ${stat("Value", x.v != null ? cr(x.v * x.p / 1e7) : "--")}${stat("Delivery (EOD)", s.deliv == null ? "--" : s.deliv.toFixed(1) + "%")}
      ${f ? stat("Market cap", f.mcap ? cr(f.mcap / 1e7) : "--") + stat("P/E (TTM)", f.pe ? f.pe.toFixed(1) : "--") + stat("EPS (TTM)", f.eps != null ? "₹" + inr(f.eps) : "--")
        + stat("Div yield", f.dy != null ? f.dy.toFixed(2) + "%" : "--") + stat("P/B", f.pb ? f.pb.toFixed(2) : "--") + stat("Beta", f.beta != null ? f.beta.toFixed(2) : "--")
        + stat("ROE", pctF(f.roe)) + stat("Debt/equity", f.de != null ? (f.de / 100).toFixed(2) : "--") : ""}</div>`;
  if (perf) html += `<div class="sec-t">Performance</div><div class="perf">${perf.map(([k, v]) => `<div class="${v == null ? "" : v >= 0 ? "pu" : "pd"}"><span>${k}</span><b class="${ud(v)}">${v == null ? "--" : sg(v, 1) + "%"}</b></div>`).join("")}</div>`;
  if (f && (f.rec || f.tgt)) {
    const pos = { strong_buy: 95, buy: 75, hold: 50, underperform: 25, sell: 5 }[f.rec] ?? 50, up = f.tgt ? (f.tgt / x.p - 1) * 100 : null;
    html += `<div class="sec-t">Analyst view</div><div class="gauge"><i style="left:calc(${pos}% - 2px)"></i></div><div class="g-l"><span>Sell</span><span>Hold</span><span>Buy</span></div>
      <div class="stats" style="margin-top:10px">${stat("Consensus", f.rec ? REC[f.rec] || f.rec : "--")}${stat("Analysts", f.an ?? "--")}${stat("Target (mean)", f.tgt ? "₹" + inr(f.tgt, 0) : "--")}${stat("Upside", up == null ? "--" : `<span class="${ud(up)}">${sg(up, 1)}%</span>`)}${stat("Target low", f.tgt_lo ? "₹" + inr(f.tgt_lo, 0) : "--")}${stat("Target high", f.tgt_hi ? "₹" + inr(f.tgt_hi, 0) : "--")}</div>
      <p class="note">12-month targets from brokerage analysts (Yahoo Finance). On average analysts are too optimistic.</p>`;
  }
  if (pick) html += `<div class="sec-t">B-Lab screen</div><div class="stats">${stat("Magic rank", "#" + pick.magic_rank + " of " + pick.of)}${stat("F-Score", pick.fscore + "/9")}${stat("Return on capital", pctF(pick.roc))}${stat("Earnings yield", pctF(pick.earnings_yield))}</div>`;
  html += `<div class="sec-t">Profile</div>`;
  if (f === undefined) html += `<p class="note">Loading…</p>`;
  else if (f) html += `<div class="stats">${stat("Sector", esc(f.sector || "--"))}${stat("Employees", f.emp ? Math.round(f.emp).toLocaleString("en-IN") : "--")}${stat("ISIN", esc(s.isin || "--"))}${stat("Listed", esc(s.listed || "--"))}</div>
      ${f.desc ? `<p class="desc ${descOpen ? "" : "clamp"}" style="margin-top:10px">${esc(f.desc)}</p><button class="more" id="more">${descOpen ? "Show less" : "Show more"}</button>` : ""}
      ${f.web ? `<p class="note" style="margin-top:6px">${esc(f.web)}</p>` : ""}`;
  else html += `<div class="stats">${stat("ISIN", esc(s.isin || "--"))}${stat("Listed", esc(s.listed || "--"))}${stat("Series", esc(s.series))}${stat("Board", esc(s.board))}</div>
      <p class="note" style="margin-top:8px">${s.etf ? `${esc(sec)} is an exchange-traded fund, not a company.` : `Company fundamentals are loaded for NIFTY 500 companies; ${esc(sec)} is outside it.`} Only NSE's official trading data is shown. Nothing is estimated.</p>`;
  $("#details").innerHTML = html;
  const more = $("#more"); if (more) more.onclick = () => { descOpen = !descOpen; renderDetails(); };
}

/* ---- movers ---- */
function renderMovers() {
  const rows = S.uni.stocks.filter(s => (board === "All" || s.board === board) && (!sector || s.ind === sector)).map(s => ({ s, x: q(s.s) })).filter(r => r.x && r.x.p != null);
  let list;
  if (movMode === "gain") list = rows.filter(r => r.x.pct != null && r.s.v > 0).sort((a, b) => b.x.pct - a.x.pct);
  else if (movMode === "lose") list = rows.filter(r => r.x.pct != null && r.s.v > 0).sort((a, b) => a.x.pct - b.x.pct);
  else if (movMode === "val") list = rows.map(r => ({ ...r, val: (r.x.v || 0) * r.x.p })).sort((a, b) => b.val - a.val);
  else if (movMode === "hi") list = rows.filter(r => r.s.hi52 && r.x.h >= r.s.hi52 * 0.999).sort((a, b) => b.x.pct - a.x.pct);
  else list = rows.filter(r => r.s.lo52 && r.x.l <= r.s.lo52 * 1.001).sort((a, b) => a.x.pct - b.x.pct);
  list = list.slice(0, 80);
  const mx = Math.max(...list.map(r => Math.abs(r.x.pct || 0)), 1);
  $("#movers").innerHTML = list.length ? list.map(r => `<div class="m-row" data-s="${esc(r.s.s)}"><span class="s">${esc(r.s.s)}${r.s.board === "SME" ? ' <span class="tag o">SME</span>' : ""}</span>
      <span class="p">${inr(r.x.p)}</span><span class="n">${esc(r.s.n)}</span><span class="c ${ud(r.x.pct)}">${movMode === "val" ? "₹" + big(r.val) : sg(r.x.pct) + "%"}</span>
      <i class="bar" style="width:${Math.abs(r.x.pct || 0) / mx * 100}%;background:${r.x.pct >= 0 ? "var(--up)" : "var(--down)"}"></i></div>`).join("")
    : '<div class="empty">No stocks match.</div>';
  $$("#movers .m-row").forEach(el => el.onclick = () => openSec(el.dataset.s));
  const note = $("#sector-note");
  note.hidden = !sector;
  if (sector) { note.innerHTML = `<span>Sector: <b>${esc(sector)}</b></span><button id="clr-sec">Clear ✕</button>`; $("#clr-sec").onclick = () => { sector = null; renderMovers(); renderHeat(); }; }
}
$$("#mov-tabs button").forEach(b => b.onclick = () => { movMode = b.dataset.m; $$("#mov-tabs button").forEach(x => x.classList.toggle("on", x === b)); renderMovers(); });
$$("#board-grp button").forEach(b => b.onclick = () => { board = b.dataset.b; $$("#board-grp button").forEach(x => x.classList.toggle("on", x === b)); renderMovers(); });

/* ---- breadth + sector heatmap ---- */
function renderHeat() {
  let a = 0, d = 0, u = 0; const g = {};
  for (const s of S.uni.stocks) {
    const x = q(s.s); if (!x || x.pct == null) continue;
    x.pct > 0 ? a++ : x.pct < 0 ? d++ : u++;
    if (s.ind) (g[s.ind] = g[s.ind] || []).push(x.pct);
  }
  const t = a + d + u || 1;
  $("#breadth").innerHTML = `<div class="b-bar"><i style="width:${a / t * 100}%;background:var(--up)"></i><i style="width:${u / t * 100}%;background:var(--dim)"></i><i style="width:${d / t * 100}%;background:var(--down)"></i></div>
    <div class="b-leg"><span class="up">▲ ${a.toLocaleString("en-IN")} advancing</span><span class="dim">${u}</span><span class="down">▼ ${d.toLocaleString("en-IN")} declining</span></div>`;
  const tiles = Object.entries(g).map(([k, v]) => ({ k, n: v.length, avg: v.reduce((x, y) => x + y, 0) / v.length, up: v.filter(x => x > 0).length })).sort((x, y) => y.avg - x.avg);
  $("#heat").innerHTML = tiles.map(t => { const al = Math.min(1, Math.abs(t.avg) / 2.5), bg = t.avg >= 0 ? `rgba(0,224,96,${0.1 + al * 0.45})` : `rgba(224,160,96,${0.12 + al * 0.5})`;
    return `<button class="${sector === t.k ? "on" : ""}" style="background:${bg}" data-k="${esc(t.k)}"><span>${esc(t.k)}</span><b>${sg(t.avg)}%</b><small>${t.up} of ${t.n} up</small></button>`; }).join("")
    || '<div class="empty">No sector data.</div>';
  $$("#heat button").forEach(b => b.onclick = () => { sector = sector === b.dataset.k ? null : b.dataset.k; renderHeat(); renderMovers(); if (sector) setView("mov"); });
}

/* ---- world indices, news, prints ---- */
function renderWei(flash) {
  const rows = S.live.indices || [], tb = $("#wei tbody");
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="4" class="empty">Index data not available.</td></tr>'; return; }
  let html = "", rgn = null;
  for (const r of rows) {
    if (r.region !== rgn) { rgn = r.region; html += `<tr class="rg"><td colspan="4">${esc(rgn.toUpperCase())}</td></tr>`; }
    if (r.error) { html += `<tr><td class="code">${esc(r.code)}<small>${esc(r.name)}</small></td><td class="r dim" colspan="3">N/A</td></tr>`; continue; }
    const p = S.prevWei[r.code], fl = flash && p != null && p !== r.value ? (r.value > p ? "flash-up" : "flash-down") : "";
    html += `<tr><td class="code">${esc(r.code)}<small>${esc(r.name)} · ${esc(r.time)}</small></td><td class="r ${fl}">${us(r.value)}</td><td class="r ${ud(r.pct)}">${sg(r.pct)}%</td><td class="r ${ud(r.ytd)}">${r.ytd == null ? "--" : sg(r.ytd, 1) + "%"}</td></tr>`;
  }
  rows.forEach(r => { if (!r.error) S.prevWei[r.code] = r.value; });
  tb.innerHTML = html;
  $("#wei-asof").textContent = S.live.generated_ist ? "updated " + S.live.generated_ist.replace(/^.*?, /, "") : "";
}
function newsTime(iso) {
  const d = new Date(iso), same = d.toLocaleDateString("en-CA", { timeZone: IST }) === new Date().toLocaleDateString("en-CA", { timeZone: IST });
  return same ? d.toLocaleTimeString("en-GB", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false }) : d.toLocaleDateString("en-GB", { timeZone: IST, day: "numeric", month: "short" });
}
function renderNews() {
  const items = [...(S.live.news || [])].sort((a, b) => ((b.tickers || []).includes(sec)) - ((a.tickers || []).includes(sec)));
  $("#news").innerHTML = items.length ? items.map(n => `<li class="${(n.tickers || []).includes(sec) ? "hit" : ""}">${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}
      <span class="meta"><b>${newsTime(n.time_utc)}</b> · ${esc(n.publisher || "")} ${(n.tickers || []).map(t => `<em>${esc(t)}</em>`).join(" ")}</span></li>`).join("")
    : '<li class="empty">No headlines available.</li>';
}
function renderPrints() {
  const it = intraOf(sec), rows = it ? it.d : [];
  $("#qr-sym").textContent = sec + (rows.length ? " · 5-min" : "");
  if (!rows.length) { $("#prints").innerHTML = '<div class="empty">No intraday prints for this stock (SME stocks have NSE end-of-day data only).</div>'; return; }
  const pc = q(sec)?.pc;
  $("#prints").innerHTML = `<table class="prints"><thead><tr><th>Time</th><th>Last</th><th>Chg</th><th>High</th><th>Low</th><th>Vol</th></tr></thead><tbody>${rows.map((r, i) => {
    const prev = i ? rows[i - 1][4] : pc, ch = prev != null ? r[4] - prev : null;
    return `<tr><td class="dim">${esc(r[0])}</td><td class="${ud(ch)}">${inr(r[4])}</td><td class="${ud(ch)}">${ch == null ? "--" : (ch > 0 ? "▲" : ch < 0 ? "▼" : "=") + inr(Math.abs(ch))}</td><td>${inr(r[2])}</td><td>${inr(r[3])}</td><td class="dim">${big(r[5])}</td></tr>`;
  }).reverse().join("")}</tbody></table>`;
}

/* ================= open a security ================= */
async function openSec(sym) {
  if (!S.map.has(sym)) return;
  sec = sym; pending = null; clearMeasure();
  history.replaceState(null, "", "#s=" + encodeURIComponent(sym));
  const s = S.map.get(sym);
  $("#sp-sym").textContent = sym; $("#sp-name").textContent = s.n;
  document.title = `${sym} ₹${inr(q(sym)?.p)} · B-LAB TERMINAL`;
  $$("#watch .wl-row").forEach(r => r.classList.toggle("sel", r.dataset.s === sym));
  descOpen = false; renderDetails(); renderNews();
  const k = shard(sym);
  await Promise.all([loadHist(k).catch(() => null), loadIntra(k).catch(() => null)]);
  if (sym !== sec) return;
  const hasIntra = !!(intraOf(sym) && intraOf(sym).d && intraOf(sym).d.length);
  $$('#iv-grp [data-iv="5m"], #iv-grp [data-iv="15m"], #iv-grp [data-iv="1h"], #rg-grp [data-rg="1D"], #rg-grp [data-rg="5D"]').forEach(b => { b.disabled = !hasIntra; b.title = hasIntra ? "" : "No intraday data for this stock"; });
  if (!hasIntra && ["5m", "15m", "1h"].includes(iv)) { iv = "D"; rg = "1Y"; syncRangeButtons(); }
  drawChart(); renderDetails(); if (view === "qr") renderPrints();
}

/* ================= symbol search dialog ================= */
const FUNCS = { HELP: "Keyboard & commands", WL: "Watchlist", MOV: "NSE movers", MAP: "Sectors & breadth", WEI: "World indices", TOP: "News", QR: "Intraday prints", BACK: "Back to B-Lab", LOGOFF: "Sign out" };
let qFilter = "all", qOpts = [], qAct = 0;
function openSearch(initial = "") { $("#search").hidden = false; const i = $("#q"); i.value = initial; i.focus(); runSearch(); }
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
    else {
      const nw = s.n.toUpperCase().split(/[^A-Z0-9&]+/), nameHit = words.every(t => nw.some(w => w.startsWith(t)));
      sc = s.s === joined ? 0 : s.s.startsWith(joined) ? 1 : nameHit && nw[0].startsWith(words[0]) ? 2 : nameHit ? 3 : s.s.includes(joined) ? 4 : 9;
    }
    if (sc < 9) out.push([sc, -((s.v || 0) * (s.c || 0)), s]);
  }
  out.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  qOpts = [...fns, ...out.slice(0, 50).map(r => ({ s: r[2] }))]; qAct = 0;
  $("#q-list").innerHTML = qOpts.map((o, i) => {
    if (o.fn) return `<li role="option" data-i="${i}" aria-selected="${i === qAct}"><span class="lg">&#8984;</span><span class="fn">${o.fn}</span><span class="n">${esc(FUNCS[o.fn])}</span><span class="t">command</span><span></span></li>`;
    const x = q(o.s.s);
    return `<li role="option" data-i="${i}" aria-selected="${i === qAct}"><span class="lg">${esc(o.s.s[0])}</span><span class="s">${esc(o.s.s)}</span><span class="n">${esc(o.s.n)}</span>
      <span class="t">${o.s.etf ? "ETF" : o.s.board === "SME" ? "SME" : "Stock"} · NSE</span><span class="q">${inr(x?.p)} <span class="${ud(x?.pct)}">${sg(x?.pct)}%</span></span></li>`;
  }).join("") || '<li class="empty">No matches.</li>';
  $("#q-foot").textContent = `${S.uni.count.toLocaleString("en-IN")} NSE securities · ↑ ↓ to move · Enter to open · Esc to close`;
}
function paintQ() { $$("#q-list li[role=option]").forEach(li => li.setAttribute("aria-selected", String(+li.dataset.i === qAct))); $("#q-list li[aria-selected=true]")?.scrollIntoView({ block: "nearest" }); }
function chooseQ(o) {
  closeSearch();
  if (!o) return;
  if (o.s) { openSec(o.s.s); return; }
  const f = o.fn;
  if (f === "BACK") location.href = "advanced.html#signals";
  else if (f === "LOGOFF") $("#logout").click();
  else if (f === "HELP") toast("/ or any letter: search · Alt+T trend line · Alt+H horizontal line · Alt+M measure · Esc: cancel, then back");
  else setView({ WL: "wl", MOV: "mov", MAP: "map", WEI: "wei", TOP: "news", QR: "qr" }[f]);
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
$("#sym-pill").onclick = () => openSearch();

/* ================= keyboard ================= */
document.addEventListener("keydown", e => {
  const typing = /INPUT|TEXTAREA/.test(document.activeElement.tagName);
  if (e.key === "Escape") {
    if (!$("#search").hidden) { closeSearch(); return; }
    if (tool !== "cross" || pending) { setTool("cross"); return; }
    if (measureShown) { clearMeasure(); return; }
    if (!$("#ind-menu").hidden) { $("#ind-menu").hidden = true; return; }
    location.href = "advanced.html#signals"; return;
  }
  if (e.altKey && !typing) { const t = { t: "trend", h: "hline", m: "measure", c: "cross" }[e.key.toLowerCase()]; if (t) { clearMeasure(); setTool(t); e.preventDefault(); } return; }
  if (typing || e.ctrlKey || e.metaKey) return;
  if (e.key === "/") { e.preventDefault(); openSearch(); return; }
  if (e.key.length === 1 && /[a-z0-9]/i.test(e.key)) { e.preventDefault(); openSearch(e.key); }
});

boot();
