/* Search-first home, the landing page on every visit: find a stock, understand it in plain words, try "what if I had invested", compare, keep a watchlist
   (shared with the terminal), then open the full terminal. Every number is a published file of this site; a missing one says so.
   Components: HyperUI (MIT) tabs/1, toasts/1, button-groups/1, range-inputs/1, empty-states/1; help bubbles use the browser's popover API.
   Files: t/universe.json + t/quotes.json (search, prices), live.json (market strip), t/d/<key>.json (5 years daily), t/x/d/Nifty_2050.json,
   t/fund.json, aladin.json, supply_graph.json (only when a story opens). */
import * as RD from "./desk-revdeps.js";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 2) => v == null || isNaN(v) ? "--" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 2) => v == null || isNaN(v) ? "--" : (v > 0 ? "+" : "") + Number(v).toFixed(d) + "%";
const cls = v => v == null || isNaN(v) ? "flat" : v > 0 ? "up" : v < 0 ? "down" : "flat";
const rupees = v => v == null || isNaN(v) ? "--" : v >= 1e12 ? "₹" + num(v / 1e12, 2) + " lakh Cr" : v >= 1e7 ? "₹" + num(v / 1e7, 0) + " Cr" : "₹" + num(v, 0);
const dkey = s => [...s].map(c => /[A-Za-z0-9]/.test(c) ? c : "_" + c.charCodeAt(0).toString(16)).join("");
async function get(f, bust) { const r = await fetch(f + (bust ? "?t=" + Date.now() : ""), { cache: bust ? "no-store" : "default" }); if (!r.ok) throw new Error(f + " " + r.status); return r.json(); }
const cache = {}; const once = (k, f) => cache[k] || (cache[k] = f().catch(e => { delete cache[k]; throw e; }));
const LS = { get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* not remembered */ } } };
const median = a => { const b = a.filter(x => x != null && isFinite(x)).sort((p, q) => p - q); return b.length ? b[Math.floor(b.length / 2)] : null; };

const S = { list: [], map: new Map(), quotes: {}, sel: -1, rows: [], intent: null, cur: null };

/* ---------------- plain-English help for every number (popover API) ---------------- */
const HELP = {
  pe: "Price ÷ earnings: how many rupees investors pay today for each rupee of the company's yearly profit. Higher can mean investors expect growth, or that it is expensive.",
  pb: "Price ÷ book value: the share price compared with what the company owns minus what it owes, per share.",
  mcap: "Market value: the share price × all the company's shares. What the whole company is worth on the stock market today.",
  dy: "Dividend yield: the cash dividends of the last year as a share of today's price.",
  revg: "Revenue growth: how much the company's sales grew over the last year.",
  pm: "Profit margin: how much of every ₹100 of sales is left as profit.",
  range: "The lowest and highest price of the last 52 weeks (one year), and where today's price sits between them.",
  deliv: "Delivery %: the share of traded shares that buyers actually kept, instead of buying and selling the same day. Higher usually means longer-term holders.",
  vol20: "Today's trading compared with an average day over the last 20 sessions. Above 1× means busier than usual.",
  model: "Our statistical model estimates the chance the price is higher after a number of trading days. 50% means it sees no edge either way. It is often wrong.",
  dd: "Biggest fall from a high: the worst drop from a peak to a later low in the period shown. A feel for how bumpy holding it has been.",
  nifty: "Nifty 50: an index of India's 50 biggest companies, used here as 'the market' to compare with.",
  links: "Customers and suppliers named in the company's own filings and earnings calls, each with the sentence it came from.",
  pred: "Predicted links are a statistical model's estimate, not facts. The model looks at four kinds of evidence: one company naming the other in its annual report, the two shares moving together beyond their industries, business descriptions that fit together, and the same business group. Links already confirmed in filings are not repeated here.",
  dep: "Revenue dependency: how much of the company's sales rest on a single customer. Indian accounting rules (Ind AS 108) make listed companies disclose every customer worth 10% or more of revenue, usually without the name. High = one customer is 25% or more; Moderate = 10 to 25%; Low = the company states that none reaches 10%.",
  geo: "Where the revenue comes from: the split by region that the company reports in its segment note. A large share from outside India means exposure to other economies and to the rupee.",
};
let helpN = 0;
const help = k => { const id = "h" + (++helpN); return `<button type="button" class="hx-help" popovertarget="${id}" aria-label="What does this mean?">i</button><div id="${id}" popover class="hx-pop">${esc(HELP[k])}</div>`; };

/* ---------------- toast (HyperUI toasts/1) ---------------- */
function toast(title, text) {
  const host = $("#hx-toasts"), el = document.createElement("div");
  el.setAttribute("role", "status");
  el.className = "rounded-md border border-green-500 bg-green-50 p-4 shadow-sm dark:border-green-400 dark:bg-green-800";
  el.innerHTML = `<div class="flex items-start gap-4"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6 text-green-700 dark:text-green-200" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
    <div class="flex-1"><strong class="block leading-tight font-medium text-green-800 dark:text-green-100">${esc(title)}</strong><p class="mt-0.5 text-sm text-green-700 dark:text-green-200">${esc(text)}</p></div></div>`;
  host.appendChild(el); setTimeout(() => el.remove(), 3600);
}

/* ---------------- watchlist (the terminal's own list) and recently viewed ---------------- */
const watch = () => LS.get("blab-watch", []) || [];
function toggleWatch(sym) {
  const w = watch();
  if (w.includes(sym)) { LS.set("blab-watch", w.filter(s => s !== sym)); toast("Removed from your watchlist", sym + " will no longer appear in the terminal's watchlist."); }
  else { LS.set("blab-watch", [sym, ...w].slice(0, 60)); toast("Added to your watchlist", sym + " now sits in your watchlist here and in the terminal."); }
  paintMine(); paintWatchBtn(sym);
}
function remember(sym) { LS.set("blab-recent", [sym, ...(LS.get("blab-recent", []) || []).filter(s => s !== sym)].slice(0, 8)); }
function paintMine() {
  const el = $("#hx-mine"); if (!el || !S.list.length) return;
  const chip = s => { const e = S.map.get(s); if (!e) return ""; const q = quoteOf(e); return `<button type="button" class="hx-chip" data-sym="${esc(s)}">${esc(s)}<b class="${cls(q.pct)}">${pct(q.pct, 1)}</b></button>`; };
  const w = watch().filter(s => S.map.has(s)).slice(0, 8), r = (LS.get("blab-recent", []) || []).filter(s => S.map.has(s) && !w.includes(s)).slice(0, 6);
  el.innerHTML = (w.length ? `<span class="text-zinc-500">★ Watchlist:</span>${w.map(chip).join("")}` : "") + (r.length ? `<span class="ml-2 text-zinc-500">Recently viewed:</span>${r.map(chip).join("")}` : "");
  el.hidden = !(w.length || r.length);
}

