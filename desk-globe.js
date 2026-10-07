/* Globe tab, second view: a D3 orthographic globe (or a flat Natural Earth map) drawn on a canvas, with the NEXUS layers: geopolitical hotspots, chokepoints with
   the vessel count inside each, cargo flights, other flights, vessels, plants named in filings, and trade lanes. The 3D globe is what the tab opens on (the last choice is remembered); "Map" is the existing Leaflet map.
   The D3 libraries (d3-geo, topojson-client, d3-quadtree, world-atlas, all pinned) load from jsDelivr only when someone switches to Globe or Flat.
   Data files (trade_lanes.json, telemetry.json, supply_graph.json, geo.json) load lazily the first time a non-Map view opens. Positions come from one workflow
   snapshot (or, on the PC running the local daemon, from its live telemetry messages). Each marker is moved along its reported course from its own fix time,
   and drawn as a faint ghost once its fix is older than the extrapolation cap: from then on nobody knows where it is. A flight's callsign prefix says who operates it, never what it carries.
   Click or tap anything: it opens the same NEXUS panel as everywhere else. "List" is the keyboard and screen-reader equivalent of the canvas.
   Speed: the entity list is built once per data or layer change, not per frame; the globe projects points with its own orthographic formula (one sine and cosine per
   point); same-style points are drawn as one batched path; the canvas is only resized when its size really changed.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. */
import * as G3 from "./desk-globe3d.js";
import * as GL from "./desk-globe-layers.js";
import { extrapolate, flightKin, vesselKin, docFromFull, applyTelemetry, ageLabel, CAPS } from "./desk-kin.js";
import { onTelemetry } from "./desk-ticks.js";
import { MAP_COLORS, hotspotColor, hotspotRadius, isStale, ageMin, ageText, countIn, filterItems, mergeLayers } from "./desk-lanes.js";

const D3 = { geo: "https://cdn.jsdelivr.net/npm/d3-geo@3.1.1/+esm", topo: "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/+esm", qt: "https://cdn.jsdelivr.net/npm/d3-quadtree@3.0.1/+esm",
  world: "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json" };
const LS = "blab.globe.layers";
const LAYERS = [["hot", "Geopolitical news attention", true], ["choke", "Chokepoints", true], ["cargo", "Cargo flights", true], ["air", "Other flights", false], ["ship", "Vessels", true], ["plant", "Plants (filings)", true], ["lane", "Trade lanes", true], ...GL.EXTRA];
const DEFAULTS = Object.fromEntries(LAYERS.map(([k, , d]) => [k, d]));
const MAX_LIST = 300, RAD = Math.PI / 180;

let manWaited = false, ctx = null, mounted = false, mode = "map", lib = null, libFailed = null, loadingLib = null, loadingData = null;
let layers = { ...DEFAULTS }, listQ = "", interacting = false, settleT = 0;
const data = { lanes: null, transport: null, graph: null };
const store = {};                                                  // globe/layers/*.json (cables, shipping lanes, power plants, company facilities): read only when their layer is on
let base = "dark";
let baseNote = "";
let c2d = null, gl = null, g3 = null, g3Failed = null, engine = "d3", follow = false;
let canvas = null, g2 = null, tip = null, W = 0, H = 0, dpr = 1, proj = null, pathGen = null, ro = null;
let rot = [-78, -18], zoom = 1, pan = [0, 0], items = [], qtree = null, qDirty = true, raf = 0, press = null, moved = 0, ents = null, colors = null, colorsKey = null;

export function init(c) { ctx = c; onTelemetry(onLive); try { layers = mergeLayers(DEFAULTS, JSON.parse(localStorage.getItem(LS))); } catch (e) { /* stored switches are only a convenience */ } try { base = localStorage.getItem("blab.globe.base") || "dark"; if (!GL.BASES.some(b => b[0] === base)) base = "dark"; } catch (e) { /* default base */ } }
const files = () => ctx.S.deskMan || {};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888";
const saveLayers = () => { try { localStorage.setItem(LS, JSON.stringify(layers)); } catch (e) { /* ignore */ } };

