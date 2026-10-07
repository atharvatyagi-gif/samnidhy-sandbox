/* NEXUS Deep Intelligence Panel and Supply Chain Inspector.
   One drawer for every entity the desk can show (company, edge, facility; flights, vessels, hotspots and groups arrive with the Globe phase):
   openNexus({ type, id, tab, tier }). Deep-linkable as #nx=company:RELIANCE. Data (supply_graph.json, shocks.json) is fetched the first time the panel opens.
   Everything shown is read from sources: each dependency carries the filing, page, a verbatim quote, a period and a confidence. A missing fact says
   "Not measured" or "Not disclosed", never a guess. A linked move is an association, not proof of cause.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. */

import { lanesAt, carrierOf, ageMin, ageText, isStale, shipTypeLabel, countIn } from "./desk-lanes.js";
import { coverageState, shareText, derivedNote } from "./desk-deps.js";
import { ageLabel } from "./desk-kin.js";

const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice.";
const REL = { supplies: "supplies", equipment_for: "equipment for", raw_material_from: "raw material from", logistics_for: "logistics for", related_party: "related party", customer_of: "customer of" };
const KIND = { co: "listed company", ext: "unlisted or foreign", anon: "unnamed customer", fac: "facility" };
const COMPANY_TABS = [["overview", "Overview"], ["chain", "Supply chain"], ["deps", "Dependencies"], ["quant", "Quant"], ["sent", "Sentiment & sweeps"], ["sources", "Sources"]];
const GEO_PREC = { exact: "Exact location", locality: "Approximate (locality)", district: "Approximate (district)", city: "Approximate (city)" };

let ctx = null, root = null, graph = null, shocks = null, loading = null, loadFailed = false, lastFocus = null;
const extra = { lanes: null };                                         // trade_lanes.json, fetched for the flight / vessel / hotspot / chokepoint panels
const MOVING = new Set(["flight", "vessel", "hotspot", "chokepoint"]);
const cur = { type: null, id: null, tab: "overview" };
const gst = { tier: 1, side: "both", low: false, view: "graph", hit: [] };

export function init(c) {
  ctx = c;
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("[data-nexus]");
    if (!a) return;
    e.preventDefault();
    const [type, ...rest] = a.dataset.nexus.split(":");
    openNexus({ type, id: rest.join(":"), tab: a.dataset.nexusTab || undefined });
  });
}

/* ---------- data ---------- */
const files = () => ctx.S.deskMan || {};
async function load() {
  if (graph || loadFailed) return;
  loading = loading || Promise.all([
    files().graph ? ctx.getJSON("supply_graph.json", false).then(j => { graph = j; }) : 0,
    files().shocks ? ctx.getJSON("shocks.json").then(j => { shocks = j; }).catch(() => { shocks = null; }) : 0,
    ctx.S.aladin || !files().aladin ? 0 : ctx.getJSON("aladin.json").then(j => { ctx.S.aladin = j; }).catch(() => 0),
    ctx.S.sentiment || !files().sentiment ? 0 : ctx.getJSON("sentiment.json").then(j => { ctx.S.sentiment = j; }).catch(() => 0),
  ]).catch(() => { loadFailed = true; }).finally(() => { loading = null; });
  await loading;
}
async function loadExtra() {
  if (!MOVING.has(cur.type)) return;
  const f = files();
  await Promise.all([
    ctx.S.transport || !f.telemetry ? 0 : ctx.getJSON("telemetry.json", true).then(j => { ctx.S.transport = j; }).catch(() => 0),
    extra.lanes || !f.lanes ? 0 : ctx.getJSON("trade_lanes.json", false).then(j => { extra.lanes = j; }).catch(() => 0),
    ctx.S.geo || !f.geo ? 0 : ctx.getJSON("geo.json").then(j => { ctx.S.geo = j; }).catch(() => 0),
    ctx.S.aladin || !f.aladin ? 0 : ctx.getJSON("aladin.json").then(j => { ctx.S.aladin = j; }).catch(() => 0),
    ctx.S.sentiment || !f.sentiment ? 0 : ctx.getJSON("sentiment.json").then(j => { ctx.S.sentiment = j; }).catch(() => 0),
  ]);
}
const nodeOf = id => graph && (graph._n || (graph._n = new Map(graph.nodes.map(n => [n.id, n])))).get(id);
const nameOf = id => { const n = nodeOf(id), u = ctx.S.map && ctx.S.map.get(id); return (u && u.n) || (n && n.n) || id; };
const edgesOf = id => graph ? (graph._adj || (graph._adj = (() => { const m = new Map(); for (const e of graph.edges) for (const k of [e.s, e.d]) { if (!m.has(k)) m.set(k, []); m.get(k).push(e); } return m; })())).get(id) || [] : [];
const lab = id => { const n = nodeOf(id); return n && n.k === "co" ? id : (n && n.n) || id; };
const minConf = () => 0.5;
const pct = (v, d = 0) => v == null ? "—" : (v * 100).toFixed(d) + "%";
const move = sym => { const q = ctx.q(sym); return q && q.pct != null ? `<span class="${ctx.ud(q.pct)}">${ctx.sg(q.pct)}%</span>` : '<span class="mut">—</span>'; };
const shareTxt = e => e.w == null ? '<span class="mut">no share stated</span>' : ctx.esc(shareText(e));

