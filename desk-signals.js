/* ALADIN: the one front page for signals. Three things on the surface for each stock (the signal, the price goal, the stop); everything else opens when you click a stock:
   how the signal was made, the forecast range and chances, and the revenue dependencies from NEXUS.
   Data (all published nightly, read-only): aladin2/weekly.json (the week's book and the chance table), aladin.json (ALADIN 1's inputs), supply_graph.json (NEXUS), the desk's own stock list.
   Wording (the signal names, the goal and stop labels) comes from the labels dictionary inside weekly.json, so switching vocabulary is a config change.
   Every number is read from a file; a missing input says "not measured" with its reason. The goal and stop are the model's own levels, not promises.
   UI patterns (table, badge, tabs, sheet, search, stat card, marker bar, stepper) are re-drawn in the desk's own CSS after the shadcn/ui and Tremor patterns listed on designeer.xyz; no third-party code is copied.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. */
import { esc, inr, pct } from "./desk-aladin2.js";
import * as A2 from "./desk-aladin2.js";
import { shareText } from "./desk-deps.js";

let ctx = null, root = null, W = null, graph = null, loading = null, failed = false;
const st = { q: "", filter: "all", sel: null, tab: "summary" };
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results.";
const REL = { supplies: "supplies", equipment_for: "supplies equipment to", raw_material_from: "sources raw material from", logistics_for: "provides logistics to", related_party: "is a related party of", customer_of: "is a customer of" };
const TABS = [["summary", "Summary"], ["how", "How it was made"], ["range", "Range and chance"], ["deps", "Revenue dependencies"]];

export function init(c) { ctx = c; }

/* ---------- pure helpers (tests/js/signals.test.mjs) ---------- */
const rel = (v, base) => v == null || !base ? null : (v / base - 1) * 100;
export function rowOf(r, side) {
  return { sym: r.sym, name: r.name, sector: r.sector, sig: side, close: r.close, goal: r.goal ?? null, stop: r.stop ?? null, goalPct: rel(r.goal, r.close), stopPct: rel(r.stop, r.close), rr: r.reward_risk ?? null,
    rank: r.rank_pct, pu: r.chance ? r.chance.closes_higher : null, pb: r.chance ? r.chance.beats_market : null, ranked: true, book: r };
}
/* The list the page shows. No search: the week's signals, positive ones strongest first, then negative ones weakest first. With a search: every stock whose symbol or name matches, signal or not. */
export function buildRows(Wk, stocks, { q = "", filter = "all", limit = 80 } = {}) {
  const book = Wk && Wk.book; if (!book) return { rows: [], total: 0 };
  const sigs = new Map(); for (const r of book.bull) sigs.set(r.sym, rowOf(r, "bull")); for (const r of book.bear) sigs.set(r.sym, rowOf(r, "bear"));
  const ql = String(q || "").trim().toLowerCase(); let rows;
  if (!ql) rows = [...book.bull].sort((a, b) => b.rank_pct - a.rank_pct).map(r => sigs.get(r.sym)).concat([...book.bear].sort((a, b) => a.rank_pct - b.rank_pct).map(r => sigs.get(r.sym)));
  else {
    const hit = (stocks || []).filter(s => s.s.toLowerCase().startsWith(ql) || s.s.toLowerCase().includes(ql) || String(s.n || "").toLowerCase().includes(ql)).sort((a, b) => (b.s.toLowerCase() === ql) - (a.s.toLowerCase() === ql) || (b.s.toLowerCase().startsWith(ql)) - (a.s.toLowerCase().startsWith(ql)) || a.s.length - b.s.length);
    rows = hit.map(s => {
      if (sigs.has(s.s)) return sigs.get(s.s);
      const k = book.ranks && book.ranks[s.s];
      return { sym: s.s, name: s.n, sector: s.ind, sig: k ? "none" : "na", close: s.c, goal: null, stop: null, goalPct: null, stopPct: null, rr: null, rank: k ? k[0] : null, pu: k ? k[1] : null, pb: k ? k[2] : null, ranked: !!k, book: null };
    });
  }
  const total = rows.length; if (filter === "bull" || filter === "bear") rows = rows.filter(r => r.sig === filter);
  return { rows: rows.slice(0, limit), total, shown: Math.min(rows.length, limit), more: Math.max(0, rows.length - limit) };
}
/* Revenue dependencies of a company from the NEXUS graph: who it supplies and who supplies it, with the share when the filing gives one, the period and the source. */
export function dependenciesOf(g, sym) {
  if (!g || !g.edges) return null;
  const nm = new Map((g.nodes || []).map(n => [n.id, n])), done = g.cos && g.cos[sym];
  const own = g.edges.filter(e => e.own === sym || e.s === sym || e.d === sym);
  const label = id => { const n = nm.get(id); if (n) return { id, name: n.n || id, listed: n.k === "co", sym: n.k === "co" ? (n.sym || id) : null }; if (g.anon && g.anon[id]) return { id, name: "Unnamed counterparty of " + g.anon[id].owner, listed: false, sym: null }; return { id, name: id, listed: false, sym: null }; };
  const rows = own.map(e => {
    const other = e.s === sym ? e.d : e.s, out = e.s === sym;
    return { other: label(other), text: out ? `${sym} ${REL[e.rel] || e.rel} ${label(e.d).name}` : `${label(e.s).name} ${REL[e.rel] || e.rel} ${sym}`, share: e.w ?? null, period: e.per || null, wb: e.wb, wd: e.wd, w: e.w, conf: e.conf ?? null, url: e.url || null, page: e.pg || null, quote: e.q || null, tier: e.tier ?? null, kind: e.kind || null };
  }).sort((a, b) => (b.share ?? -1) - (a.share ?? -1) || (b.conf ?? 0) - (a.conf ?? 0));
  return { rows, read: !!done, done: g.coverage ? g.coverage.companies_done : null, total: g.coverage ? g.coverage.companies_total : null };
}
export const fmtLevel = (v, p) => v == null ? null : { price: inr(v, 2), rel: pct(p, 1) };

