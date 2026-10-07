/* desk-globe-layers.js: the rest of the standard Map's layers, for the 3D globe, the flat map and the 2D fallback.
   The standard (Leaflet) Map shows: chokepoints, live flights, PortWatch disruptions, USGS earthquakes, NASA EONET natural events, GDACS alerts, shipping lanes,
   submarine cables, India power plants, company facilities (Wikidata) and the news-attention hotspots, on a Dark / Satellite / Streets base. This file gives the
   other Globe views the same layers and base maps, from the same published files (globe.json and globe/layers/*.json). Nothing here is invented: a layer with
   no data simply has no markers, and the legend says so. Positions are only drawn from the files; hazards older than 7 days were already dropped by freshGlobe(). */
export const EXTRA = [["disr", "Disruptions (PortWatch)", true], ["quake", "Earthquakes M4.5+ (USGS)", true], ["nat", "Natural events, 7d (NASA EONET)", true], ["alert", "Disaster alerts (GDACS)", true],
  ["slane", "Shipping lanes", true], ["cable", "Submarine cables", true], ["power", "Power plants, India ≥100MW", false], ["asset", "Company facilities (Wikidata)", false], ["border", "Country borders", true]];
export const BASES = [["dark", "Dark (default)"], ["sat", "Satellite"], ["street", "Streets"]];
export const TILE = {
  sat: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  street: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
};
export const COLORS = { quake: "#ffd400", nat: "#e8e8e8", alert: "#ef4444", disr: "#ef4444", asset: "#fafafa", cable: "#f0c674", slane: "#4fc3f7",
  fuel: { Coal: "#8a8a8a", Gas: "#f0c674", Hydro: "#4fc3f7", Solar: "#ffd400", Wind: "#2ecc71", Nuclear: "#a78bfa", Oil: "#ff4d4d" } };
const FILES = { cable: "globe/layers/cables.json", slane: "globe/layers/shipping_lanes.json", power: "globe/layers/power_plants_india.json", asset: "globe/layers/company_assets.json" };
const RAD = Math.PI / 180;
export const EXTRA_TYPES = new Set(["disruption", "quake", "natural", "alert", "powerplant", "asset"]);

/* the four optional files are read only when their layer is on, and only once (a failed read is not retried every frame) */
export function loadFiles(layers, store, getJSON) {
  const jobs = [];
  for (const [k, url] of Object.entries(FILES)) {
    if (!layers[k] || store[k] !== undefined) continue;
    store[k] = null;
    jobs.push((getJSON ? getJSON(url, false) : fetch(url).then(r => (r.ok ? r.json() : null))).then(j => { store[k] = j || null; }).catch(() => { store[k] = null; }));
  }
  return Promise.all(jobs);
}