/* ---------- shell ---------- */
function shell() {
  if (root) return root;
  root = document.createElement("div");
  root.id = "nx-root";
  root.hidden = true;
  root.innerHTML = `<div class="nx-back" data-nx-close></div>
    <aside class="nx-drawer nx-dark" role="dialog" aria-modal="true" aria-labelledby="nx-title" tabindex="-1">
      <div class="nx-head"><div><div class="kick" id="nx-kind"></div><h2 id="nx-title"></h2><div class="asof" id="nx-asof"></div></div>
        <button class="btn-line sm" data-nx-close aria-label="Close the NEXUS panel">Close ✕</button></div>
      <div class="nx-tabs seg" id="nx-tabs" role="tablist" aria-label="NEXUS sections"></div>
      <div class="nx-body" id="nx-body"></div>
      <div class="nx-foot"><p class="note">${DISCLAIMER}</p></div>
    </aside>`;
  document.body.appendChild(root);
  root.addEventListener("click", e => {
    if (e.target.closest("[data-nx-close]")) closeNexus();
    const t = e.target.closest("[data-nx-tab]");
    if (t) { cur.tab = t.dataset.nxTab; draw(); }
  });
  root.addEventListener("keydown", e => {
    if (e.key === "Escape") { e.stopPropagation(); closeNexus(); return; }
    if (e.key !== "Tab") return;
    const f = [...root.querySelectorAll('button, a[href], input, select, summary, [tabindex="0"]')].filter(x => !x.disabled && x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  root.addEventListener("change", e => {
    const el = e.target;
    if (el.id === "nx-tier") { gst.tier = +el.value; draw(); }
    else if (el.id === "nx-side") { gst.side = el.value; draw(); }
    else if (el.id === "nx-low") { gst.low = el.checked; draw(); }
  });
  root.querySelector("#nx-body").addEventListener("click", e => {
    const v = e.target.closest("[data-nx-view]");
    if (v) { gst.view = v.dataset.nxView; draw(); }
  });
  return root;
}

export async function openNexus(a) {
  if (!ctx) return;
  shell();
  lastFocus = document.activeElement;
  Object.assign(cur, { type: a.type, id: a.id, tab: a.tab || (a.type === "company" ? "overview" : "overview") });
  if (a.tier) gst.tier = a.tier;
  ctx.S.nx = `${cur.type}:${cur.id}`;
  history.replaceState(null, "", (location.hash.replace(/&?nx=[^&]*/, "") || "#v=brief") + `&nx=${encodeURIComponent(ctx.S.nx)}`);
  root.hidden = false;
  document.body.classList.add("nx-open");
  paintHead();
  root.querySelector("#nx-body").innerHTML = '<div class="nx-skel" aria-busy="true"><i></i><i></i><i></i></div>';
  const globeOpen = (() => { const v = document.getElementById("v-globe"); return !!v && !v.hidden && v.offsetParent !== null; })();
  root.classList.toggle("nx-docked", globeOpen);                                   // on the Globe, a desktop-width drawer sits beside it and leaves it usable
  root.querySelector(".nx-drawer").setAttribute("aria-modal", globeOpen && window.innerWidth > 700 ? "false" : "true");
  root.querySelector(".nx-drawer").focus();
  await load();
  await loadExtra();
  if (!root.hidden && cur.id === a.id) draw();
}
export function closeNexus() {
  if (!root || root.hidden) return;
  root.hidden = true;
  document.body.classList.remove("nx-open");
  ctx.S.nx = null;
  history.replaceState(null, "", location.hash.replace(/&?nx=[^&]*/, "") || "#v=brief");
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
export function openFromHash(raw) {
  if (!raw) return;
  const [type, ...rest] = decodeURIComponent(raw).split(":");
  if (type && rest.length) openNexus({ type, id: rest.join(":") });
}

function paintHead() {
  const { esc } = ctx, t = cur.type, id = cur.id;
  let title = id, kind = t;
  if (t === "company") { title = `${id} · ${nameOf(id)}`; kind = "NEXUS · company"; }
  else if (t === "facility") { const f = graph && graph.fac[id]; title = f ? f.n : id; kind = "NEXUS · facility"; }
  else if (t === "edge") { const e = graph && graph.edges.find(x => x.id === id); title = e ? `${lab(e.s)} → ${lab(e.d)}` : id; kind = "NEXUS · dependency"; }
  else if (t === "flight") { const f = flightRow(id); title = f ? `${f[1] || f[0]} · flight` : `${id} · flight`; kind = "NEXUS · flight"; }
  else if (t === "vessel") { const v = vesselRow(id); title = v ? `${v[1] || v[0]} · vessel` : `${id} · vessel`; kind = "NEXUS · vessel"; }
  else if (t === "hotspot") { const r = regionOf(id); title = r ? r.name : id; kind = "NEXUS · hotspot"; }
  else if (t === "chokepoint") { const c = chokeOf(id); title = c ? c.name : id; kind = "NEXUS · chokepoint"; }
  else kind = `NEXUS · ${t}`;
  root.querySelector("#nx-kind").textContent = kind;
  root.querySelector("#nx-title").textContent = title;
  const T = ctx.S.transport;
  root.querySelector("#nx-asof").textContent = MOVING.has(t) && (t === "flight" || t === "vessel" || t === "chokepoint") && T ? `Position snapshot ${ageText(ageMin(T.generated_utc))}${isStale(T) ? " · older than its limit" : ""}`
    : graph ? `Supply-chain data generated ${graph.generated_utc} · ${graph.coverage.companies_done} companies read` : "";
  const tabs = t === "company" ? COMPANY_TABS : [];
  root.querySelector("#nx-tabs").innerHTML = tabs.map(([k, l]) => `<button role="tab" aria-selected="${cur.tab === k}" class="${cur.tab === k ? "on" : ""}" data-nx-tab="${k}">${l}</button>`).join("");
  void esc;
}

function draw() {
  if (!root || root.hidden) return;
  paintHead();
  const body = root.querySelector("#nx-body");
  if (MOVING.has(cur.type)) { body.innerHTML = cur.type === "flight" ? flightPanel() : cur.type === "vessel" ? vesselPanel() : cur.type === "hotspot" ? hotspotPanel() : chokePanel(); return; }
  if (!files().graph && !graph) { body.innerHTML = '<p class="note">The supply-chain data has not been published yet, so there are no dependencies to show. Everything else about this entity stays available in the ALADIN tab.</p>'; return; }
  if (!graph) { body.innerHTML = '<p class="note">The supply-chain data could not be loaded. Try again in a minute.</p>'; return; }
  const t = cur.type;
  body.innerHTML = t === "company" ? companyTab() : t === "facility" ? facilityPanel() : t === "edge" ? edgePanel() : placeholderPanel();
  if (t === "company" && cur.tab === "chain") drawGraph(body);
}

function placeholderPanel() {
  return `<p class="note">There is no panel for "${ctx.esc(cur.type)}".</p>`;
}

/* ---------- flights, vessels, hotspots, chokepoints (the Globe) ---------- */
const flightRow = id => ((ctx.S.transport || {}).flights || []).find(r => r[0] === id);
const vesselRow = id => ((ctx.S.transport || {}).vessels || []).find(r => String(r[0]) === String(id));
const regionOf = id => ((ctx.S.geo || {}).regions || []).find(r => r.id === id);
const chokeOf = id => ((extra.lanes || {}).chokepoints || []).find(c => c.id === id);
const NM = '<span class="mut">Not measured</span>';

/* "lane-level inference": companies listed against the hand-drawn lanes a position falls inside. NEVER about this one flight or ship. */
function stocksFor(row) {
  if (row.sym) return ctx.S.map.has(row.sym) ? [row.sym] : [];
  return ctx.S.uni.stocks.filter(u => u.ind === row.ind && u.n500).sort((a, b) => (b.v || 0) * (b.c || 0) - (a.v || 0) * (a.c || 0)).slice(0, 5).map(u => u.s);
}
function exposureTable(rows, withDelta) {
  const { esc } = ctx, seen = new Set(), out = [];
  for (const r of rows) for (const sym of stocksFor(r)) {
    const k = sym + r.dir + (r.laneId || ""); if (seen.has(k)) continue; seen.add(k);
    const v = ctx.stockView ? ctx.stockView(sym) : null, d = withDelta && ctx.geoDelta ? ctx.geoDelta(sym) : null;
    out.push(`<tr><td><button class="lnk" data-nexus="company:${esc(sym)}">${esc(sym)}</button> <span class="mut">${esc(nameOf(sym))}</span></td><td class="${r.dir === "+" ? "up" : "down"}" title="${r.dir === "+" ? "Tends to gain" : "Tends to lose"} when this is disrupted">${r.dir === "+" ? "▲" : "▼"}</td>
      <td class="mut">${esc(r.why)}${r.lane ? ` <i>(${esc(r.lane)})</i>` : ""}</td><td class="r">${move(sym)}</td>${withDelta ? `<td class="r">${d ? `<span class="${d.dp > 0 ? "up" : d.dp < 0 ? "down" : ""}" title="P(up) with the geopolitical adjustment minus P(up) without it, ${d.h}-day, model estimate">${d.dp > 0 ? "▲ +" : d.dp < 0 ? "▼ " : ""}${d.dp.toFixed(1)} pts</span>` : '<span class="mut">not available</span>'}</td>` : ""}
      <td class="r">${v ? pct(v.p) : '<span class="mut">—</span>'}</td></tr>`);
  }
  return out.length ? `<div class="tablecard"><table class="tbl sm"><thead><tr><th>Company</th><th></th><th>Why it is linked</th><th class="r">Move today</th>${withDelta ? '<th class="r">ΔP(up)</th>' : ""}<th class="r">P(up)</th></tr></thead><tbody>${out.join("")}</tbody></table></div>` : '<p class="mut">No listed company is linked to this.</p>';
}
const FIXED_ROWS = op => `<tr><th>Cargo manifest / Bill of Lading</th><td>Not measured — private/paid customs data</td></tr><tr><th>Receiving client</th><td>Not measured</td></tr><tr><th>Logistics carrier</th><td>${op}</td></tr>`;
function laneBlock(lat, lon, kind) {
  const L = extra.lanes ? lanesAt(lat, lon, extra.lanes.lanes, kind) : [];
  if (!extra.lanes) return '<p class="mut">The trade-lane list has not been published yet.</p>';
  if (!L.length) return '<p class="mut">This position is not inside any lane in our list, so no company is linked to it. Nothing is guessed.</p>';
  const rows = L.flatMap(l => (l.exposure || []).map(e => ({ ...e, lane: l.name, laneId: l.id })));
  return `<p class="mut">Inside: ${L.map(l => ctx.esc(l.name)).join("; ")}.</p>${exposureTable(rows, false)}<p class="mut">${ctx.esc(extra.lanes.note)}</p>`;
}
const fixText = fix => fix ? `${new Date(fix * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC (${ageLabel(Date.now() / 1000 - fix)} ago)` : "not reported";
const snapNote = k => { const T = ctx.S.transport; return T ? `<p class="mut">${ctx.esc((((T.sources || {})[k]) || {}).attribution || "")} Snapshot ${ctx.esc(ageText(ageMin(T.generated_utc)))}${isStale(T) ? " (older than its limit: treat as out of date)" : ""}. Positions are not live.</p>` : ""; };

function flightPanel() {
  const { esc } = ctx, T = ctx.S.transport, f = flightRow(cur.id);
  if (!T) return '<p class="note">No flight snapshot is published yet, so there is nothing to show. Nothing is guessed.</p>';
  if (!f) return `<p class="note">Not in the current snapshot (age ${esc(ageText(ageMin(T.generated_utc)))}). Aircraft move: it may have landed or left the area covered.</p>`;
  const c = carrierOf(f[1], T.carriers), op = c ? `${esc(c.name)} <span class="mut">(inferred from the callsign prefix ${esc(c.prefix)})</span>` : '<span class="mut">Operator not identified from the callsign</span>';
  return `<table class="tbl sm"><tbody><tr><th>Callsign</th><td>${esc(f[1] || "—")}</td></tr><tr><th>ICAO24 (aircraft address)</th><td>${esc(f[0])}</td></tr><tr><th>Operator</th><td>${op}</td></tr>
    <tr><th>Freighter airline?</th><td>${c ? (c.cargo ? "Yes: this airline flies dedicated freighters" : "No: a passenger airline") : "Unknown"} <span class="mut">(says nothing about what is on board)</span></td></tr>
    <tr><th>Registered in</th><td>${esc(f[8] || "—")}</td></tr><tr><th>Position</th><td>${f[2].toFixed(3)}, ${f[3].toFixed(3)}</td></tr><tr><th>Altitude</th><td>${f[4] == null ? "—" : Math.round(f[4]).toLocaleString("en-IN") + " m"}</td></tr>
    <tr><th>Speed</th><td>${f[5] == null ? "—" : Math.round(f[5] * 3.6) + " km/h"}</td></tr><tr><th>Heading</th><td>${f[6] == null ? "—" : f[6] + "°"}</td></tr><tr><th>Climb</th><td>${f[7] == null ? "—" : f[7] + " m/s"}</td></tr><tr><th>Position time (the source's own)</th><td>${esc(fixText(f[10]))}</td></tr>${FIXED_ROWS(c ? esc(c.name) + ' <span class="mut">(inferred from the callsign prefix)</span>' : NM)}</tbody></table>
    <div class="sec-t">Lane-level exposure (inference, not this shipment)</div>${laneBlock(f[2], f[3], "air")}${snapNote("flights")}`;
}
function vesselPanel() {
  const { esc } = ctx, T = ctx.S.transport, v = vesselRow(cur.id);
  if (!T || !T.vessels) return `<p class="note">${esc((T && (T.reason || T.vessels_reason)) || "Vessel layer off: no AIS key.")}</p>`;
  if (!v) return `<p class="note">Not in the current snapshot (age ${esc(ageText(ageMin(T.generated_utc)))}). Ships move: it may have left the areas covered.</p>`;
  return `<table class="tbl sm"><tbody><tr><th>Name</th><td>${esc(v[1] || "not broadcast")}</td></tr><tr><th>MMSI</th><td>${esc(v[0])}</td></tr><tr><th>Type</th><td>${esc(shipTypeLabel(v[7]))}</td></tr>
    <tr><th>Destination (as broadcast)</th><td>${esc(v[8] || "not broadcast")}</td></tr><tr><th>ETA (as broadcast)</th><td>${esc(v[9] || "not broadcast")}</td></tr><tr><th>Position time (the source's own)</th><td>${esc(fixText(v[10]))}</td></tr><tr><th>Position</th><td>${v[2].toFixed(3)}, ${v[3].toFixed(3)}</td></tr>
    <tr><th>Speed / course</th><td>${v[4] == null ? "—" : v[4] + " kn"} / ${v[5] == null ? "—" : Math.round(v[5]) + "°"}</td></tr>${FIXED_ROWS(NM)}</tbody></table>
    <div class="sec-t">Lane-level exposure (inference, not this shipment)</div>${laneBlock(v[2], v[3], "sea")}${snapNote("vessels")}`;
}
function sparkSvg(a) {
  const v = (a || []).filter(x => x != null);
  if (v.length < 2) return '<span class="mut">No history yet</span>';
  const lo = Math.min(...v), hi = Math.max(...v), W = 220, H = 36, pts = v.map((y, i) => `${(i / (v.length - 1) * W).toFixed(1)},${(H - 2 - (hi === lo ? 0.5 : (y - lo) / (hi - lo)) * (H - 4)).toFixed(1)}`).join(" ");
  return `<svg class="nx-spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="30-day news-attention history"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}
function hotspotPanel() {
  const { esc } = ctx, r = regionOf(cur.id);
  if (!r) return '<p class="note">The geopolitical index has not been published yet, or this region is not in it.</p>';
  const lanes = ((extra.lanes || {}).lanes || []).filter(l => l.geo_region === r.id), cps = ((extra.lanes || {}).chokepoints || []).filter(c => c.geo_region === r.id), T = ctx.S.transport;
  const heads = (r.heads || []).slice(0, 5).map(h => `<li><a href="${esc(h.url)}" target="_blank" rel="noopener noreferrer">${esc(h.title)}</a> <span class="mut">${esc(h.source || "")}</span></li>`).join("");
  return `<p><b>${esc(r.level)}${r.score == null ? "" : " · " + r.score}</b> <span class="mut">${esc(r.kind)} · news attention and tone, not events</span></p>
    ${r.baseline && !r.baseline.ready ? `<p class="mut">Building its baseline: ${r.baseline.n} of ${r.baseline.need} samples over ${r.baseline.days} of ${r.baseline.need_days} days. The score appears once there is a baseline to compare against.</p>` : ""}
    <div class="sec-t">30-day history</div>${sparkSvg(r.spark)}
    <div class="sec-t">Affected lanes and chokepoints</div>${lanes.length || cps.length ? `<ul class="nx-ul">${lanes.map(l => `<li>${esc(l.name)} <span class="mut">(${esc(l.kind)} lane)</span></li>`).join("")}${cps.map(c => `<li><button class="lnk" data-nexus="chokepoint:${esc(c.id)}">${esc(c.name)}</button> <span class="mut">${T && T.vessels ? countIn(T.vessels, c.bbox) + " vessels in the snapshot" : "vessel count not available"}</span></li>`).join("")}</ul>` : '<p class="mut">No lane in our list is tied to this region.</p>'}
    <div class="sec-t">Exposed on NSE</div>${exposureTable(r.exposure || [], true)}
    <p class="mut">ΔP(up) is the change the geopolitical adjustment makes to a stock's ALADIN probability (model estimate; its sign is the lean the news adds, across every region the stock is exposed to). Association, not proof of cause.</p>
    <div class="sec-t">Headlines</div>${heads ? `<ul class="nx-ul">${heads}</ul>` : '<p class="mut">None in the last cycle.</p>'}`;
}
function chokePanel() {
  const { esc } = ctx, c = chokeOf(cur.id), T = ctx.S.transport;
  if (!c) return '<p class="note">This chokepoint is not in the lane list.</p>';
  const r = c.geo_region ? regionOf(c.geo_region) : null, lanes = ((extra.lanes || {}).lanes || []).filter(l => (l.path || []).some(([lo, la]) => la >= c.bbox[1] - 3 && la <= c.bbox[3] + 3 && lo >= c.bbox[0] - 3 && lo <= c.bbox[2] + 3));
  return `<table class="tbl sm"><tbody><tr><th>Position</th><td>${c.lat.toFixed(2)}, ${c.lon.toFixed(2)}</td></tr><tr><th>Vessels in the box</th><td>${T && T.vessels ? countIn(T.vessels, c.bbox) + " in the snapshot" : esc((T && T.vessels_reason) || "Vessel layer off: no AIS key.")}</td></tr>
    <tr><th>News-attention region</th><td>${r ? `<button class="lnk" data-nexus="hotspot:${esc(r.id)}">${esc(r.name)}</button> · ${esc(r.level)}${r.score == null ? "" : " " + r.score}` : '<span class="mut">none tied to this chokepoint</span>'}</td></tr></tbody></table>
    <div class="sec-t">Lanes that pass through</div>${lanes.length ? `<ul class="nx-ul">${lanes.map(l => `<li>${esc(l.name)}</li>`).join("")}</ul>${exposureTable(lanes.flatMap(l => (l.exposure || []).map(e => ({ ...e, lane: l.name, laneId: l.id }))), false)}` : '<p class="mut">None in our list.</p>'}${snapNote("vessels")}`;
}

/* ---------- company ---------- */
function companyTab() {
  return ({ overview: overviewTab, chain: chainTab, deps: depsTab, quant: quantTab, sent: sentTab, sources: sourcesTab })[cur.tab]();
}
function stockA() { return ((ctx.S.aladin || {}).stocks || {})[cur.id]; }
function covLine(sym) { return coverageState(graph, sym).label; }
function overviewTab() {
  const { esc } = ctx, sym = cur.id, a = stockA(), x = ctx.q(sym), A = ctx.S.aladin;
  const price = x ? `${ctx.inr(x.p)} <span class="${ctx.ud(x.pct)}">${x.pct != null ? ctx.sg(x.pct) + "%" : ""}</span>` : "—";
  let al = '<p class="mut">ALADIN has no probability for this stock (not enough price history, or not covered).</p>';
  if (a && a.t) {
    const hs = Object.keys(a.t.p).sort((p, q) => p - q);
    const comb = a.comb || {};
    al = `<table class="tbl sm"><thead><tr><th>Horizon</th><th class="r">P(up) nightly</th><th>Confidence</th><th>Views agreeing</th></tr></thead><tbody>${hs.map(h => `<tr><td>${h} days</td><td class="r">${comb[h] ? pct(comb[h][0]) : "—"}</td><td>${comb[h] ? esc(comb[h][1]) : "—"}</td><td>${comb[h] ? esc(comb[h][2]) : "—"}</td></tr>`).join("")}</tbody></table>
      <p>Fundamental ${a.f && a.f.sc != null ? Math.round(a.f.sc) : "—"} · Technical ${Math.round(a.t.sc)} · Supply-chain impact ${a.x ? (a.x.i > 0 ? "+" : "") + a.x.i.toFixed(1) + " (positive = adverse)" : '<span class="mut">not measured</span>'}</p>
      <p class="mut">Nightly model data as of ${esc(A.as_of)}. The ALADIN tab updates P(up) during the day with live sentiment and sweeps.</p>`;
  }
  return `<div class="ol-grid"><div class="ol-stat"><b>${price}</b><span>last price</span></div><div class="ol-stat"><b>${edgesOf(sym).length}</b><span>disclosed links<br><small>${esc(covLine(sym))}</small></span></div></div>
    <div class="sec-t">ALADIN</div>${al}
    <div class="al-act"><button class="btn-line sm" data-nx-tab="chain">Supply chain</button> <button class="btn-line sm" data-open="${esc(sym)}">Open chart</button> <button class="btn-line sm" data-aladin="${esc(sym)}">Open in ALADIN</button></div>`;
}

/* dependencies: every edge that touches the company, with the counterparty's move today */
function depsTab() {
  const { esc } = ctx, sym = cur.id, es = edgesOf(sym).filter(e => gst.low || e.conf >= minConf());
  const sh = new Map(((shocks || {}).shocks || []).map(s => [s.edge, s]));
  if (!es.length) return `<p class="note">Not measured: no dependency of ${esc(sym)} is disclosed in the filings read so far. ${esc(covLine(sym))}</p>`;
  const rows = es.slice().sort((p, q) => (q.w || 0) - (p.w || 0) || q.conf - p.conf).map(e => {
    const up = e.d === sym, cp = up ? e.s : e.d, cn = nodeOf(cp), listed = cn && cn.k === "co";
    const s = sh.get(e.id);
    return `<tr><td>${up ? "Supplier" : "Customer"}</td><td>${listed ? `<button class="lnk" data-nexus="company:${esc(cp)}">${esc(cp)}</button>` : esc((cn && cn.n) || cp)} <span class="mut">${esc(KIND[(cn || {}).k] || "")}</span></td>
      <td>${esc(REL[e.rel] || e.rel)}${e.comp ? ` · ${esc(e.comp)}` : ""}</td><td>${shareTxt(e)}</td><td>${esc(e.per || "—")}</td><td class="r">${e.conf.toFixed(2)}</td><td class="r">${listed ? move(cp) : '<span class="mut">—</span>'}${s ? ` <span class="mut" title="Counterparty's 5-day residual move">z ${s.z > 0 ? "+" : ""}${s.z}</span>` : ""}</td>
      <td><details class="nx-q"><summary>quote</summary><p>“${esc(e.q)}”</p><p class="mut">${esc(e.doc)} · page ${e.pg} · <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">source</a> · <button class="lnk" data-nexus="edge:${esc(e.id)}">details</button></p></details></td></tr>`;
  }).join("");
  return `<label class="nx-chk"><input type="checkbox" id="nx-low" ${gst.low ? "checked" : ""}> Include low-confidence links (below ${minConf()})</label>
    <div class="tablecard"><table class="tbl sm"><thead><tr><th>Role</th><th>Counterparty</th><th>Link</th><th>Share</th><th>Period</th><th class="r">Conf</th><th class="r">Move today</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="mut">A share is the supplier's revenue share for customers and the customer's purchase share for suppliers; the two are never mixed. Association, not proof of cause.</p>`;
}

function quantTab() {
  const { esc } = ctx, a = stockA();
  if (!a || !a.t) return '<p class="note">No ALADIN data for this stock.</p>';
  const t = a.t, f = a.f || {}, d = f.dist, num = (v, k = 2) => v == null || !isFinite(v) ? "—" : Number(v).toFixed(k);
  return `<p>Market turbulence now ${pct(t.hmm)} · market-factor residual z ${num(t.pca_z)}</p>
    <p>${d ? `Distress: ${esc(d.band)} · distance to default ${num(d.dd, 1)} · default probability ${d.pd == null ? "—" : (d.pd * 100).toFixed(2) + "%"} · Altman Z″ ${num(d.z2, 1)}` : '<span class="mut">Distress model not applicable (financial company or no debt)</span>'}</p>
    <div class="sec-t">What moved the Technical view most</div><div>${ctx.driversHtml(t.drv, 5) || '<span class="mut">—</span>'}</div>
    <p class="mut">From the nightly model run, ${esc((ctx.S.aladin || {}).as_of || "")}.</p>`;
}
function sentTab() {
  const { esc } = ctx, sym = cur.id, s = ((ctx.S.sentiment || {}).stocks || {})[sym];
  const items = s && s.items ? s.items.slice(0, 6).map(i => `<li>${esc(i[0])} <span class="mut">· ${esc(i[2])}</span></li>`).join("") : "";
  const evs = (ctx.S.sweepEv || []).filter(e => e.sym === sym).slice(-5).reverse();
  return `<div class="sec-t">Sentiment</div>${s ? `<p><b>${esc(s.lvl)}</b> · score ${s.sc > 0 ? "+" : ""}${Math.round(s.sc)} · ${s.n} headline${s.n === 1 ? "" : "s"}</p><ul class="nx-ul">${items}</ul>` : '<p class="mut">No headline matched in the last 72 hours.</p>'}
    <div class="sec-t">Liquidity sweeps</div>${evs.length ? evs.map(e => `<p>${e.dir > 0 ? "▲" : "▼"} ${esc(e.lvl)} at ${Number(e.px).toFixed(2)} · volume ${Number(e.rvol).toFixed(1)}× normal · ${e.confirmed ? "confirmed" : "forming"}</p>`).join("") : '<p class="mut">No sweep seen. Sweeps need the local tick program running on your PC.</p>'}`;
}
function sourcesTab() {
  const { esc } = ctx, sym = cur.id, es = edgesOf(sym);
  const fac = Object.entries(graph.fac || {}).filter(([, f]) => f.co === sym);
  const li = es.map(e => `<li><b>${esc(lab(e.s))} → ${esc(lab(e.d))}</b> (${esc(REL[e.rel] || e.rel)}) · ${esc(e.per || "—")} · conf ${e.conf.toFixed(2)} · ${esc(e.doc)} p.${e.pg} · <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">source</a><br><span class="mut">“${esc(e.q)}”</span></li>`).join("");
  const lf = fac.map(([id, f]) => `<li><b>${esc(f.n)}</b> (${esc(f.kind)}) · p.${f.pg} · <a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">source</a><br><span class="mut">“${esc(f.q)}”</span></li>`).join("");
  return `<p class="mut">${esc(covLine(sym))}</p><div class="sec-t">Links</div>${li ? `<ul class="nx-ul">${li}</ul>` : '<p class="mut">None.</p>'}<div class="sec-t">Facilities named in filings</div>${lf ? `<ul class="nx-ul">${lf}</ul>` : '<p class="mut">None.</p>'}`;
}

/* ---------- the graph ---------- */
function chainTab() {
  const { esc } = ctx, sym = cur.id;
  const ctl = `<div class="controls nx-ctl"><label>Depth <select id="nx-tier"><option value="1" ${gst.tier === 1 ? "selected" : ""}>Tier 1</option><option value="2" ${gst.tier === 2 ? "selected" : ""}>Tier 2</option><option value="3" ${gst.tier === 3 ? "selected" : ""}>Tier 3</option></select></label>
    <label>Show <select id="nx-side"><option value="both" ${gst.side === "both" ? "selected" : ""}>Suppliers and customers</option><option value="suppliers" ${gst.side === "suppliers" ? "selected" : ""}>Suppliers</option><option value="customers" ${gst.side === "customers" ? "selected" : ""}>Customers</option></select></label>
    <label class="nx-chk"><input type="checkbox" id="nx-low" ${gst.low ? "checked" : ""}> Include low-confidence links</label>
    <span class="seg"><button class="${gst.view === "graph" ? "on" : ""}" data-nx-view="graph">Graph</button><button class="${gst.view === "table" ? "on" : ""}" data-nx-view="table">Table</button></span></div>`;
  const g = buildGraph(sym);
  if (!g.edges.length) return `${ctl}<p class="note">Not measured: no dependency of ${esc(sym)} is disclosed in the filings read so far. ${esc(covLine(sym))} Deeper tiers: not disclosed.</p>`;
  const note = `<p class="mut">Left: suppliers. Right: customers. Line width = disclosed share; gold ring = at least 10%; dashed = low confidence; hollow = unlisted or unnamed. ${g.more ? `${g.more} more not drawn. ` : ""}Beyond what listed companies disclose: not disclosed.</p>`;
  return ctl + (gst.view === "graph" ? `<div class="nx-gwrap"><canvas id="nx-canvas" aria-hidden="true"></canvas><div class="nx-tip" id="nx-tip" hidden></div></div>${note}` : "") + tableOf(g, sym);
}
function buildGraph(focal) {
  const MAX = 120, lvl = new Map([[focal, 0]]);
  const ok = e => (gst.low || e.conf >= minConf()) && e.kind !== "sector_io";
  let frontier = [focal];
  for (let d = 1; d <= gst.tier; d++) {
    const next = [];
    for (const nid of frontier) {
      const L = lvl.get(nid);
      for (const e of edgesOf(nid)) {
        if (!ok(e)) continue;
        const upstream = e.d === nid, other = upstream ? e.s : e.d, side = Math.sign(L);
        if (nid !== focal && ((side < 0 && !upstream) || (side > 0 && upstream))) continue;      // keep going the same way as the node was reached
        if (nid === focal && ((gst.side === "suppliers" && !upstream) || (gst.side === "customers" && upstream))) continue;
        if (lvl.has(other)) continue;
        if (lvl.size >= MAX) continue;
        lvl.set(other, upstream ? L - 1 : L + 1);
        const n = nodeOf(other);
        if (n && n.k === "co") next.push(other);
      }
    }
    frontier = next;
  }
  const edges = graph.edges.filter(e => ok(e) && lvl.has(e.s) && lvl.has(e.d));
  let total = new Set();
  for (const e of graph.edges) if (ok(e) && (lvl.has(e.s) !== lvl.has(e.d))) total.add(lvl.has(e.s) ? e.d : e.s);
  return { lvl, edges, more: Math.max(0, lvl.size >= MAX ? total.size : 0) };
}
function tableOf(g, sym) {
  const { esc } = ctx;
  const rows = g.edges.slice().sort((p, q) => (q.w || 0) - (p.w || 0) || q.conf - p.conf).map(e => `<tr><td>${esc(lab(e.s))}</td><td>${esc(REL[e.rel] || e.rel)}</td><td>${esc(lab(e.d))}</td><td>${shareTxt(e)}</td><td class="r">${e.conf.toFixed(2)}</td><td>${esc(e.per || "—")}</td><td><button class="lnk" data-nexus="edge:${esc(e.id)}">evidence</button></td></tr>`).join("");
  return `<div class="tablecard${gst.view === "graph" ? " nx-alt" : ""}"><table class="tbl sm" aria-label="Supply chain of ${esc(sym)} as a table"><thead><tr><th>Supplier</th><th>Link</th><th>Customer</th><th>Share</th><th class="r">Conf</th><th>Period</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888";
function drawGraph(body) {
  const cv = body.querySelector("#nx-canvas");
  if (!cv) return;
  const focal = cur.id, g = buildGraph(focal), tip = body.querySelector("#nx-tip");
  const dpr = window.devicePixelRatio || 1, W = cv.parentElement.clientWidth || 560;
  const levels = new Map();
  for (const [id, L] of g.lvl) { if (!levels.has(L)) levels.set(L, []); levels.get(L).push(id); }
  const ks = [...levels.keys()].sort((a, b) => a - b), rowMax = Math.max(...[...levels.values()].map(v => v.length));
  const H = Math.max(260, Math.min(720, 60 + rowMax * 34));
  cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + "px"; cv.style.height = H + "px";
  const c = cv.getContext("2d"); c.scale(dpr, dpr); c.clearRect(0, 0, W, H);
  const pos = new Map(), colW = ks.length > 1 ? (W - 120) / (ks.length - 1) : 0;
  ks.forEach((L, i) => { const ids = levels.get(L).sort((a, b) => nameOf(a).localeCompare(nameOf(b))); ids.forEach((id, j) => pos.set(id, { x: ks.length > 1 ? 60 + i * colW : W / 2, y: (j + 1) * H / (ids.length + 1) })); });
  const acc = css("--acc"), gold = css("--gold"), ink = css("--ink-2"), ink4 = css("--ink-4"), rule = css("--rule-2"), down = css("--down"), card = css("--card");
  g.hit = [];
  for (const e of g.edges) {
    const a = pos.get(e.s), b = pos.get(e.d);
    c.beginPath(); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y);
    c.strokeStyle = e.w != null && e.w >= 0.10 ? gold : rule; c.lineWidth = 1 + (e.w || 0) * 8; c.setLineDash(e.conf < minConf() ? [4, 4] : []); c.stroke(); c.setLineDash([]);
    if (e.w != null && e.w >= 0.10) { c.fillStyle = gold; c.font = "10px sans-serif"; c.fillText(`${Math.round(e.w * 100)}% · conf ${e.conf.toFixed(1)}`, (a.x + b.x) / 2 - 20, (a.y + b.y) / 2 - 4); }
  }
  const items = [];
  for (const [id, p] of pos) {
    const n = nodeOf(id), listed = n && n.k === "co", r = id === focal ? 11 : 7;
    c.beginPath(); c.arc(p.x, p.y, r, 0, 7);
    if (listed || id === focal) { c.fillStyle = id === focal ? acc : ink; c.fill(); } else { c.fillStyle = card; c.fill(); c.strokeStyle = n && n.k === "anon" ? down : ink4; c.lineWidth = 1.5; c.stroke(); }
    c.fillStyle = ink; c.font = "11px sans-serif";
    const label = (listed ? id : (n ? n.n : id)) || id, t = label.length > 22 ? label.slice(0, 21) + "…" : label;
    const up = g.lvl.get(id) < 0;
    c.textAlign = up ? "left" : p.x > W - 100 ? "right" : "left";
    if (up) c.fillText(t, Math.max(4, p.x - r), p.y - r - 5); else c.fillText(t, p.x + (p.x > W - 100 ? -r - 4 : r + 4), p.y + 4);
    items.push({ id, x: p.x, y: p.y, r: r + 4 });
  }
  const at = (mx, my) => items.find(i => (i.x - mx) ** 2 + (i.y - my) ** 2 <= i.r * i.r * 1.6);
  cv.onmousemove = ev => {
    const rc = cv.getBoundingClientRect(), it = at(ev.clientX - rc.left, ev.clientY - rc.top);
    cv.style.cursor = it ? "pointer" : "default";
    if (!it) { tip.hidden = true; return; }
    const ed = g.edges.filter(e => e.s === it.id || e.d === it.id).sort((p, q) => (q.w || 0) - (p.w || 0))[0];
    const n = nodeOf(it.id);
    tip.innerHTML = `<b>${ctx.esc((n && n.n) || it.id)}</b><br><span class="mut">${ctx.esc(KIND[(n || {}).k] || "")}</span>${ed ? `<br>“${ctx.esc(ed.q.length > 150 ? ed.q.slice(0, 149) + "…" : ed.q)}”` : ""}`;
    tip.hidden = false; tip.style.left = Math.min(ev.clientX - rc.left + 12, W - 240) + "px"; tip.style.top = (ev.clientY - rc.top + 12) + "px";
  };
  cv.onmouseleave = () => { tip.hidden = true; };
  cv.onclick = ev => {
    const rc = cv.getBoundingClientRect(), it = at(ev.clientX - rc.left, ev.clientY - rc.top);
    const n = it && nodeOf(it.id);
    if (it && it.id !== focal && n && n.k === "co") openNexus({ type: "company", id: it.id, tab: "chain" });
  };
}

/* ---------- edge and facility ---------- */
function edgePanel() {
  const { esc } = ctx, e = graph.edges.find(x => x.id === cur.id);
  if (!e) return '<p class="note">This dependency is not in the current supply-chain data.</p>';
  const s = ((shocks || {}).shocks || []).find(x => x.edge === e.id);
  const end = id => { const n = nodeOf(id); return n && n.k === "co" ? `<button class="lnk" data-nexus="company:${esc(id)}">${esc(id)}</button> ${esc(nameOf(id))} ${move(id)}` : `${esc((n && n.n) || id)} <span class="mut">${esc(KIND[(n || {}).k] || "")}</span>`; };
  return `<table class="tbl sm"><tbody><tr><th>Supplier</th><td>${end(e.s)}</td></tr><tr><th>Customer</th><td>${end(e.d)}</td></tr><tr><th>Link</th><td>${esc(REL[e.rel] || e.rel)}${e.comp ? ` · ${esc(e.comp)}` : ""}</td></tr>
    <tr><th>Share</th><td>${shareTxt(e)}${derivedNote(e) ? `<div class="mut">${esc(derivedNote(e))}</div>` : ""}</td></tr><tr><th>Period</th><td>${esc(e.per || "—")}</td></tr><tr><th>Confidence</th><td>${e.conf.toFixed(2)} <span class="mut">(quote verified 0.5, counterparty named 0.2, share stated 0.2, period recent 0.1)</span></td></tr>
    <tr><th>Read from</th><td>${esc(e.doc)} · page ${e.pg} · <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">source</a></td></tr></tbody></table>
    <div class="sec-t">Quote</div><blockquote class="nx-quote">“${esc(e.q)}”</blockquote>
    ${s ? `<p>Counterparty ${esc(s.cp)}: 5-day beta-adjusted move ${s.dr > 0 ? "+" : ""}${s.dr} % pts; it moved ${s.cp_ret == null ? "—" : (s.cp_ret * 100).toFixed(1) + "%"} on the day, and ${esc(s.focal)} ${s.focal_ret == null ? "—" : (s.focal_ret * 100).toFixed(1) + "%"}.</p>` : ""}
    <p class="mut">A linked move is an association, not proof of cause. Model estimate only.</p>`;
}
function facilityPanel() {
  const { esc } = ctx, f = graph.fac[cur.id];
  if (!f) return '<p class="note">This facility is not in the current supply-chain data.</p>';
  const nd = "<span class=\"mut\">Not disclosed</span>";
  const loc = f.lat != null ? `${f.lat.toFixed(3)}, ${f.lon.toFixed(3)} · ${esc(GEO_PREC[f.geo_prec] || "Approximate")}` : '<span class="mut">Not located yet (the filing gives no usable address)</span>';
  const eq = (f.eq || []).length ? `<table class="tbl sm"><thead><tr><th>Item</th><th>Vendor</th><th>Quote</th></tr></thead><tbody>${f.eq.map(x => `<tr><td>${esc(x.item)}</td><td>${esc(x.vendor || "Not disclosed")}</td><td class="mut">“${esc(x.q)}”</td></tr>`).join("")}</tbody></table>` : nd;
  const linked = edgesOf(f.co).slice(0, 8);
  return `<table class="tbl sm"><tbody><tr><th>Operator</th><td><button class="lnk" data-nexus="company:${esc(f.co)}">${esc(f.co)}</button> ${esc(nameOf(f.co))}</td></tr><tr><th>Kind</th><td>${esc(f.kind)}</td></tr><tr><th>Location</th><td>${loc}</td></tr>
    <tr><th>Products</th><td>${(f.prod || []).length ? esc(f.prod.join(", ")) : nd}</td></tr>
    <tr><th>Capacity</th><td>${f.cap && f.cap.v != null ? `${esc(f.cap.v)} ${esc(f.cap.u || "")} <span class="mut">“${esc(f.cap.q)}”</span>` : nd}</td></tr>
    <tr><th>Utilisation</th><td>${f.util && f.util.pct != null ? `${esc(f.util.pct)}% (${esc(f.util.per || "period not stated")}) <span class="mut">“${esc(f.util.q)}”</span>` : nd}</td></tr></tbody></table>
    <div class="sec-t">Equipment lineage</div>${eq}
    <div class="sec-t">Operator's disclosed links</div>${linked.length ? `<ul class="nx-ul">${linked.map(e => `<li><button class="lnk" data-nexus="edge:${esc(e.id)}">${esc(lab(e.s))} → ${esc(lab(e.d))}</button> · ${shareTxt(e)}</li>`).join("")}</ul>` : '<p class="mut">None.</p>'}
    <p class="mut">Read from the filing, page ${f.pg} · <a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">source</a>: “${esc(f.q)}”</p>`;
}