/* ---------- loading ---------- */
async function load() {
  if (W || failed) return;
  if (!loading) loading = Promise.all([
    ctx.getJSON("aladin2/weekly.json", false).then(j => { W = j; }).catch(() => { failed = true; }),
    ctx.S.aladin ? 0 : ctx.getJSON("aladin.json", false).then(j => { ctx.S.aladin = j; }).catch(() => 0)]).finally(() => { loading = null; });
  await loading;
}
function loadGraph() { if (graph || !ctx) return; ctx.getJSON("supply_graph.json", false).then(j => { graph = j; if (st.sel && st.tab === "deps") paintSheet(); }).catch(() => { graph = { edges: [], missing: true }; if (st.sel && st.tab === "deps") paintSheet(); }); }

/* ---------- drawing ---------- */
const lab = () => (W && W.labels) || { bull: "BULLISH SIGNAL", bear: "BEARISH SIGNAL", none: "NO EDGE", goal: "Range edge", stop: "Exit level", signal: "Signal" };
const sigName = sig => sig === "bull" ? lab().bull : sig === "bear" ? lab().bear : sig === "none" ? lab().none : "NOT RANKED";
const badge = sig => `<span class="sg-badge ${sig}">${esc(sigName(sig))}</span>`;
function levelCell(v, p, basis) { const f = fmtLevel(v, p); return f ? `<b>${f.price}</b><small class="${p >= 0 ? "up" : "down"}">${f.rel}</small>` : `<span class="sg-nm" title="${esc(basis || "")}">${basis ? "not measured" : "--"}</span>`; }

