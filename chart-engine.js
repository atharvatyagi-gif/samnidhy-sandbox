/* B-LAB chart engine: a TradingView-style chart on TradingView's open-source Lightweight Charts 5 (Apache-2.0).
   - chart types: candles, hollow candles, Heikin-Ashi, bars, line, area, baseline
   - indicators from chart-indicators.js: add several of each, settings (lengths, sources, colours), hide/remove
     from the legend, oscillators in their own panes with levels and shaded bands
   - drawing tools drawn on the chart canvas (a series primitive): trend line, ray, extended line, horizontal
     line / ray, vertical line, rectangle, Fibonacci retracement, price range, text. Select, drag, recolour,
     delete, undo. Drawings are stored by date/time + price, so they stay put across intervals.
   - compare other symbols in % ; screenshot with the legend burnt in. */

import { INDICATORS, IND, SOURCES, defaults, heikinAshi } from "./chart-indicators.js";

const LCW = () => window.LightweightCharts;
const LS = { get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d) => v == null || isNaN(v) ? "—" : Math.abs(v) >= 1e7 ? (v / 1e7).toFixed(2) + " Cr" : Math.abs(v) >= 1e5 && d === "vol" ? (v / 1e5).toFixed(2) + " L"
  : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d === "vol" ? 0 : Math.abs(v) >= 1000 ? 1 : 2, maximumFractionDigits: d === "vol" ? 0 : Math.abs(v) >= 1000 ? 1 : 2 });
const uid = () => "i" + Math.random().toString(36).slice(2, 9);

export const THEME = { bg: "#061a10", text: "#a39679", grid: "rgba(181,166,130,0.07)", border: "rgba(181,166,130,0.25)", up: "#00e060", down: "#e0a060",
  upFill: "rgba(0,224,96,0.9)", cross: "rgba(181,166,130,0.5)", label: "#11352a", ink: "#e8dcc3", acc: "#00e060" };
export const CHART_TYPES = [["candle", "Candles"], ["hollow", "Hollow candles"], ["heikin", "Heikin-Ashi"], ["bars", "Bars"], ["line", "Line"], ["area", "Area"], ["baseline", "Baseline"]];
export const TOOLS = {
  cursor: { name: "Cursor", pts: 0 }, trend: { name: "Trend line", pts: 2 }, ray: { name: "Ray", pts: 2 }, ext: { name: "Extended line", pts: 2 },
  hline: { name: "Horizontal line", pts: 1 }, hray: { name: "Horizontal ray", pts: 1 }, vline: { name: "Vertical line", pts: 1 },
  rect: { name: "Rectangle", pts: 2 }, fib: { name: "Fib retracement", pts: 2 }, range: { name: "Price range", pts: 2 }, text: { name: "Text", pts: 1 },
};
const SWATCH = ["#4fd1c5", "#00e060", "#f0c674", "#e0a060", "#ff6b6b", "#6fa8ff", "#a78bfa", "#e8dcc3"];
const FIB = [[0, "#a39679"], [0.236, "#ff6b6b"], [0.382, "#e0a060"], [0.5, "#00e060"], [0.618, "#4fd1c5"], [0.786, "#6fa8ff"], [1, "#a39679"]];
const DEFAULT_INDS = [{ id: "vol", params: defaults("vol") }, { id: "sma", params: { len: 50, src: "close" } }, { id: "sma", params: { len: 200, src: "close" }, colors: { v: "#e0a060" } }];
const ICON = {
  eye: '<svg viewBox="0 0 16 16" width="13" height="13"><path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="8" r="2" fill="currentColor"/></svg>',
  set: '<svg viewBox="0 0 16 16" width="13" height="13"><circle cx="8" cy="8" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 1v2.2M8 12.8V15M1 8h2.2M12.8 8H15M3 3l1.6 1.6M11.4 11.4 13 13M13 3l-1.6 1.6M4.6 11.4 3 13" stroke="currentColor" stroke-width="1.4"/></svg>',
  del: '<svg viewBox="0 0 16 16" width="13" height="13"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" stroke-width="1.6"/></svg>',
};

/* ---------- canvas layers (Lightweight Charts series primitives) ---------- */
class Layer {                       // calls paint(ctx, size) on every chart redraw
  constructor(paint, z) { this.paint = paint; this.z = z; this.views = [{ zOrder: () => this.z, renderer: () => ({ draw: t => t.useMediaCoordinateSpace(({ context, mediaSize }) => this.paint(context, mediaSize)) }) }]; }
  attached(p) { this.req = p.requestUpdate; }
  detached() { this.req = null; }
  updateAllViews() {}
  paneViews() { return this.views; }
}

export class ChartEngine {
  constructor(host, hooks = {}) {
    this.host = host; this.hooks = hooks;
    host.innerHTML = '<div class="eng-chart"></div><div class="eng-legend"></div><div class="eng-hint" hidden></div><div class="eng-dbar" hidden></div>';
    this.el = host.querySelector(".eng-chart"); this.lg = host.querySelector(".eng-legend"); this.hint = host.querySelector(".eng-hint"); this.dbar = host.querySelector(".eng-dbar");
    this.inds = LS.get("blab-inds2", null) || DEFAULT_INDS.map(d => ({ uid: uid(), vis: true, colors: {}, ...d, params: { ...defaults(d.id), ...d.params } }));
    this.inds.forEach(i => { i.params = { ...defaults(i.id), ...i.params }; i.colors = i.colors || {}; if (i.vis == null) i.vis = true; });
    this.type = LS.get("blab-ct2", "candle"); this.magnet = LS.get("blab-magnet", false); this.scale = "auto";
    this.tool = "cursor"; this.stay = false; this.hidden = false; this.sel = null; this.placing = null; this.drag = null; this.undoStack = [];
    this.compare = []; this.bars = []; this.T = []; this.sym = ""; this.iv = "D";
    this.wireMouse(); this.wireLegend();
    new ResizeObserver(() => this.placeLegends()).observe(host);
    this.cdT = setInterval(() => this.tickCountdown(), 1000);
  }