const geom = e => { e.la = e.lat * RAD; e.lo = e.lon * RAD; e.sl = Math.sin(e.la); e.cl = Math.cos(e.la); return e; };
/* point entities, in the same shape desk-globe.js uses for plants and hotspots */
export function entities(layers, store, G) {
  const out = [], H = (G && G.hazards) || {};
  if (layers.disr) (H.disruptions || []).forEach((d, i) => { if (d.lat != null) out.push(geom({ layer: "disr", type: "disruption", id: "d" + i, name: d.name || d.type || "Port disruption", row: d, lat: d.lat, lon: d.lon })); });
  if (layers.quake) (H.earthquakes || []).forEach((q, i) => { if (q.lat != null) out.push(geom({ layer: "quake", type: "quake", id: "q" + i, name: `M${q.mag} earthquake`, row: q, lat: q.lat, lon: q.lon, mag: q.mag })); });
  if (layers.nat) (H.natural_events || []).forEach((n, i) => { if (n.lat != null) out.push(geom({ layer: "nat", type: "natural", id: "n" + i, name: n.title, row: n, lat: n.lat, lon: n.lon })); });
  if (layers.alert) (H.alerts || []).forEach((a, i) => { if (a.lat != null) out.push(geom({ layer: "alert", type: "alert", id: "a" + i, name: a.name || a.type || "Disaster alert", row: a, lat: a.lat, lon: a.lon })); });
  if (layers.power && store.power) (store.power.plants || []).forEach((p, i) => { if (p.lat != null) out.push(geom({ layer: "power", type: "powerplant", id: "p" + i, name: p.name, row: p, lat: p.lat, lon: p.lon, mw: p.capacity_mw, fuel: p.fuel })); });
  if (layers.asset && store.asset) (store.asset.assets || []).forEach((a, i) => { if (a.lat != null) out.push(geom({ layer: "asset", type: "asset", id: "f" + i, name: a.facility, row: a, lat: a.lat, lon: a.lon })); });
  return out;
}
/* polylines: [{ key, color, width, alpha, lines: [[[lon, lat], ...], ...] }] */
export function lineSets(layers, store) {
  const sets = [];
  if (layers.slane && store.slane) {
    const by = { Major: [], Middle: [], Minor: [] };
    for (const l of store.slane.lanes || []) (by[l.type] || by.Minor).push(...l.lines);
    sets.push({ key: "slane", color: COLORS.slane, width: 1.6, alpha: 0.75, lines: [...by.Major, ...by.Middle, ...by.Minor] });
  }
  if (layers.cable && store.cable) sets.push({ key: "cable", color: COLORS.cable, width: 1.3, alpha: 0.6, lines: (store.cable.cables || []).flatMap(c => c.lines) });
  return sets;
}
const ago = iso => { if (!iso) return null; const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000)); return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`; };
export function detail(e) {
  const r = e.row;
  switch (e.type) {
    case "quake": return `${r.place || "location n/a"} · ${ago(r.time_utc) || ""}${r.tsunami ? " · tsunami warning" : ""}`;
    case "natural": return `${r.category || "event"} · ${ago(r.date) || "date n/a"}`;
    case "alert": return `${r.type || "alert"} · ${r.alert || "level n/a"}${r.country ? " · " + r.country : ""}`;
    case "disruption": return `${r.type || "port disruption"} · ${r.alert || "level n/a"}${r.country ? " · " + r.country : ""}`;
    case "powerplant": return `${r.fuel || "fuel n/a"} · ${Number(r.capacity_mw).toLocaleString("en-IN")} MW`;
    default: return `${r.company || "company n/a"} · ${r.type || "facility"}`;
  }
}
/* the card shown when one of these is clicked (the NEXUS panel only knows flights, vessels, hotspots, chokepoints and plants named in filings) */
export function card(e, esc) {
  const r = e.row, rows = [], add = (k, v) => { if (v != null && v !== "") rows.push(`<tr><td>${esc(k)}</td><td>${esc(String(v))}</td></tr>`); };
  let src = "", url = r.url;
  if (e.type === "quake") { add("Place", r.place); add("Tsunami warning", r.tsunami ? "Yes" : "No"); add("Time", ago(r.time_utc)); src = "USGS Earthquake Hazards Program"; }
  else if (e.type === "natural") { add("Category", r.category); add("Date", ago(r.date)); src = "NASA EONET"; }
  else if (e.type === "alert") { add("Type", r.type); add("Alert level", r.alert); add("Country", r.country); src = "GDACS"; }
  else if (e.type === "disruption") { add("Type", r.type); add("Alert level", r.alert); add("Country", r.country); add("Severity", r.severity); add("Ports affected", r.n_ports); add("From", ago(r.from_utc)); add("To", ago(r.to_utc)); src = "IMF PortWatch disruptions (real port-impact data)"; }
  else if (e.type === "powerplant") { add("Fuel", r.fuel); add("Capacity", `${Number(r.capacity_mw).toLocaleString("en-IN")} MW`); add("Commissioned", r.commissioning_year); add("Data vintage", r.data_vintage); src = "WRI Global Power Plant Database, not real-time"; }
  else { add("Company", r.company); add("Type", r.type); src = "Wikidata: real but thin coverage, not every company is mapped"; }
  const link = url && /^https?:\/\//.test(url) ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Source →</a>` : "";
  return `<button type="button" class="gd-card-x" aria-label="Close">×</button><h5>${esc(e.name || "")}</h5><table>${rows.join("")}</table><p class="fp-src">${esc(src)}${link}</p>`;
}
export const legendRows = layers => {
  const r = [];
  if (layers.quake) r.push([COLORS.quake, "Earthquake (size = magnitude)"]);
  if (layers.nat) r.push([COLORS.nat, "Natural event"]);
  if (layers.alert) r.push([COLORS.alert, "Disaster alert"]);
  if (layers.disr) r.push([COLORS.alert, "Port disruption"]);
  if (layers.power) r.push([COLORS.fuel.Coal, "Power plant (colour = fuel)"]);
  if (layers.asset) r.push([COLORS.asset, "Company facility"]);
  if (layers.slane) r.push([COLORS.slane, "Shipping lane", "line"]);
  if (layers.cable) r.push([COLORS.cable, "Submarine cable", "line"]);
  return r;
};

/* ---------- base maps for the 3D globe: Esri tiles (Dark / Satellite / Streets, the same three as the standard Map) re-projected to a world texture ---------- */
const mercY = lat => Math.log(Math.tan(Math.PI / 4 + (Math.max(-85.0511, Math.min(85.0511, lat)) * RAD) / 2));
export async function tileCanvas(kind, size = [4096, 2048], zoom = 3) {
  const url = TILE[kind]; if (!url) throw new Error("unknown base " + kind);
  const n = 1 << zoom, ts = 256, S = n * ts, src = document.createElement("canvas"); src.width = src.height = S;
  const sg = src.getContext("2d", { willReadFrequently: true });
  const tiles = [];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) tiles.push(new Promise((res, rej) => {
    const im = new Image(); im.crossOrigin = "anonymous";
    im.onload = () => { sg.drawImage(im, x * ts, y * ts); res(); }; im.onerror = () => rej(new Error("tile " + x + "," + y)); im.src = url.replace("{z}", zoom).replace("{x}", x).replace("{y}", y);
  }));
  await Promise.all(tiles);
  const [W, H] = size, out = document.createElement("canvas"); out.width = W; out.height = H;
  const og = out.getContext("2d"), srcData = sg.getImageData(0, 0, S, S).data, img = og.createImageData(W, H), d = img.data;
  const y0 = mercY(85.0511);
  for (let py = 0; py < H; py++) {
    const lat = 90 - (py + 0.5) / H * 180, my = (y0 - mercY(lat)) / (2 * y0), sy = Math.min(S - 1, Math.max(0, Math.floor(my * S)));
    for (let px = 0; px < W; px++) {
      const sx = Math.min(S - 1, Math.floor((px + 0.5) / W * S)), si = (sy * S + sx) * 4, di = (py * W + px) * 4;
      d[di] = srcData[si]; d[di + 1] = srcData[si + 1]; d[di + 2] = srcData[si + 2]; d[di + 3] = 255;
    }
  }
  og.putImageData(img, 0, 0);
  return out;
}