function shell() {
  const b = W && W.book, c = b ? b.counts : null, L = lab();
  const chip = (k, t, n) => `<button type="button" class="sg-chip ${st.filter === k ? "on" : ""}" data-f="${k}" aria-pressed="${st.filter === k}">${esc(t)}${n != null ? ` <i>${n}</i>` : ""}</button>`;
  return `<div class="sg">
    <div class="sg-head"><div><h2>ALADIN signals</h2><p>${b ? `Weekly view as of the ${esc(b.as_of)} close · hold for ${b.horizon_trading_days} trading days` : "Loading…"}</p></div>
      <div class="sg-links"><button type="button" class="btn-line sm" data-go="a2bot">Bot console</button><button type="button" class="btn-line sm" data-go="a2">Research pages</button></div></div>
    ${b ? `<div class="sg-stats"><div class="sg-stat"><span>${esc(L.bull)} signals</span><b class="up">${c.bull}</b></div><div class="sg-stat"><span>${esc(L.bear)} signals</span><b class="down">${c.bear}</b></div><div class="sg-stat"><span>${esc(L.none)}</span><b>${c.hold.toLocaleString("en-IN")}</b></div>
      <div class="sg-stat wide"><span>Chance the best-ranked closes higher</span><b>${esc(pct0(bestChance()))}</b><small>measured 2013 to 2026, checked on years the model had not seen</small></div></div>` : ""}
    <div class="sg-bar"><div class="sg-search"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="M14 14l4 4"/></svg><input id="sg-q" type="search" inputmode="search" autocomplete="off" spellcheck="false" placeholder="Search any stock: symbol or company name" value="${esc(st.q)}" aria-label="Search any stock"></div>
      <div class="sg-chips" role="group" aria-label="Filter">${chip("all", "All", null)}${chip("bull", L.bull, c ? c.bull : null)}${chip("bear", L.bear, c ? c.bear : null)}</div></div>
    <div id="sg-list"></div>
    <p class="note a2v-dis">${DISCLAIMER}</p>
    <div id="sg-sheet-host"></div></div>`;
}
const pct0 = v => v == null ? "--" : (v * 100).toFixed(1) + "%";
function bestChance() { const c = W && W.book && W.book.bull[0] && W.book.bull[0].chance; return c ? c.closes_higher : null; }

function listHtml() {
  const { rows, total, more } = buildRows(W, ctx.S.uni ? ctx.S.uni.stocks : [], { q: st.q, filter: st.filter }), L = lab();
  if (!W || !W.book) return `<p class="note">${failed ? "The signals file is not published yet." : "Loading…"}</p>`;
  if (!rows.length) return `<div class="sg-empty"><b>Nothing found.</b><span>${st.q ? "No stock matches that search." : "No signals this week: every stock reads as " + esc(L.none) + "."}</span></div>`;
  const body = rows.map(r => `<tr tabindex="0" data-sym="${esc(r.sym)}" class="${r.sym === st.sel ? "on" : ""}"><td class="sg-st"><b>${esc(r.sym)}</b><small>${esc(r.name || "")}</small></td><td>${badge(r.sig)}</td>
      <td class="r">${r.sig === "bull" || r.sig === "bear" ? levelCell(r.goal, r.goalPct, r.book && r.book.goal_basis) : '<span class="sg-nm">--</span>'}</td><td class="r">${r.sig === "bull" || r.sig === "bear" ? levelCell(r.stop, r.stopPct, "x") : '<span class="sg-nm">--</span>'}</td><td class="sg-go" aria-hidden="true">›</td></tr>`).join("");
  return `<div class="sg-tablewrap"><table class="sg-table"><thead><tr><th>Stock</th><th>${esc(L.signal || "Signal")}</th><th class="r">${esc(L.goal || "Range edge")}</th><th class="r">${esc(L.stop || "Exit level")}</th><th></th></tr></thead><tbody>${body}</tbody></table></div>
    <p class="note">${more ? `Showing ${rows.length} of ${total}. Search to find any other stock. ` : ""}${st.q ? "" : `Prices are the ${esc(W.book.as_of)} close. The ${esc(L.goal || "range edge").toLowerCase()} is the edge of the model's 5-day 50% price range; the ${esc(L.stop || "exit level").toLowerCase()} is 2 average daily moves from the price. Click a stock for the reasons.`}</p>`;
}

