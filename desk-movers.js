/* MOVERS, extended. Three views over the same tab: "Price & volume" (the existing table, now with relative volume and a sweep badge), "ALADIN probability" (who moved
   most in P(up) since the last saved night, and which front moved it) and "Supply-chain shocks" (a linked stock's move against the share a counterparty is of it).
   Every row, in every view, expands (lazily: nothing is fetched until the first expansion) into supply lineage, quant drivers and sentiment & sweeps, each ending in
   "Open in NEXUS". Expansions stay open across the page's polls, and live price changes patch existing cells instead of rebuilding the table.
   The wording is "linked move" and "association, not proof of cause": a counterparty's move does not cause a stock's.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. */
import { lineage, rankShocks, shockSentence, shareText, docLabel, listedDependencyStocks } from "./desk-deps.js";
import { preload as alPreload, sentHtml } from "./desk-aladin.js";

let ctx = null, kind = "price", horizon = 10, graph = null, graphLoading = null, shocks = null, moves = null, movesTried = false;
const open = new Set();
const files = () => ctx.S.deskMan || {};
const KINDS = { price: "Price & volume", aladin: "ALADIN probability", shock: "Supply-chain shocks" };
const pct0 = v => v == null ? "—" : Math.round(v * 100) + "%";

export function init(c) {
  ctx = c;
  const kb = ctx.$("#mov-kind");
  if (kb) kb.addEventListener("click", e => { const b = e.target.closest("[data-k]"); if (b) setKind(b.dataset.k); });
  const hb = ctx.$("#mov-h");
  if (hb) hb.addEventListener("click", e => { const b = e.target.closest("[data-h]"); if (b) { horizon = +b.dataset.h; paintSeg(); renderAlt(); } });
  const v = ctx.$("#v-movers");
  if (v) v.addEventListener("click", e => {
    const t = e.target.closest(".mv-tg");
    if (t) { e.preventDefault(); e.stopPropagation(); toggle(t.dataset.s); return; }
    const r = e.target.closest("tr.mv-r");                                           // a row of the two new tables toggles; the price table's rows still open the chart
    if (r && !e.target.closest("a, button, [data-nexus]")) toggle(r.dataset.s);
  });
}

