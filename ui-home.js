/* Search-first home: search any NSE security, then its whole story (5-year chart vs Nifty 50, returns, ranges, the business, what the models see,
   disclosed business links, trading activity), then the full terminal. Every number is a published file of this site; a missing one says so.
   Files: t/universe.json + t/quotes.json (search list and prices), live.json (market strip), t/d/<key>.json (5 years daily), t/x/d/Nifty_2050.json,
   t/fund.json, aladin.json, supply_graph.json (loaded only when a story opens). */
import { marketField } from "./ui-field.js";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 2) => v == null || isNaN(v) ? "--" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 2) => v == null || isNaN(v) ? "--" : (v > 0 ? "+" : "") + Number(v).toFixed(d) + "%";
const cls = v => v == null || isNaN(v) ? "flat" : v > 0 ? "up" : v < 0 ? "down" : "flat";
const rupees = v => v == null ? "--" : v >= 1e12 ? "₹" + num(v / 1e12, 2) + " lakh Cr" : v >= 1e7 ? "₹" + num(v / 1e7, 0) + " Cr" : "₹" + num(v, 0);
const dkey = s => [...s].map(c => /[A-Za-z0-9]/.test(c) ? c : "_" + c.charCodeAt(0).toString(16)).join("");
async function get(f, bust) { const r = await fetch(f + (bust ? "?t=" + Date.now() : ""), { cache: bust ? "no-store" : "default" }); if (!r.ok) throw new Error(f + " " + r.status); return r.json(); }
const cache = {}; const once = (k, f) => cache[k] || (cache[k] = f().catch(e => { delete cache[k]; throw e; }));

const S = { list: [], map: new Map(), quotes: {}, date: null, sel: -1, rows: [] };

/* ---------------- background spotlight follows the pointer ---------------- */
let raf = 0;
addEventListener("pointermove", e => { if (raf) return; raf = requestAnimationFrame(() => { raf = 0; document.documentElement.style.setProperty("--mx", e.clientX + "px"); document.documentElement.style.setProperty("--my", e.clientY + "px"); }); }, { passive: true });

/* ---------------- placeholder that types real names ---------------- */
const input = $("#Search"), box = $("#hx-results");
const EX = ["Reliance Industries", "HDFC Bank", "Tata Motors", "Infosys", "Zomato", "ITC", "Bajaj Finance", "Adani Ports", "Asian Paints", "Larsen & Toubro"];
(function typer() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let i = 0, j = 0, del = false;
  const tick = () => {
    if (document.activeElement === input || input.value) { input.placeholder = "Name or symbol, e.g. RELIANCE"; return setTimeout(tick, 600); }
    const w = EX[i % EX.length]; j += del ? -1 : 1; input.placeholder = "Search " + w.slice(0, j) + (del ? "" : "▏");
    if (!del && j === w.length) { del = true; return setTimeout(tick, 1400); }
    if (del && j === 0) { del = false; i++; }
    setTimeout(tick, del ? 35 : 70);
  };
  tick();
})();

