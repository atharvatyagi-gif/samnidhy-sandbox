/* Pure helpers for the Globe's NEXUS layers: which trade lane or chokepoint a position falls in, who operates a callsign (inferred), how old a snapshot is,
   hotspot colours, list-view rows. No DOM, no network, so every rule here is unit-tested (tests/js/lanes.test.mjs).
   Honesty rules these helpers encode: a callsign prefix says who OPERATES a flight, never what it carries or for whom; a lane match says a position lies inside a
   hand-drawn corridor, so the companies listed for it are a lane-level inference and never about that one flight or ship. */

/* The colours of the standard Map (globe-map.js: orange plane dots, blue trade lanes), so the 3D globe, the flat canvas and the legend all match it */
export const MAP_COLORS = { air: "#ffb347", cargo: "#ffd400", ship: "#4fc3f7", lane: "#4fc3f7" };

/* bbox is [lonMin, latMin, lonMax, latMax] */
export const inBox = (lat, lon, b) => lat >= b[1] && lat <= b[3] && lon >= b[0] && lon <= b[2];

export function lanesAt(lat, lon, lanes, kind) {
  return (lanes || []).filter(l => (!kind || l.kind === kind) && (l.bbox || []).some(b => inBox(lat, lon, b)));
}
export function chokepointAt(lat, lon, cps) { return (cps || []).find(c => inBox(lat, lon, c.bbox)) || null; }
export function countIn(vessels, bbox) { return (vessels || []).filter(v => v[2] != null && v[3] != null && inBox(v[2], v[3], bbox)).length; }

/* callsign -> { prefix, name, cargo } from the first three letters, or null when that airline is not in the (short, hand-seeded) list */
export function carrierOf(callsign, carriers) {
  const p = String(callsign || "").trim().slice(0, 3).toUpperCase(), c = carriers && carriers[p];
  return c ? { prefix: p, name: c[0], cargo: !!c[1] } : null;
}

export function ageMin(iso, now = Date.now()) {
  const t = Date.parse(iso);
  return Number.isFinite(t) ? Math.max(0, Math.round((now - t) / 60000)) : null;
}
export function ageText(m) {
  return m == null ? "age unknown" : m < 1 ? "under a minute old" : m < 90 ? `${m} min old` : `${(m / 60).toFixed(1)} h old`;
}
/* greyed out when the snapshot is older than the age it declares for itself (twice its refresh interval), or has no readable date */
export function isStale(doc, now = Date.now()) {
  if (!doc) return true;
  const m = ageMin(doc.generated_utc, now);
  return m == null || m > (doc.max_age_min ?? 20);
}

/* AIS ship-type code -> words (IEC 61162 / ITU-R M.1371 groups) */
export function shipTypeLabel(code) {
  if (code == null || !Number.isFinite(+code)) return "Type not broadcast";
  const c = +code;
  if (c >= 80 && c <= 89) return "Tanker";
  if (c >= 70 && c <= 79) return "Cargo ship";
  if (c >= 60 && c <= 69) return "Passenger ship";
  if (c >= 40 && c <= 49) return "High-speed craft";
  const m = { 30: "Fishing", 31: "Towing", 32: "Towing (large)", 33: "Dredging", 34: "Diving", 35: "Military", 36: "Sailing", 37: "Pleasure craft", 50: "Pilot vessel", 51: "Search and rescue", 52: "Tug", 53: "Port tender", 55: "Law enforcement" };
  return m[c] || (c >= 90 ? "Other" : "Type " + c);
}

/* the dependable one-line description of a lane's companies: rows { sym | ind, dir, why } are the lane's own, with the lane named for the caption */
export function exposureRows(lanes) {
  const out = [];
  for (const l of lanes || []) for (const e of l.exposure || []) out.push({ ...e, lane: l.name, laneId: l.id });
  return out;
}

/* hotspot colour: below 35 the quiet grey, then gold (35) blending to the "down" colour (100). Colours are CSS variable VALUES read by the caller, never literals here. */
function rgb(s) {
  s = String(s || "").trim();
  let m = /^#([0-9a-f]{3})$/i.exec(s); if (m) return m[1].split("").map(x => parseInt(x + x, 16));
  m = /^#([0-9a-f]{6})$/i.exec(s); if (m) return [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16));
  m = /^rgba?\(([^)]+)\)/i.exec(s); if (m) return m[1].split(",").slice(0, 3).map(x => Math.round(+x));
  return [136, 136, 136];
}
export function lerpColor(a, b, t) {
  const A = rgb(a), B = rgb(b), k = Math.max(0, Math.min(1, t));
  return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * k)).join(",")})`;
}
export function hotspotColor(score, quiet, gold, hot) {
  if (score == null || score < 35) return quiet;
  return lerpColor(gold, hot, (score - 35) / 65);
}
export const hotspotRadius = score => 5 + (score == null ? 0 : Math.max(0, Math.min(100, score))) / 10;

/* list view: the same entities as the canvas, filtered by a text box. Each item: { type, id, name, detail }. */
export function filterItems(items, q) {
  const s = String(q || "").trim().toLowerCase();
  return s ? items.filter(i => `${i.type} ${i.name} ${i.detail || ""} ${i.id}`.toLowerCase().includes(s)) : items;
}

/* the layer switches a viewer last chose (stored per browser); anything unknown is ignored and the defaults fill the rest */
export function mergeLayers(defaults, stored) {
  const out = { ...defaults };
  if (stored && typeof stored === "object") for (const k of Object.keys(defaults)) if (typeof stored[k] === "boolean") out[k] = stored[k];
  return out;
}
