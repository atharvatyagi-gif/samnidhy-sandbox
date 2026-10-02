/* B-LAB globe: a real pan/zoom/scroll map (Leaflet.js, BSD-2-Clause, https://leafletjs.com) with three free,
   no-key base maps (Esri World Dark Gray/Imagery/Streets, server.arcgisonline.com - verified by fetching
   tiles directly; CARTO's basemap CDN was tried first but now returns an "API KEY REQUIRED" placeholder
   image instead of real tiles, so it was dropped) and Leaflet.markercluster (also jsDelivr, MIT) for the
   denser layers - the same trusted-CDN pattern this app already uses for Lightweight Charts.
   Data (data/globe/latest.json, from scripts/globe_data.py): real live flight positions (OpenSky), real
   daily vessel-transit counts by type (IMF PortWatch - not live AIS, its own lag shown on screen), real
   hazards (PortWatch disruptions, USGS earthquakes, NASA EONET, GDACS alerts), and real news (Google News
   RSS, GDELT as a bonus). There is no free live cargo-ship *position* source, so ships are not drawn as
   icons; PortWatch's real daily counts stand in for that instead - still real data, just not real-time AIS.
   "Why it matters" lines are static reference facts, shown separately from the live data next to them -
   never presented as a prediction of what will happen. */

const LEAFLET_CSS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";
const CLUSTER_CSS = ["https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.css",
  "https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"];
const CLUSTER_JS = "https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js";
let leafletLoad = null;
function loadCss(href, mark) {
  if (document.querySelector(`link[data-${mark}]`)) return;
  const l = document.createElement("link"); l.rel = "stylesheet"; l.href = href; l.dataset[mark] = "1";
  document.head.appendChild(l);
}
function loadScript(src) {
  return new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = () => rej(new Error(src + " failed to load")); document.head.appendChild(s); });
}
function loadLeaflet() {
  if (window.L && window.L.markerClusterGroup) return Promise.resolve();
  if (leafletLoad) return leafletLoad;
  loadCss(LEAFLET_CSS, "leaflet"); CLUSTER_CSS.forEach((h, i) => loadCss(h, "cluster" + i));
  leafletLoad = loadScript(LEAFLET_JS).then(() => loadScript(CLUSTER_JS));
  return leafletLoad;
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pinIcon = cls => window.L.divIcon({ className: "globe-pin-wrap", html: `<span class="globe-pin${cls ? " " + cls : ""}"><i></i></span>`, iconSize: [24, 24], iconAnchor: [12, 22], popupAnchor: [0, -22] });
const dotIcon = (cls, size = 14) => window.L.divIcon({ className: "globe-dot-wrap", html: `<span class="globe-dot ${cls}"></span>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2], popupAnchor: [0, -size / 2] });

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
function sparkSvg(vals, w = 220, h = 36) {
  if (!vals || vals.length < 2) return "";
  const mn = Math.min(...vals), mx = Math.max(...vals), span = mx - mn || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - (v - mn) / span * h).toFixed(1)}`).join(" ");
  return `<svg class="fp-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}
function vesselPopup(name, v) {
  if (!v) return `<p class="fp-src">No recent IMF PortWatch vessel data for ${esc(name)}.</p>`;
  const pct = v.avg7_vs_prior90_pct;
  const pctTxt = pct == null ? "—" : `${pct > 0 ? "+" : ""}${pct}%`;
  const rows = [
    ["Date (PortWatch)", esc(v.date)], ["Vessels that day", v.n_total],
    ["Tankers", v.n_tanker], ["Container ships", v.n_container], ["Dry bulk", v.n_dry_bulk],
    ["General cargo", v.n_general_cargo], ["RoRo", v.n_roro],
    ["7-day avg vs prior 90-day avg", pctTxt],
  ];
  return `<div class="fp"><h5>Real vessel traffic — ${esc(name)}</h5>
    ${sparkSvg(v.sparkline_90d)}
    <table>${rows.map(([k, val]) => `<tr><td>${esc(k)}</td><td>${val}</td></tr>`).join("")}</table>
    ${v.industries && v.industries.length ? `<p class="fp-src">Top industries served: ${v.industries.map(esc).join(", ")}.</p>` : ""}
    <p class="fp-src">IMF PortWatch (portwatch.imf.org) - real daily vessel counts, not live AIS; expect a few days' lag.</p>
  </div>`;
}
function hazardPopup(title, rows, srcLine, url) {
  return `<div class="fp"><h5>${esc(title)}</h5><table>${rows.filter(r => r[1] != null && r[1] !== "").map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(String(v))}</td></tr>`).join("")}</table>
    <p class="fp-src">${esc(srcLine)}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Source →</a>` : ""}</p></div>`;
}
const ago = iso => { if (!iso) return "—"; const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000)); return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`; };