/* ---------------- data for the search ---------------- */
function quoteOf(e) {
  const l = S.quotes[e.s];
  return l && l.d >= e.date ? { p: l.p, pct: l.pct, live: true, t: l.t, d: l.d } : { p: e.c, pct: e.pct, live: false, d: e.date };
}
Promise.all([get("t/universe.json"), get("t/quotes.json", true).catch(() => ({}))]).then(([u, q]) => {
  S.quotes = q.quotes || {}; S.date = u.session_date;
  S.list = u.stocks.map(e => ({ ...e, ns: (e.n || "").toLowerCase(), ss: e.s.toLowerCase() })); S.list.forEach(e => S.map.set(e.s, e));
  $("#hx-count").textContent = S.list.length.toLocaleString("en-IN");
  const top = S.list.filter(e => e.board === "Main" && !e.etf && e.val_cr).sort((a, b) => b.val_cr - a.val_cr).slice(0, 6);
  $("#hx-trending").insertAdjacentHTML("beforeend", top.map(e => { const qq = quoteOf(e); return `<button type="button" class="hx-chip" data-sym="${esc(e.s)}">${esc(e.s)}<b class="${cls(qq.pct)}">${pct(qq.pct, 1)}</b></button>`; }).join(""));
  $("#hx-trending").addEventListener("click", ev => { const b = ev.target.closest("[data-sym]"); if (b) openStory(b.dataset.sym); });
  try { S.field = marketField($("#hx-field"), S.list, quoteOf, sym => openStory(sym)); } catch (err) { $("#hx-fieldnote").hidden = true; }
  if (input.value) render();
  const hp = new URLSearchParams(location.hash.slice(1)); if (hp.get("s") && S.map.has(hp.get("s"))) openStory(hp.get("s"));
}).catch(() => { box.hidden = false; box.innerHTML = '<li class="empty">The stock list could not be loaded. Please try again in a minute.</li>'; });

get("live.json", true).then(L => {
  const by = {}; (L.markets || []).forEach(m => { by[m.ticker] = m; });
  document.querySelectorAll("[data-mkt]").forEach(el => {
    const m = by[el.dataset.mkt], v = el.querySelector("[data-v]"), c = el.querySelector("[data-c]");
    if (!m || m.value == null) { c.textContent = "not available"; return; }
    v.textContent = num(m.value, m.value > 1000 ? 0 : 2); c.textContent = pct(m.change_pct); c.className = cls(m.change_pct);
  });
  $("#hx-asof").textContent = "As of " + (L.generated_ist || "--") + " · market " + (L.market || "status unknown");
}).catch(() => { $("#hx-asof").textContent = "Market prices could not be loaded right now."; });

