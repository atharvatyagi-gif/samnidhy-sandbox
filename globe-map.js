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
      L.circleMarker([f.lat, f.lon], { radius: 2.5, weight: 0, fillColor: "#ffb347", fillOpacity: 0.85, className: "globe-plane" })
        .bindTooltip(`${esc(f.callsign || "flight")}${f.alt_m != null ? " · " + Math.round(f.alt_m) + " m" : ""}`)
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