/* ---------- the three views ---------- */
function paintSeg() {
  ctx.$$("#mov-kind button").forEach(b => { const on = b.dataset.k === kind; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  const hb = ctx.$("#mov-h"); if (hb) { hb.hidden = kind !== "aladin"; ctx.$$("#mov-h button").forEach(b => { const on = +b.dataset.h === horizon; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }); }
  const price = ctx.$("#mov-price"), alt = ctx.$("#mov-alt");
  if (price) price.hidden = kind !== "price";
  if (alt) alt.hidden = kind === "price";
}
export function setKind(k) {
  if (!KINDS[k] || !ctx) return;
  kind = k; paintSeg();
  if (k !== "price") renderAlt(); else restore();
}
export const currentKind = () => kind;

async function renderAlt() {
  const el = ctx.$("#mov-alt"); if (!el) return;
  el.innerHTML = '<p class="empty">Loading…</p>';
  if (kind === "aladin") await renderMoves(el); else if (kind === "shock") await renderShocks(el);
  restore();
}

/* ---------- ALADIN probability movers ---------- */
async function renderMoves(el) {
  const { esc } = ctx;
  if (!files().moves) { el.innerHTML = '<p class="empty">ALADIN\'s night-to-night comparison has not been published yet. It is written after each nightly run.</p>'; return; }
  if (!moves && !movesTried) { movesTried = true; moves = await ctx.getJSON("aladin_moves.json").catch(() => null); }
  if (!moves) { el.innerHTML = '<p class="empty">The comparison could not be loaded. Try again in a minute.</p>'; return; }
  if (!moves.ok) { el.innerHTML = `<p class="empty">Needs more history: ${esc(moves.reason)}</p>`; return; }
  const H = moves.h[String(horizon)] || { up: [], down: [], compared: 0 };
  const rows = (list, label) => `<div class="tablecard" tabindex="0" role="region" aria-label="${label}"><div class="card-bar">${label}</div><table class="tbl sm"><thead><tr><th>#</th><th>Symbol</th><th class="mov-co">Company</th><th class="r">P(up) now</th><th class="r">Change</th><th class="r mov-co">Was</th><th>Confidence</th><th>Moved by</th></tr></thead><tbody>${list.map((r, i) => {
    const u = ctx.S.map.get(r.s) || {}, on = open.has(r.s);
    return `<tr class="mv-r" data-s="${esc(r.s)}"><td class="mut">${i + 1}</td><td class="sym"><button class="mv-tg" data-s="${esc(r.s)}" aria-expanded="${on}" aria-label="${on ? "Hide" : "Show"} lineage, drivers and sentiment for ${esc(r.s)}">${on ? "▾" : "▸"}</button> ${esc(r.s)}</td><td class="co mov-co">${esc(u.n || "")}</td>
      <td class="num">${pct0(r.p)}</td><td class="num ${r.dp > 0 ? "up" : "down"}">${r.dp > 0 ? "▲ +" : "▼ "}${r.dp.toFixed(1)} pts</td><td class="num mut mov-co">${pct0(r.prev)}</td><td><span class="tag${r.conf === "High" ? " acc" : ""}">${esc(r.conf)}</span></td><td>${esc(r.front)}</td></tr>${on ? `<tr class="mv-x" data-for="${esc(r.s)}"><td colspan="8"></td></tr>` : ""}`;
  }).join("") || '<tr><td colspan="8" class="empty">No stock moved in this direction.</td></tr>'}</tbody></table></div>`;
  el.innerHTML = `<p class="asof">Nightly model, ${esc(moves.as_of)} compared with ${esc(moves.prev_as_of)} · ${H.compared.toLocaleString("en-IN")} stocks compared at ${horizon} days · <b>not live</b>: it changes once a night.</p>
    <div class="ol-two">${rows(H.up, "Biggest rises in P(up)")}${rows(H.down, "Biggest falls in P(up)")}</div>
    <p class="note">P(up) is the combined ALADIN estimate (Technical, Fundamental, supply-chain impact and Sentiment), recomputed the same way for both nights. "Moved by" names the front whose contribution to the log-odds changed most between the two nights. A model estimate that is often wrong: ALADIN is a statistical model built by students. Educational analysis only, not investment advice.</p>`;
}

/* ---------- supply-chain shocks ---------- */
async function loadGraph() {
  if (graph || !files().graph) return graph;
  graphLoading = graphLoading || ctx.getJSON("supply_graph.json", false).then(j => { graph = j; }).catch(() => { graph = false; }).finally(() => { graphLoading = null; });
  await graphLoading;
  return graph;
}
const liveMove = sym => { const x = ctx.q(sym); return x && x.pct != null ? x.pct : null; };
function shockRows() { return rankShocks((shocks || {}).shocks, (graph || {}).edges, liveMove); }
async function renderShocks(el) {
  const { esc } = ctx;
  if (!files().shocks || !files().graph) { el.innerHTML = '<p class="empty">The supply-chain shock list has not been published yet.</p>'; return; }
  if (!shocks) shocks = await ctx.getJSON("shocks.json").catch(() => null);
  await loadGraph();
  if (!shocks || !graph) { el.innerHTML = '<p class="empty">The supply-chain data could not be loaded. Try again in a minute.</p>'; return; }
  const rows = shockRows();
  if (!rows.length) {
    const L = listedDependencyStocks(graph), read = graph.coverage.companies_done, total = graph.coverage.companies_total;
    el.innerHTML = `<p class="asof">${shocks.as_of ? "Shocks as of " + esc(shocks.as_of) : "No shock scores have been computed yet"} · linked moves, not causes</p>
      <p class="empty">No supply-chain shock to show. <b>${L.focal.size} of ${read}</b> companies read so far have a disclosed dependency on another listed company with a stated share (${total ? `${read} of ${total} listed securities have been read` : `${read} companies read`}), through ${L.edges} such dependenc${L.edges === 1 ? "y" : "ies"}. A shock needs one of those and a counterparty that moves by at least 3 percentage points beyond the market over 5 days, so there is nothing to rank right now. This fills in as more filings are read.</p>`;
    return;
  }
  const sig = rows.map(r => r.edge).join(",");
  el.dataset.sig = sig;
  el.innerHTML = `<p class="asof">Shocks as of ${esc(shocks.as_of || "an unknown date")} · moves are live where a quote exists, otherwise the last close · linked moves, not causes</p>
    <div class="tablecard"><table class="tbl sm" id="mov-shock"><thead><tr><th>#</th><th>Counterparty</th><th class="r">Move today</th><th>Stock affected</th><th class="r">Move today</th><th>Link</th><th class="r">Conf</th></tr></thead><tbody>${rows.map((r, i) => shockRow(r, i)).join("")}</tbody></table></div>
    <p class="note">Ordered by the counterparty's share of the stock times how far the counterparty moved. Only links read from a filing with a verified quote and confidence of at least 0.5 are used. Association, not proof of cause.</p>`;
}
function shockRow(r, i) {
  const { esc } = ctx, e = r.edgeRow, sg = v => v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
  const cls = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
  return `<tr class="mv-sh" data-e="${esc(r.edge)}"><td class="mut">${i + 1}</td><td><button class="lnk" data-nexus="company:${esc(r.cp)}">${esc(r.cp)}</button></td><td class="num sh-cp ${cls(r.cpMove)}">${sg(r.cpMove)}</td>
    <td><button class="lnk" data-nexus="company:${esc(r.focal)}">${esc(r.focal)}</button></td><td class="num sh-fo ${cls(r.focalMove)}">${sg(r.focalMove)}</td>
    <td><button class="lnk" data-nexus="edge:${esc(r.edge)}">${esc(shareText(e))}</button><div class="mut sh-tx">${esc(shockSentence(r))}</div></td><td class="num">${(e.conf ?? 0).toFixed(2)} <span class="mut">${esc(docLabel(e))}</span></td></tr>`;
}
/* live quotes arrive: update the move cells and the sentence in place; rebuild only when the order changed */
function patchShocks() {
  const el = ctx.$("#mov-alt"); if (!el || !shocks || !graph) return;
  const rows = shockRows();
  if (!rows.length || el.dataset.sig !== rows.map(r => r.edge).join(",")) { renderShocks(el); return; }
  const sg = v => v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`, cls = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
  for (const r of rows) {
    const tr = el.querySelector(`tr.mv-sh[data-e="${CSS.escape(r.edge)}"]`); if (!tr) continue;
    const a = tr.querySelector(".sh-cp"), b = tr.querySelector(".sh-fo"), t = tr.querySelector(".sh-tx");
    a.textContent = sg(r.cpMove); a.className = `num sh-cp ${cls(r.cpMove)}`; b.textContent = sg(r.focalMove); b.className = `num sh-fo ${cls(r.focalMove)}`; t.textContent = shockSentence(r);
  }
}
/* called from the page's poll */
export function refresh() { if (ctx && kind === "shock") patchShocks(); }

/* ---------- row expansion (all views) ---------- */
async function ensureDeps() {
  await Promise.all([alPreload().catch(() => null), loadGraph()]);
}
function expansionHtml(sym) {
  const { esc } = ctx, a = ((ctx.S.aladin || {}).stocks || {})[sym], N = graph ? new Map(graph.nodes.map(n => [n.id, n])) : null;
  const nm = id => { const n = N && N.get(id); return n && n.k === "co" ? `<button class="lnk" data-nexus="company:${esc(id)}">${esc(id)}</button>` : esc((n && n.n) || id); };
  const edgeLine = (e, other) => `<li>${nm(other)} · ${esc(shareText(e))} <span class="mut">· conf ${(e.conf ?? 0).toFixed(1)} · ${esc(e.per || "")}</span> <button class="lnk" data-nexus="edge:${esc(e.id)}">evidence</button></li>`;
  let lin;
  if (!files().graph) lin = '<p class="mut">The supply-chain data has not been published yet.</p>';
  else if (graph === false) lin = '<p class="mut">The supply-chain data could not be loaded.</p>';
  else if (!graph) lin = '<p class="mut">Loading…</p>';
  else {
    const L = lineage(graph, sym), read = graph.cos && graph.cos[sym];
    lin = !L.any ? `<p class="mut">${read ? "Not measured: no dependency of this company is disclosed in the filings read." : "Not measured: this company's filings have not been read yet."}</p>`
      : `<div class="sec-t">Customers</div>${L.customers.length ? `<ul class="nx-ul">${L.customers.map(e => edgeLine(e, e.d)).join("")}</ul>` : '<p class="mut">None disclosed</p>'}
         <div class="sec-t">Suppliers</div>${L.suppliers.length ? `<ul class="nx-ul">${L.suppliers.map(e => edgeLine(e, e.s)).join("")}</ul>` : '<p class="mut">None disclosed</p>'}
         <div class="sec-t">Component bottlenecks</div>${L.bottlenecks.length ? `<ul class="nx-ul">${L.bottlenecks.map(b => `<li>${esc(b.comp)}: supplied only by ${nm(b.edge.s)} <span class="mut">in the filings read</span></li>`).join("")}</ul>` : '<p class="mut">Not disclosed</p>'}`;
  }
  let quant;
  if (!a || !a.t) quant = `<p class="mut">${ctx.S.aladin ? "ALADIN has no probability for this stock (not enough price history, or not covered)." : (files().aladin ? "Loading…" : "ALADIN data has not been published yet.")}</p>`;
  else {
    const t = a.t, d = a.f && a.f.dist, n = (v, k = 2) => v == null || !isFinite(v) ? "—" : Number(v).toFixed(k);
    quant = `<p>Market turbulence now ${pct0(t.hmm)} · market-factor residual z ${n(t.pca_z)}</p>
      <p>${d ? `Distress: ${esc(d.band)} · distance to default ${n(d.dd, 1)} · default probability ${d.pd == null ? "—" : (d.pd * 100).toFixed(2) + "%"} · Altman Z″ ${n(d.z2, 1)}` : '<span class="mut">Distress model not applicable (financial company or no debt)</span>'}</p>
      <div class="sec-t">What moved the Technical view most</div><div>${ctx.driversHtml(t.drv, 5) || '<span class="mut">—</span>'}</div>`;
  }
  const s = ((ctx.S.sentiment || {}).stocks || {})[sym], evs = (ctx.S.sweepEv || []).filter(e => e.sym === sym).slice(-3).reverse();
  const retail = s && s.rn ? `${s.rn} distinct author${s.rn === 1 ? "" : "s"} in 24 h (Reddit, when configured)` : "not measured: needs at least 5 distinct authors in 24 h";
  const sent = `${ctx.S.sentiment ? sentHtml(sym, true, false) : '<p class="mut">Sentiment data has not been loaded.</p>'}
    <p class="mut">Retail chatter: ${esc(retail)}</p>
    <div class="sec-t">Liquidity sweeps</div>${evs.length ? evs.map(e => `<p>${e.dir > 0 ? "▲" : "▼"} ${esc(e.lvl)} at ${Number(e.px).toFixed(2)} · volume ${Number(e.rvol).toFixed(1)}× normal · wick ${Math.round(e.wick * 100)}% · ${e.confirmed ? "confirmed" : "forming"}</p>`).join("") : '<p class="mut">No sweep seen. Sweeps need the local tick program.</p>'}`;
  const go = (tab, label) => `<p><a href="#" data-nexus="company:${esc(sym)}" data-nexus-tab="${tab}">Open in NEXUS →</a> <span class="mut">${label}</span></p>`;
  return `<div class="al-x3"><div><div class="sec-t">Supply lineage</div>${lin}${go("chain", "supply chain")}</div><div><div class="sec-t">Quant drivers</div>${quant}${go("quant", "quant")}</div><div><div class="sec-t">Sentiment &amp; sweeps</div>${sent}${go("sent", "sentiment and sweeps")}</div></div>`;
}
const rowsFor = sym => [...ctx.$$("#v-movers tr[data-s]")].filter(r => r.dataset.s === sym && !r.classList.contains("mv-x"));
function placeExpansion(tr, sym) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("mv-x") && next.dataset.for === sym) return next;
  const x = document.createElement("tr"); x.className = "mv-x"; x.dataset.for = sym;
  const td = document.createElement("td"); td.colSpan = tr.children.length; x.appendChild(td); tr.after(x);
  return x;
}
function fill(sym) { ctx.$$(`#v-movers tr.mv-x[data-for="${CSS.escape(sym)}"] > td`).forEach(td => { td.innerHTML = expansionHtml(sym); }); }
function mark(tr, on, sym) {
  const b = tr.querySelector(".mv-tg"); if (!b) return;
  b.setAttribute("aria-expanded", String(on)); b.textContent = on ? "▾" : "▸"; b.setAttribute("aria-label", `${on ? "Hide" : "Show"} lineage, drivers and sentiment for ${sym}`);
}
export function toggle(sym) {
  const on = !open.has(sym);
  on ? open.add(sym) : open.delete(sym);
  for (const tr of rowsFor(sym)) {
    const nx = tr.nextElementSibling;
    if (on) { placeExpansion(tr, sym); } else if (nx && nx.classList.contains("mv-x")) nx.remove();
    mark(tr, on, sym);
  }
  if (on) { fill(sym); ensureDeps().then(() => { if (open.has(sym)) fill(sym); }); }
}
/* the tables were rebuilt: put every open expansion back */
export function restore() {
  if (!ctx) return;
  for (const sym of open) {
    const rows = rowsFor(sym);
    for (const tr of rows) { placeExpansion(tr, sym); mark(tr, true, sym); }
    if (rows.length) { fill(sym); ensureDeps().then(() => { if (open.has(sym)) fill(sym); }); }
  }
}