/* ---------------- search ---------------- */
function score(e, q) {
  let s = e.ss === q ? 1000 : e.ss.startsWith(q) ? 600 : e.ns.startsWith(q) ? 500 : e.ns.includes(" " + q) ? 400 : e.ss.includes(q) ? 250 : e.ns.includes(q) ? 200 : -1;
  if (s < 0) return s;
  return s + (e.n500 ? 60 : 0) + (e.board === "Main" ? 20 : 0) + Math.min(40, Math.log10(1 + (e.val_cr || 0)) * 12) - (e.etf ? 30 : 0);
}
const hl = (text, q) => { const i = text.toLowerCase().indexOf(q); return i < 0 ? esc(text) : esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.length)) + "</mark>" + esc(text.slice(i + q.length)); };
function render() {
  const q = input.value.trim().toLowerCase();
  if (!q) { box.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
  S.rows = S.list.map(e => [score(e, q), e]).filter(r => r[0] >= 0).sort((a, b) => b[0] - a[0]).slice(0, 8).map(r => r[1]); S.sel = S.rows.length ? 0 : -1;
  box.innerHTML = S.rows.length ? S.rows.map((e, i) => { const qq = quoteOf(e); return `<li role="option" id="opt-${i}" data-sym="${esc(e.s)}" aria-selected="${i === S.sel}">
      <span class="sym">${hl(e.s, q)}</span><span class="nm">${hl(e.n || "", q)}</span><span class="px">₹${num(qq.p)}</span><span class="ch ${cls(qq.pct)}">${pct(qq.pct)}</span></li>`; }).join("")
    : `<li class="empty">No NSE security matches "${esc(input.value)}".</li>`;
  box.hidden = false; input.setAttribute("aria-expanded", "true"); input.setAttribute("aria-activedescendant", S.sel >= 0 ? "opt-" + S.sel : "");
}
function move(d) {
  if (!S.rows.length) return; S.sel = (S.sel + d + S.rows.length) % S.rows.length;
  box.querySelectorAll("li[role=option]").forEach((li, i) => li.setAttribute("aria-selected", String(i === S.sel)));
  input.setAttribute("aria-activedescendant", "opt-" + S.sel); box.querySelector(`#opt-${S.sel}`)?.scrollIntoView({ block: "nearest" });
}
input.addEventListener("input", render);
input.addEventListener("keydown", e => {
  if (e.key === "ArrowDown") { e.preventDefault(); move(1); } else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
  else if (e.key === "Enter" && S.sel >= 0) { e.preventDefault(); openStory(S.rows[S.sel].s); }
  else if (e.key === "Escape") { input.value = ""; render(); }
});
box.addEventListener("click", e => { const li = e.target.closest("[data-sym]"); if (li) openStory(li.dataset.sym); });
addEventListener("keydown", e => {
  if (e.key === "/" && document.activeElement !== input && $("#story").hidden) { e.preventDefault(); input.focus(); }
  if (e.key === "Escape" && !$("#story").hidden) closeStory();
});
document.addEventListener("click", e => { if (!e.target.closest("#hx-beam")) box.hidden = true; });

/* ---------------- the stock story ---------------- */
let chart = null, last = null;
const RANGES = [["1M", 21], ["3M", 63], ["6M", 126], ["1Y", 252], ["3Y", 756], ["5Y", 99999]];
function retOver(d, n) { if (!d || d.length < 2) return null; const i = Math.max(0, d.length - 1 - n); return d.length - 1 - i < Math.min(n, 5) ? null : (d[d.length - 1][4] / d[i][4] - 1) * 100; }
function niftyOver(nf, fromDate) { if (!nf) return null; const a = nf.find(r => r[0] >= fromDate); return a ? (nf[nf.length - 1][4] / a[4] - 1) * 100 : null; }

async function openStory(sym) {
  const e = S.map.get(sym); if (!e) return;
  box.hidden = true; input.blur();
  history.replaceState(null, "", "#s=" + encodeURIComponent(sym));
  const st = $("#story"), host = $("#story-in"); st.hidden = false; document.body.style.overflow = "hidden"; last = document.activeElement;
  const qq = quoteOf(e);
  $("#st-sticky").innerHTML = `<span class="font-mono font-bold text-emerald-400">${esc(e.s)}</span><span class="truncate text-sm text-zinc-300">${esc(e.n || "")}</span><span class="ml-auto font-mono font-semibold">₹${num(qq.p)}</span><span class="font-mono text-sm ${cls(qq.pct)}">${pct(qq.pct)}</span>`;
  $("#st-sticky").classList.remove("on");
  $("#st-cta").innerHTML = `<a href="expert-terminal.html#v=terminal&s=${encodeURIComponent(e.s)}" class="hx-open rounded-xl bg-emerald-500 px-6 py-3.5 text-base font-semibold text-zinc-950 shadow-lg shadow-emerald-500/20 transition hover:bg-emerald-400">Open ${esc(e.s)} in the full terminal →</a>`;
  host.innerHTML = `
    <div class="flex items-center justify-between gap-4">
      <button type="button" id="st-back" class="rounded-lg border border-zinc-800 px-3 py-2 text-sm text-zinc-300 hover:border-zinc-600">← Search</button>
      <span class="text-xs text-zinc-500">${qq.live ? "Delayed live price, " + esc(qq.t || "") + " IST" : "NSE close, " + esc(qq.d || "")}</span>
    </div>
    <div class="mt-6 flex flex-wrap items-end justify-between gap-6">
      <div>
        <p class="font-mono text-sm font-semibold text-emerald-400">${esc(e.s)} · NSE${e.n500 ? " · NIFTY 500" : ""}</p>
        <h2 id="st-name" class="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">${esc(e.n || e.s)}</h2>
        <p class="mt-1 text-zinc-400" id="st-sector">${esc(e.ind || "")}</p>
      </div>
      <div class="text-right">
        <p class="font-mono text-4xl font-bold">₹${num(qq.p)}</p>
        <p class="font-mono text-lg font-semibold ${cls(qq.pct)}">${pct(qq.pct)} <span class="text-sm text-zinc-500">today</span></p>
      </div>
    </div>
    <div class="st-card mt-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div><h3>Price history</h3><p class="mt-1 text-sm" id="st-perf">Loading…</p></div>
        <div class="st-tabs" role="group" aria-label="Period">${RANGES.map(([k]) => `<button type="button" data-r="${k}" aria-pressed="${k === "1Y"}">${k}</button>`).join("")}</div>
      </div>
      <div id="st-chart" class="mt-4 h-[340px] w-full" aria-label="Price chart"></div>
      <p class="mt-2 text-xs text-zinc-500"><span class="inline-block h-0.5 w-4 bg-zinc-500 align-middle"></span> Nifty 50 over the same period, scaled to start at the same point.</p>
    </div>
    <div class="st-card mt-4"><h3>Returns vs the market</h3><div class="st-ret" id="st-ret"></div><p class="mt-2 text-xs text-zinc-500">Price change only, before dividends. Small grey number: Nifty 50 over the same period.</p></div>
    <div class="mt-4 grid gap-4 md:grid-cols-2">
      <div class="st-card" id="st-range"><h3>Where the price sits</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
      <div class="st-card" id="st-trade"><h3>Trading activity, last session</h3></div>
      <div class="st-card" id="st-biz"><h3>The business</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
      <div class="st-card" id="st-model"><h3>What our models see</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
    </div>
    <div class="st-card mt-4" id="st-links"><h3>Disclosed business links</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
    <p class="mt-6 text-center text-xs text-zinc-500">Educational analysis, not investment advice. Models are statistical and often wrong.</p>
`;
  $("#st-back").onclick = closeStory; $("#st-back").focus();
  if (S.field) S.field.pause();
  st.scrollTop = 0; st.onscroll = () => $("#st-sticky")?.classList.toggle("on", st.scrollTop > 170);
  host.querySelectorAll(".st-card").forEach(c => c.classList.add("st-reveal"));
  const io = new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }), { root: st, threshold: 0.08 });
  host.querySelectorAll(".st-reveal").forEach(c => io.observe(c));
  $("#st-cta .hx-open").addEventListener("click", ev => { if (ev.metaKey || ev.ctrlKey) return; ev.preventDefault(); const href = ev.currentTarget.href; document.body.classList.add("hx-leave"); setTimeout(() => { location.href = href; }, 330); });
  tradeCard(e);
  const [d, nf] = await Promise.all([get(`t/d/${dkey(sym)}.json`).then(j => j.d).catch(() => null), once("nifty", () => get("t/x/d/Nifty_2050.json").then(j => j.d)).catch(() => null)]);
  if (d && d.length && qq.d && qq.d > d[d.length - 1][0] && qq.p) d.push([qq.d, qq.p, qq.p, qq.p, qq.p, 0]);   // the published history can lag a day or two: end it at today's price
  storyChart(e, d, nf); returnsCard(d, nf); rangeCard(e, d);
  once("fund", () => get("t/fund.json").then(j => j.stocks || {})).then(f => bizCard(e, f[sym])).catch(() => bizCard(e, null));
  once("aladin", () => get("aladin.json")).then(a => modelCard(a, sym)).catch(() => modelCard(null, sym));
  once("graph", () => get("supply_graph.json")).then(g => linksCard(g, sym)).catch(() => linksCard(null, sym));
}
function closeStory() {
  if (S.field) S.field.resume();
  $("#story").hidden = true; document.body.style.overflow = ""; if (chart) { chart.remove(); chart = null; }
  history.replaceState(null, "", location.pathname + location.search); (last && last.focus ? last : input).focus();
}