/* ----- the sheet (detail) ----- */
function meter(label, v, ci, n) {
  if (v == null) return `<div class="sg-meter"><div class="sg-ml"><span>${esc(label)}</span><b>not measured</b></div></div>`;
  const lo = ci ? ci[0] : v, hi = ci ? ci[1] : v, pos = x => Math.max(0, Math.min(100, (x - 0.3) / 0.4 * 100));
  return `<div class="sg-meter"><div class="sg-ml"><span>${esc(label)}</span><b>${pct0(v)}</b></div><div class="sg-track" role="img" aria-label="${esc(label)} ${pct0(v)}${ci ? ", 95% range " + pct0(lo) + " to " + pct0(hi) : ""}"><i class="sg-ci" style="left:${pos(lo)}%;width:${Math.max(1, pos(hi) - pos(lo))}%"></i><i class="sg-half" style="left:${pos(0.5)}%"></i><i class="sg-mk" style="left:${pos(v)}%"></i></div>
    <small>${ci ? `95% range ${pct0(lo)} to ${pct0(hi)}` : ""}${n ? ` · ${n.toLocaleString("en-IN")} past stock-weeks` : ""} · the thin line is a coin flip (50%)</small></div>`;
}
function summaryHtml(r) {
  const L = lab(), b = r.book; if (!b) return holdSummary(r);
  const c = b.chance, bull = r.sig === "bull", rec = b.record;
  const tile = (name, big, sub, cls = "") => `<div class="sg-tile ${cls}"><span>${esc(name)}</span><b>${big}</b><small>${sub}</small></div>`;
  const rrText = r.rr == null ? "" : r.rr < 1 ? `<p class="sg-warn">The ${esc((L.goal || "range edge").toLowerCase())} is closer than the ${esc((L.stop || "exit level").toLowerCase())} (reward ${r.rr.toFixed(2)} for each 1 of risk): one win is smaller than one loss, so this only pays if it wins often enough. The chances below say how often it has.</p>` : `<p class="sg-ok">Reward ${r.rr.toFixed(2)} for each 1 of risk.</p>`;
  return `<div class="sg-tiles">${tile(L.signal || "Signal", badge(r.sig), `${bull ? "enter at the next open" : "exit if you hold it; do not add it"} · ${W.book.horizon_trading_days} trading days`)}
      ${tile(L.goal || "Range edge", r.goal != null ? `${inr(r.goal)} <em class="${r.goalPct >= 0 ? "up" : "down"}">${pct(r.goalPct, 1)}</em>` : '<span class="sg-nm">not measured</span>', esc(b.goal_basis || ""))}
      ${tile(L.stop || "Stop loss", `${inr(r.stop)} <em class="${r.stopPct >= 0 ? "up" : "down"}">${pct(r.stopPct, 1)}</em>`, esc(b.stop_basis || ""))}</div>${rrText}
    <div class="sg-card"><h4>Chance, from 13 years of out-of-sample history</h4>${c ? meter("Closes higher in 5 trading days", c.closes_higher, c.closes_higher_ci95, c.n_stock_weeks) + meter("Beats the market in 5 trading days", c.beats_market, c.beats_market_ci95, c.n_stock_weeks) : '<p class="note">Not measured for this rank.</p>'}</div>
    <div class="sg-card"><h4>What to do</h4><p>${esc(b.what_to_do)}</p>${bull && b.entry_zone ? `<dl class="sg-dl"><div><dt>Entry zone</dt><dd>${inr(b.entry_zone[0])} to ${inr(b.entry_zone[1])}</dd></div><div><dt>Exit</dt><dd>${esc(b.exit)}</dd></div><div><dt>Round trip cost</dt><dd>${esc(String(b.round_trip_cost_bps))} bps</dd></div>${b.size_for_capital ? `<div><dt>Size for ₹${b.size_for_capital.capital.toLocaleString("en-IN")}</dt><dd>${b.size_for_capital.qty.toLocaleString("en-IN")} shares, ₹${b.size_for_capital.capital_at_risk.toLocaleString("en-IN")} at risk</dd></div>` : ""}</dl>` : ""}</div>
    ${rec ? `<div class="sg-card"><h4>The same signal in the past (history, not live)</h4><dl class="sg-dl"><div><dt>Stock-weeks</dt><dd>${rec.n.toLocaleString("en-IN")}</dd></div><div><dt>Closed higher</dt><dd>${pct0(rec.share_closing_up)}</dd></div>${bull ? `<div><dt>After costs, vs the market</dt><dd>${rec.net_bps >= 0 ? "+" : ""}${rec.net_bps} bps a week</dd></div><div><dt>Years positive</dt><dd>${esc(rec.years_positive_net || "--")}</dd></div>` : `<div><dt>Vs the market, before costs</dt><dd>${rec.gross_excess_bps} bps a week</dd></div><div><dt>Years below the market</dt><dd>${esc(rec.years_below_market || "--")}</dd></div>`}</dl></div>` : ""}`;
}
function holdSummary(r) {
  const L = lab(), none = r.sig === "none";
  return `<div class="sg-tiles">${`<div class="sg-tile"><span>${esc(L.signal || "Signal")}</span><b>${badge(r.sig)}</b><small>${none ? "not in the best 1% or worst 5% of the week's ranking" : "too thinly traded to rank for a weekly call"}</small></div>`}
    <div class="sg-tile"><span>${esc(L.goal || "Range edge")}</span><b><span class="sg-nm">--</span></b><small>no signal, no levels</small></div><div class="sg-tile"><span>${esc(L.stop || "Exit level")}</span><b><span class="sg-nm">--</span></b><small>no signal, no levels</small></div></div>
    ${none && r.pu != null ? `<div class="sg-card"><h4>For a typical stock at this rank (${(r.rank * 100).toFixed(0)}th percentile)</h4>${meter("Closes higher in 5 trading days", r.pu, null, null)}${meter("Beats the market in 5 trading days", r.pb, null, null)}<p class="note">Near the middle, the chances are close to a coin flip: that is why ALADIN stays out.</p></div>` : '<p class="note">No weekly call for this stock.</p>'}`;
}
function howHtml(r) {
  const b = r.book, L = lab(), a = ctx.S.aladin && ctx.S.aladin.stocks && ctx.S.aladin.stocks[r.sym];
  const N = W.book.universe.toLocaleString("en-IN"), c = b && b.chance;
  const steps = r.rank == null ? [] : [
    ["Score", `ALADIN 1 gives the stock a 5-day score: a ${pct0(r.book ? r.book.p5 : (a && a.t && a.t.p && a.t.p["5"]))} model chance of closing higher. The rule only compares stocks with each other, so a score under 50% can still be the best of the week.`],
    ["Rank", `Among ${N} liquid stocks it ranks at the ${(r.rank * 100).toFixed(2)}th percentile (higher is better).`],
    ["Rule", r.sig === "bull" ? `It is inside the best 1%, so the signal is ${esc(L.bull)}.` : r.sig === "bear" ? `It is inside the worst 5%, so the signal is ${esc(L.bear)}.` : `It is not in the best 1% or worst 5%, so the signal is ${esc(L.none)}.`],
    ["Chance", c ? `Stocks at this rank closed higher ${pct0(c.closes_higher)} of the time and beat the market ${pct0(c.beats_market)} of the time over 5 trading days.` : `Measured chance for this rank: not measured.`],
    ["Levels", b ? `The ${esc((L.goal || "range edge").toLowerCase())} is the ${esc(b.goal_basis || "not measured")}; the ${esc((L.stop || "exit level").toLowerCase())} is 2 average daily moves from the price.` : "No levels: no signal."],
    ["Cost", b ? `Trading it costs about ${b.round_trip_cost_bps} bps round trip; the signal only counts if the edge is bigger than that.` : "No position, so no cost."]];
  const names = (ctx.S.aladin && ctx.S.aladin.model && ctx.S.aladin.model.names) || {}, nice = n => names[n] || ({ dom: "day of the month", moy: "month of the year", dow: "day of the week" })[n] || n, drv = a && a.t && a.t.drv ? a.t.drv.slice(0, 6).map(([n, v]) => [nice(n), v]) : null, mx = drv ? Math.max(...drv.map(d => Math.abs(d[1])), 1e-9) : 1;
  const inputs = [["Prices and volume (ALADIN 1 technical score)", "In the rule", a && a.t ? `score ${pct0(a.t.p && a.t.p["5"])}` : "not measured"], ["Company fundamentals", "Shown, not in the rule", a && a.f ? `fundamental score ${a.f.sc ?? "not measured"}` : "not measured"],
    ["News sentiment", "Shown, not in the rule", b && b.evidence && b.evidence.sentiment_level ? esc(b.evidence.sentiment_level) : "not measured"], ["Revenue dependencies (NEXUS)", "Shown, not in the rule yet", a && a.x && a.x.i != null ? `impact ${a.x.i}` : "see the next tabs"]];
  return `<div class="sg-card"><h4>The steps</h4><ol class="sg-steps">${steps.map(([t, x], i) => `<li><span>${i + 1}</span><div><b>${esc(t)}</b><p>${x}</p></div></li>`).join("") || '<li><div><p>This stock is not ranked.</p></div></li>'}</ol></div>
    ${drv ? `<div class="sg-card"><h4>What pushed ALADIN 1's score (for this stock)</h4><ul class="sg-bars">${drv.map(([n, v]) => `<li><span>${esc(n)}</span><div><i class="${v >= 0 ? "up" : "down"}" style="width:${(Math.abs(v) / mx * 100).toFixed(0)}%"></i></div><em>${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}</em></li>`).join("")}</ul><p class="note">Longer bar, bigger push. Green pushed the chance up, red pushed it down.</p></div>` : ""}
    <div class="sg-card"><h4>Which inputs are in the rule</h4><table class="sg-mini"><tbody>${inputs.map(([n, s, v]) => `<tr><td>${esc(n)}</td><td><span class="sg-tag ${s === "In the rule" ? "on" : ""}">${esc(s)}</span></td><td>${v}</td></tr>`).join("")}</tbody></table>
      <p class="note">Only the price-and-volume score decides the signal. Fundamentals, sentiment and dependencies were tested against the weekly result and did not improve it (and the dependency data is too new to test properly), so they are shown as context, not used in the rule. When they pass a proper test they will be added.</p></div>`;
}
function rangeHtml(r) {
  if (!A2.loaded(r.sym)) A2.ready(r.sym).then(() => { if (st.sel === r.sym && st.tab === "range") paintSheet(); });
  setTimeout(() => { const el = root.querySelector("#a2-brief"); if (el) A2.bind(el, r.sym); }, 0);
  return `<div class="sg-card a2-embed">${A2.wrap(r.sym)}</div><p class="note">The chart on the Terminal tab draws the same range to the right of the last candle.</p>`;
}
function depsHtml(r) {
  if (!graph) { loadGraph(); return '<p class="note">Loading the dependency graph…</p>'; }
  const d = dependenciesOf(graph, r.sym);
  if (!d || graph.missing) return '<p class="note">The dependency graph is not published yet.</p>';
  const q = s => ctx.S.quotes && ctx.S.quotes[s], row = x => {
    const o = x.other, pq = o.sym ? q(o.sym) : null, u = o.sym && ctx.S.map ? ctx.S.map.get(o.sym) : null;
    return `<li><div class="sg-dh"><b>${esc(x.text)}</b>${x.share != null ? `<span class="sg-tag on">${esc(shareText({ w: x.w, wb: x.wb, wd: x.wd }))}</span>` : '<span class="sg-tag">share not disclosed</span>'}</div>
      <small>${esc(x.period || "period not stated")} · confidence ${x.conf != null ? Math.round(x.conf * 100) + "%" : "n/a"}${pq ? ` · ${esc(o.sym)} ${pct(pq.pct, 1)} today${u && u.r1m != null ? `, ${pct(u.r1m, 1)} in a month` : ""}` : ""}</small>
      ${x.quote ? `<blockquote>“${esc(x.quote)}”</blockquote>` : ""}${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">Filing${x.page ? ", page " + x.page : ""} ↗</a>` : ""}</li>`;
  };
  return `<div class="sg-card"><h4>Who ${esc(r.sym)} depends on, and who depends on it</h4>${d.rows.length ? `<ul class="sg-deps">${d.rows.slice(0, 8).map(row).join("")}</ul>${d.rows.length > 8 ? `<p class="note">${d.rows.length - 8} more in NEXUS.</p>` : ""}`
      : `<p class="note">${d.read ? "The filings were read and no dependency was disclosed." : "Not measured: the filings for this company have not been read yet. NEXUS has read " + (d.done ?? "some") + " of " + (d.total ?? "all") + " listed companies so far."}</p>`}
    <div class="sg-actions"><button type="button" class="btn-ink" id="sg-nx">Open the full supply-chain view →</button></div>
    <p class="note">Every link carries its filing, page and a verbatim quote. A move in a linked stock is an association, not proof of cause. Dependencies are not part of the signal rule yet: see "How it was made".</p></div>`;
}