/* ---------------- data for the search ---------------- */
const input = $("#Search"), box = $("#hx-results");
function quoteOf(e) {
  const l = S.quotes[e.s];
  return l && l.d >= e.date ? { p: l.p, pct: l.pct, live: true, t: l.t, d: l.d } : { p: e.c, pct: e.pct, live: false, d: e.date };
}
Promise.all([get("t/universe.json"), get("t/quotes.json", true).catch(() => ({}))]).then(([u, q]) => {
  S.quotes = q.quotes || {};
  S.list = u.stocks.map(e => ({ ...e, ns: (e.n || "").toLowerCase(), ss: e.s.toLowerCase() })); S.list.forEach(e => S.map.set(e.s, e));
  $("#hx-count").textContent = S.list.length.toLocaleString("en-IN");
  const top = S.list.filter(e => e.board === "Main" && !e.etf && e.val_cr).sort((a, b) => b.val_cr - a.val_cr).slice(0, 6);
  $("#hx-trending").insertAdjacentHTML("beforeend", top.map(e => { const qq = quoteOf(e); return `<button type="button" class="hx-chip" data-sym="${esc(e.s)}">${esc(e.s)}<b class="${cls(qq.pct)}">${pct(qq.pct, 1)}</b></button>`; }).join(""));
  paintMine();
  if (input.value) render();
  const hp = new URLSearchParams(location.hash.slice(1)); if (hp.get("s") && S.map.has(hp.get("s"))) openStory(hp.get("s"), hp.get("tab"));
}).catch(() => { box.hidden = false; box.innerHTML = '<li class="empty">The stock list could not be loaded. Please try again in a minute.</li>'; });
addEventListener("hashchange", () => { const hp = new URLSearchParams(location.hash.slice(1)), s = hp.get("s"); if (s && S.map.has(s) && (!S.cur || S.cur.e.s !== s)) openStory(s, hp.get("tab")); else if (!s && S.cur) closeStory(); });
document.addEventListener("click", ev => { const b = ev.target.closest("#hx-trending [data-sym], #hx-mine [data-sym], #hx-movers [data-sym]"); if (b) { closeMovers(); openStory(b.dataset.sym, S.intent); } });

get("live.json", true).then(L => {
  const by = {}; (L.markets || []).forEach(m => { by[m.ticker] = m; });
  document.querySelectorAll("[data-mkt]").forEach(el => {
    const m = by[el.dataset.mkt], v = el.querySelector("[data-v]"), c = el.querySelector("[data-c]");
    if (!m || m.value == null) { c.textContent = "not available"; return; }
    v.textContent = num(m.value, m.value > 1000 ? 0 : 2); c.textContent = pct(m.change_pct); c.className = cls(m.change_pct);
  });
  $("#hx-asof").textContent = "As of " + (L.generated_ist || "--") + " · market " + (L.market || "status unknown");
}).catch(() => { $("#hx-asof").textContent = "Market prices could not be loaded right now."; });

/* ---------------- tasks on the home page ---------------- */
const INTENT_HINT = { whatif: "Pick a stock for the what-if calculator…", chart: "Pick the first stock to compare…" };
document.querySelectorAll("[data-task]").forEach(b => b.addEventListener("click", () => {
  const t = b.dataset.task;
  if (t === "movers") return openMovers();
  if (t === "deps") return openDeps();
  S.intent = t; input.placeholder = INTENT_HINT[t]; input.focus();
  $("#hx-intent").hidden = false; $("#hx-intent-t").textContent = t === "whatif" ? "What if I had invested: choose a stock" : "Compare: choose the first stock, then add the second on its chart";
}));
$("#hx-intent-x").addEventListener("click", () => { S.intent = null; $("#hx-intent").hidden = true; input.placeholder = "Name or symbol, e.g. RELIANCE"; });
function openMovers() {
  if (!S.list.length) return;
  const n5 = S.list.filter(e => e.n500 && !e.etf), byP = n5.map(e => [e, quoteOf(e).pct]).filter(r => r[1] != null).sort((a, b) => b[1] - a[1]);
  const row = ([e, p]) => `<li><button type="button" data-sym="${esc(e.s)}" class="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-zinc-800"><span class="min-w-0"><b class="font-mono text-sm">${esc(e.s)}</b><span class="block truncate text-xs text-zinc-400">${esc(e.n || "")}</span></span><span class="font-mono text-sm font-semibold ${cls(p)}">${pct(p)}</span></button></li>`;
  $("#hx-movers-body").innerHTML = `<div class="grid gap-6 sm:grid-cols-2"><div><h3 class="mb-2 text-sm font-semibold text-emerald-400">Biggest rises</h3><ul>${byP.slice(0, 8).map(row).join("")}</ul></div>
    <div><h3 class="mb-2 text-sm font-semibold text-red-400">Biggest falls</h3><ul>${byP.slice(-8).reverse().map(row).join("")}</ul></div></div>
    <p class="mt-4 text-xs text-zinc-500">Among the NIFTY 500, change since the previous close. Tap any stock to see its story.</p>`;
  $("#hx-movers").showModal();
}
function closeMovers() { ["#hx-movers", "#hx-deps"].forEach(k => { const d = $(k); if (d && d.open) d.close(); }); }
async function openDeps() {
  const body = $("#hx-deps-body"); body.innerHTML = '<p class="text-sm text-zinc-400">Loading…</p>'; $("#hx-deps").showModal();
  const doc = await once("deps", () => get("dependencies.json")).catch(() => null);
  if (!doc) { body.innerHTML = '<p class="text-sm text-zinc-400">The dependency profiles could not be loaded.</p>'; return; }
  const rows = RD.mostDependent(doc, 40).filter(r => S.map.has(r.sym));
  const lv = r => RD.LEVELS[r.lvl];
  body.innerHTML = rows.length ? `<ul class="divide-y divide-zinc-800">${rows.map(r => { const u = S.map.get(r.sym), q = quoteOf(u);
      return `<li><button type="button" data-sym="${esc(r.sym)}" data-tab="revenue" class="flex w-full items-center justify-between gap-3 px-2 py-3 text-left hover:bg-zinc-900"><span class="min-w-0"><b class="font-mono text-sm">${esc(r.sym)}</b> <span class="text-xs text-zinc-400">${esc(u.n || "")}</span><span class="block text-sm text-zinc-300">${esc(r.why)}${r.abroad != null && r.abroad >= 0.05 ? ` · ${(r.abroad * 100).toFixed(0)}% from outside India` : ""}</span></span>
        <span class="shrink-0 text-right"><span class="block font-mono text-lg font-bold ${lv(r).tone === "down" ? "text-red-300" : "text-amber-200"}">${r.share != null ? (r.share * 100).toFixed(0) + "%" : "≥10%"}</span><span class="font-mono text-xs ${cls(q.pct)}">${pct(q.pct)} today</span></span></button></li>`; }).join("")}</ul>
      <p class="mt-4 text-xs text-zinc-500">${doc.counts.high} high, ${doc.counts.moderate} moderate, ${doc.counts.low} low and ${doc.counts.unknown} not yet disclosed among ${Object.keys(doc.cos).length} companies read. From each company's own filings; nothing is estimated.</p>`
    : '<p class="text-sm text-zinc-400">No company has disclosed a customer worth 10% or more of revenue in the filings read so far.</p>';
  body.querySelectorAll("[data-sym]").forEach(b => b.onclick = () => { closeMovers(); openStory(b.dataset.sym, "revenue"); });
}
$("#hx-deps-x").addEventListener("click", closeMovers);
$("#hx-movers-x").addEventListener("click", closeMovers);

