/* B-LAB globe: a real pan/zoom/scroll map (Leaflet.js, BSD-2-Clause, https://leafletjs.com) on Esri's free
   "World Dark Gray" basemap (server.arcgisonline.com, no API key needed - verified by fetching a tile directly;
   CARTO's basemap CDN was tried first but now returns an "API KEY REQUIRED" placeholder image instead of real
   tiles, so it was dropped) - the same trusted-CDN pattern this app already uses for Lightweight Charts.
   Data (data/globe/latest.json, from scripts/globe_data.py): real live flight positions near each of 7
   shipping/oil chokepoints (OpenSky Network) and real news about each one and about world events generally
   (GDELT Project). There is no free live cargo-ship position source, so ships are not drawn; each chokepoint's
   card carries real news instead. "Why it matters" lines are static reference facts, shown separately from the
   live flight/news data next to them - never presented as a prediction of what will happen. */

const LEAFLET_CSS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";
let leafletLoad = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (leafletLoad) return leafletLoad;
  leafletLoad = new Promise((res, rej) => {
    if (!document.querySelector("link[data-leaflet]")) {
      const l = document.createElement("link"); l.rel = "stylesheet"; l.href = LEAFLET_CSS; l.dataset.leaflet = "1";
      document.head.appendChild(l);
    }
    const s = document.createElement("script");
    s.src = LEAFLET_JS; s.onload = res; s.onerror = () => rej(new Error("Leaflet failed to load"));
    document.head.appendChild(s);
  });
  return leafletLoad;
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pinIcon = cls => window.L.divIcon({ className: "globe-pin-wrap", html: `<span class="globe-pin${cls ? " " + cls : ""}"><i></i></span>`, iconSize: [24, 24], iconAnchor: [12, 22], popupAnchor: [0, -22] });

// Real ICAO 3-letter airline designators (public reference data, e.g. ICAO Doc 8585) for carriers that
// plausibly fly near these 7 chokepoints. A callsign whose prefix isn't in here shows as "Unknown operator" -
// never a guess. This is the only way to attach an airline name: OpenSky's state vectors carry a callsign, not
// an airline field, and there is no free lookup API for this, so it is a small static table, same as the
// chokepoints' own "why it matters" reference facts.
const AIRLINES = {
  UAE: "Emirates", ETD: "Etihad Airways", QTR: "Qatar Airways", SVA: "Saudia", FDB: "flydubai", ABY: "Air Arabia",
  GFA: "Gulf Air", KAC: "Kuwait Airways", OMA: "Oman Air", MSR: "EgyptAir", RJA: "Royal Jordanian", ELY: "El Al",
  AIC: "Air India", IGO: "IndiGo", SEJ: "SpiceJet", VTI: "Vistara", PIA: "Pakistan International", GOW: "Go First",
  SIA: "Singapore Airlines", MAS: "Malaysia Airlines", CPA: "Cathay Pacific", THA: "Thai Airways",
  GIA: "Garuda Indonesia", AXM: "AirAsia", JST: "Jetstar", VJC: "VietJet Air", PAL: "Philippine Airlines",
  CAL: "China Airlines", EVA: "EVA Air", CES: "China Eastern", CSN: "China Southern", CCA: "Air China",
  CQH: "Juneyao Airlines", CDG: "Shandong Airlines", HDA: "Hong Kong Airlines", CXA: "Xiamen Airlines",
  CMP: "Copa Airlines", AAL: "American Airlines", UAL: "United Airlines", DAL: "Delta Air Lines",
  AVA: "Avianca", ACA: "Air Canada", VOI: "Volaris", AMX: "Aeromexico", LAN: "LATAM Airlines",
  THY: "Turkish Airlines", AFL: "Aeroflot", DLH: "Lufthansa", BAW: "British Airways", AFR: "Air France",
  KLM: "KLM Royal Dutch Airlines", IBE: "Iberia", SWR: "Swiss International", AUA: "Austrian Airlines",
  PGT: "Pegasus Airlines", AZA: "ITA Airways", TAR: "Tunisair", RAM: "Royal Air Maroc", MEA: "Middle East Airlines",
  FDX: "FedEx Express", UPS: "UPS Airlines", DHK: "DHL (European Air Transport)", GEC: "Lufthansa Cargo",
  QFA: "Qantas", ANZ: "Air New Zealand", JAL: "Japan Airlines", ANA: "All Nippon Airways", KAL: "Korean Air",
  AAR: "Asiana Airlines",
};
const airlineOf = callsign => AIRLINES[String(callsign || "").trim().slice(0, 3).toUpperCase()] || null;
const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compassOf = deg => deg == null ? "" : COMPASS[Math.round(deg / 22.5) % 16];
const kt = ms => ms == null ? null : Math.round(ms * 1.94384);
const kmh = ms => ms == null ? null : Math.round(ms * 3.6);
function vrateLabel(ms) {
  if (ms == null) return "Level flight data unavailable";
  if (ms > 0.5) return `Climbing, ${ms.toFixed(1)} m/s`;
  if (ms < -0.5) return `Descending, ${Math.abs(ms).toFixed(1)} m/s`;
  return "Level flight";
}
const EMERGENCY_SQUAWK = { "7500": "HIJACK", "7600": "RADIO FAILURE", "7700": "GENERAL EMERGENCY" };
function flightPopup(f) {
  const airline = airlineOf(f.callsign);
  const emg = f.squawk && EMERGENCY_SQUAWK[f.squawk];
  const rows = [
    ["Operator", airline || `Unknown operator (code: ${esc((f.callsign || "").slice(0, 3)) || "—"})`],
    ["Aircraft (ICAO24)", esc(f.icao24 || "—")],
    ["Registered in", esc(f.country || "—")],
    ["Altitude (barometric)", f.alt_m != null ? `${Math.round(f.alt_m).toLocaleString("en-IN")} m` : "—"],
    ["Altitude (GPS)", f.geo_alt_m != null ? `${Math.round(f.geo_alt_m).toLocaleString("en-IN")} m` : "—"],
    ["Speed", f.velocity_ms != null ? `${kmh(f.velocity_ms)} km/h (${kt(f.velocity_ms)} kt)` : "—"],
    ["Heading", f.heading != null ? `${compassOf(f.heading)}, ${Math.round(f.heading)}°` : "—"],
    ["Vertical rate", vrateLabel(f.vrate_ms)],
    ["On ground", f.on_ground ? "Yes" : "No"],
    ["Squawk (transponder code)", f.squawk ? esc(f.squawk) + (emg ? ` — ${emg}` : "") : "—"],
    ["Position updated", f.age_s != null ? `${f.age_s}s ago` : "—"],
    ["Route", "Not available"],
  ];
  return `<div class="fp">${emg ? `<div class="fp-emg">⚠ Transponder: ${emg}</div>` : ""}
    <h5>${esc(f.callsign || "Unknown callsign")}${airline ? ` <span class="fp-al">${esc(airline)}</span>` : ""}</h5>
    <table>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")}</table>
    <p class="fp-src">Live ADS-B data via OpenSky Network. Route (origin → destination) isn't shown: OpenSky's free anonymous tier returns a 403 for flight-route lookups - only a registered account (free signup) unlocks it.</p>
  </div>`;
}