function sheetHtml(r) {
  const tab = TABS.find(t => t[0] === st.tab) ? st.tab : "summary", b = r.book;
  const body = tab === "summary" ? summaryHtml(r) : tab === "how" ? howHtml(r) : tab === "range" ? rangeHtml(r) : depsHtml(r);
  return `<div class="sg-back" data-close="1"></div><aside class="sg-sheet" role="dialog" aria-modal="true" aria-label="${esc(r.sym)} details">
    <header><div><h3>${esc(r.sym)} ${badge(r.sig)}</h3><p>${esc(r.name || "")}${r.sector ? " · " + esc(r.sector) : ""} · close ${inr(r.close)}</p></div><div class="sg-hbtns"><button type="button" class="btn-line sm" id="sg-chart">Open chart</button><button type="button" class="sg-x" data-close="1" aria-label="Close">×</button></div></header>
    <nav class="sg-tabs" role="tablist">${TABS.map(([k, t]) => `<button type="button" role="tab" data-t="${k}" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}">${esc(t)}</button>`).join("")}</nav>
    <div class="sg-body">${body}</div><footer>${DISCLAIMER}</footer></aside>`;
}
function currentRow() {
  const { rows } = buildRows(W, ctx.S.uni ? ctx.S.uni.stocks : [], { q: st.sel, filter: "all", limit: 5 });
  return rows.find(r => r.sym === st.sel) || null;
}
function paintSheet() {
  const host = root && root.querySelector("#sg-sheet-host"); if (!host) return;
  const r = st.sel && W ? currentRow() : null;
  if (!r) { host.innerHTML = ""; document.documentElement.classList.remove("sg-lock"); return; }
  const keep = host.querySelector(".sg-body"), top = keep ? keep.scrollTop : 0;
  host.innerHTML = sheetHtml(r); document.documentElement.classList.add("sg-lock");
  const nb = host.querySelector(".sg-body"); if (nb) nb.scrollTop = top;
  host.querySelectorAll("[data-close]").forEach(b => b.onclick = close);
  host.querySelectorAll("[data-t]").forEach(b => b.onclick = () => { st.tab = b.dataset.t; if (nb) nb.scrollTop = 0; paintSheet(); });
  const ch = host.querySelector("#sg-chart"); if (ch) ch.onclick = () => { const s = st.sel; close(); ctx.openSec(s); ctx.go("terminal"); };
  const nx = host.querySelector("#sg-nx"); if (nx) nx.onclick = () => { import("./desk-nexus.js").then(m => m.openNexus({ type: "company", id: st.sel })); };
  const sheet = host.querySelector(".sg-sheet"); if (sheet) { sheet.focus?.(); }
}
function open(sym, tab) { st.sel = sym; st.tab = tab || "summary"; paintSheet(); const x = root.querySelector(".sg-x"); if (x) x.focus(); root.querySelectorAll("#sg-list tbody tr").forEach(tr => tr.classList.toggle("on", tr.dataset.sym === sym)); }
function close() { st.sel = null; paintSheet(); root.querySelectorAll("#sg-list tbody tr.on").forEach(tr => tr.classList.remove("on")); }

function paintList() {
  const el = root.querySelector("#sg-list"); if (!el) return; el.innerHTML = listHtml();
  el.querySelectorAll("tbody tr").forEach(tr => { tr.onclick = () => open(tr.dataset.sym); tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(tr.dataset.sym); } }; });
}
function bind() {
  const q = root.querySelector("#sg-q"); if (q) q.oninput = () => { st.q = q.value; paintList(); };
  if (q) q.onkeydown = e => { if (e.key === "Enter") { const tr = root.querySelector("#sg-list tbody tr"); if (tr) open(tr.dataset.sym); } };
  root.querySelectorAll("[data-f]").forEach(b => b.onclick = () => { st.filter = b.dataset.f; root.querySelectorAll("[data-f]").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); }); paintList(); });
}
export async function mount() {
  root = document.getElementById("signals"); if (!root) return;
  if (!document.__sgKey) { document.__sgKey = true; document.addEventListener("keydown", e => { if (e.key === "Escape" && st.sel && root && root.isConnected) close(); }); }
  if (!W) { root.innerHTML = '<p class="note">Loading…</p>'; await load(); }
  const q0 = root.querySelector("#sg-q"), had = q0 && q0.value;
  root.innerHTML = shell(); bind(); paintList(); if (had) root.querySelector("#sg-q").value = had; paintSheet();
}
export const _test = { reset: () => { W = null; graph = null; failed = false; loading = null; st.q = ""; st.filter = "all"; st.sel = null; st.tab = "summary"; }, set: (w, g) => { W = w; graph = g; } };