/* ---------------- search ---------------- */
function score(e, q) {
  let s = e.ss === q ? 1000 : e.ss.startsWith(q) ? 600 : e.ns.startsWith(q) ? 500 : e.ns.includes(" " + q) ? 400 : e.ss.includes(q) ? 250 : e.ns.includes(q) ? 200 : -1;
  if (s < 0) return s;
  return s + (e.n500 ? 60 : 0) + (e.board === "Main" ? 20 : 0) + Math.min(40, Math.log10(1 + (e.val_cr || 0)) * 12) - (e.etf ? 30 : 0);
}
const hl = (text, q) => { const i = text.toLowerCase().indexOf(q); return i < 0 ? esc(text) : esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.length)) + "</mark>" + esc(text.slice(i + q.length)); };
function matches(q) { return S.list.map(e => [score(e, q), e]).filter(r => r[0] >= 0).sort((a, b) => b[0] - a[0]).slice(0, 8).map(r => r[1]); }
function render() {
  const q = input.value.trim().toLowerCase();
  if (!q) { box.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
  S.rows = matches(q); S.sel = S.rows.length ? 0 : -1;
  box.innerHTML = S.rows.length ? S.rows.map((e, i) => { const qq = quoteOf(e); return `<li role="option" id="opt-${i}" data-sym="${esc(e.s)}" aria-selected="${i === S.sel}">
      <span class="sym">${hl(e.s, q)}</span><span class="nm">${hl(e.n || "", q)}</span><span class="px">₹${num(qq.p)}</span><span class="ch ${cls(qq.pct)}">${pct(qq.pct)}</span></li>`; }).join("")
    : `<li class="empty">No NSE security matches "${esc(input.value)}". Try the company's name or its NSE symbol.</li>`;
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
  else if (e.key === "Enter" && S.sel >= 0) { e.preventDefault(); openStory(S.rows[S.sel].s, S.intent); }
  else if (e.key === "Escape") { input.value = ""; render(); }
});
box.addEventListener("click", e => { const li = e.target.closest("[data-sym]"); if (li) openStory(li.dataset.sym, S.intent); });
addEventListener("keydown", e => {
  if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && $("#story").hidden) { e.preventDefault(); input.focus(); }
  if (e.key === "Escape" && !$("#story").hidden && !document.querySelector(":popover-open")) closeStory();
});
document.addEventListener("click", e => { if (!e.target.closest("#hx-beam")) box.hidden = true; if (!e.target.closest("#cmp-wrap")) { const c = $("#cmp-results"); if (c) c.hidden = true; } });

/* ---------------- the stock story: tabs ---------------- */
const TABS = [["overview", "Overview"], ["chart", "Chart"], ["business", "Business"], ["revenue", "Revenue & customers"], ["whatif", "What if I had invested?"]];
const RANGES = [["1M", 21], ["3M", 63], ["6M", 126], ["1Y", 252], ["3Y", 756], ["5Y", 99999]];
let chart = null, last = null;
const tabBtn = (k, label, on) => on
  ? `<button role="tab" id="tab-${k}" aria-controls="panel-${k}" aria-selected="true" data-tab="${k}" class="border-b-2 border-blue-600 px-4 py-2 text-sm font-medium whitespace-nowrap text-blue-600 transition-colors hover:text-blue-700 dark:hover:text-blue-500">${label}</button>`
  : `<button role="tab" id="tab-${k}" aria-controls="panel-${k}" aria-selected="false" tabindex="-1" data-tab="${k}" class="border-b-2 border-transparent px-4 py-2 text-sm font-medium whitespace-nowrap text-gray-600 transition-colors hover:text-gray-700 dark:text-gray-300 dark:hover:text-gray-200">${label}</button>`;
function selectTab(k) {
  if (!TABS.some(t => t[0] === k)) k = "overview";
  $("#st-tabs").innerHTML = TABS.map(([t, l]) => tabBtn(t, l, t === k)).join("");
  document.querySelectorAll("[data-panel]").forEach(p => { p.hidden = p.dataset.panel !== k; });
  if (k === "chart" && chart) chart.timeScale().fitContent();
  if (S.cur) history.replaceState(null, "", "#s=" + encodeURIComponent(S.cur.e.s) + (k !== "overview" ? "&tab=" + k : ""));
}

async function openStory(sym, tab) {
  const e = S.map.get(sym); if (!e) return;
  box.hidden = true; input.blur(); remember(sym); paintMine();
  S.intent = null; $("#hx-intent").hidden = true; input.placeholder = "Name or symbol, e.g. RELIANCE";
  const st = $("#story"), host = $("#story-in"); st.hidden = false; st.scrollTop = 0; document.body.style.overflow = "hidden"; if (!S.cur) last = document.activeElement;
  if (chart) { chart.remove(); chart = null; }
  const qq = quoteOf(e); S.cur = { e, qq, d: null, nf: null, cmp: null, range: null };
  $("#st-cta").innerHTML = `<a href="expert-terminal.html#v=terminal&s=${encodeURIComponent(e.s)}" class="hx-open rounded-xl bg-emerald-500 px-6 py-3.5 text-base font-semibold text-zinc-950 shadow-lg shadow-emerald-500/20 transition hover:bg-emerald-400">Open ${esc(e.s)} in the full terminal →</a>`;
  const BG = "border border-gray-200 px-3 py-2 font-medium text-gray-700 transition-colors hover:bg-gray-50 hover:text-gray-900 focus:z-10 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-white focus:outline-none dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800 dark:hover:text-white dark:focus:ring-offset-gray-900";
  host.innerHTML = `
    <div class="flex items-center justify-between gap-4">
      <button type="button" id="st-back" class="rounded-lg border border-zinc-800 px-3 py-2 text-sm text-zinc-300 hover:border-zinc-600">← Back to search</button>
      <span class="text-xs text-zinc-500">${qq.live ? "Delayed live price, " + esc(qq.t || "") + " IST" : "NSE close, " + esc(qq.d || "")}</span>
    </div>
    <div class="mt-6 flex flex-wrap items-end justify-between gap-6">
      <div class="min-w-0">
        <p class="font-mono text-sm font-semibold text-emerald-400">${esc(e.s)} · NSE${e.n500 ? " · NIFTY 500" : ""}</p>
        <h2 id="st-name" class="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">${esc(e.n || e.s)}</h2>
        <p class="mt-1 text-zinc-400" id="st-sector">${esc(e.ind || "")}</p>
      </div>
      <div class="text-right">
        <p class="font-mono text-4xl font-bold">₹${num(qq.p)}</p>
        <p class="font-mono text-lg font-semibold ${cls(qq.pct)}">${pct(qq.pct)} <span class="text-sm text-zinc-500">today</span></p>
      </div>
    </div>
    <!-- HyperUI application/button-groups/1 -->
    <div class="mt-5 inline-flex" role="group" aria-label="Actions">
      <button type="button" id="st-watch" class="rounded-s-sm ${BG}"></button>
      <button type="button" data-go="chart" class="-ms-px ${BG}">Compare</button>
      <button type="button" data-go="whatif" class="-ms-px rounded-e-sm ${BG}">What if?</button>
    </div>
    <!-- HyperUI application/tabs/1 -->
    <div class="mt-6 -mb-px overflow-x-auto border-b border-gray-200 dark:border-gray-700"><div role="tablist" aria-label="About this stock" class="flex gap-1" id="st-tabs"></div></div>
    <section data-panel="overview" id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" class="mt-5 space-y-4">
      <div class="st-card"><h3>In plain words</h3><ul class="mt-3 space-y-2 text-[15px] leading-relaxed text-zinc-200" id="st-plain"><li class="text-zinc-500">Reading the numbers…</li></ul></div>
      <div class="grid gap-4 md:grid-cols-2"><div class="st-card" id="st-range"><h3>Where the price sits</h3></div><div class="st-card" id="st-model"><h3>What our models see</h3></div></div>
      <div class="st-card" id="st-depmini" hidden></div>
      <div class="st-card" id="st-peers"><h3>Similar companies</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
    </section>
    <section data-panel="chart" id="panel-chart" role="tabpanel" aria-labelledby="tab-chart" class="mt-5 space-y-4" hidden>
      <div class="st-card">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div><h3>Price history</h3><p class="mt-1 text-sm" id="st-perf">Loading…</p></div>
          <div class="st-tabs" role="group" aria-label="Period">${RANGES.map(([k]) => `<button type="button" data-r="${k}" aria-pressed="${k === "1Y"}">${k}</button>`).join("")}</div>
        </div>
        <div class="relative mt-4 max-w-md" id="cmp-wrap">
          <label for="cmp" class="sr-only">Compare with another stock</label>
          <input id="cmp" type="text" autocomplete="off" placeholder="+ Compare with another stock" class="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500" />
          <ul id="cmp-results" class="hx-results" role="listbox" aria-label="Stocks to compare" hidden></ul>
        </div>
        <div id="st-chart" class="mt-4 h-[360px] w-full" aria-label="Price chart"></div>
        <p class="mt-2 text-xs text-zinc-500" id="st-legend"></p>
      </div>
      <div class="st-card"><h3>Returns vs the market ${help("nifty")}</h3><div class="st-ret" id="st-ret"></div><p class="mt-2 text-xs text-zinc-500">Price change only, before dividends. Small grey number: Nifty 50 over the same period.</p></div>
      <div class="st-card" id="st-trade"><h3>Trading activity, last session</h3></div>
    </section>
    <section data-panel="business" id="panel-business" role="tabpanel" aria-labelledby="tab-business" class="mt-5" hidden><div class="st-card" id="st-biz"><h3>The business</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div></section>
    <section data-panel="whatif" id="panel-whatif" role="tabpanel" aria-labelledby="tab-whatif" class="mt-5" hidden><div class="st-card" id="st-whatif"><h3>What if I had invested?</h3><p class="mt-3 text-sm text-zinc-400">Loading the price history…</p></div></section>
    <section data-panel="revenue" id="panel-revenue" role="tabpanel" aria-labelledby="tab-revenue" class="mt-5 space-y-4" hidden>
      <div class="st-card" id="st-dep"><h3>Revenue dependency ${help("dep")}</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
      <div class="st-card" id="st-links"><h3>Named customers and suppliers ${help("links")}</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
      <div class="st-card" id="st-pred"><h3>Predicted links ${help("pred")}</h3><p class="mt-3 text-sm text-zinc-400">Loading…</p></div>
    </section>
    <p class="mt-6 text-center text-xs text-zinc-500">Educational analysis, not investment advice. Models are statistical and often wrong.</p>`;
  $("#st-back").onclick = closeStory; $("#st-back").focus();
  $("#st-watch").onclick = () => toggleWatch(e.s); paintWatchBtn(e.s);
  host.querySelectorAll("[data-go]").forEach(b => b.onclick = () => { selectTab(b.dataset.go); if (b.dataset.go === "chart") $("#cmp").focus(); });
  $("#st-tabs").addEventListener("click", ev => { const b = ev.target.closest("[data-tab]"); if (b) selectTab(b.dataset.tab); });
  $("#st-tabs").addEventListener("keydown", ev => {
    const keys = TABS.map(t => t[0]), i = keys.indexOf(ev.target.dataset.tab);
    if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") { ev.preventDefault(); const k = keys[(i + (ev.key === "ArrowRight" ? 1 : -1) + keys.length) % keys.length]; selectTab(k); $("#tab-" + k).focus(); }
  });
  selectTab(tab || "overview");
  if (tab === "chart") setTimeout(() => $("#cmp")?.focus(), 50);
  $("#st-cta .hx-open").addEventListener("click", ev => { if (ev.metaKey || ev.ctrlKey) return; ev.preventDefault(); const href = ev.currentTarget.href; document.body.classList.add("hx-leave"); setTimeout(() => { location.href = href; }, 330); });
  tradeCard(e); bindCompare();
  const [d, nf] = await Promise.all([get(`t/d/${dkey(sym)}.json`).then(j => j.d).catch(() => null), once("nifty", () => get("t/x/d/Nifty_2050.json").then(j => j.d)).catch(() => null)]);
  if (S.cur?.e !== e) return;
  if (d && d.length && qq.d && qq.d > d[d.length - 1][0] && qq.p) d.push([qq.d, qq.p, qq.p, qq.p, qq.p, 0]);   // the published history can lag a day or two: end it at today's price
  S.cur.d = d; S.cur.nf = nf;
  storyChart(); returnsCard(d, nf); rangeCard(e, d); whatIf();
  const [f, a, g, dp] = await Promise.all([once("fund", () => get("t/fund.json").then(j => j.stocks || {})).catch(() => null), once("aladin", () => get("aladin.json")).catch(() => null),
    once("graph", () => get("supply_graph.json")).catch(() => null), once("deps", () => get("dependencies.json")).catch(() => null)]);
  if (S.cur?.e !== e) return;
  const pd = dp && dp.cos && dp.cos[sym];
  predCard(sym);
  bizCard(e, f, sym); modelCard(a, sym); linksCard(g, sym, pd); peersCard(e, f, sym); plainWords(e, d, nf, f, a, sym, pd); depCard(e, pd); depMini(e, pd);
}
function paintWatchBtn(sym) { const b = $("#st-watch"); if (!b) return; const on = watch().includes(sym); b.textContent = on ? "★ Watching" : "☆ Watch"; b.setAttribute("aria-pressed", String(on)); }
function closeStory() {
  $("#story").hidden = true; document.body.style.overflow = ""; if (chart) { chart.remove(); chart = null; } S.cur = null;
  history.replaceState(null, "", location.pathname + location.search); (last && last.focus ? last : input).focus();
}