/* ---------- mounting: the bar sits above the Leaflet map; nothing else loads until a non-Map view is chosen ---------- */
export function mount() {
  if (mounted || !ctx) return;
  const bar = ctx.$("#gd-bar"); if (!bar) return;
  mounted = true;
  bar.innerHTML = `<div class="seg" id="gd-mode" role="group" aria-label="Map style"><button data-m="map" aria-pressed="true" class="on">Map</button><button data-m="globe" aria-pressed="false">Globe</button><button data-m="flat" aria-pressed="false">Flat</button><button data-m="list" aria-pressed="false">List</button></div>
    <button class="btn-line sm" id="gd-follow" hidden aria-pressed="false">Follow</button>
    <div class="gd-layers" id="gd-layers" hidden></div><div class="gd-chips" id="gd-chips"></div>`;
  bar.addEventListener("click", e => { const m = e.target.closest("[data-m]"); if (m) setMode(m.dataset.m); if (e.target.closest("#gd-follow")) toggleFollow(); });
  bar.addEventListener("change", e => {
    const b = e.target.dataset && e.target.dataset.base;
    if (b) { base = b; try { localStorage.setItem("blab.globe.base", b); } catch (err) { /* ignore */ } if (g3 && engine === "3d") g3.setBase(b); chips(); return; }
    const k = e.target.dataset && e.target.dataset.layer;
    if (k) { layers[k] = e.target.checked; saveLayers(); ents = null; legend(); render(); GL.loadFiles(layers, store, ctx.getJSON).then(() => { ents = null; legend(); render(); }); }
  });
  const wrap = ctx.$("#gd-wrap");
  canvas = c2d = ctx.$("#gd-canvas"); tip = ctx.$("#gd-tip");
  if (wrap && canvas) {
    Object.defineProperty(canvas, "_items", { get: () => items.map(i => ({ x: i.x, y: i.y, type: i.e.type, id: i.e.id, kind: i.e.kind })) });     // read only by the browser tests, built on demand
    canvas.addEventListener("pointerdown", e => { press = { x: e.clientX, y: e.clientY }; moved = 0; try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointers cannot be captured */ } });
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", () => { if (tip) tip.hidden = true; });
    canvas.addEventListener("wheel", e => { e.preventDefault(); zoom = Math.max(0.8, Math.min(6, zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12))); moving(); }, { passive: false });
    gl = ctx.$("#gd-gl");
    if (gl) Object.defineProperty(gl, "_items", { get: () => (g3 ? g3.listPts.map(i => ({ x: i.x, y: i.y, type: i.type, id: i.id, kind: i.kind })) : []) });
    ro = new ResizeObserver(() => { if (engine === "3d" && g3) g3.resize(); else if (mode === "globe" || mode === "flat") schedule(); });
    ro.observe(wrap);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) schedule(); });
  chips();
  let first = "globe";                                                  // the 3D globe is what the tab opens on; the choice made last time wins
  try { first = localStorage.getItem("blab-map-mode") || first; } catch (err) { /* default */ }
  if (!["map", "globe", "flat", "list"].includes(first)) first = "globe";
  if (first !== "map") setMode(first);
}