function storyChart(e, d, nf) {
  const el = $("#st-chart"), perf = $("#st-perf");
  if (!d || !d.length) { el.innerHTML = '<p class="grid h-full place-content-center text-sm text-zinc-500">No price history is published for this security (SME and some recent listings are not covered).</p>'; perf.textContent = ""; return; }
  const LC = window.LightweightCharts;
  if (!LC) { el.innerHTML = '<p class="grid h-full place-content-center text-sm text-zinc-500">The chart library could not be loaded.</p>'; return; }
  const cv = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const css = (n, a = 1) => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(n).trim(); cv.fillRect(0, 0, 1, 1); const [r, g, b] = cv.getImageData(0, 0, 1, 1).data; return `rgba(${r},${g},${b},${a})`; };
  chart = LC.createChart(el, { autoSize: true, layout: { background: { color: "transparent" }, textColor: css("--color-zinc-400"), fontFamily: "JetBrains Mono, monospace", attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { color: css("--color-zinc-800") } }, rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false }, crosshair: { mode: 1 },
    handleScroll: false, handleScale: false });
  const area = chart.addSeries(LC.AreaSeries, { lineWidth: 2, priceLineVisible: false });
  const bench = chart.addSeries(LC.LineSeries, { color: css("--color-zinc-500"), lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  const show = key => {
    const n = RANGES.find(r => r[0] === key)[1], seg = d.slice(-Math.min(d.length, n + 1));
    const r = (seg[seg.length - 1][4] / seg[0][4] - 1) * 100, k = r >= 0 ? "--color-emerald-400" : "--color-red-400";
    area.applyOptions({ lineColor: css(k), topColor: css(k, 0.28), bottomColor: css(k, 0) });
    area.setData(seg.map(x => ({ time: x[0], value: x[4] })));
    const nseg = nf ? nf.filter(x => x[0] >= seg[0][0]) : [];
    bench.setData(nseg.length ? nseg.map(x => ({ time: x[0], value: x[4] / nseg[0][4] * seg[0][4] })) : []);
    chart.timeScale().fitContent();
    const nr = nseg.length ? (nseg[nseg.length - 1][4] / nseg[0][4] - 1) * 100 : null;
    perf.innerHTML = `<b class="font-mono ${cls(r)}">${pct(r)}</b> <span class="text-zinc-400">over ${key === "5Y" ? "the period shown (from " + esc(seg[0][0]) + ")" : key}</span>${nr != null ? ` <span class="text-zinc-500">· Nifty 50 ${pct(nr)}</span>` : ""}`;
    document.querySelectorAll(".st-tabs button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.r === key)));
  };
  document.querySelectorAll(".st-tabs button").forEach(b => b.onclick = () => show(b.dataset.r));
  show("1Y");
}
function returnsCard(d, nf) {
  const el = $("#st-ret");
  el.innerHTML = RANGES.map(([k, n]) => {
    const r = retOver(d, n), i = d ? Math.max(0, d.length - 1 - n) : 0, nr = d && r != null ? niftyOver(nf, d[i][0]) : null;
    return `<div><span>${k === "5Y" ? "Max" : k}</span><b class="${cls(r)}" data-count="${r == null ? "" : r.toFixed(1)}">${pct(r, 1)}</b><small>${nr != null ? "Nifty " + pct(nr, 1) : "&nbsp;"}</small></div>`;
  }).join("");
  countUp(el.querySelectorAll("[data-count]"));
}
function countUp(nodes) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const t0 = performance.now(), list = [...nodes].filter(n => n.dataset.count !== "").map(n => [n, +n.dataset.count]);
  const step = now => { const k = Math.min(1, (now - t0) / 700), f = 1 - Math.pow(1 - k, 3); list.forEach(([n, v]) => { n.textContent = pct(v * f, 1); }); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function rangeCard(e, d) {
  const el = $("#st-range"), lo = e.lo52, hi = e.hi52, p = quoteOf(e).p;
  let h = `<h3>Where the price sits</h3>`;
  if (lo && hi && hi > lo) {
    const x = Math.max(0, Math.min(100, (p - lo) / (hi - lo) * 100));
    h += `<div class="st-range" role="img" aria-label="Price at ${x.toFixed(0)}% of its 52-week range"><i style="left:${x}%"></i></div>
      <div class="mt-2 flex justify-between font-mono text-xs text-zinc-400"><span>52-week low ₹${num(lo)}</span><span>high ₹${num(hi)}</span></div>
      <p class="mt-2 text-sm text-zinc-300">${(hi / p - 1) * 100 < 0.5 ? "Trading at its 52-week high." : `${pct(-(1 - p / hi) * 100, 1)} below its 52-week high.`}</p>`;
  }
  if (d && d.length > 20) {
    let peak = d[0][4], mdd = 0, best = [null, -1e9], worst = [null, 1e9], hiAll = d[0], loAll = d[0];
    for (let i = 1; i < d.length; i++) {
      const c = d[i][4], r = (c / d[i - 1][4] - 1) * 100; peak = Math.max(peak, c); mdd = Math.min(mdd, (c / peak - 1) * 100);
      if (r > best[1]) best = [d[i][0], r]; if (r < worst[1]) worst = [d[i][0], r]; if (c > hiAll[4]) hiAll = d[i]; if (c < loAll[4]) loAll = d[i];
    }
    h += `<dl class="st-kv"><dt>Highest close since ${esc(d[0][0].slice(0, 4))}</dt><dd>₹${num(hiAll[4])} <span class="text-zinc-500">${esc(hiAll[0])}</span></dd>
      <dt>Lowest close</dt><dd>₹${num(loAll[4])} <span class="text-zinc-500">${esc(loAll[0])}</span></dd>
      <dt>Biggest fall from a high</dt><dd class="down">${pct(mdd, 1)}</dd>
      <dt>Best day</dt><dd class="up">${pct(best[1], 1)} <span class="text-zinc-500">${esc(best[0])}</span></dd>
      <dt>Worst day</dt><dd class="down">${pct(worst[1], 1)} <span class="text-zinc-500">${esc(worst[0])}</span></dd></dl>`;
  } else if (!(lo && hi)) h += `<p class="mt-3 text-sm text-zinc-400">Not enough price history to measure.</p>`;
  el.innerHTML = h;
}
function tradeCard(e) {
  $("#st-trade").innerHTML = `<h3>Trading activity, last session</h3><dl class="st-kv">
    <dt>Shares traded</dt><dd>${e.v != null ? num(e.v, 0) : "--"}</dd>
    <dt>Value traded</dt><dd>${e.val_cr != null ? "₹" + num(e.val_cr, 1) + " Cr" : "--"}</dd>
    <dt>vs its 20-day average</dt><dd>${e.v && e.avgv20 ? num(e.v / e.avgv20, 1) + "×" : "--"}</dd>
    <dt>Delivery (kept, not day-traded)</dt><dd>${e.deliv != null ? num(e.deliv, 1) + "%" : "--"}</dd>
    <dt>Listed on NSE</dt><dd>${esc(e.listed || "--")}</dd></dl>`;
}
function bizCard(e, f) {
  const el = $("#st-biz");
  if (!f) { el.innerHTML = `<h3>The business</h3><p class="mt-3 text-sm text-zinc-400">No company financials are published for this security.</p>`; return; }
  if (f.sector || f.industry) $("#st-sector").textContent = [f.sector, f.industry].filter(Boolean).join(" · ");
  const desc = f.desc ? (f.desc.length > 260 ? f.desc.slice(0, 260).replace(/\s\S*$/, "") + "…" : f.desc) : "";
  el.innerHTML = `<h3>The business</h3>${desc ? `<p class="mt-3 text-sm leading-relaxed text-zinc-300">${esc(desc)}</p>` : ""}<dl class="st-kv">
    <dt>Market value</dt><dd>${rupees(f.mcap)}</dd>
    <dt>Price ÷ earnings (P/E)</dt><dd>${f.pe != null ? num(f.pe, 1) : "--"}</dd>
    <dt>Price ÷ book value</dt><dd>${f.pb != null ? num(f.pb, 1) : "--"}</dd>
    <dt>Revenue growth, last year</dt><dd class="${cls(f.revg)}">${f.revg != null ? pct(f.revg * 100, 1) : "--"}</dd>
    <dt>Profit margin</dt><dd>${f.pm != null ? num(f.pm * 100, 1) + "%" : "--"}</dd>
    <dt>Dividend yield</dt><dd>${f.dy != null ? num(f.dy, 2) + "%" : "--"}</dd></dl>`;
}
function modelCard(a, sym) {
  const el = $("#st-model"), s = a && a.stocks && a.stocks[sym], p = s && s.t && s.t.p;
  if (!p) { el.innerHTML = `<h3>What our models see</h3><p class="mt-3 text-sm text-zinc-400">This security is not scored by the model (it needs 250 days of trading history and recent activity).</p>`; return; }
  const names = (a.model && a.model.names) || {}, drv = (s.t.drv || []).filter(([n]) => names[n] || !/^(dom|moy|dow)$/.test(n)).slice(0, 3).map(([n]) => names[n] || n);
  const bar = v => `<div class="mt-1 h-1.5 rounded-full bg-zinc-800"><div class="h-1.5 rounded-full ${v >= 0.5 ? "bg-emerald-400" : "bg-red-400"}" style="width:${(v * 100).toFixed(0)}%"></div></div>`;
  el.innerHTML = `<h3>What our models see</h3><p class="mt-3 text-sm text-zinc-400">Estimated chance that the price is higher after… (model data as of ${esc(a.as_of || "--")})</p>
    <dl class="mt-3 space-y-3">${["5", "10", "20"].filter(h => p[h] != null).map(h => `<div><div class="flex justify-between text-sm"><dt>${h} trading days</dt><dd class="font-mono font-semibold">${(p[h] * 100).toFixed(0)}%</dd></div>${bar(p[h])}</div>`).join("")}</dl>
    ${drv.length ? `<p class="mt-3 text-xs text-zinc-500">Weighing most right now: ${drv.map(esc).join(", ")}.</p>` : ""}
    <p class="mt-2 text-xs text-zinc-500">50% means the model sees no edge either way. A statistical model, often wrong.</p>`;
}
function linksCard(g, sym) {
  const el = $("#st-links");
  if (!g) { el.innerHTML = `<h3>Disclosed business links</h3><p class="mt-3 text-sm text-zinc-400">The supply-chain map could not be loaded.</p>`; return; }
  const nodes = new Map((g.nodes || []).map(n => [n.id, n])), es = (g.edges || []).filter(x => x.s === sym || x.d === sym).slice(0, 8);
  const read = (g.cos || {})[sym];
  if (!es.length) { el.innerHTML = `<h3>Disclosed business links</h3><p class="mt-3 text-sm text-zinc-400">${read ? "This company's filings were read; none named a customer or supplier the checks could confirm." : "This company's filings have not been read yet. The map grows every day."}</p>`; return; }
  const row = x => { const other = x.s === sym ? x.d : x.s, n = nodes.get(other), name = (n && n.n) || x.cpn || other, role = x.s === sym ? "customer" : "supplier";                     // every link type reads "s supplies d"
    return `<li class="flex items-start justify-between gap-3 border-t border-zinc-800 py-2.5 first:border-0"><span><span class="text-zinc-100">${esc(name)}</span>${n && n.sym ? ` <span class="font-mono text-xs text-emerald-400">${esc(n.sym)}</span>` : ""}<span class="block text-xs text-zinc-500">“${esc((x.q || "").slice(0, 140))}”</span></span><span class="shrink-0 rounded-full border border-zinc-700 px-2 py-0.5 text-xs text-zinc-400">${role}</span></li>`; };
  el.innerHTML = `<h3>Disclosed business links</h3><p class="mt-2 text-sm text-zinc-400">Named in the company's own filings and calls, each with the sentence it came from.</p><ul class="mt-2">${es.map(row).join("")}</ul>`;
}