/* ---------------- Overview: plain words ---------------- */
function retOver(d, n) { if (!d || d.length < 2) return null; const i = Math.max(0, d.length - 1 - n); return d.length - 1 - i < Math.min(n, 5) ? null : (d[d.length - 1][4] / d[i][4] - 1) * 100; }
function niftyFrom(nf, from) { if (!nf) return null; const a = nf.find(r => r[0] >= from); return a ? (nf[nf.length - 1][4] / a[4] - 1) * 100 : null; }
function industryOf(f, sym, e) { return (f && f[sym] && f[sym].industry) || e.ind || null; }
function plainWords(e, d, nf, f, a, sym, pd) {
  const out = [], name = (e.n || e.s).replace(/ Limited$| Ltd\.?$/i, ""), fs = f && f[sym], ind = industryOf(f, sym, e);
  if (d && d.length > 200) {
    const r = retOver(d, 252), i = Math.max(0, d.length - 1 - 252), m = niftyFrom(nf, d[i][0]);
    if (r != null) out.push(`Over the past year ${esc(name)} is <b class="${cls(r)}">${r >= 0 ? "up" : "down"} ${Math.abs(r).toFixed(0)}%</b>${m != null ? `, while the Nifty 50 is ${m >= 0 ? "up" : "down"} ${Math.abs(m).toFixed(0)}%: it did <b>${r > m + 2 ? "better than" : r < m - 2 ? "worse than" : "about the same as"}</b> the market` : ""}.`);
  } else out.push(`${esc(name)} has less than a year of price history here, so long-term comparisons are not shown.`);
  if (e.hi52 && e.lo52) { const p = quoteOf(e).p, below = (1 - p / e.hi52) * 100; out.push(below < 1 ? "It is trading at its highest price of the past year." : `It is <b>${below.toFixed(0)}% below</b> its highest price of the past year${p <= e.lo52 * 1.02 ? ", close to its lowest" : ""}.`); }
  if (fs && fs.pe != null && ind && f) {
    const peers = Object.values(f).filter(x => x && x.industry === ind && x.pe != null && x.pe > 0), med = peers.length >= 4 ? median(peers.map(x => x.pe)) : null;
    out.push(`Investors pay <b>₹${num(fs.pe, 1)}</b> for every ₹1 of its yearly profit (P/E)${med ? `, ${fs.pe > med * 1.15 ? "more than" : fs.pe < med * 0.85 ? "less than" : "similar to"} the typical ${esc(ind)} company (${num(med, 1)})` : ""}.`);
  }
  const ds = RD.plainSentence(pd, name);
  if (ds) out.push(`${esc(ds)} <button type="button" class="text-emerald-400 underline" data-go-tab="revenue">See customers</button>`);
  const p10 = a && a.stocks && a.stocks[sym] && a.stocks[sym].t && a.stocks[sym].t.p && a.stocks[sym].t.p["10"];
  if (p10 != null) out.push(`Our model gives a <b>${(p10 * 100).toFixed(0)}%</b> chance it is higher in 10 trading days: ${Math.abs(p10 - 0.5) < 0.04 ? "no clear edge either way" : p10 > 0.5 ? "a slight lean up, nothing certain" : "a slight lean down, nothing certain"}.`);
  $("#st-plain").innerHTML = out.map(s => `<li class="flex gap-2"><span class="text-emerald-400" aria-hidden="true">•</span><span>${s}</span></li>`).join("");
  $("#st-plain").querySelectorAll("[data-go-tab]").forEach(b => b.onclick = () => selectTab(b.dataset.goTab));
}