export class GlobeMap {
  constructor(host, hooks = {}) {
    this.host = host; this.hooks = hooks; this.sel = null; this.markers = new Map();
    host.innerHTML = '<div class="globe-wrap"><div class="globe-leaflet"></div><div class="globe-msg">Loading the map…</div></div>';
    this.el = host.querySelector(".globe-leaflet"); this.msg = host.querySelector(".globe-msg");
    this.ready = this.buildBase();
  }
  async buildBase() {
    try {
      await loadLeaflet();
      const L = window.L;
      this.map = L.map(this.el, { worldCopyJump: true, minZoom: 2, maxZoom: 12 }).setView([20, 25], 2);
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
        attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors, and the GIS user community',
        maxZoom: 16,
      }).addTo(this.map);
      this.flightLayer = L.layerGroup().addTo(this.map);
      this.chokeLayer = L.layerGroup().addTo(this.map);
      this.msg.hidden = true;
    } catch (e) {
      this.msg.textContent = "The map couldn't load (needs an internet connection the first time). Chokepoint cards below still work.";
    }
  }
  async update(data) {
    await this.ready;
    if (!this.map) return;
    const L = window.L;
    this.data = data;
    this.flightLayer.clearLayers();
    for (const p of data.chokepoints || []) for (const f of (p.flights && p.flights.sample) || []) {
      if (f.lat == null) continue;
      const airline = airlineOf(f.callsign);
      L.circleMarker([f.lat, f.lon], { radius: 4, weight: 6, opacity: 0, fillColor: "#ffb347", fillOpacity: 0.9, className: "globe-plane" })
        .bindTooltip(`${esc(f.callsign || "flight")}${airline ? " · " + esc(airline) : ""}${f.alt_m != null ? " · " + Math.round(f.alt_m).toLocaleString("en-IN") + " m" : ""}`)
        .bindPopup(flightPopup(f), { className: "globe-popup fp-popup", minWidth: 250, maxWidth: 280 })
        .addTo(this.flightLayer);
    }
    this.chokeLayer.clearLayers(); this.markers.clear();
    for (const p of data.chokepoints || []) {
      const n = (p.flights && p.flights.count) || 0;
      const m = L.marker([p.lat, p.lon], { icon: pinIcon(this.flagOf(p.id)), keyboard: true, alt: p.name, title: p.name })
        .bindPopup(`<b>${esc(p.name)}</b><br>${n} flight${n === 1 ? "" : "s"} now`, { className: "globe-popup" })
        .on("click", () => this.select(p.id))
        .addTo(this.chokeLayer);
      const elm = m.getElement(); if (elm) elm.setAttribute("data-id", p.id);
      this.markers.set(p.id, m);
    }
  }
  flagOf(id) {                                              // "active"/"quiet": this run's own count vs. the 7-point average (see terminal.js activityFlag)
    const pts = (this.data && this.data.chokepoints) || [];
    const counts = pts.map(p => (p.flights && p.flights.count) || 0), avg = counts.reduce((a, b) => a + b, 0) / (counts.length || 1);
    const n = (pts.find(p => p.id === id)?.flights?.count) || 0;
    const cls = avg <= 0 ? "" : n >= avg * 1.5 ? "active" : n <= avg * 0.3 ? "quiet" : "";
    return `${cls}${this.sel === id ? " on" : ""}`.trim();
  }
  select(id) {                                              // one entry point for both the map and the cards (terminal.js)
    this.sel = this.sel === id ? null : id;
    for (const [pid, m] of this.markers) {
      m.setIcon(pinIcon(this.flagOf(pid)));
      const elm = m.getElement(); if (elm) elm.setAttribute("data-id", pid);
    }
    this.hooks.onSelect?.(this.sel);
  }
}