const BASEMAPS = {
  dark: { name: "Dark (default)", url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors, and the GIS user community' },
  sat: { name: "Satellite", url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: 'Tiles &copy; Esri &mdash; Esri, Maxar, Earthstar Geographics, and the GIS user community' },
  street: { name: "Streets", url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, FAO, NOAA, USGS, and the GIS user community' },
};
const ZOOM_PRESETS = { world: [[20, 25], 2], india: [[22, 80], 5] };

export class GlobeMap {
  constructor(host, hooks = {}) {
    this.host = host; this.hooks = hooks; this.sel = null; this.markers = new Map();
    host.innerHTML = '<div class="globe-wrap"><div class="globe-leaflet"></div><div class="globe-msg">Loading the map…</div><div class="globe-legend" id="globe-legend"></div></div>';
    this.el = host.querySelector(".globe-leaflet"); this.msg = host.querySelector(".globe-msg");
    this.ready = this.buildBase();
  }
  async buildBase() {
    try {
      await loadLeaflet();
      const L = window.L;
      this.map = L.map(this.el, { worldCopyJump: true, minZoom: 2, maxZoom: 12 }).setView(...ZOOM_PRESETS.world);
      this.baseLayers = {};
      for (const [key, b] of Object.entries(BASEMAPS)) this.baseLayers[b.name] = L.tileLayer(b.url, { attribution: b.attribution, maxZoom: 16 });
      this.baseLayers[BASEMAPS.dark.name].addTo(this.map);

      this.flightLayer = L.layerGroup().addTo(this.map);
      this.chokeLayer = L.layerGroup().addTo(this.map);
      this.disruptionLayer = L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: 6 }).addTo(this.map);
      this.quakeLayer = L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: 6 }).addTo(this.map);
      this.naturalLayer = L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: 6 }).addTo(this.map);
      this.alertLayer = L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: 6 }).addTo(this.map);

      this.layerControl = L.control.layers(this.baseLayers, {
        "Chokepoints": this.chokeLayer, "Live flights": this.flightLayer,
        "Disruptions (PortWatch)": this.disruptionLayer, "Earthquakes M4.5+ (USGS)": this.quakeLayer,
        "Natural events, 7d (NASA EONET)": this.naturalLayer, "Disaster alerts (GDACS)": this.alertLayer,
      }, { collapsed: true, position: "topright" }).addTo(this.map);
      L.control.scale({ metric: true, imperial: false, position: "bottomleft" }).addTo(this.map);

      const presets = L.control({ position: "topleft" });
      presets.onAdd = () => {
        const d = L.DomUtil.create("div", "globe-presets leaflet-bar");
        d.innerHTML = '<a href="#" data-z="world" title="Zoom to world view">World</a><a href="#" data-z="india" title="Zoom to India">India</a>';
        L.DomEvent.disableClickPropagation(d);
        d.querySelectorAll("a").forEach(a => a.onclick = e => { e.preventDefault(); this.map.setView(...ZOOM_PRESETS[a.dataset.z]); });
        return d;
      };
      presets.addTo(this.map);

      const fs = L.control({ position: "topleft" });
      fs.onAdd = () => {
        const d = L.DomUtil.create("div", "globe-fs leaflet-bar");
        d.innerHTML = '<a href="#" title="Fullscreen">⛶</a>';
        L.DomEvent.disableClickPropagation(d);
        d.querySelector("a").onclick = e => { e.preventDefault(); if (!document.fullscreenElement) this.host.requestFullscreen?.(); else document.exitFullscreen?.(); };
        return d;
      };
      fs.addTo(this.map);

      const coord = L.control({ position: "bottomright" });
      coord.onAdd = () => { const d = L.DomUtil.create("div", "globe-coord"); d.textContent = "—, —"; return d; };
      coord.addTo(this.map);
      this.coordEl = this.el.querySelector(".globe-coord");
      this.map.on("mousemove", e => { if (this.coordEl) this.coordEl.textContent = `${e.latlng.lat.toFixed(2)}, ${e.latlng.lng.toFixed(2)}`; });

      this.msg.hidden = true;
      await this.loadSlowLayers();   // shipping lanes, cables, power plants - fetched once, change at most weekly
    } catch (e) {
      this.msg.textContent = "The map couldn't load (needs an internet connection the first time). Chokepoint cards below still work.";
    }
  }
  /* Adds an overlay the layer control can switch on; `onFirstOn` runs each time it is switched on (the caller loads its data
     lazily). Used by desk-map.js for the geopolitical news-attention layer. */
  async addLazyOverlay(name, onOn) {
    await this.ready;
    if (!this.map || !this.layerControl) return null;
    const lg = window.L.layerGroup();
    this.layerControl.addOverlay(lg, name);
    this.map.on("overlayadd", e => { if (e.layer === lg) onOn(lg); });
    return lg;
  }
  async loadSlowLayers() {
    const L = window.L;
    this.laneLayer = L.layerGroup();
    this.cableLayer = L.layerGroup();
    this.plantLayer = L.layerGroup();
    const FUEL_COLOR = { Coal: "#8a8a8a", Gas: "#f0c674", Hydro: "#4fc3f7", Solar: "#ffd400", Wind: "#2ecc71", Nuclear: "#a78bfa", Oil: "#ff4d4d" };
    try {
      const lanes = await fetch("globe/layers/shipping_lanes.json").then(r => r.ok ? r.json() : null);
      if (lanes) for (const lane of lanes.lanes || []) {
        const w = lane.type === "Major" ? 1.4 : lane.type === "Middle" ? 1 : 0.6;
        const op = lane.type === "Major" ? 0.55 : lane.type === "Middle" ? 0.4 : 0.25;
        for (const line of lane.lines) L.polyline(line.map(([x, y]) => [y, x]), { color: "#4fc3f7", weight: w, opacity: op })
          .bindTooltip(`${esc(lane.type)} shipping lane`).addTo(this.laneLayer);
      }
    } catch (e) { /* optional layer: map still works without it */ }
    try {
      const cables = await fetch("globe/layers/cables.json").then(r => r.ok ? r.json() : null);
      if (cables) {
        for (const c of cables.cables || []) for (const line of c.lines) L.polyline(line.map(([x, y]) => [y, x]), { color: "#f0c674", weight: 0.8, opacity: 0.3 })
          .bindTooltip(esc(c.name || "Submarine cable")).addTo(this.cableLayer);
        for (const lp of cables.landing_points || []) L.circleMarker([lp.lat, lp.lon], { radius: lp.india ? 4 : 2.5, weight: 0, fillColor: lp.india ? "#f0c674" : "#8a8a8a", fillOpacity: 0.8 })
          .bindTooltip(esc(lp.name)).addTo(this.cableLayer);
      }
    } catch (e) { /* optional layer */ }
    try {
      const plants = await fetch("globe/layers/power_plants_india.json").then(r => r.ok ? r.json() : null);
      if (plants) for (const p of plants.plants || []) L.circleMarker([p.lat, p.lon], { radius: Math.max(3, Math.min(10, p.capacity_mw / 300)), weight: 1, color: "#04120b", fillColor: FUEL_COLOR[p.fuel] || "#8a8a8a", fillOpacity: 0.8 })
        .bindPopup(hazardPopup(p.name, [["Fuel", p.fuel], ["Capacity", `${p.capacity_mw.toLocaleString("en-IN")} MW`], ["Commissioned", p.commissioning_year], ["Data vintage", p.data_vintage]], "WRI Global Power Plant Database - not real-time"), { className: "globe-popup" })
        .addTo(this.plantLayer);
    } catch (e) { /* optional layer */ }
    this.assetLayer = L.layerGroup();
    this.assetsByCompany = {};
    try {
      const assets = await fetch("globe/layers/company_assets.json").then(r => r.ok ? r.json() : null);
      if (assets) for (const a of assets.assets || []) {
        (this.assetsByCompany[a.company] = this.assetsByCompany[a.company] || []).push(a);
        L.marker([a.lat, a.lon], { icon: dotIcon("diamond") })
          .bindPopup(hazardPopup(a.facility, [["Company", a.company], ["Type", a.type]], "Wikidata - real but thin coverage, not every company is mapped"), { className: "globe-popup" })
          .addTo(this.assetLayer);
      }
    } catch (e) { /* optional layer */ }
    if (this.layerControl) {
      this.layerControl.addOverlay(this.laneLayer, "Shipping lanes");
      this.layerControl.addOverlay(this.cableLayer, "Submarine cables");
      this.layerControl.addOverlay(this.plantLayer, "Power plants, India ≥100MW");
      this.layerControl.addOverlay(this.assetLayer, "Company facilities (Wikidata)");
    }
  }
  /* Called from terminal.js when a stock is opened: flies to and highlights that company's real mapped
     facilities, if Wikidata has any - returns the match count so the caller can show an honest "none mapped"
     state instead of a silent no-op when it's 0. Matches by company name substring (NSE universe has no
     direct Wikidata QID mapping today), case-insensitive, both directions to catch "Reliance Industries" vs
     "Reliance Industries Limited". */
  async showCompanyAssets(companyName) {
    await this.ready;                                      // the slow layers (incl. these assets) finish loading inside buildBase()
    if (!this.map || !this.assetsByCompany) return [];
    const q = String(companyName || "").toLowerCase();
    const hits = Object.entries(this.assetsByCompany).filter(([name]) => name.toLowerCase().includes(q) || q.includes(name.toLowerCase()));
    const pts = hits.flatMap(([, list]) => list);
    if (!pts.length) return [];
    if (!this.map.hasLayer(this.assetLayer)) this.assetLayer.addTo(this.map);
    if (pts.length === 1) this.map.setView([pts[0].lat, pts[0].lon], 6);
    else this.map.fitBounds(pts.map(p => [p.lat, p.lon]), { padding: [40, 40], maxZoom: 6 });
    return pts;
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
      const v = p.vessels;
      const m = L.marker([p.lat, p.lon], { icon: pinIcon(this.flagOf(p.id)), keyboard: true, alt: p.name, title: p.name })
        .bindPopup(`<div class="fp"><h5>${esc(p.name)}</h5><table><tr><td>Live flights</td><td>${n}</td>${v ? `<tr><td>Vessels (${esc(v.date)})</td><td>${v.n_total}</td></tr>` : ""}</table></div>`, { className: "globe-popup" })
        .on("click", () => this.select(p.id))
        .addTo(this.chokeLayer);
      const elm = m.getElement(); if (elm) elm.setAttribute("data-id", p.id);
      this.markers.set(p.id, m);
    }

    const H = data.hazards || {};
    this.disruptionLayer.clearLayers();
    for (const d of H.disruptions || []) {
      if (d.lat == null) continue;
      const cls = d.alert === "RED" ? "red" : d.alert === "ORANGE" ? "orange" : "grey";
      L.marker([d.lat, d.lon], { icon: dotIcon("sq " + cls) })
        .bindPopup(hazardPopup(`${d.name || d.type}`, [["Type", d.type], ["Alert level", d.alert], ["Country", d.country], ["Severity", d.severity],
          ["Ports affected", d.n_ports], ["From", d.from_utc ? ago(d.from_utc) : null], ["To", d.to_utc ? ago(d.to_utc) : null]],
          "IMF PortWatch disruptions (real port-impact data)"), { className: "globe-popup" })
        .addTo(this.disruptionLayer);
    }
    this.quakeLayer.clearLayers();
    for (const q of H.earthquakes || []) {
      if (q.lat == null) continue;
      const r = Math.max(4, Math.min(16, q.mag * 2.2));
      L.circleMarker([q.lat, q.lon], { radius: r, weight: 1, color: "#ffd400", fillColor: "#ffd400", fillOpacity: 0.35, className: "globe-quake" })
        .bindPopup(hazardPopup(`M${q.mag} earthquake`, [["Place", q.place], ["Tsunami warning", q.tsunami ? "Yes" : "No"], ["Time", ago(q.time_utc)]],
          "USGS Earthquake Hazards Program", q.url), { className: "globe-popup" })
        .addTo(this.quakeLayer);
    }
    this.naturalLayer.clearLayers();
    for (const n of H.natural_events || []) {
      if (n.lat == null) continue;
      L.marker([n.lat, n.lon], { icon: dotIcon("tri") })
        .bindPopup(hazardPopup(n.title, [["Category", n.category], ["Date", n.date ? ago(n.date) : null]], "NASA EONET", n.url), { className: "globe-popup" })
        .addTo(this.naturalLayer);
    }
    this.alertLayer.clearLayers();
    for (const a of H.alerts || []) {
      if (a.lat == null) continue;
      const cls = (a.alert || "").toLowerCase() === "red" ? "red" : (a.alert || "").toLowerCase() === "orange" ? "orange" : "green";
      L.marker([a.lat, a.lon], { icon: dotIcon("tri " + cls) })
        .bindPopup(hazardPopup(a.name || a.type, [["Type", a.type], ["Alert level", a.alert], ["Country", a.country]], "GDACS", a.url), { className: "globe-popup" })
        .addTo(this.alertLayer);
    }

    const legend = this.host.querySelector("#globe-legend");
    if (legend) legend.innerHTML = [
      ["acc", "Chokepoint"], ["plane", "Live flight"], ["sq red", "Disruption (red)"], ["sq orange", "Disruption (orange)"],
      ["quake", "Earthquake M4.5+"], ["tri", "Natural event"], ["tri red", "Alert (red)"],
    ].map(([cls, label]) => `<span class="gl-item"><i class="gl-${cls}"></i>${esc(label)}</span>`).join("");
  }
  vesselPopupFor(id) {   // used by terminal.js when a card is clicked, to keep the popup content identical to the map's own
    const p = (this.data && this.data.chokepoints || []).find(x => x.id === id);
    return p ? vesselPopup(p.name, p.vessels) : "";
  }
  flagOf(id) {                                              // "active"/"quiet": this run's own count vs. the 7-point average (see terminal.js activityFlag)
    const pts = (this.data && this.data.chokepoints) || [];
    const counts = pts.map(p => (p.flights && p.flights.count) || 0), avg = counts.reduce((a, b) => a + b, 0) / (counts.length || 1);
    const n = (pts.find(p => p.id === id)?.flights?.count) || 0;
    const cls = avg <= 0 ? "" : n >= avg * 1.5 ? "active" : n <= avg * 0.3 ? "quiet" : "";
    return `${cls}${this.sel === id ? " on" : ""}`.trim();
  }
  resize() {                                                // Leaflet sizes itself from its container at construction time;
    this.ready.then(() => { if (this.map) this.map.invalidateSize(); });   // if it was hidden (display:none) then, tiles come out wrong until this runs
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