/* ---------------- Chart with compare ---------------- */
function bindCompare() {
  const ci = $("#cmp"), cr = $("#cmp-results"); let rows = [], sel = 0;
  const paint = () => { const q = ci.value.trim().toLowerCase(); if (!q) { cr.hidden = true; return; } rows = matches(q).filter(x => x.s !== S.cur.e.s); sel = 0;
    cr.innerHTML = rows.map((x, i) => `<li role="option" data-sym="${esc(x.s)}" aria-selected="${i === 0}"><span class="sym">${hl(x.s, q)}</span><span class="nm">${hl(x.n || "", q)}</span><span class="px"></span><span class="ch"></span></li>`).join("") || `<li class="empty">No match.</li>`; cr.hidden = false; };
  const pick = async s => { cr.hidden = true; ci.value = s; const d2 = await get(`t/d/${dkey(s)}.json`).then(j => j.d).catch(() => null); if (!d2) { toast("No price history", s + " has no published history to compare."); return; } S.cur.cmp = { s, d: d2 }; storyChart(); };
  ci.addEventListener("input", paint);
  ci.addEventListener("keydown", ev => { if (ev.key === "Enter" && rows[sel]) { ev.preventDefault(); pick(rows[sel].s); } if (ev.key === "Escape") { cr.hidden = true; } });
  cr.addEventListener("click", ev => { const li = ev.target.closest("[data-sym]"); if (li) pick(li.dataset.sym); });
}
function storyChart() {
  const { d, nf, cmp, e } = S.cur, el = $("#st-chart"), perf = $("#st-perf");
  if (!d || !d.length) { el.innerHTML = '<p class="grid h-full place-content-center text-sm text-zinc-500">No price history is published for this security (SME and some recent listings are not covered).</p>'; perf.textContent = ""; return; }
  const LC = window.LightweightCharts;
  if (!LC) { el.innerHTML = '<p class="grid h-full place-content-center text-sm text-zinc-500">The chart library could not be loaded.</p>'; return; }
  if (chart) { chart.remove(); chart = null; }
  const cv = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const css = (n, a = 1) => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(n).trim(); cv.fillRect(0, 0, 1, 1); const [r, g, b] = cv.getImageData(0, 0, 1, 1).data; return `rgba(${r},${g},${b},${a})`; };
  chart = LC.createChart(el, { autoSize: true, layout: { background: { color: "transparent" }, textColor: css("--color-zinc-400"), fontFamily: "JetBrains Mono, monospace", attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { color: css("--color-zinc-800") } }, rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false }, crosshair: { mode: 1 }, handleScroll: false, handleScale: false });
  const pctMode = !!cmp, pf = { priceFormat: { type: "custom", formatter: v => pct(v, 1) } };
  const main = pctMode ? chart.addSeries(LC.LineSeries, { lineWidth: 2, priceLineVisible: false, ...pf }) : chart.addSeries(LC.AreaSeries, { lineWidth: 2, priceLineVisible: false });
  const other = pctMode ? chart.addSeries(LC.LineSeries, { color: css("--color-sky-400"), lineWidth: 2, priceLineVisible: false, ...pf }) : null;
  const bench = chart.addSeries(LC.LineSeries, { color: css("--color-zinc-500"), lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...(pctMode ? pf : {}) });
  const show = key => {
    const n = RANGES.find(r => r[0] === key)[1], seg = d.slice(-Math.min(d.length, n + 1)), from = seg[0][0];
    const r = (seg[seg.length - 1][4] / seg[0][4] - 1) * 100, k = r >= 0 ? "--color-emerald-400" : "--color-red-400";
    const nseg = nf ? nf.filter(x => x[0] >= from) : [], nr = nseg.length ? (nseg[nseg.length - 1][4] / nseg[0][4] - 1) * 100 : null;
    if (pctMode) {
      main.applyOptions({ color: css(k) }); main.setData(seg.map(x => ({ time: x[0], value: (x[4] / seg[0][4] - 1) * 100 })));
      const cs = cmp.d.filter(x => x[0] >= from), cr = cs.length ? (cs[cs.length - 1][4] / cs[0][4] - 1) * 100 : null;
      other.setData(cs.map(x => ({ time: x[0], value: (x[4] / cs[0][4] - 1) * 100 })));
      bench.setData(nseg.map(x => ({ time: x[0], value: (x[4] / nseg[0][4] - 1) * 100 })));
      perf.innerHTML = `<b class="font-mono ${cls(r)}">${esc(e.s)} ${pct(r)}</b> · <b class="font-mono text-sky-400">${esc(cmp.s)} ${pct(cr)}</b>${nr != null ? ` · <span class="text-zinc-500">Nifty ${pct(nr)}</span>` : ""} <span class="text-zinc-500">over ${key}</span>`;
      $("#st-legend").innerHTML = `Both lines start at 0% so you can compare. <button type="button" id="cmp-clear" class="ml-2 underline">Remove ${esc(cmp.s)}</button>`;
      $("#cmp-clear").onclick = () => { S.cur.cmp = null; $("#cmp").value = ""; storyChart(); };
    } else {
      main.applyOptions({ lineColor: css(k), topColor: css(k, 0.28), bottomColor: css(k, 0) }); main.setData(seg.map(x => ({ time: x[0], value: x[4] })));
      bench.setData(nseg.length ? nseg.map(x => ({ time: x[0], value: x[4] / nseg[0][4] * seg[0][4] })) : []);
      perf.innerHTML = `<b class="font-mono ${cls(r)}">${pct(r)}</b> <span class="text-zinc-400">over ${key === "5Y" ? "the period shown (from " + esc(from) + ")" : key}</span>${nr != null ? ` <span class="text-zinc-500">· Nifty 50 ${pct(nr)}</span>` : ""}`;
      $("#st-legend").innerHTML = `<span class="inline-block h-0.5 w-4 bg-zinc-500 align-middle"></span> Nifty 50 over the same period, scaled to start at the same point.`;
    }
    chart.timeScale().fitContent();
    document.querySelectorAll(".st-tabs button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.r === key)));
    S.cur.range = key;
  };
  document.querySelectorAll(".st-tabs button").forEach(b => b.onclick = () => show(b.dataset.r));
  show(S.cur.range || "1Y");
}
function returnsCard(d, nf) {
  $("#st-ret").innerHTML = RANGES.map(([k, n]) => {
    const r = retOver(d, n), i = d ? Math.max(0, d.length - 1 - n) : 0, nr = d && r != null ? niftyFrom(nf, d[i][0]) : null;
    return `<div><span>${k === "5Y" ? "Max" : k}</span><b class="${cls(r)}">${pct(r, 1)}</b><small>${nr != null ? "Nifty " + pct(nr, 1) : "&nbsp;"}</small></div>`;
  }).join("");
}
function rangeCard(e, d) {
  const el = $("#st-range"), lo = e.lo52, hi = e.hi52, p = quoteOf(e).p;
  let h = `<h3>Where the price sits ${help("range")}</h3>`;
  if (lo && hi && hi > lo) {
    const x = Math.max(0, Math.min(100, (p - lo) / (hi - lo) * 100));
    h += `<div class="st-range" role="img" aria-label="Price at ${x.toFixed(0)}% of its 52-week range"><i style="left:${x}%"></i></div>
      <div class="mt-2 flex justify-between font-mono text-xs text-zinc-400"><span>1-year low ₹${num(lo)}</span><span>high ₹${num(hi)}</span></div>`;
  }
  if (d && d.length > 20) {
    let peak = d[0][4], mdd = 0;
    for (let i = 1; i < d.length; i++) { peak = Math.max(peak, d[i][4]); mdd = Math.min(mdd, (d[i][4] / peak - 1) * 100); }
    h += `<dl class="st-kv"><dt>Biggest fall from a high, since ${esc(d[0][0].slice(0, 4))} ${help("dd")}</dt><dd class="down">${pct(mdd, 1)}</dd></dl>`;
  } else if (!(lo && hi)) h += `<p class="mt-3 text-sm text-zinc-400">Not enough price history to measure.</p>`;
  el.innerHTML = h;
}
function tradeCard(e) {
  $("#st-trade").innerHTML = `<h3>Trading activity, last session</h3><dl class="st-kv">
    <dt>Shares traded</dt><dd>${e.v != null ? num(e.v, 0) : "--"}</dd>
    <dt>Value traded</dt><dd>${e.val_cr != null ? "₹" + num(e.val_cr, 1) + " Cr" : "--"}</dd>
    <dt>vs a normal day ${help("vol20")}</dt><dd>${e.v && e.avgv20 ? num(e.v / e.avgv20, 1) + "×" : "--"}</dd>
    <dt>Delivery ${help("deliv")}</dt><dd>${e.deliv != null ? num(e.deliv, 1) + "%" : "--"}</dd>
    <dt>Listed on NSE</dt><dd>${esc(e.listed || "--")}</dd></dl>`;
}