function setMode(m) {
  if (!ctx || m === mode) return;
  mode = m;
  try { localStorage.setItem("blab-map-mode", m); } catch (err) { /* private window: the choice is simply not remembered */ }
  ctx.$$("#gd-mode button").forEach(b => { const on = b.dataset.m === m; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  if (m === "map" || m === "list") { if (g3) g3.close(); engine = "d3"; setCanvas("d3"); }
  const leaflet = ctx.$("#globe-map"), wrap = ctx.$("#gd-wrap"), list = ctx.$("#gd-list");
  if (leaflet) leaflet.hidden = m !== "map";
  if (wrap) wrap.hidden = !(m === "globe" || m === "flat");
  if (list) list.hidden = m !== "list";
  ctx.$("#gd-layers").hidden = m === "map";
  if (m === "map") { ctx.resizeGlobe && ctx.resizeGlobe(); chips(); return; }
  paintLayerBox();
  ensureData().then(() => { ents = null; chips(); paintLayerBox(); render(); });
  if (m === "globe" || m === "flat") ensureLib().then(() => start3d(m)).then(() => render());
}

/* ---------- the WebGL engine (desk-globe3d.js, three.js imported only now) with the D3 canvas as the fallback ---------- */
/* the canvas that is on screen carries the id gd-canvas (the browser tests and the page look for that one) */
function setCanvas(which) {
  const two = c2d, three = gl;                                  // both elements were captured at mount: looking them up by id would find the wrong one after a swap
  if (!two || !three) return;
  two.id = which === "3d" ? "gd-canvas-2d" : "gd-canvas"; three.id = which === "3d" ? "gd-canvas" : "gd-gl";
  two.hidden = which === "3d"; three.hidden = which !== "3d";
  if (which !== "3d") canvas = two;
}
async function start3d(m) {
  if (!lib) return fall3d(libFailed || "the map library did not load");
  if (g3Failed || !G3.webglOk()) return fall3d(g3Failed || "WebGL is not available in this browser");
  try {
    if (!g3) {
      g3 = await G3.create({ canvas: gl, wrap: ctx.$("#gd-wrap"), ctx, lib, hooks: {
        pick: e => pickEntity(e), baseOk: () => chips(), baseFail: (k, why) => { baseNote = `The ${k === "sat" ? "Satellite" : "Streets"} base could not load (${why}); showing Dark.`; base = "dark"; paintLayerBox(); chips(); },
        hover: (e, x, y) => { if (!tip) return; if (!e) { tip.hidden = true; return; } tip.innerHTML = `<b>${ctx.esc(e.name)}</b><br><span class="mut">${ctx.esc(e.type)} · ${ctx.esc(detailOf(e))}</span>`; tip.hidden = false; tip.style.left = Math.min(x + 12, (g3.W || 600) - 230) + "px"; tip.style.top = Math.max(4, y + 12) + "px"; },
        select: id => { const b = ctx.$("#gd-follow"); if (b) { b.hidden = !id; if (!id) { follow = false; b.setAttribute("aria-pressed", "false"); b.classList.remove("on"); } } },
        follow: on => { follow = on; const b = ctx.$("#gd-follow"); if (b) { b.setAttribute("aria-pressed", String(on)); b.classList.toggle("on", on); } },
        governor: () => chips(),
        lost: () => { g3Failed = "the graphics context was lost"; fall3d(g3Failed); },
      } });
    }
    engine = "3d"; setCanvas("3d"); gl.__g3 = g3;                       // (the browser tests read g3.stats())
    g3.open(m); g3.setBorders(layers.border); if (base !== "dark") g3.setBase(base);
    chips();
  } catch (e) { fall3d(String((e && e.message) || e).slice(0, 80)); }
}
function fall3d(reason) {
  g3Failed = reason; engine = "d3"; if (g3) { try { g3.close(); } catch (e) { /* already gone */ } }
  setCanvas("d3"); chips(); schedule();
}
function toggleFollow() { if (!g3) return; follow = !follow; g3.setFollow(follow); const b = ctx.$("#gd-follow"); if (b) { b.setAttribute("aria-pressed", String(follow)); b.classList.toggle("on", follow); } }

/* ---------- data (lazy) and libraries (lazy) ---------- */
function ensureData() {
  if (loadingData) return loadingData;
  if (!Object.keys(files()).length && !manWaited) {                       // the list of data files has not arrived yet: wait for it (up to 10 s) instead of caching "nothing to load"
    return loadingData = new Promise(res => { let n = 0; const t = setInterval(() => { if (Object.keys(files()).length || ++n > 40) { clearInterval(t); manWaited = true; loadingData = null; res(ensureData()); } }, 250); });
  }
  const one = (key, file, set) => files()[key] ? ctx.getJSON(file, key === "telemetry").then(set).catch(() => { }) : Promise.resolve();
  loadingData = Promise.all([
    GL.loadFiles(layers, store, ctx.getJSON),
    one("lanes", "trade_lanes.json", j => { data.lanes = j; }),
    one("telemetry", "telemetry.json", j => { data.transport = j; ctx.S.transport = j; }),
    one("graph", "supply_graph.json", j => { data.graph = j; }),
    ctx.S.geo || !files().geo ? 0 : ctx.getJSON("geo.json").then(j => { ctx.S.geo = j; }).catch(() => { }),
  ]).finally(() => { setTimeout(() => { loadingData = null; }, 60000); });                // re-read the snapshot at most once a minute
  return loadingData;
}
function ensureLib() {
  if (lib || libFailed) return Promise.resolve(lib);
  loadingLib = loadingLib || Promise.all([import(D3.geo), import(D3.topo), import(D3.qt), fetch(D3.world).then(r => { if (!r.ok) throw new Error("world map " + r.status); return r.json(); })])
    .then(([geo, topo, qt, world]) => { lib = { geo, qt, land: topo.feature(world, world.objects.land), countries: topo.feature(world, world.objects.countries), india: null }; lib.india = lib.countries.features.find(f => String(f.id) === "356") || null; })
    .catch(e => { libFailed = e.message || "could not load"; });
  return loadingLib;
}

/* ---------- the entities every view shows (built once per data or layer change) ---------- */
function regions() { return ((ctx.S.geo || {}).regions || []).filter(r => r.lat != null && r.lon != null); }
const geom = e => { e.la = e.lat * RAD; e.lo = e.lon * RAD; e.sl = Math.sin(e.la); e.cl = Math.cos(e.la); return e; };
function build() {
  const out = [], T = data.transport;
  if (layers.hot) for (const r of regions()) out.push(geom({ layer: "hot", type: "hotspot", id: r.id, name: r.name, row: r, lat: r.lat, lon: r.lon, score: r.score, kind: r.kind }));
  if (layers.choke && data.lanes) for (const c of data.lanes.chokepoints) {
    const n = T && T.vessels ? countIn(T.vessels, c.bbox) : null;
    out.push(geom({ layer: "choke", type: "chokepoint", id: c.id, name: c.name, row: c, lat: c.lat, lon: c.lon, bbox: c.bbox, count: n }));
  }
  if (T) for (const f of T.flights || []) {
    const cargo = f[9] === 1;
    if ((cargo && layers.cargo) || (!cargo && layers.air)) out.push(geom({ layer: cargo ? "cargo" : "air", type: "flight", id: f[0], name: f[1] || f[0], row: f, lat: f[2], lon: f[3], hdg: f[6], kin: flightKin(f), cap: CAPS.flight }));
  }
  if (layers.ship && T && T.vessels) for (const v of T.vessels) out.push(geom({ layer: "ship", type: "vessel", id: String(v[0]), name: v[1] || String(v[0]), row: v, lat: v[2], lon: v[3], hdg: v[5] != null ? v[5] : v[6], kin: vesselKin(v), cap: CAPS.vessel }));
  if (layers.plant && data.graph) for (const [id, f] of Object.entries(data.graph.fac || {})) if (f.lat != null) out.push(geom({ layer: "plant", type: "facility", id, name: f.n, row: f, lat: f.lat, lon: f.lon, prec: f.geo_prec }));
  out.push(...GL.entities(layers, store, ctx.S.globe));
  return out;
}
const entities = () => ents || (ents = build());
function detailOf(e) {                                                   // text is made only when someone looks at it (tooltip, list), never per frame
  if (GL.EXTRA_TYPES.has(e.type)) return GL.detail(e);
  const r = e.row;
  if (e.type === "hotspot") return `${r.kind || "region"} · ${r.score == null ? "building baseline" : r.level + " " + r.score}`;
  if (e.type === "chokepoint") return e.count == null ? "vessel count not available" : `${e.count} vessel${e.count === 1 ? "" : "s"} in the snapshot`;
  if (e.type === "flight") return `${r[8] || "origin country unknown"} · ${r[4] == null ? "altitude n/a" : Math.round(r[4]) + " m"}`;
  if (e.type === "vessel") return r[8] ? "to " + r[8] : "destination not broadcast";
  return `${r.co} · ${r.geo_prec === "exact" ? "exact location" : "approximate (" + (r.geo_prec || "?") + ")"}`;
}

/* ---------- the bar ---------- */
function paintLayerBox() {
  const T = data.transport;
  const bases = `<div class="gd-bases" role="radiogroup" aria-label="Base map">${GL.BASES.map(([k, l]) => `<label class="nx-chk"><input type="radio" name="gd-base" data-base="${k}" ${base === k ? "checked" : ""}> ${l}</label>`).join("")}</div>`;
  ctx.$("#gd-layers").innerHTML = bases + LAYERS.map(([k, l]) => {
    const off = k === "ship" && T && !T.vessels;
    return `<label class="nx-chk" ${off ? `title="${ctx.esc(T.reason || T.vessels_reason || "No vessel feed")}"` : ""}><input type="checkbox" data-layer="${k}" ${layers[k] ? "checked" : ""} ${off ? "disabled" : ""}> ${l}</label>`;
  }).join("");
}
/* the legend of the standard Map (same chips), for what the 3D globe and the flat canvas draw; only the layers that are switched on */
function legend() {
  const el = ctx.$("#gd-legend"); if (!el) return;
  const dot = (c, shape) => `<i style="background:${c};${shape === "sq" ? "border-radius:2px;" : shape === "dia" ? "border-radius:1px;transform:rotate(45deg);" : ""}"></i>`;
  const ring = c => `<i style="background:none;border:1.5px solid ${c};box-sizing:border-box"></i>`;
  const rows = [];
  if (layers.hot) rows.push([dot("var(--down)"), "News hotspot (red = high)"], [dot("var(--ink-4)", "dia"), "Chokepoint hotspot"]);
  if (layers.choke) rows.push([dot("var(--acc)", "sq"), "Chokepoint"]);
  if (layers.air) rows.push([dot(MAP_COLORS.air), "Live flight"]);
  if (layers.cargo) rows.push([dot(MAP_COLORS.cargo), "Freighter flight"]);
  if (layers.ship) rows.push([dot(MAP_COLORS.ship, "sq"), "Vessel"]);
  if (layers.plant) rows.push([dot("var(--acc)"), "Plant (exact)"], [ring("var(--acc)"), "Plant (approximate)"]);
  if (layers.lane) rows.push([`<i style="background:${MAP_COLORS.lane};height:2px;border-radius:0"></i>`, "Trade lane"]);
  for (const [c, label, kind] of GL.legendRows(layers)) rows.push([kind === "line" ? `<i style="background:${c};height:2px;border-radius:0"></i>` : dot(c), label]);
  el.innerHTML = rows.map(([sw, label]) => `<span class="gl-item">${sw}${ctx.esc(label)}</span>`).join("");
}
function chips() {
  legend();
  const el = ctx.$("#gd-chips"); if (!el) return;
  const T = data.transport;
  if (!T && !files().telemetry) { el.innerHTML = '<span class="gd-chip off">Flights and vessels: no snapshot published yet</span>'; return; }
  if (!T) { el.innerHTML = mode === "map" ? '<span class="gd-chip">Flights and vessels: open Globe, Flat or List to load the snapshot</span>' : '<span class="gd-chip">Loading the snapshot…</span>'; return; }
  const nowS = Date.now() / 1000, fs = (T.sources || {}).flights || {}, vs = (T.sources || {}).vessels;
  const newest = rows => rows && rows.length ? Math.max(...rows.map(r => r[r.length - 1])) : null;
  const fAge = newest(T.flights) == null ? null : nowS - newest(T.flights), vAge = newest(T.vessels) == null ? null : nowS - newest(T.vessels);
  const fOld = fAge == null || fAge > CAPS.flight, vOld = vAge == null || vAge > CAPS.vessel;
  const cad = T.cadence_s ? `refreshed about every ${ageLabel(T.cadence_s)}` : "refresh rate unknown";
  const nf = (T.flights || []).length, nc = (T.flights || []).filter(f => f[9] === 1).length;
  const live = T.live ? "LIVE · THIS PC · " : "";
  el.innerHTML = `<span class="gd-chip${fOld ? " stale" : ""}" title="${ctx.esc(fs.attribution || "")}">${live}Flights · ${ctx.esc(fs.name || "OpenSky")} · ${cad} · newest fix ${ctx.esc(ageLabel(fAge))} old · ${nf} aircraft (${nc} on freighter callsigns)${fOld ? " · positions not live" : ""}</span>
    <span class="gd-chip${T.vessels ? (vOld ? " stale" : "") : " off"}" title="${ctx.esc((vs && vs.attribution) || "")}">${T.vessels ? `${live}Vessels · ${ctx.esc((vs && vs.name) || "AIS")} · newest fix ${ctx.esc(ageLabel(vAge))} old · ${T.vessels.length} ships${vOld ? " · positions not live" : ""}` : "Vessels · layer off: " + ctx.esc(T.reason || T.vessels_reason || "no feed")}</span>`;
  el.insertAdjacentHTML("beforeend", extraChips());
}
/* the engine in use: a notice when WebGL is not available, and the governor's "Reduced detail" */
function extraChips() {
  const { esc } = ctx, out = [];
  if ((mode === "globe" || mode === "flat") && g3Failed) out.push(`<span class="gd-chip stale" title="${esc(g3Failed)}">Flat 2D map: the 3D globe could not start (${esc(g3Failed)})</span>`);
  if (baseNote) out.push(`<span class="gd-chip stale">${esc(baseNote)}</span>`);
  else if (base !== "dark" && engine !== "3d" && (mode === "globe" || mode === "flat")) out.push(`<span class="gd-chip">Satellite and Streets base maps need the 3D globe; this view shows Dark.</span>`);
  if (engine === "3d" && g3 && g3.gov.reduced) out.push(`<span class="gd-chip stale" title="The frame rate dropped, so ${g3.gov.name === "no_trails" ? "trails are off" : g3.gov.name === "cap_2000" ? "trails are off and at most 2,000 markers are drawn" : "trails are off, at most 2,000 markers are drawn and the sharpness is lowered"}; it steps back up after 10 s of smooth frames">Reduced detail</span>`);
  return out.join("");
}

/* messages from the local daemon (only arrive on the PC running it): a full snapshot, then deltas. The public snapshot is ignored while they flow. */
let liveDoc = null, redrawT = 0;
function onLive(m) {
  if (!ctx || m.type !== "telemetry") return;
  liveDoc = m.full || !liveDoc ? docFromFull(m) : applyTelemetry(liveDoc, m);
  data.transport = liveDoc; ctx.S.transport = liveDoc; ents = null;
  if (mounted) { paintLayerBox(); render(); }
  if (!redrawT) redrawT = setInterval(() => { if (mounted && !document.hidden && (mode === "globe" || mode === "flat")) schedule(); }, 1000);   // markers glide between reports
}
const liveNow = () => !!liveDoc && Date.now() / 1000 - liveDoc.lastMsgAt < 180;

/* ---------- rendering ---------- */
function render() {
  chips();
  if (mode === "list") return renderList();
  if (engine === "3d" && g3 && (mode === "globe" || mode === "flat")) { g3.setLines(GL.lineSets(layers, store)); g3.setBorders(layers.border); g3.sync(entities(), data.lanes, layers); return; }
  if (mode === "globe" || mode === "flat") schedule();
}
/* called while the viewer is dragging or zooming */
function moving() { interacting = true; clearTimeout(settleT); settleT = setTimeout(() => { interacting = false; schedule(); }, 180); schedule(); }
function schedule() { if (raf) return; raf = requestAnimationFrame(() => { raf = 0; if (!document.hidden) draw(); }); }

function size() {
  const wrap = canvas.parentElement, d = window.devicePixelRatio || 1;
  const w = Math.max(280, wrap.clientWidth || 600), h = Math.round(Math.min(Math.max(320, w * (mode === "flat" ? 0.52 : 0.72)), 720));
  if (w !== W || h !== H || d !== dpr || !g2) {                           // resizing a canvas clears it and reallocates its bitmap: only when it really changed
    W = w; H = h; dpr = d; canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); canvas.style.width = W + "px"; canvas.style.height = H + "px"; g2 = canvas.getContext("2d");
  }
  g2.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function palette() {
  const key = document.documentElement.getAttribute("data-theme") || "dark";
  if (colors && colorsKey === key) return colors;
  colorsKey = key;
  return (colors = { ocean: css("--card"), land: css("--sunken"), rule: css("--rule-2"), acc: css("--acc"), gold: css("--gold"), hot: css("--down"), quiet: css("--ink-4"), ink: css("--ink-2"), ink3: css("--ink-3") });
}
/* -> a function entity -> [x, y] | null. The globe uses the orthographic formula directly (the point is hidden when it is on the far side); the flat map asks D3. */
function projector() {
  const { geo } = lib;
  if (mode === "globe") {
    const lc = -rot[0] * RAD, pc = -rot[1] * RAD, sp = Math.sin(pc), cp = Math.cos(pc), R = Math.min(W, H) / 2 * 0.92 * zoom, cx = W / 2, cy = H / 2;
    proj = geo.geoOrthographic().rotate(rot).translate([cx, cy]).scale(R).clipAngle(90).precision(interacting ? 3 : 0.7);
    return e => { const dl = e.lo - lc, cd = Math.cos(dl); if (sp * e.sl + cp * e.cl * cd <= 0.001) return null; return [cx + R * e.cl * Math.sin(dl), cy - R * (cp * e.sl - sp * e.cl * cd)]; };
  }
  proj = geo.geoNaturalEarth1().rotate([-70, 0]).fitSize([W, H], { type: "Sphere" }).precision(interacting ? 3 : 0.7);
  const k = proj.scale(); proj.scale(k * zoom).translate([proj.translate()[0] + pan[0], proj.translate()[1] + pan[1]]);
  return e => { const p = proj([e.lon, e.lat]); return p && isFinite(p[0]) ? p : null; };
}

function draw() {
  if (!canvas) return;
  if (!lib) {
    if (libFailed && (mode === "globe" || mode === "flat")) { size(); g2.clearRect(0, 0, W, H); g2.fillStyle = css("--ink-3"); g2.font = "13px sans-serif"; g2.fillText("The map library could not be loaded (" + libFailed + "). The standard map and the List view still work.", 16, 28); }
    return;
  }
  size();
  const at = projector(), P = palette();
  pathGen = lib.geo.geoPath(proj, g2);
  g2.clearRect(0, 0, W, H);
  g2.beginPath(); pathGen({ type: "Sphere" }); g2.fillStyle = P.ocean; g2.fill();
  if (!interacting) { g2.strokeStyle = P.rule; g2.lineWidth = 1; g2.stroke(); }
  g2.beginPath(); pathGen(lib.land); g2.fillStyle = P.land; g2.fill();
  if (!interacting) { g2.strokeStyle = P.rule; g2.lineWidth = 0.6; g2.stroke(); }
  if (layers.border && lib.countries) { g2.beginPath(); pathGen({ type: "FeatureCollection", features: lib.countries.features }); g2.strokeStyle = P.ink3; g2.globalAlpha = 0.65; g2.lineWidth = 0.8; g2.stroke(); g2.globalAlpha = 1; }
  if (lib.india && !interacting) { g2.beginPath(); pathGen(lib.india); g2.strokeStyle = P.acc; g2.lineWidth = 1.2; g2.stroke(); }
  for (const set of GL.lineSets(layers, store)) {
    g2.beginPath(); for (const line of set.lines) pathGen({ type: "LineString", coordinates: line });
    g2.strokeStyle = set.color; g2.globalAlpha = set.alpha; g2.lineWidth = set.width * 0.8; g2.stroke(); g2.globalAlpha = 1;
  }
  if (layers.lane && data.lanes) for (const l of data.lanes.lanes) { g2.beginPath(); pathGen({ type: "LineString", coordinates: l.path }); g2.strokeStyle = MAP_COLORS.lane; g2.globalAlpha = 0.55; g2.lineWidth = 1; g2.setLineDash(l.kind === "air" ? [3, 4] : []); g2.stroke(); g2.setLineDash([]); g2.globalAlpha = 1; }

  const all = entities(), hit = [], air = [], ships = [], cargo = [];
  const nowS = Date.now() / 1000;
  for (const e of all) {
    if (e.kin) {                                                  // flights and vessels: where is it now, from its own fix time
      const k = extrapolate(e.kin, nowS, e.cap);
      if (k.lat !== e.lat || k.lon !== e.lon) { e.lat = k.lat; e.lon = k.lon; geom(e); }
      e.ghost = k.ghost; e.age = k.age;
    }
    const p = at(e); if (!p) continue;
    e.x = p[0]; e.y = p[1];
    if (e.layer === "air") { air.push(e); hit.push({ x: e.x, y: e.y, r: 4, e, i: hit.length }); }
    else if (e.layer === "ship") { ships.push(e); hit.push({ x: e.x, y: e.y, r: 4, e, i: hit.length }); }
    else if (e.layer === "cargo") { cargo.push(e); hit.push({ x: e.x, y: e.y, r: 6, e, i: hit.length }); }
  }
  for (const [a, pick] of [[1, e => !e.ghost], [0.3, e => e.ghost]]) {            // live markers solid, ghosts (older than the cap: position not live) faint
    const A = air.filter(pick), S = ships.filter(pick), C = cargo.filter(pick);
    // other flights: one batched path of small dots
    if (A.length) { g2.globalAlpha = a; g2.beginPath(); for (const e of A) { g2.moveTo(e.x + 1.7, e.y); g2.arc(e.x, e.y, 1.7, 0, 7); } g2.fillStyle = MAP_COLORS.air; g2.fill(); }
    // vessels: one batched path of small squares
    if (S.length) { g2.globalAlpha = a; g2.beginPath(); for (const e of S) g2.rect(e.x - 2.5, e.y - 2.5, 5, 5); g2.fillStyle = MAP_COLORS.ship; g2.fill(); }
    // cargo flights: little aircraft shapes pointing along their heading, one path
    if (C.length) {
      g2.globalAlpha = a; g2.beginPath();
      for (const e of C) { const h = (e.hdg || 0) * RAD, s = Math.sin(h), c = Math.cos(h), v = (px, py) => [e.x + px * c - py * s, e.y + px * s + py * c], A1 = v(0, -6), B = v(4, 5), C1 = v(0, 3), D = v(-4, 5); g2.moveTo(A1[0], A1[1]); g2.lineTo(B[0], B[1]); g2.lineTo(C1[0], C1[1]); g2.lineTo(D[0], D[1]); g2.closePath(); }
      g2.fillStyle = MAP_COLORS.cargo; g2.fill();
    }
  }
  g2.globalAlpha = 1;
  // the few big things on top: plants, chokepoints, hotspots
  for (const e of all) {
    if (e.type === "flight" || e.type === "vessel" || e.x == null || !at(e)) continue;
    const x = e.x, y = e.y; let r = 6;
    if (GL.EXTRA_TYPES.has(e.type)) {
      const c = e.type === "quake" ? GL.COLORS.quake : e.type === "natural" ? GL.COLORS.nat : e.type === "asset" ? GL.COLORS.asset : e.type === "powerplant" ? (GL.COLORS.fuel[e.fuel] || "#8a8a8a") : GL.COLORS.alert;
      r = e.type === "quake" ? Math.max(3, Math.min(10, (e.mag || 4.5) * 1.6)) : e.type === "powerplant" ? Math.max(2.5, Math.min(6, (e.mw || 100) / 400 + 2)) : 4.5;
      g2.beginPath();
      if (e.type === "natural" || e.type === "asset" || e.type === "disruption") { g2.moveTo(x, y - r); g2.lineTo(x + r, y); g2.lineTo(x, y + r); g2.lineTo(x - r, y); g2.closePath(); }
      else if (e.type === "alert") g2.rect(x - r, y - r, 2 * r, 2 * r); else g2.arc(x, y, r, 0, 7);
      if (e.type === "quake") { g2.globalAlpha = 0.35; g2.fillStyle = c; g2.fill(); g2.globalAlpha = 1; g2.strokeStyle = c; g2.lineWidth = 1.2; g2.stroke(); } else { g2.fillStyle = c; g2.fill(); }
    } else if (e.type === "facility") { g2.beginPath(); g2.arc(x, y, 4.5, 0, 7); if (e.prec === "exact") { g2.fillStyle = P.acc; g2.fill(); } else { g2.strokeStyle = P.acc; g2.lineWidth = 1.6; g2.stroke(); } r = 6; }
    else if (e.type === "chokepoint") {
      const b = e.bbox, A = at(geom({ lat: b[1], lon: b[0] })), C = at(geom({ lat: b[3], lon: b[2] }));
      if (A && C) { g2.strokeStyle = P.acc; g2.lineWidth = 1; g2.setLineDash([2, 2]); g2.strokeRect(Math.min(A[0], C[0]), Math.min(A[1], C[1]), Math.abs(C[0] - A[0]), Math.abs(C[1] - A[1])); g2.setLineDash([]); }
      g2.fillStyle = P.acc; g2.font = "10px sans-serif"; g2.textAlign = "left"; g2.fillText(e.count == null ? e.name : `${e.name} · ${e.count}`, x + 7, y - 6);
      g2.beginPath(); g2.rect(x - 3, y - 3, 6, 6); g2.fill(); r = 7;
    } else if (e.type === "hotspot") {
      r = hotspotRadius(e.score); g2.beginPath();
      if (e.kind === "chokepoint") { g2.moveTo(x, y - r); g2.lineTo(x + r, y); g2.lineTo(x, y + r); g2.lineTo(x - r, y); g2.closePath(); } else g2.arc(x, y, r, 0, 7);
      g2.fillStyle = hotspotColor(e.score, P.quiet, P.gold, P.hot); g2.globalAlpha = 0.75; g2.fill(); g2.globalAlpha = 1; g2.strokeStyle = P.ink; g2.lineWidth = 0.8; g2.stroke();
    }
    hit.push({ x, y, r: Math.max(r, 5), e, i: hit.length });
  }
  items = hit; qDirty = true;
  canvas.dataset.items = String(hit.length); canvas.dataset.mode = mode;
}

/* a click: the NEXUS panel for what it knows (flights, vessels, hotspots, chokepoints, plants named in filings); a small source card for hazards, power plants and company facilities */
function pickEntity(e) {
  if (!GL.EXTRA_TYPES.has(e.type)) { ctx.openNexus({ type: e.type, id: e.id }); return; }
  const wrap = ctx.$("#gd-wrap"); if (!wrap) return;
  let c = ctx.$("#gd-card"); if (!c) { c = document.createElement("div"); c.id = "gd-card"; c.className = "gd-card"; c.setAttribute("role", "dialog"); wrap.appendChild(c); c.addEventListener("click", ev => { if (ev.target.closest(".gd-card-x")) c.hidden = true; }); }
  c.innerHTML = GL.card(e, ctx.esc); c.hidden = false;
}

/* ---------- interaction: drag to rotate (or pan the flat map), wheel to zoom, click to open NEXUS ---------- */
/* the item under the pointer: every item whose reach (at least 8 px, 14 px for a finger, or its own radius) covers the point; the nearest wins, and where several sit
   on the same spot the one drawn last (on top) wins. Hotspots are drawn last of all, so a big hotspot can still be hit at its edge. */
function nearest(x, y, touch) {
  if (!items.length || !lib || !lib.qt) return null;
  if (qDirty) { qtree = lib.qt.quadtree().x(d => d.x).y(d => d.y).addAll(items); qDirty = false; }
  const rad = touch ? 14 : 8; let best = null, bd = Infinity;
  qtree.visit((node, x0, y0, x1, y1) => {
    if (!node.length) {
      let n = node;
      do {
        const d = n.data, dist = Math.hypot(d.x - x, d.y - y);
        if (dist <= Math.max(rad, d.r) && (best === null || dist < bd - 1 || (Math.abs(dist - bd) <= 1 && d.i > best.i))) { best = d; bd = dist; }
        n = n.next;
      } while (n);
    }
    return x0 > x + 24 || x1 < x - 24 || y0 > y + 24 || y1 < y - 24;
  });
  return best && best.e;
}
function onMove(ev) {
  const rc = canvas.getBoundingClientRect(), x = ev.clientX - rc.left, y = ev.clientY - rc.top;
  if (press) {
    const dx = ev.clientX - press.x, dy = ev.clientY - press.y; moved += Math.abs(dx) + Math.abs(dy);
    if (mode === "globe") { rot = [rot[0] + dx * 0.35 / zoom, Math.max(-80, Math.min(80, rot[1] - dy * 0.35 / zoom))]; } else { pan = [pan[0] + dx, pan[1] + dy]; }
    press = { x: ev.clientX, y: ev.clientY }; if (tip) tip.hidden = true; moving(); return;
  }
  const e = nearest(x, y, ev.pointerType === "touch");
  canvas.style.cursor = e ? "pointer" : "grab";
  if (!tip) return;
  if (!e) { tip.hidden = true; return; }
  tip.innerHTML = `<b>${ctx.esc(e.name)}</b><br><span class="mut">${ctx.esc(e.type)} · ${ctx.esc(detailOf(e))}</span>`;
  tip.hidden = false; tip.style.left = Math.min(x + 12, W - 230) + "px"; tip.style.top = Math.max(4, y + 12) + "px";
}
function onUp(ev) {
  const was = press; press = null;
  if (!was || moved > 5) return;
  const rc = canvas.getBoundingClientRect(), e = nearest(ev.clientX - rc.left, ev.clientY - rc.top, ev.pointerType === "touch");
  if (e) pickEntity(e);
}

/* ---------- list view: every entity as a row, filterable, keyboard reachable ---------- */
function renderList() {
  const box = ctx.$("#gd-list"), { esc } = ctx;
  const all = entities().map(e => ({ type: e.type, id: e.id, name: e.name, detail: detailOf(e), lat: e.lat, lon: e.lon })), rows = filterItems(all, listQ), shown = rows.slice(0, MAX_LIST);
  box.innerHTML = `<div class="controls"><input id="gd-q" type="search" placeholder="Filter the list (e.g. hormuz, FDX, tanker)" aria-label="Filter the map list" value="${esc(listQ)}"><span class="mut">${rows.length.toLocaleString("en-IN")} of ${all.length.toLocaleString("en-IN")} items${rows.length > MAX_LIST ? ` · first ${MAX_LIST} shown: narrow the filter` : ""}</span></div>
    <div class="tablecard"><table class="tbl sm" aria-label="Everything on the map, as a table"><thead><tr><th>Layer</th><th>Name</th><th>Detail</th><th class="r">Position</th><th>Open</th></tr></thead><tbody>${shown.map(e => `<tr><td>${esc(e.type)}</td><td>${esc(e.name)}</td><td class="mut">${esc(e.detail || "")}</td><td class="r">${e.lat.toFixed(2)}, ${e.lon.toFixed(2)}</td><td><button class="lnk" data-nexus="${esc(e.type)}:${esc(e.id)}">open</button></td></tr>`).join("") || '<tr><td colspan="5" class="empty">Nothing to show: switch a layer on, or no data has been published for it yet.</td></tr>'}</tbody></table></div>`;
  const q = box.querySelector("#gd-q");
  q.oninput = () => { listQ = q.value; const pos = q.selectionStart; renderList(); const n = ctx.$("#gd-q"); n.focus(); n.setSelectionRange(pos, pos); };
}

/* called by the page's slow poll: pick up a newer snapshot without a reload */
export async function refresh() {
  if (!ctx || !mounted || mode === "map" || !files().telemetry || liveNow()) return;
  try { const j = await ctx.getJSON("telemetry.json"); if (!data.transport || j.generated_utc !== data.transport.generated_utc) { data.transport = j; ctx.S.transport = j; ents = null; paintLayerBox(); render(); } } catch (e) { /* keep the last snapshot */ }
}
export const currentMode = () => mode;