  /* ================= data + build ================= */
  load({ sym, name, iv, bars, intraday, keepRange, compare }) {
    const same = sym === this.sym && iv === this.iv;
    this.sym = sym; this.name = name; this.iv = iv; this.bars = bars; this.intraday = intraday; if (compare) this.compare = compare;
    this.T = bars.map(b => typeof b.time === "number" ? b.time : Date.UTC(+b.time.slice(0, 4), +b.time.slice(5, 7) - 1, +b.time.slice(8, 10)) / 1000);
    const d = this.T.slice(-40).map((t, i, a) => i ? t - a[i - 1] : null).filter(Boolean).sort((a, b) => a - b);
    this.step = d.length ? d[d.length >> 1] : 86400;
    if (!same) { this.sel = null; this.placing = null; this.undoStack = []; }
    this.build(keepRange && same);
  }
  seriesData(bars) {
    const t = this.type, B = t === "heikin" ? heikinAshi(bars) : bars;
    return ["candle", "hollow", "heikin", "bars"].includes(t) ? B.map(b => ({ time: b.time, open: b.o, high: b.h, low: b.l, close: b.c })) : B.map(b => ({ time: b.time, value: b.c }));
  }
  build(keepRange) {
    const L = LCW(); if (!L) { this.hooks.message?.("The chart library could not load. Check your connection and reload."); return; }
    const prev = keepRange && this.chart ? this.chart.timeScale().getVisibleLogicalRange() : null;
    if (this.chart) { this.chart.remove(); this.chart = null; }
    const b = this.bars;
    if (!b.length) { this.lg.innerHTML = ""; return; }
    const chart = this.chart = L.createChart(this.el, {
      autoSize: true,
      layout: { background: { type: "solid", color: THEME.bg }, textColor: THEME.text, fontFamily: "'IBM Plex Mono', Consolas, monospace", fontSize: 11, attributionLogo: false,
        panes: { separatorColor: "rgba(181,166,130,0.22)", separatorHoverColor: "rgba(0,224,96,0.35)", enableResize: true } },
      grid: { vertLines: { color: THEME.grid }, horzLines: { color: THEME.grid } },
      rightPriceScale: { borderColor: THEME.border, scaleMargins: { top: 0.1, bottom: this.inds.some(i => i.id === "vol" && i.vis) ? 0.2 : 0.08 } },
      timeScale: { borderColor: THEME.border, timeVisible: this.intraday, secondsVisible: false, rightOffset: 8, barSpacing: this.intraday ? 7 : 6, minBarSpacing: 0.5 },
      crosshair: { mode: this.magnet ? 1 : 0, vertLine: { color: THEME.cross, style: 3, labelBackgroundColor: THEME.label }, horzLine: { color: THEME.cross, style: 3, labelBackgroundColor: THEME.label } },
      localization: { priceFormatter: p => fmt(p) },
      handleScroll: this.tool === "cursor", handleScale: this.tool === "cursor",
    });
    try { L.createTextWatermark(chart.panes()[0], { horzAlign: "center", vertAlign: "center", lines: [{ text: this.sym, color: "rgba(232,220,195,0.05)", fontSize: 72, fontStyle: "bold" }] }); } catch (e) {}
    const t = this.type, base = { priceLineColor: THEME.ink, priceLineStyle: 2 };
    if (t === "candle" || t === "heikin") this.main = chart.addSeries(L.CandlestickSeries, { ...base, upColor: THEME.upFill, downColor: THEME.down, borderUpColor: THEME.up, borderDownColor: THEME.down, wickUpColor: THEME.up, wickDownColor: THEME.down });
    else if (t === "hollow") this.main = chart.addSeries(L.CandlestickSeries, { ...base, upColor: "rgba(0,0,0,0)", downColor: THEME.down, borderUpColor: THEME.up, borderDownColor: THEME.down, wickUpColor: THEME.up, wickDownColor: THEME.down });
    else if (t === "bars") this.main = chart.addSeries(L.BarSeries, { ...base, upColor: THEME.up, downColor: THEME.down, thinBars: false });
    else if (t === "line") this.main = chart.addSeries(L.LineSeries, { ...base, color: THEME.acc, lineWidth: 2 });
    else if (t === "area") this.main = chart.addSeries(L.AreaSeries, { ...base, lineColor: THEME.acc, topColor: "rgba(0,224,96,0.25)", bottomColor: "rgba(0,224,96,0.02)", lineWidth: 2 });
    else this.main = chart.addSeries(L.BaselineSeries, { ...base, baseValue: { type: "price", price: b[0].c }, topLineColor: THEME.up, bottomLineColor: THEME.down,
      topFillColor1: "rgba(0,224,96,0.25)", topFillColor2: "rgba(0,224,96,0.03)", bottomFillColor1: "rgba(224,160,96,0.03)", bottomFillColor2: "rgba(224,160,96,0.25)", lineWidth: 2 });
    // indicators are calculated first: some (Ichimoku, Alligator) draw into the future, which needs empty future bars
    const calcs = this.inds.map(ins => { const def = IND[ins.id]; if (!def || (def.intradayOnly && !this.intraday)) return null; try { return def.calc(b, ins.params); } catch (e) { return {}; } });
    let extra = 0;
    calcs.forEach((v, k) => { if (v) for (const o of IND[this.inds[k].id].outs) extra = Math.max(extra, (v[o.k] || []).length - b.length); });
    this.future = this.futureTimes(extra);
    this.main.setData([...this.seriesData(b), ...this.future.map(time => ({ time }))]);
    const timeAt = i => i < b.length ? b[i].time : this.future[i - b.length];
    if (this.compare.length || this.scale !== "auto") chart.priceScale("right").applyOptions({ mode: this.compare.length ? 2 : { auto: 0, log: 1, pct: 2 }[this.scale] });

    // indicators
    this.out = {}; this.paneOf = {}; let pane = 1;
    for (const [k, ins] of this.inds.entries()) {
      const def = IND[ins.id]; if (!def) continue;
      const p = def.pane === "main" ? 0 : pane++;
      this.paneOf[ins.uid] = p;
      if (def.intradayOnly && !this.intraday) { this.out[ins.uid] = { na: true, vals: {} }; if (p) pane--; this.paneOf[ins.uid] = 0; continue; }
      const vals = calcs[k] || {};
      const series = {};
      for (const o of def.outs) {
        const color = ins.colors[o.k] || o.color, arr = vals[o.k] || [], cols = vals[o.k + "_color"];
        const common = { priceLineVisible: false, lastValueVisible: p > 0 || def.id !== "vol", visible: ins.vis, crosshairMarkerVisible: false, title: "",
          ...(def.scale ? { priceScaleId: def.scale } : {}) };
        let s;
        if (o.type === "hist") s = chart.addSeries(L.HistogramSeries, { ...common, color, priceFormat: def.id === "vol" ? { type: "volume" } : { type: "price", precision: 2, minMove: 0.01 } }, p);
        else if (o.type === "dots") s = chart.addSeries(L.LineSeries, { ...common, color, lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.6 }, p);
        else s = chart.addSeries(L.LineSeries, { ...common, color, lineWidth: o.w || 1.5 }, p);
        s.setData(arr.map((v, i) => { const t = timeAt(i); return t == null ? null : v == null ? { time: t } : cols ? { time: t, value: v, color: cols[i] || color } : { time: t, value: v }; }).filter(Boolean));
        series[o.k] = s;
      }
      if (def.scale === "vol") chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      const first = series[def.outs[0].k];
      (def.levels || []).forEach(v => first.createPriceLine({ price: v, color: "rgba(181,166,130,0.35)", lineStyle: 2, lineWidth: 1, axisLabelVisible: false }));
      if (ins.vis && def.fill) { const [a, c, col] = def.fill; series[a].attachPrimitive(new Layer((ctx) => this.fillBand(ctx, series[a], vals[a], vals[c], col), "bottom")); }
      if (ins.vis && def.fill2) { const [a, c, up, dn] = def.fill2; series[a].attachPrimitive(new Layer((ctx) => this.fillBand(ctx, series[a], vals[a], vals[c], up, dn), "bottom")); }
      if (ins.vis && def.band) { const [hi, lo, col] = def.band; first.attachPrimitive(new Layer((ctx) => this.fillBand(ctx, first, b.map(() => hi), b.map(() => lo), col), "bottom")); }
      this.out[ins.uid] = { series, vals };
    }
    // compare
    this.cmpSeries = this.compare.map(c => {
      const m = new Map(c.bars.map(x => [x.time, x.c]));
      const s = chart.addSeries(L.LineSeries, { color: c.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: c.label });
      s.setData(b.map(x => m.has(x.time) ? { time: x.time, value: m.get(x.time) } : { time: x.time }));
      return { ...c, series: s, map: m };
    });
    // drawings on the price pane
    this.layer = new Layer((ctx, size) => this.paintDrawings(ctx, size), "top");
    this.main.attachPrimitive(this.layer);
    const panes = chart.panes();
    panes.forEach((pn, i) => { try { pn.setStretchFactor(i === 0 ? Math.max(3, panes.length) : 1); } catch (e) {} });
    chart.subscribeCrosshairMove(p => this.renderLegend(p));
    chart.timeScale().subscribeVisibleLogicalRangeChange(r => { this.placeLegends(); if (r && r.from < 15) this.hooks.nearStart?.(this); });
    if (prev) chart.timeScale().setVisibleLogicalRange(prev); else this.hooks.defaultRange?.(this);
    this.lgKey = null; this.renderLegend(); requestAnimationFrame(() => this.placeLegends());
    this.hooks.built?.(this);
  }
  refresh() { this.build(true); }
  /* TradingView-style countdown to the current candle's close, shown next to the last price.
     Intraday candles only with the real-time feed (delayed candles are already closed); daily = time to 15:30 IST. */
  tickCountdown() {
    const drop = () => { if (this.cdLine) { try { this.cdMain.removePriceLine(this.cdLine); } catch (e) {} this.cdLine = null; } };
    if (!this.chart || !this.bars.length || !this.hooks.marketOpen?.()) return drop();
    const step = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600 }[this.iv], nowIst = Date.now() / 1000 + 19800, close = Math.floor(nowIst / 86400) * 86400 + 930 * 60;
    const last = this.bars[this.bars.length - 1];
    let end;
    if (step && typeof last.time === "number" && this.hooks.realtime?.()) end = Math.min(last.time + step, close);
    else if (this.iv === "D") end = close;
    else return drop();
    const left = Math.round(end - nowIst);
    if (left < 0 || left > 7 * 3600) return drop();
    const hh = Math.floor(left / 3600), mm = Math.floor(left % 3600 / 60), ss = left % 60, two = n => String(n).padStart(2, "0");
    const title = (hh ? `${hh}:${two(mm)}` : `${mm}`) + `:${two(ss)}`;
    if (this.cdLine && this.cdMain !== this.main) this.cdLine = null;         // the chart was rebuilt
    if (!this.cdLine) { this.cdMain = this.main; this.cdLine = this.main.createPriceLine({ price: last.c, color: "rgba(0,0,0,0)", lineWidth: 1, axisLabelVisible: false, title }); }
    else this.cdLine.applyOptions({ price: last.c, title });
  }
  /* Real-time: update the last candle in place (or start a new one) without rebuilding the chart.
     Indicators are recalculated when a new candle starts (and at most every 5 s for Heikin-Ashi). */
  upsertBar(bar) {
    if (!this.chart || !this.bars.length) return;
    const b = this.bars, last = b[b.length - 1];
    let fresh = false;
    if (bar.time === last.time) b[b.length - 1] = { ...last, ...bar };
    else if (String(bar.time) > String(last.time) && (typeof bar.time === typeof last.time)) { b.push(bar); fresh = true;
      this.T.push(typeof bar.time === "number" ? bar.time : Date.UTC(+bar.time.slice(0, 4), +bar.time.slice(5, 7) - 1, +bar.time.slice(8, 10)) / 1000); }
    else return;
    if (fresh || this.type === "heikin" || this.future?.length) { clearTimeout(this.rt); this.rt = setTimeout(() => this.refresh(), fresh ? 50 : 5000); if (this.type === "heikin" || this.future?.length) return; }
    const x = b[b.length - 1];
    try {
      this.main.update(["candle", "hollow", "bars"].includes(this.type) ? { time: x.time, open: x.o, high: x.h, low: x.l, close: x.c } : { time: x.time, value: x.c });
      const vol = this.inds.find(i => i.id === "vol" && i.vis), vs = vol && this.out[vol.uid]?.series?.v;
      if (vs) vs.update({ time: x.time, value: x.v || 0, color: x.c >= x.o ? "rgba(0,224,96,0.30)" : "rgba(224,160,96,0.32)" });
    } catch (e) { this.refresh(); }
    this.renderLegend();
  }
  futureTimes(k) {                    // k empty bars after the last one, at this chart's spacing
    const b = this.bars, out = []; if (!k || !b.length) return out;
    const last = b[b.length - 1].time;
    if (typeof last === "number") { for (let i = 1; i <= k; i++) out.push(last + i * this.step); return out; }
    const d = new Date(last + "T00:00:00Z");
    while (out.length < k) {
      if (this.iv === "M") d.setUTCMonth(d.getUTCMonth() + 1); else if (this.iv === "W") d.setUTCDate(d.getUTCDate() + 7);
      else { d.setUTCDate(d.getUTCDate() + 1); if (d.getUTCDay() === 0 || d.getUTCDay() === 6) continue; }
      out.push(d.toISOString().slice(0, 10));
    }
    return out;
  }
  fillBand(ctx, s, up, lo, color, color2) {
    const ts = this.chart?.timeScale(), r = ts?.getVisibleLogicalRange(); if (!r) return;
    const from = Math.max(0, Math.floor(r.from) - 1), to = Math.min(up.length - 1, lo.length - 1, Math.ceil(r.to) + 1);
    let top = [], bot = [], sign = null;
    const flush = () => { if (top.length > 1) { ctx.beginPath(); top.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); for (let i = bot.length - 1; i >= 0; i--) ctx.lineTo(bot[i][0], bot[i][1]); ctx.closePath(); ctx.fillStyle = color2 && sign === false ? color2 : color; ctx.fill(); } top = []; bot = []; };
    for (let i = from; i <= to; i++) {
      if (up[i] == null || lo[i] == null) { flush(); continue; }
      if (color2) { const sg = up[i] >= lo[i]; if (sign !== null && sg !== sign) { const keep = top.length ? [top[top.length - 1], bot[bot.length - 1]] : null; flush(); if (keep) { top.push(keep[0]); bot.push(keep[1]); } } sign = sg; }
      const x = ts.logicalToCoordinate(i), yu = s.priceToCoordinate(up[i]), yl = s.priceToCoordinate(lo[i]);
      if (x == null || yu == null || yl == null) { flush(); continue; }
      top.push([x, yu]); bot.push([x, yl]);
    }
    flush();
  }

  /* ================= legend (per pane, TradingView style) ================= */
  idxAt(p) { const n = this.bars.length - 1; if (p && p.logical != null) return Math.max(0, Math.min(n, Math.round(p.logical))); return n; }
  renderLegend(p) {
    if (!this.chart) return;
    const b = this.bars, i = this.idxAt(p), x = this.type === "heikin" ? heikinAshi(b.slice(0, i + 1))[i] : b[i], prev = i ? b[i - 1].c : null;
    const ch = prev ? x.c - prev : null, chp = prev ? ch / prev * 100 : null, cl = ch == null ? "" : ch >= 0 ? "up" : "down";
    const headVals = `<span>O <b class="${cl}">${fmt(x.o)}</b></span><span>H <b class="${cl}">${fmt(x.h)}</b></span><span>L <b class="${cl}">${fmt(x.l)}</b></span><span>C <b class="${cl}">${fmt(x.c)}</b></span>
      <b class="${cl}">${ch == null ? "" : (ch >= 0 ? "+" : "−") + fmt(Math.abs(ch)) + " (" + (ch >= 0 ? "+" : "−") + Math.abs(chp).toFixed(2) + "%)"}</b><span class="lg-d">${esc(b[i].lbl || "")}</span>`;
    const insVals = ins => { const def = IND[ins.id], o = this.out[ins.uid]; if (!def || !o) return "";
      return o.na ? '<span class="lg-na">intraday only</span>' : def.outs.map(out => { const v = (o.vals[out.k] || [])[i]; return `<b style="color:${ins.colors[out.k] || out.color}">${fmt(v, def.id === "vol" && out.k === "v" ? "vol" : undefined)}</b>`; }).join(" "); };
    const cmpVals = c => `<b style="color:${c.color}">${fmt(c.map.get(b[i].time))}</b>`;
    // only the numbers change on mouse moves; the rows (and their eye / settings / remove buttons) stay put
    const key = JSON.stringify([this.sym, this.iv, this.type, this.chart.panes().length, this.inds.map(x => [x.uid, x.vis, this.paneOf[x.uid], x.params]), (this.cmpSeries || []).map(c => c.sym)]);
    if (key === this.lgKey && this.lg.firstChild) {
      const h = this.lg.querySelector(".lg-sym .lg-vals"); if (h) h.innerHTML = headVals;
      this.lg.querySelectorAll(".lg-row[data-uid]").forEach(r => { const ins = this.inds.find(x => x.uid === r.dataset.uid); const v = r.querySelector(".lg-vals"); if (ins && v) v.innerHTML = insVals(ins); });
      this.lg.querySelectorAll(".lg-row[data-cmp]").forEach(r => { const c = this.cmpSeries[+r.dataset.cmp]; const v = r.querySelector(".lg-vals"); if (c && v) v.innerHTML = cmpVals(c); });
      return;
    }
    this.lgKey = key;
    const byPane = {};
    const row = ins => { const def = IND[ins.id]; if (!def || !this.out[ins.uid]) return "";
      return `<div class="lg-row${ins.vis ? "" : " off"}" data-uid="${ins.uid}"><span class="lg-n">${esc(def.label(ins.params))}</span><span class="lg-vals">${insVals(ins)}</span><span class="lg-b">
        <button data-a="eye" title="${ins.vis ? "Hide" : "Show"}">${ICON.eye}</button><button data-a="set" title="Settings">${ICON.set}</button><button data-a="del" title="Remove">${ICON.del}</button></span></div>`; };
    for (const ins of this.inds) (byPane[this.paneOf[ins.uid] ?? 0] ||= []).push(row(ins));
    const cmp = (this.cmpSeries || []).map((c, k) => `<div class="lg-row" data-cmp="${k}"><span class="lg-n" style="color:${c.color}">${esc(c.label)}</span><span class="lg-vals">${cmpVals(c)}</span><span class="lg-b"><button data-a="uncmp" title="Remove comparison">${ICON.del}</button></span></div>`).join("");
    const head = `<div class="lg-row lg-sym"><span class="lg-t">${esc(this.sym)} · ${esc(this.iv)} · NSE</span><span class="lg-vals">${headVals}</span></div>`;
    const n = this.chart.panes().length;
    let html = `<div class="lg-pane" data-p="0">${head}${(byPane[0] || []).join("")}${cmp}</div>`;
    for (let k = 1; k < n; k++) html += `<div class="lg-pane" data-p="${k}">${(byPane[k] || []).join("")}</div>`;
    this.lg.innerHTML = html;
    this.placeLegends();
  }
  placeLegends() {
    if (!this.chart) return;
    const panes = this.chart.panes(); let top = 0;
    panes.forEach((pn, k) => { const el = this.lg.querySelector(`.lg-pane[data-p="${k}"]`); if (el) el.style.top = top + 4 + "px"; top += pn.getHeight() + 1; });
  }
  wireLegend() {
    this.lg.addEventListener("click", e => {
      const btn = e.target.closest("button[data-a]"); if (!btn) return;
      e.stopPropagation();
      const a = btn.dataset.a;
      if (a === "uncmp") { this.compare.splice(+btn.closest("[data-cmp]").dataset.cmp, 1); this.hooks.compareChanged?.(this.compare); this.refresh(); return; }
      const ins = this.inds.find(x => x.uid === btn.closest("[data-uid]").dataset.uid); if (!ins) return;
      if (a === "eye") { ins.vis = !ins.vis; this.saveInds(); this.refresh(); }
      else if (a === "del") { this.inds = this.inds.filter(x => x !== ins); this.saveInds(); this.refresh(); }
      else if (a === "set") this.openSettings(ins);
    });
  }
  saveInds() { LS.set("blab-inds2", this.inds.map(({ uid: u, id, params, colors, vis }) => ({ uid: u, id, params, colors, vis }))); this.hooks.indsChanged?.(this.inds); }

  /* ================= indicator dialogs ================= */
  modal(title, body, onOk) {
    const m = document.createElement("div"); m.className = "eng-modal";
    m.innerHTML = `<div class="eng-box" role="dialog" aria-label="${esc(title)}"><div class="eng-bh"><b>${esc(title)}</b><button class="eng-x" aria-label="Close">${ICON.del}</button></div><div class="eng-bb">${body}</div>
      ${onOk ? '<div class="eng-bf"><button class="btn-line" data-f="reset">Defaults</button><span class="grow"></span><button class="btn-line" data-f="cancel">Cancel</button><button class="btn-ink" data-f="ok">OK</button></div>' : ""}</div>`;
    const close = () => { m.remove(); document.removeEventListener("keydown", key, true); };
    const key = e => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
    m.addEventListener("mousedown", e => { if (e.target === m) close(); });
    m.querySelector(".eng-x").onclick = close;
    document.addEventListener("keydown", key, true);
    document.body.appendChild(m);
    return { m, close };
  }
  openIndicators() {
    const groups = [...new Set(INDICATORS.map(d => d.group))];
    const list = q => groups.map(g => { const items = INDICATORS.filter(d => d.group === g && (!q || d.name.toLowerCase().includes(q) || d.id.includes(q)));
      return items.length ? `<h6>${esc(g)}</h6>` + items.map(d => `<button class="eng-ind${recIds.has(d.id) ? " rec" : ""}" data-id="${d.id}"><span>${esc(d.name)}</span><small>${d.pane === "main" ? "on price" : "own pane"}${this.inds.some(x => x.id === d.id) ? " · on chart" : ""}</small></button>`).join("") : ""; }).join("") || '<p class="eng-empty">No indicator matches.</p>';
    const recIds = new Set((this.recommended || []).flatMap(r => r.add.map(a => a[0])));
    const recHtml = (this.recommended || []).length ? `<h6>★ Recommended for ${esc(this.sym)} (tested on its past prices; see Details)</h6>` + this.recommended.map((r, k) => `<button class="eng-ind rec" data-rec="${k}"><span>${esc(r.name)}</span><small>adds ${r.add.map(a => esc(IND[a[0]].label({ ...defaults(a[0]), ...a[1] }))).join(" + ")}</small></button>`).join("") : "";
    const { m } = this.modal("Indicators", `<input class="eng-q" type="search" placeholder="Search ${INDICATORS.length} indicators (e.g. RSI, EMA, Ichimoku)" aria-label="Search indicators"><div class="eng-list">${recHtml}${list("")}</div>
      <p class="eng-note">Click to add. You can add the same indicator more than once (e.g. EMA 9 and EMA 21). Hover a legend line on the chart to hide, change or remove it.</p>`);
    const q = m.querySelector(".eng-q"), L = m.querySelector(".eng-list");
    const paint = () => { const v = q.value.trim().toLowerCase(); L.innerHTML = (v ? "" : recHtml) + list(v); };
    q.focus(); q.oninput = paint;
    L.addEventListener("click", e => { const b = e.target.closest(".eng-ind"); if (!b) return;
      if (b.dataset.rec != null) this.recommended[+b.dataset.rec].add.forEach(([id, p]) => this.addIndicator(id, p)); else this.addIndicator(b.dataset.id);
      paint(); });
  }
  addIndicator(id, params) {
    const ins = { uid: uid(), id, params: { ...defaults(id), ...params }, colors: {}, vis: true };
    if (id === "vol" && this.inds.some(x => x.id === "vol")) { this.hooks.toast?.("Volume is already on the chart"); return; }
    this.inds.push(ins); this.saveInds(); this.refresh();
    const def = IND[id]; this.hooks.toast?.(`${def.label(ins.params)} added${def.intradayOnly && !this.intraday ? " (shows on 5m / 15m / 1h charts)" : ""}`);
  }
  openSettings(ins) {
    const def = IND[ins.id];
    const field = p => p.opts ? `<label><span>${esc(p.label)}</span><select data-k="${p.k}">${Object.entries(p.opts).map(([k, v]) => `<option value="${k}"${ins.params[p.k] === k ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`
      : `<label><span>${esc(p.label)}</span><input type="number" data-k="${p.k}" value="${ins.params[p.k]}" min="${p.min}" max="${p.max}" step="${p.step}"></label>`;
    const colors = def.outs.map(o => `<label><span>${esc(o.name)} colour</span><input type="color" data-c="${o.k}" value="${(ins.colors[o.k] || o.color).startsWith("#") ? (ins.colors[o.k] || o.color) : "#83795f"}"></label>`).join("");
    const { m, close } = this.modal(def.name, `<div class="eng-form">${def.params.map(field).join("") || '<p class="eng-note">No inputs.</p>'}${colors}</div>`, true);
    m.querySelector('[data-f="cancel"]').onclick = close;
    m.querySelector('[data-f="reset"]').onclick = () => { m.querySelectorAll("[data-k]").forEach(i => { const p = def.params.find(x => x.k === i.dataset.k); i.value = p.def; }); m.querySelectorAll("[data-c]").forEach(i => { const o = def.outs.find(x => x.k === i.dataset.c); if (o.color.startsWith("#")) i.value = o.color; }); };
    m.querySelector('[data-f="ok"]').onclick = () => {
      m.querySelectorAll("[data-k]").forEach(i => { const p = def.params.find(x => x.k === i.dataset.k); ins.params[p.k] = p.opts ? i.value : Math.min(p.max, Math.max(p.min, +i.value || p.def)); });
      m.querySelectorAll("[data-c]").forEach(i => { const o = def.outs.find(x => x.k === i.dataset.c); if (i.value !== o.color) ins.colors[o.k] = i.value; else delete ins.colors[o.k]; });
      this.saveInds(); close(); this.refresh();
    };
  }

  /* ================= options ================= */
  setType(t) { this.type = t; LS.set("blab-ct2", t); this.refresh(); }
  setScale(s) { this.scale = s; if (!this.compare.length) this.chart?.priceScale("right").applyOptions({ mode: { auto: 0, log: 1, pct: 2 }[s] }); }
  setMagnet(on) { this.magnet = on; LS.set("blab-magnet", on); this.chart?.applyOptions({ crosshair: { mode: on ? 1 : 0 } }); }
  setCompare(list) { this.compare = list; this.refresh(); }
  fit() { this.chart?.timeScale().fitContent(); }
  zoom(f) { const ts = this.chart?.timeScale(), r = ts?.getVisibleLogicalRange(); if (!r) return; const mid = (r.from + r.to) / 2, h = (r.to - r.from) / 2 * f; ts.setVisibleLogicalRange({ from: mid - h, to: mid + h }); }
  showBars(from, to) { this.chart?.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: (to ?? this.bars.length - 1) + 8 }); }
  goTo(dateIso) {
    const t = Date.UTC(+dateIso.slice(0, 4), +dateIso.slice(5, 7) - 1, +dateIso.slice(8, 10)) / 1000, l = Math.round(this.tToL(t));
    const r = this.chart?.timeScale().getVisibleLogicalRange(); const w = r ? (r.to - r.from) / 2 : 60;
    this.chart?.timeScale().setVisibleLogicalRange({ from: l - w, to: l + w });
  }
  snapshot() {
    if (!this.chart) return null;
    const cv = this.chart.takeScreenshot(), ctx = cv.getContext("2d"), dpr = cv.width / this.el.clientWidth;
    ctx.save(); ctx.scale(dpr, dpr); ctx.font = "600 12px 'IBM Plex Mono', Consolas, monospace";
    let y = 18;
    for (const r of this.lg.querySelectorAll('.lg-pane[data-p="0"] .lg-row')) { ctx.fillStyle = "rgba(6,26,16,0.75)"; const t = r.textContent.replace(/\s+/g, " ").trim(); ctx.fillRect(6, y - 13, ctx.measureText(t).width + 8, 17); ctx.fillStyle = THEME.ink; ctx.fillText(t, 10, y); y += 18; }
    ctx.fillStyle = "rgba(232,220,195,0.55)"; ctx.fillText("B-LAB DESK · NSE data, educational use", 10, this.el.clientHeight - 38); ctx.restore();
    return cv;
  }

  /* ================= drawings ================= */
  get key() { return "blab-draw2"; }
  get drawings() { return (LS.get(this.key, {})[this.sym]) || []; }
  set drawings(list) { const all = LS.get(this.key, {}); all[this.sym] = list; LS.set(this.key, all); this.layer?.req?.(); this.hooks.drawingsChanged?.(list); }
  pushUndo() { this.undoStack.push(JSON.stringify(this.drawings)); if (this.undoStack.length > 60) this.undoStack.shift(); }
  undo() { if (!this.undoStack.length) { this.hooks.toast?.("Nothing to undo"); return; } this.drawings = JSON.parse(this.undoStack.pop()); this.sel = null; this.showDbar(); }
  clearDrawings() { const n = this.drawings.length; if (!n) { this.hooks.toast?.("No drawings on " + this.sym); return; } this.pushUndo(); this.drawings = []; this.sel = null; this.showDbar(); this.hooks.toast?.(`Removed ${n} drawing${n > 1 ? "s" : ""} (Ctrl+Z to undo)`); }
  toggleHidden() { this.hidden = !this.hidden; this.sel = null; this.showDbar(); this.layer?.req?.(); return this.hidden; }
  setTool(t, stay = false) {
    this.tool = t; this.stay = stay; this.placing = null;
    this.chart?.applyOptions({ handleScroll: t === "cursor", handleScale: t === "cursor" });
    this.host.classList.toggle("drawing", t !== "cursor");
    const info = TOOLS[t]; this.hint.hidden = t === "cursor";
    this.hint.textContent = t === "cursor" ? "" : `${info.name}: ${info.pts === 2 ? "click the first point" : "click on the chart"} · Esc to cancel`;
    this.hooks.toolChanged?.(t);
    this.layer?.req?.();
  }
  tToL(t) {
    const T = this.T, n = T.length; if (!n) return 0;
    if (t <= T[0]) return (t - T[0]) / this.step;
    if (t >= T[n - 1]) return n - 1 + (t - T[n - 1]) / this.step;
    let lo = 0, hi = n - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (T[m] <= t) lo = m; else hi = m; }
    return lo + (t - T[lo]) / (T[hi] - T[lo]);
  }
  lToT(l) {
    const T = this.T, n = T.length;
    if (l <= 0) return T[0] + l * this.step;
    if (l >= n - 1) return T[n - 1] + (l - (n - 1)) * this.step;
    const i = Math.floor(l); return T[i] + (T[i + 1] - T[i]) * (l - i);
  }
  X(t) { return this.chart.timeScale().logicalToCoordinate(this.tToL(t)); }
  Y(p) { return this.main.priceToCoordinate(p); }
  pointFrom(e) {
    if (!this.chart) return null;
    const r = this.el.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (x < 0 || y < 0 || x > this.chart.timeScale().width() || y > this.chart.panes()[0].getHeight()) return null;
    const l = this.chart.timeScale().coordinateToLogical(x); let p = this.main.coordinateToPrice(y);
    if (l == null || p == null) return null;
    if (this.magnet) { const b = this.bars[Math.max(0, Math.min(this.bars.length - 1, Math.round(l)))]; if (b) p = [b.o, b.h, b.l, b.c].reduce((a, v) => Math.abs(v - p) < Math.abs(a - p) ? v : a, b.c); }
    return { x, y, l, t: this.lToT(l), p };
  }
  wireMouse() {
    const H = this.host;
    H.addEventListener("pointerdown", e => this.onDown(e), true);
    H.addEventListener("mousedown", e => { if (this.swallow) { e.stopPropagation(); e.preventDefault(); } }, true);
    H.addEventListener("pointermove", e => this.onMove(e), true);
    H.addEventListener("mousemove", e => { if (this.drag) e.stopPropagation(); }, true);
    window.addEventListener("pointerup", e => this.onUp(e), true);
    H.addEventListener("dblclick", e => { const h = this.hit(e); if (h && h.d.type === "text") { this.editText(h.d); e.stopPropagation(); } }, true);
  }
  onDown(e) {
    this.swallow = false;
    if (e.button !== 0 || e.target.closest(".eng-legend button, .eng-dbar, .eng-modal")) return;
    const pt = this.pointFrom(e); if (!pt) return;
    if (this.tool !== "cursor") {
      this.swallow = true; e.stopPropagation(); e.preventDefault();
      const info = TOOLS[this.tool], color = LS.get("blab-dcolor", SWATCH[0]);
      if (info.pts === 1) {
        const d = { id: uid(), type: this.tool, a: { t: pt.t, p: pt.p }, color };
        if (this.tool === "text") { const txt = prompt("Text for the chart:", ""); if (!txt) { this.setTool("cursor"); return; } d.text = txt.slice(0, 200); }
        this.pushUndo(); this.drawings = [...this.drawings, d]; this.sel = d.id; this.showDbar();
        if (!this.stay) this.setTool("cursor");
        return;
      }
      if (!this.placing) { this.placing = { id: uid(), type: this.tool, a: { t: pt.t, p: pt.p }, b: { t: pt.t, p: pt.p }, color }; this.hint.textContent = `${info.name}: click the second point · Esc to cancel`; }
      else { this.placing.b = { t: pt.t, p: pt.p }; const d = this.placing; this.placing = null; this.pushUndo(); this.drawings = [...this.drawings, d]; this.sel = d.id; this.showDbar(); if (!this.stay) this.setTool("cursor"); else this.hint.textContent = `${info.name}: click the first point`; }
      this.layer?.req?.();
      return;
    }
    const h = this.hit(e);
    if (h) {
      this.swallow = true; e.stopPropagation(); e.preventDefault();
      this.sel = h.d.id; this.showDbar();
      this.pushUndo();
      this.drag = { id: h.d.id, part: h.part, start: pt, orig: JSON.parse(JSON.stringify(h.d)) };
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
      try { this.host.setPointerCapture(e.pointerId); } catch (err) {}
      this.layer?.req?.();
    } else if (this.sel) { this.sel = null; this.showDbar(); this.layer?.req?.(); }
  }
  onMove(e) {
    if (this.placing) { const pt = this.pointFrom(e); if (pt) { this.placing.b = { t: pt.t, p: pt.p }; this.layer?.req?.(); } return; }
    if (this.drag) {
      e.stopPropagation();
      const pt = this.pointFrom(e) || (() => { const r = this.el.getBoundingClientRect(); const l = this.chart.timeScale().coordinateToLogical(e.clientX - r.left); const p = this.main.coordinateToPrice(Math.min(e.clientY - r.top, this.chart.panes()[0].getHeight())); return l == null || p == null ? null : { l, t: this.lToT(l), p }; })();
      if (!pt) return;
      const g = this.drag, o = g.orig, dl = pt.l - g.start.l, dp = pt.p - g.start.p;
      const mv = q => q && { t: this.lToT(this.tToL(q.t) + dl), p: q.p + dp };
      const list = this.drawings.map(d => {
        if (d.id !== g.id) return d;
        if (g.part === "a") return { ...d, a: { t: pt.t, p: pt.p } };
        if (g.part === "b") return { ...d, b: { t: pt.t, p: pt.p } };
        return { ...d, a: mv(o.a), b: mv(o.b) };
      });
      const all = LS.get(this.key, {}); all[this.sym] = list; LS.set(this.key, all); this.layer?.req?.();
      return;
    }
    if (this.tool === "cursor" && !this.hidden) this.host.style.cursor = this.hit(e) ? "move" : "";
  }
  onUp() {
    if (this.drag) { this.drag = null; this.chart?.applyOptions({ handleScroll: this.tool === "cursor", handleScale: this.tool === "cursor" }); this.hooks.drawingsChanged?.(this.drawings); this.showDbar(); }
    setTimeout(() => { this.swallow = false; }, 0);
  }
  cancel() {
    if (this.placing || this.tool !== "cursor") { this.setTool("cursor"); return true; }
    if (this.sel) { this.sel = null; this.showDbar(); this.layer?.req?.(); return true; }
    return false;
  }
  deleteSelected() { if (!this.sel) return false; this.pushUndo(); this.drawings = this.drawings.filter(d => d.id !== this.sel); this.sel = null; this.showDbar(); return true; }
  editText(d) { const t = prompt("Text:", d.text || ""); if (t == null) return; this.pushUndo(); this.drawings = this.drawings.map(x => x.id === d.id ? { ...x, text: t.slice(0, 200) } : x); }
  showDbar() {
    const d = this.drawings.find(x => x.id === this.sel);
    if (!d) { this.dbar.hidden = true; return; }
    this.dbar.innerHTML = `<span>${esc(TOOLS[d.type].name)}</span>${SWATCH.map(c => `<button class="sw${c === d.color ? " on" : ""}" data-c="${c}" style="background:${c}" title="Colour"></button>`).join("")}
      ${d.type === "text" ? '<button class="db" data-x="text">Edit text</button>' : ""}<button class="db" data-x="del" title="Delete (Del)">Delete</button>`;
    this.dbar.hidden = false;
    this.dbar.onclick = e => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.c) { this.pushUndo(); LS.set("blab-dcolor", b.dataset.c); this.drawings = this.drawings.map(x => x.id === d.id ? { ...x, color: b.dataset.c } : x); this.showDbar(); }
      else if (b.dataset.x === "del") this.deleteSelected();
      else if (b.dataset.x === "text") this.editText(d);
    };
  }
  geom(d, W, Hh) {
    const xa = this.X(d.a.t), ya = this.Y(d.a.p), xb = d.b ? this.X(d.b.t) : null, yb = d.b ? this.Y(d.b.p) : null;
    if (xa == null || ya == null || (d.b && (xb == null || yb == null))) return null;
    const ext = (x1, y1, x2, y2, both) => { const dx = x2 - x1, dy = y2 - y1; if (!dx && !dy) return [x1, y1, x2, y2];
      const k = Math.max(W, Hh) * 4 / Math.hypot(dx, dy); return [both ? x1 - dx * k : x1, both ? y1 - dy * k : y1, x2 + dx * k, y2 + dy * k]; };
    switch (d.type) {
      case "trend": return { seg: [xa, ya, xb, yb], pts: [[xa, ya], [xb, yb]] };
      case "ray": return { seg: ext(xa, ya, xb, yb, false), pts: [[xa, ya], [xb, yb]] };
      case "ext": return { seg: ext(xa, ya, xb, yb, true), pts: [[xa, ya], [xb, yb]] };
      case "hline": return { seg: [0, ya, W, ya], pts: [[xa, ya]] };
      case "hray": return { seg: [xa, ya, W, ya], pts: [[xa, ya]] };
      case "vline": return { seg: [xa, 0, xa, Hh], pts: [[xa, ya]] };
      case "text": return { box: [xa, ya - 16, xa + 8 + (d.text || "").length * 7.2, ya + 4], pts: [[xa, ya]] };
      default: return { box: [Math.min(xa, xb), Math.min(ya, yb), Math.max(xa, xb), Math.max(ya, yb)], pts: [[xa, ya], [xb, yb]] };
    }
  }
  hit(e) {
    if (this.hidden || !this.chart) return null;
    const r = this.el.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (y > this.chart.panes()[0].getHeight()) return null;
    const W = this.chart.timeScale().width(), Hh = this.chart.panes()[0].getHeight(), list = this.drawings;
    const dSeg = (s) => { const [x1, y1, x2, y2] = s, dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy, t = L2 ? Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / L2)) : 0; return Math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)); };
    for (let k = list.length - 1; k >= 0; k--) {
      const d = list[k], g = this.geom(d, W, Hh); if (!g) continue;
      if (d.id === this.sel) { const i = g.pts.findIndex(([px, py]) => Math.hypot(px - x, py - y) < 8); if (i >= 0 && g.pts.length > 1) return { d, part: i ? "b" : "a" }; }
      if (g.seg && dSeg(g.seg) < 6) return { d, part: "body" };
      if (g.box) { const [x1, y1, x2, y2] = g.box; if (x >= x1 - 4 && x <= x2 + 4 && y >= y1 - 4 && y <= y2 + 4) return { d, part: "body" }; }
    }
    return null;
  }
  paintDrawings(ctx, size) {
    if (!this.chart || this.hidden) return;
    const W = this.chart.timeScale().width(), Hh = size.height;
    const list = this.placing ? [...this.drawings, this.placing] : this.drawings;
    ctx.save(); ctx.lineCap = "round";
    const label = (text, x, y, color, align = "left", bg = "rgba(6,26,16,0.85)") => { ctx.font = "600 11px 'IBM Plex Mono', Consolas, monospace"; const w = ctx.measureText(text).width;
      const bx = align === "right" ? x - w - 8 : align === "center" ? x - w / 2 - 4 : x; ctx.fillStyle = bg; ctx.fillRect(bx, y - 12, w + 8, 16); ctx.fillStyle = color; ctx.fillText(text, bx + 4, y); };
    for (const d of list) {
      const g = this.geom(d, W, Hh); if (!g) continue;
      const sel = d.id === this.sel || d === this.placing;
      ctx.strokeStyle = d.color; ctx.lineWidth = sel ? 2.4 : 1.8; ctx.setLineDash([]);
      if (g.seg) { ctx.beginPath(); ctx.moveTo(g.seg[0], g.seg[1]); ctx.lineTo(g.seg[2], g.seg[3]); ctx.stroke(); }
      if (d.type === "hline" || d.type === "hray") label(fmt(d.a.p), W - 4, g.seg[1] - 4, d.color, "right");
      if (d.type === "rect") { const [x1, y1, x2, y2] = g.box; ctx.fillStyle = d.color + "22"; ctx.fillRect(x1, y1, x2 - x1, y2 - y1); ctx.strokeRect(x1, y1, x2 - x1, y2 - y1); }
      if (d.type === "text") { ctx.font = "600 13px 'IBM Plex Sans', sans-serif"; ctx.fillStyle = "rgba(6,26,16,0.8)"; const w = ctx.measureText(d.text || "").width; ctx.fillRect(g.box[0], g.box[1], w + 8, 20); ctx.fillStyle = d.color; ctx.fillText(d.text || "", g.box[0] + 4, g.box[1] + 15); if (sel) { ctx.strokeRect(g.box[0], g.box[1], w + 8, 20); } }
      if (d.type === "fib") {
        const [x1, , x2] = g.box, pa = d.a.p, pb = d.b.p;
        let prevY = null;
        FIB.forEach(([lv, col], k) => { const p = pb + (pa - pb) * lv, y = this.Y(p); if (y == null) return;
          if (prevY != null) { ctx.fillStyle = col + "14"; ctx.fillRect(x1, Math.min(prevY, y), x2 - x1, Math.abs(y - prevY)); }
          ctx.strokeStyle = col; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
          label(`${lv} (${fmt(p)})`, x1 - 4, y - 3, col, "right"); prevY = y; });
        ctx.setLineDash([4, 4]); ctx.strokeStyle = d.color; ctx.beginPath(); ctx.moveTo(g.pts[0][0], g.pts[0][1]); ctx.lineTo(g.pts[1][0], g.pts[1][1]); ctx.stroke(); ctx.setLineDash([]);
      }
      if (d.type === "range") {
        const [x1, y1, x2, y2] = g.box, dp = d.b.p - d.a.p, pc = dp / d.a.p * 100, bars = Math.round(Math.abs(this.tToL(d.b.t) - this.tToL(d.a.t))), up = dp >= 0, col = up ? "#00e060" : "#ff6b6b";
        ctx.fillStyle = up ? "rgba(0,224,96,0.12)" : "rgba(255,107,107,0.12)"; ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
        ctx.strokeStyle = col; ctx.lineWidth = 1.4; ctx.beginPath(); const xm = (x1 + x2) / 2; ctx.moveTo(xm, g.pts[0][1]); ctx.lineTo(xm, g.pts[1][1]); ctx.stroke();
        label(`${up ? "+" : "−"}${fmt(Math.abs(dp))} (${up ? "+" : "−"}${Math.abs(pc).toFixed(2)}%) · ${bars} bar${bars === 1 ? "" : "s"}`, xm, (up ? y1 : y2 + 16) - 4, col, "center");
      }
      if (sel) g.pts.forEach(([px, py]) => { ctx.beginPath(); ctx.arc(px, py, 4.5, 0, Math.PI * 2); ctx.fillStyle = THEME.bg; ctx.fill(); ctx.strokeStyle = d.color; ctx.lineWidth = 2; ctx.stroke(); });
    }
    ctx.restore();
  }
}