/* ---------------- Business, vs the industry ---------------- */
function bizCard(e, f, sym) {
  const el = $("#st-biz"), fs = f && f[sym];
  if (!fs) { el.innerHTML = `<h3>The business</h3><p class="mt-3 text-sm text-zinc-400">No company financials are published for this security.</p>`; return; }
  const ind = fs.industry; if (fs.sector || ind) $("#st-sector").textContent = [fs.sector, ind].filter(Boolean).join(" · ");
  const peers = ind ? Object.values(f).filter(x => x && x.industry === ind) : [], med = k => peers.length >= 4 ? median(peers.map(x => x[k])) : null;
  const row = (label, k, fmt, hk) => { const v = fs[k], m = med(k); return `<tr class="border-t border-zinc-800"><th scope="row" class="py-2.5 pr-3 text-left font-normal text-zinc-400">${label} ${hk ? help(hk) : ""}</th><td class="py-2.5 text-right font-mono font-semibold">${fmt(v)}</td><td class="py-2.5 pl-3 text-right font-mono text-zinc-500">${m != null ? fmt(m) : "--"}</td></tr>`; };
  const desc = fs.desc || "", cut = desc.length > 220;
  el.innerHTML = `<h3>The business</h3>${desc ? `<p class="mt-3 text-[15px] leading-relaxed text-zinc-300">${esc(cut ? desc.slice(0, 220).replace(/\s\S*$/, "") + "…" : desc)}${cut ? ` <button type="button" id="biz-more" class="text-emerald-400 underline">Read more</button>` : ""}</p>` : ""}
    <table class="mt-4 w-full text-[15px]"><thead><tr class="text-xs tracking-wide text-zinc-500 uppercase"><th class="pb-2 text-left font-medium">Measure</th><th class="pb-2 text-right font-medium">${esc(e.s)}</th><th class="pb-2 pl-3 text-right font-medium">Typical ${esc(ind || "peer")}</th></tr></thead><tbody>
      ${row("Market value", "mcap", rupees, "mcap")}${row("P/E", "pe", v => v == null ? "--" : num(v, 1), "pe")}${row("Price ÷ book", "pb", v => v == null ? "--" : num(v, 1), "pb")}
      ${row("Revenue growth", "revg", v => v == null ? "--" : pct(v * 100, 1), "revg")}${row("Profit margin", "pm", v => v == null ? "--" : num(v * 100, 1) + "%", "pm")}${row("Dividend yield", "dy", v => v == null ? "--" : num(v, 2) + "%", "dy")}
    </tbody></table><p class="mt-3 text-xs text-zinc-500">"Typical" is the median of ${peers.length} listed ${esc(ind || "")} companies with published financials.</p>`;
  const more = $("#biz-more"); if (more) more.onclick = () => { more.parentElement.textContent = desc; };
}
function peersCard(e, f, sym) {
  const el = $("#st-peers"), ind = industryOf(f, sym, e);
  if (!f || !ind) { el.innerHTML = `<h3>Similar companies</h3><p class="mt-3 text-sm text-zinc-400">No industry is published for this security.</p>`; return; }
  const peers = Object.entries(f).filter(([s, x]) => s !== sym && x && x.industry === ind && S.map.has(s)).sort((a, b) => (b[1].mcap || 0) - (a[1].mcap || 0)).slice(0, 6);
  if (!peers.length) { el.innerHTML = `<h3>Similar companies</h3><p class="mt-3 text-sm text-zinc-400">No other listed ${esc(ind)} company has published financials.</p>`; return; }
  el.innerHTML = `<h3>Similar companies · ${esc(ind)}</h3><div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">${peers.map(([s]) => { const u = S.map.get(s), q = quoteOf(u);
    return `<button type="button" data-peer="${esc(s)}" class="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 px-3 py-2.5 text-left transition hover:border-zinc-600"><span class="min-w-0"><b class="font-mono text-sm">${esc(s)}</b><span class="block truncate text-xs text-zinc-400">${esc(u.n || "")}</span></span><span class="text-right"><span class="block font-mono text-sm">₹${num(q.p)}</span><span class="font-mono text-xs ${cls(u.r1y)}">1Y ${pct(u.r1y, 0)}</span></span></button>`; }).join("")}</div>`;
  el.querySelectorAll("[data-peer]").forEach(b => b.onclick = () => openStory(b.dataset.peer));
}

/* ---------------- Models ---------------- */
function modelCard(a, sym) {
  const el = $("#st-model"), s = a && a.stocks && a.stocks[sym], p = s && s.t && s.t.p;
  if (!p) { el.innerHTML = `<h3>What our models see ${help("model")}</h3><p class="mt-3 text-sm text-zinc-400">Not scored: the model needs 250 days of trading history and recent activity.</p>`; return; }
  const bar = v => `<div class="mt-1 h-1.5 rounded-full bg-zinc-800"><div class="h-1.5 rounded-full ${v >= 0.5 ? "bg-emerald-400" : "bg-red-400"}" style="width:${(v * 100).toFixed(0)}%"></div></div>`;
  el.innerHTML = `<h3>What our models see ${help("model")}</h3><p class="mt-3 text-sm text-zinc-400">Chance the price is higher after… (as of ${esc(a.as_of || "--")})</p>
    <dl class="mt-3 space-y-3">${["5", "10", "20"].filter(h => p[h] != null).map(h => `<div><div class="flex justify-between text-sm"><dt>${h} trading days</dt><dd class="font-mono font-semibold">${(p[h] * 100).toFixed(0)}%</dd></div>${bar(p[h])}</div>`).join("")}</dl>`;
}

/* ---------------- What if I had invested? (HyperUI range-inputs/1) ---------------- */
const AMOUNTS = [1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000];
const BACKS = [["1 month", 21], ["3 months", 63], ["6 months", 126], ["1 year", 252], ["2 years", 504], ["3 years", 756], ["5 years", 1235]];
const SLIDER = "mt-3 h-3.5 w-full appearance-none rounded-full bg-gray-300 [&::-webkit-slider-thumb]:size-7 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-[6px] [&::-webkit-slider-thumb]:border-gray-500 [&::-webkit-slider-thumb]:bg-gray-200";
function whatIf() {
  const el = $("#st-whatif"), { d, nf, e } = S.cur;
  if (!d || d.length < 22) { el.innerHTML = `<h3>What if I had invested?</h3><p class="mt-3 text-sm text-zinc-400">Not enough price history for this calculator.</p>`; return; }
  const backs = BACKS.filter(b => b[1] < d.length);
  el.innerHTML = `<h3>What if I had invested?</h3><p class="mt-2 text-sm text-zinc-400">Move the sliders. Uses real past closing prices.</p>
    <div class="mt-5 grid gap-6 md:grid-cols-2">
      <div class="space-y-6">
        <label for="wi-amt"><span class="block text-sm font-medium text-gray-900 dark:text-gray-200">Amount: <b id="wi-amt-v" class="font-mono"></b></span>
          <input type="range" id="wi-amt" min="0" max="${AMOUNTS.length - 1}" value="2" class="${SLIDER}" /></label>
        <label for="wi-back"><span class="block text-sm font-medium text-gray-900 dark:text-gray-200">Invested: <b id="wi-back-v" class="font-mono"></b></span>
          <input type="range" id="wi-back" min="0" max="${backs.length - 1}" value="${Math.min(3, backs.length - 1)}" class="${SLIDER}" /></label>
      </div>
      <div class="rounded-xl border border-zinc-800 bg-zinc-950 p-5" aria-live="polite" id="wi-out"></div>
    </div>
    <p class="mt-4 text-xs text-zinc-500">Price change only: before dividends, brokerage, taxes and the bid-ask spread. The past does not predict the future.</p>`;
  const paint = () => {
    const amt = AMOUNTS[+$("#wi-amt").value], [bl, bn] = backs[+$("#wi-back").value], i = Math.max(0, d.length - 1 - bn), p0 = d[i][4], p1 = d[d.length - 1][4];
    const val = amt * p1 / p0, gain = val - amt; let peak = p0, mdd = 0, low = p0;
    for (let k = i; k < d.length; k++) { peak = Math.max(peak, d[k][4]); mdd = Math.min(mdd, d[k][4] / peak - 1); low = Math.min(low, d[k][4]); }
    const nr = niftyFrom(nf, d[i][0]), nval = nr != null ? amt * (1 + nr / 100) : null;
    $("#wi-amt-v").textContent = "₹" + num(amt, 0); $("#wi-back-v").textContent = bl + " ago (" + d[i][0] + ")";
    $("#wi-out").innerHTML = `<p class="text-sm text-zinc-400">₹${num(amt, 0)} in ${esc(e.s)} on ${esc(d[i][0])} would be worth</p>
      <p class="mt-1 font-mono text-4xl font-bold">₹${num(val, 0)}</p>
      <p class="mt-1 font-mono text-lg font-semibold ${cls(gain)}">${gain >= 0 ? "+" : "-"}₹${num(Math.abs(gain), 0)} (${pct((val / amt - 1) * 100, 1)})</p>
      <dl class="st-kv text-sm">${nval != null ? `<dt>Same money in the Nifty 50</dt><dd class="${cls(nval - amt)}">₹${num(nval, 0)}</dd>` : ""}
        <dt>Lowest it was worth on the way</dt><dd class="down">₹${num(amt * low / p0, 0)}</dd>
        <dt>Biggest fall from a high on the way</dt><dd class="down">${pct(mdd * 100, 1)}</dd></dl>`;
  };
  $("#wi-amt").oninput = paint; $("#wi-back").oninput = paint; paint();
}

/* ---------------- Revenue & customers ---------------- */
const BADGE = { down: "border-red-500 text-red-300", warn: "border-amber-400 text-amber-200", up: "border-emerald-500 text-emerald-300", mut: "border-zinc-600 text-zinc-400" };
const badge = d => `<span class="rounded-full border ${BADGE[d.tone]} px-2.5 py-0.5 text-sm font-semibold whitespace-nowrap">${esc(d.label)}</span>`;   /* HyperUI application/badges/1 (outlined) */
function geoBar(segs) {
  if (!segs.length) return "";
  return `<div class="mt-3 flex h-3 overflow-hidden rounded-full bg-zinc-800" role="img" aria-label="${esc(segs.map(g => g.region + " " + (g.share * 100).toFixed(0) + "%").join(", "))}">${segs.map((g, i) => `<span class="${g.home ? "bg-emerald-500" : ["bg-sky-400", "bg-violet-400", "bg-amber-400", "bg-zinc-400", "bg-pink-400"][i % 5]}" style="width:${(g.share * 100).toFixed(1)}%" title="${esc(g.region)} ${(g.share * 100).toFixed(1)}%"></span>`).join("")}</div>
    <ul class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-zinc-300">${segs.map((g, i) => `<li class="flex items-center gap-1.5"><span class="inline-block size-2.5 rounded-full ${g.home ? "bg-emerald-500" : ["bg-sky-400", "bg-violet-400", "bg-amber-400", "bg-zinc-400", "bg-pink-400"][i % 5]}"></span>${esc(g.region)} <b class="font-mono">${(g.share * 100).toFixed(1)}%</b></li>`).join("")}</ul>`;
}
function depCard(e, p) {
  const el = $("#st-dep"), d = RD.summary(p), name = (e.n || e.s).replace(/ Limited$| Ltd\.?$/i, "");
  if (!p) { el.innerHTML = `<h3>Revenue dependency ${help("dep")}</h3><p class="mt-3 text-sm text-zinc-400">This company's filings have not been read yet. The map grows every day.</p>`; return; }
  const top = d.top, big = top && top.share != null ? `<p class="mt-4 font-mono text-4xl font-bold">${(top.share * 100).toFixed(top.share < 0.1 ? 1 : 0)}%</p><p class="text-sm text-zinc-400">of revenue from ${esc(top.name || "one customer (not named in the filing)")}${top.src === "derived" ? ", worked out from its related-party sales ÷ revenue" : ""}</p>` : "";
  const majors = d.major.customers.filter(c => !(top && c.share === top.share)).map(c => `<li class="border-t border-zinc-800 py-2.5 first:border-0"><span class="font-semibold">${c.share != null ? (c.share * 100).toFixed(1) + "%" : "10% or more"}</span> <span class="text-zinc-400">· ${esc(c.name || "one customer")}${c.where ? " · " + esc(c.where) : ""}${c.amount_cr != null ? " · ₹" + num(c.amount_cr, 0) + " Cr" : ""}</span><span class="block text-xs text-zinc-500">“${esc((c.q || "").slice(0, 200))}”</span></li>`).join("");
  el.innerHTML = `<h3>Revenue dependency ${help("dep")}</h3>
    <div class="mt-3 flex flex-wrap items-center gap-3">${badge(d)}<span class="text-[15px] text-zinc-200">${esc(RD.plainSentence(p, name) || p.why)}</span></div>
    ${big}${top && top.q ? `<p class="mt-3 text-sm text-zinc-500">From the filing: “${esc(top.q.slice(0, 240))}${top.q.length > 240 ? "…" : ""}”${top.url ? ` <a class="underline" href="${esc(top.url)}" target="_blank" rel="noopener">source</a>` : ""}</p>` : ""}
    ${majors ? `<h4 class="mt-5 text-sm font-semibold text-zinc-300">Other customers worth 10% or more of revenue</h4><ul class="mt-1">${majors}</ul>` : ""}
    ${d.major.status === "none_over_10" ? `<p class="mt-3 text-sm text-zinc-400">The annual report says: “${esc((d.major.q || "").slice(0, 200))}”</p>` : ""}
    ${d.geo.length ? `<h4 class="mt-6 text-sm font-semibold text-zinc-300">Where the revenue comes from ${help("geo")}</h4>${geoBar(RD.geoSegments(d.geo))}` : ""}
    ${brsrBlock(p)}
    <p class="mt-5 text-xs text-zinc-500">Read from the company's own filings${p.read.segment_note ? ` (segment note ${esc(p.read.segment_note.slice(0, 10))})` : ""}. Nothing is estimated: a company that does not say stays "Not disclosed".</p>`;
}
function brsrBlock(p) {
  const b = RD.brsrLines(p); if (!b || !(b.mix.length || b.cust)) return "";
  return `<h4 class="mt-6 text-sm font-semibold text-zinc-300">What it sells and to whom${b.fy ? ` <span class="font-normal text-zinc-500">(sustainability report ${esc(b.fy)})</span>` : ""}</h4>
    ${b.mix.length ? `<ul class="mt-2 space-y-1.5">${b.mix.map(m => `<li class="grid grid-cols-[1fr_auto] items-center gap-3 text-sm"><span class="min-w-0 truncate text-zinc-300" title="${esc(m.d)}">${esc(m.d)}</span><span class="font-mono text-zinc-200">${(m.share * 100).toFixed(m.share < 0.1 ? 1 : 0)}%</span><span class="col-span-2 h-1.5 overflow-hidden rounded-full bg-zinc-800"><span class="block h-full rounded-full bg-emerald-600" style="width:${(m.share * 100).toFixed(1)}%"></span></span></li>`).join("")}</ul>` : ""}
    ${b.cust ? `<p class="mt-3 text-sm text-zinc-400"><span class="text-zinc-300">Customers:</span> ${esc(b.cust)}</p>` : ""}${b.exports != null ? `<p class="mt-2 text-sm text-zinc-400">Exports: ${(b.exports * 100).toFixed(1)}% of turnover.</p>` : ""}`;
}
function depMini(e, p) {
  const el = $("#st-depmini"), d = RD.summary(p);
  if (!p || p.lvl === "unknown" && !d.geo.length && p.abroad == null) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `<div class="flex flex-wrap items-center justify-between gap-3"><h3>Revenue dependency ${help("dep")}</h3><button type="button" class="text-sm text-emerald-400 underline" data-go-tab="revenue">Customers and regions →</button></div>
    <div class="mt-3 flex flex-wrap items-center gap-3">${badge(d)}<span class="text-sm text-zinc-300">${esc(p.lvl === "unknown" && p.abroad != null ? RD.plainSentence(p, e.s) : p.why)}</span></div>${d.geo.length ? geoBar(RD.geoSegments(d.geo)) : ""}`;
  el.querySelector("[data-go-tab]").onclick = () => selectTab("revenue");
}
async function predCard(sym) {
  const el = $("#st-pred"), h = `<h3>Predicted links ${help("pred")}</h3>`;
  if (!el) return;
  const [idx, sh] = await Promise.all([once("pl", () => get("pl/index.json")).catch(() => null), once("pl" + RD.predShard(sym), () => get(`pl/${RD.predShard(sym)}.json`)).catch(() => null)]);
  if (S.cur?.e?.s !== sym) return;
  if (!sh) { el.innerHTML = h + `<p class="mt-3 text-sm text-zinc-400">Predicted links could not be loaded.</p>`; return; }
  const names = new Map(S.list.map(x => [x.s, x.n])), rows = RD.predList(sh, sym, names, 8), test = RD.predTestLine(idx);
  if (!rows.length) { el.innerHTML = h + `<p class="mt-3 text-sm text-zinc-400">No predicted link has evidence we can show for this company yet.</p>`; return; }
  const row = r => `<li class="border-t border-zinc-800 py-3 first:border-0"><details><summary class="flex cursor-pointer items-start justify-between gap-3"><span class="min-w-0">${S.map.has(r.sym) ? `<button type="button" data-peer="${esc(r.sym)}" class="text-left text-zinc-100 underline decoration-zinc-600 underline-offset-4 hover:decoration-zinc-300">${esc(r.name)}</button>` : `<span class="text-zinc-100">${esc(r.name)}</span>`} <span class="font-mono text-xs text-emerald-400">${esc(r.sym)}</span>
      <span class="block text-xs text-zinc-500">${r.kinds.map(k => esc(RD.kindLabel(k))).join(" · ")}${r.rival ? " · same industry: may be a rival" : ""}</span></span>
      <span class="shrink-0 rounded-full border border-zinc-600 px-2.5 py-0.5 text-sm whitespace-nowrap text-zinc-300">Why?</span></summary>
      <ul class="mt-2 space-y-1 text-sm text-zinc-300">${r.reasons.map(t => `<li class="flex gap-2"><span class="text-emerald-400" aria-hidden="true">•</span><span>${esc(t)}</span></li>`).join("")}</ul>
      ${r.quote ? `<p class="mt-2 text-xs text-zinc-500">“${esc(r.quote.text.slice(0, 220))}${r.quote.text.length > 220 ? "…" : ""}”${r.quote.url ? ` <a class="underline" href="${esc(r.quote.url)}" target="_blank" rel="noopener">source</a>` : ""}</p>` : r.source ? `<p class="mt-2 text-xs text-zinc-500"><a class="underline" href="${esc(r.source)}" target="_blank" rel="noopener">The filing</a></p>` : ""}</details></li>`;
  el.innerHTML = h + `<p class="mt-2 text-sm text-zinc-400"><b class="text-amber-200">${esc(RD.PRED_LABEL)}.</b> Listed companies a model thinks may do business with this one, beyond the links confirmed in filings. Tap one to see the evidence.</p>
    <ul class="mt-2">${rows.map(row).join("")}</ul>${test ? `<p class="mt-4 text-xs text-zinc-500">${esc(test)}</p>` : ""}`;
  el.querySelectorAll("[data-peer]").forEach(b => b.onclick = ev => { ev.preventDefault(); openStory(b.dataset.peer, "revenue"); });
}
function linksCard(g, sym, pd) {
  const el = $("#st-links"), h = `<h3>Named customers and suppliers ${help("links")}</h3>`;
  if (!g) { el.innerHTML = h + `<p class="mt-3 text-sm text-zinc-400">The supply-chain map could not be loaded.</p>`; return; }
  const nodes = new Map((g.nodes || []).map(n => [n.id, n])), es = (g.edges || []).filter(x => x.s === sym || x.d === sym).slice(0, 10), read = (g.cos || {})[sym];
  if (!es.length) {
    el.innerHTML = h + `<!-- HyperUI application/empty-states/1 --><div class="mx-auto max-w-md py-6 text-center"><h4 class="text-lg font-bold text-gray-900 dark:text-white">No links yet</h4>
      <p class="mt-3 text-pretty text-gray-700 dark:text-gray-200">${read ? "This company's filings were read; none named a customer or supplier that passed our checks." : "This company's filings have not been read yet. The map grows every day."}</p></div>`; return;
  }
  const row = x => { const other = x.s === sym ? x.d : x.s, n = nodes.get(other), name = (n && n.n) || x.cpn || other, role = x.s === sym ? "customer" : "supplier", listed = n && n.sym && S.map.has(n.sym);
    return `<li class="flex items-start justify-between gap-3 border-t border-zinc-800 py-3 first:border-0"><span class="min-w-0">${listed ? `<button type="button" data-peer="${esc(n.sym)}" class="text-left text-zinc-100 underline decoration-zinc-600 underline-offset-4 hover:decoration-zinc-300">${esc(name)}</button> <span class="font-mono text-xs text-emerald-400">${esc(n.sym)}</span>` : `<span class="text-zinc-100">${esc(name)}</span>`}<span class="block text-xs text-zinc-500">“${esc((x.q || "").slice(0, 160))}”</span></span>
      <span class="shrink-0 rounded-full border border-zinc-600 px-2.5 py-0.5 text-sm whitespace-nowrap text-zinc-300">${role}</span></li>`; };
  el.innerHTML = h + `<p class="mt-2 text-sm text-zinc-400">Named in the company's own filings and calls, or the other company's, each with the sentence it came from.</p><ul class="mt-2">${es.map(row).join("")}</ul>`;
  el.querySelectorAll("[data-peer]").forEach(b => b.onclick = () => openStory(b.dataset.peer));
}
