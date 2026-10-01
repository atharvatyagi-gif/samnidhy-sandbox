/* B-LAB globe: a layered pan/zoom map (Leaflet.js, BSD-2-Clause, https://leafletjs.com) on Esri's free basemaps
   (server.arcgisonline.com, no API key - CARTO's CDN now needs a key, so it isn't used).

   Every layer is a real, published dataset, shown with its own source and as-of time in the layer panel:
     live    data/globe/latest.json (scripts/globe_data.py, about hourly)
             - aircraft near the 7 key chokepoints (OpenSky Network, live ADS-B)
             - daily ship transits by vessel type through 28 chokepoints, port calls at India's ports and
               port-disrupting events (IMF PortWatch, from satellite AIS; the source lags about 1-2 weeks, so
               it is always dated by its own latest day, never shown as "now")
             - earthquakes M4.5+ (USGS), open natural events (NASA EONET), disaster alerts (GDACS)
     weekly  data/globe/layers/cables.json (TeleGeography), companies.json (Wikidata)
     static  data/globe/layers/lanes.json (Benden 2022 / CIA shipping lanes), power_in.json (WRI power plants)
   Nothing on this map is a prediction. "Why it matters" lines and exposure tags are reference facts. */

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
const num = (v, d = 0) => v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const pinIcon = cls => window.L.divIcon({ className: "globe-pin-wrap", html: `<span class="globe-pin${cls ? " " + cls : ""}"><i></i></span>`, iconSize: [24, 24], iconAnchor: [12, 22], popupAnchor: [0, -22] });
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: in-memory only */ } } };
const agoTxt = iso => {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  return m < 60 ? `${m}m ago` : m < 2880 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
};
const dayTxt = d => d ? new Date(d + "T00:00:00Z").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "—";

// Real ICAO 3-letter airline designators (public reference data, ICAO Doc 8585). A callsign whose prefix isn't
// in here shows as "Unknown operator" - never a guess. OpenSky's state vectors carry a callsign, not an airline.
const AIRLINES = {
  UAE: "Emirates", ETD: "Etihad Airways", QTR: "Qatar Airways", SVA: "Saudia", FDB: "flydubai", ABY: "Air Arabia",
  GFA: "Gulf Air", KAC: "Kuwait Airways", OMA: "Oman Air", MSR: "EgyptAir", RJA: "Royal Jordanian", ELY: "El Al",
  AIC: "Air India", IGO: "IndiGo", SEJ: "SpiceJet", VTI: "Vistara", PIA: "Pakistan International", GOW: "Go First",
  AXB: "Air India Express", AKJ: "Akasa Air",
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
const table = rows => `<table>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")}</table>`;
function flightPopup(f) {
  const airline = airlineOf(f.callsign);
  const emg = f.squawk && EMERGENCY_SQUAWK[f.squawk];
  return `<div class="fp">${emg ? `<div class="fp-emg">⚠ Transponder: ${emg}</div>` : ""}
    <h5>${esc(f.callsign || "Unknown callsign")}${airline ? ` <span class="fp-al">${esc(airline)}</span>` : ""}</h5>
    ${table([
      ["Operator", airline || `Unknown operator (code: ${esc((f.callsign || "").slice(0, 3)) || "—"})`],
      ["Aircraft (ICAO24)", esc(f.icao24 || "—")],
      ["Registered in", esc(f.country || "—")],
      ["Altitude (barometric)", f.alt_m != null ? `${num(f.alt_m)} m` : "—"],
      ["Altitude (GPS)", f.geo_alt_m != null ? `${num(f.geo_alt_m)} m` : "—"],
      ["Speed", f.velocity_ms != null ? `${kmh(f.velocity_ms)} km/h (${kt(f.velocity_ms)} kt)` : "—"],
      ["Heading", f.heading != null ? `${compassOf(f.heading)}, ${Math.round(f.heading)}°` : "—"],
      ["Vertical rate", vrateLabel(f.vrate_ms)],
      ["On ground", f.on_ground ? "Yes" : "No"],
      ["Squawk (transponder code)", f.squawk ? esc(f.squawk) + (emg ? ` — ${emg}` : "") : "—"],
      ["Position updated", f.age_s != null ? `${f.age_s}s ago` : "—"],
      ["Route", "Not available"],
    ])}
    <p class="fp-src">Live ADS-B data via OpenSky Network. Route (origin → destination) needs a registered OpenSky account, so it isn't shown rather than guessed.</p>
  </div>`;
}

/* ---------- small SVG sparkline (real daily values only; gaps stay gaps) ---------- */
function spark(series, cols, { w = 250, h = 54 } = {}) {
  const pts = series.filter(r => r[1] != null);
  if (pts.length < 2) return "";
  const max = Math.max(...pts.map(r => r[1])) || 1;
  const x = i => (i / (series.length - 1)) * (w - 2) + 1, y = v => h - 2 - (v / max) * (h - 6);
  const path = col => series.map((r, i) => r[col] == null ? null : `${x(i).toFixed(1)},${y(r[col]).toFixed(1)}`).filter(Boolean).join(" ");
  const lines = cols.map(([col, cls]) => `<polyline class="${cls}" points="${path(col)}"/>`).join("");
  return `<svg class="gsp" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="Daily values, last ${series.length} days">${lines}</svg>
    <div class="gsp-ax"><span>${dayTxt(series[0][0])}</span><span>max ${num(max)}</span><span>${dayTxt(series[series.length - 1][0])}</span></div>`;
}
const avg = (arr, col) => { const v = arr.map(r => r[col]).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
// Transit stats straight from the source's daily counts: the last 7 published days against the 90 before them.
export function transitStats(c) {
  const s = (c && c.series) || [];
  if (s.length < 14) return null;
  const last7 = s.slice(-7), base = s.slice(-97, -7);
  const a7 = avg(last7, 1), a90 = avg(base, 1), t7 = avg(last7, 2), c7 = avg(last7, 3);
  return { a7, a90, chg: a7 != null && a90 ? (a7 / a90 - 1) * 100 : null, tanker7: t7, container7: c7, through: s[s.length - 1][0] };
}
const chgHtml = v => v == null ? "—" : `<span class="${v > 0 ? "up" : v < 0 ? "down" : "flat"}">${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(0)}%</span>`;
function transitBlock(c) {
  const st = transitStats(c);
  if (!st) return '<p class="fp-src">No daily ship-transit series published for this chokepoint.</p>';
  const ty = c.annual_by_type || {};
  return `${table([
      ["Ships/day, last 7 days", `${num(st.a7, 1)} (${chgHtml(st.chg)} vs prior 90-day avg ${num(st.a90, 1)})`],
      ["Tankers/day, last 7 days", num(st.tanker7, 1)],
      ["Container ships/day, last 7 days", num(st.container7, 1)],
      ["Vessels in a year (PortWatch reference)", num(c.annual_vessels)],
      ["…of which tankers / container", `${num(ty.tanker)} / ${num(ty.container)}`],
      ["Top cargo by trade value", esc((c.industries || []).join(", ") || "—")],
    ])}
    <div class="gsp-lg"><i class="l-tot"></i>All ships <i class="l-tank"></i>Tankers <i class="l-cont"></i>Container</div>
    ${spark(c.series.slice(-90), [[1, "l-tot"], [2, "l-tank"], [3, "l-cont"]])}
    <p class="fp-src">Daily transit counts from IMF PortWatch (satellite AIS), data through ${esc(dayTxt(st.through))}. The source publishes with a lag of about one to two weeks.</p>`;
}

/* ---------- layer definitions ---------- */
const FUEL_COL = { Coal: "#8d6e63", Gas: "#4fc3f7", Hydro: "#3d8bfd", Nuclear: "#c77dff", Solar: "#ffd166", Wind: "#80ed99", Oil: "#ef476f" };
const ALERT_COL = { RED: "#ff4d4d", Red: "#ff4d4d", ORANGE: "#ff9f1c", Orange: "#ff9f1c", GREEN: "#2ecc71", Green: "#2ecc71" };
const EONET_COL = { Wildfires: "#ff7b00", "Severe Storms": "#4fc3f7", Volcanoes: "#ff4d4d", Floods: "#3d8bfd", "Sea and Lake Ice": "#cfe8ff", Earthquakes: "#ffd166", Drought: "#c9a227", "Dust and Haze": "#bfa58a", Landslides: "#a47148", Snow: "#ffffff", "Temperature Extremes": "#ff006e", "Water Color": "#2ec4b6", Manmade: "#adb5bd" };
const GDACS_TYPE = { TC: "Tropical cyclone", FL: "Flood", EQ: "Earthquake", DR: "Drought", VO: "Volcano", WF: "Wildfire", TS: "Tsunami" };

const LAYERS = [
  { key: "key7", label: "7 key chokepoints", col: "#7fd1a8", on: true, group: "Trade" },
  { key: "ships", label: "Ship transits · 28 chokepoints", col: "#ffb347", on: true, group: "Trade" },
  { key: "ports", label: "India ports · daily calls", col: "#4fc3f7", on: true, group: "Trade" },
  { key: "lanes", label: "Shipping lanes", col: "#5f8f7a", on: true, group: "Trade", file: "lanes" },
  { key: "disrupt", label: "Port-disrupting events (60d)", col: "#ff4d4d", on: true, group: "Trade" },
  { key: "flights", label: "Live aircraft", col: "#ffd166", on: true, group: "Air" },
  { key: "quakes", label: "Earthquakes M4.5+ (7d)", col: "#ffd166", on: true, group: "Hazards" },
  { key: "gdacs", label: "Disaster alerts (GDACS)", col: "#ff9f1c", on: true, group: "Hazards" },
  { key: "eonet", label: "Natural events (NASA EONET)", col: "#ff7b00", on: false, group: "Hazards" },
  { key: "cables", label: "Submarine cables", col: "#9d8cff", on: false, group: "Infrastructure", file: "cables" },
  { key: "power", label: "India power plants ≥100 MW", col: "#8d6e63", on: false, group: "Infrastructure", file: "power_in" },
  { key: "company", label: "Selected stock's sites", col: "#ff6bd6", on: true, group: "Stock", file: "companies" },
];

export class GlobeMap {
  constructor(host, hooks = {}) {
    this.host = host; this.hooks = hooks; this.sel = null; this.markers = new Map();
    this.layers = {}; this.files = {}; this.counts = {}; this.asof = {};
    this.state = Object.assign(Object.fromEntries(LAYERS.map(l => [l.key, l.on])), store.get("globe.layers", {}));
    host.innerHTML = `<div class="globe-wrap">
      <div class="globe-leaflet"></div><div class="globe-msg">Loading the map…</div>
      <div class="globe-co" hidden></div></div>`;
    this.el = host.querySelector(".globe-leaflet"); this.msg = host.querySelector(".globe-msg"); this.coEl = host.querySelector(".globe-co");
    this.ready = this.buildBase();
  }

  async buildBase() {
    try {
      await loadLeaflet();
      const L = window.L;
      this.map = L.map(this.el, { worldCopyJump: true, minZoom: 2, maxZoom: 14, preferCanvas: true, zoomSnap: 0.5 }).setView([20, 60], 2.5);
      const esri = (svc, o = {}) => L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`,
        { maxZoom: 16, attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors, and the GIS user community', ...o });
      const darkLabels = esri("Canvas/World_Dark_Gray_Reference", { pane: "labels" });
      this.map.createPane("labels"); this.map.getPane("labels").style.zIndex = 450; this.map.getPane("labels").style.pointerEvents = "none";
      this.map.createPane("lines"); this.map.getPane("lines").style.zIndex = 350;
      this.bases = {
        dark: L.layerGroup([esri("Canvas/World_Dark_Gray_Base"), darkLabels]),
        sat: L.layerGroup([esri("World_Imagery"), esri("Reference/World_Boundaries_and_Places", { pane: "labels" })]),
        street: L.layerGroup([esri("World_Street_Map")]),
      };
      this.base = store.get("globe.base", "dark");
      (this.bases[this.base] || this.bases.dark).addTo(this.map);
      for (const l of LAYERS) this.layers[l.key] = L.layerGroup();
      L.control.scale({ position: "bottomright", imperial: false }).addTo(this.map);
      this.addControls(L);
      for (const l of LAYERS) if (this.state[l.key]) this.layers[l.key].addTo(this.map);
      this.map.on("mousemove", e => { if (this.coordEl) this.coordEl.textContent = `${e.latlng.lat.toFixed(3)}°, ${(((e.latlng.lng + 540) % 360) - 180).toFixed(3)}°`; });
      for (const l of LAYERS) if (l.file && this.state[l.key] && l.key !== "company") this.loadFileLayer(l);
      this.msg.hidden = true;
    } catch (e) {
      this.msg.textContent = "The map couldn't load (needs an internet connection the first time). The chokepoint cards below still work.";
    }
  }

  addControls(L) {
    const self = this;
    const Panel = L.Control.extend({
      options: { position: "topright" },
      onAdd() {
        const d = L.DomUtil.create("div", "glc");
        L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
        self.panel = d; self.panelOpen = store.get("globe.panel", window.innerWidth > 700);
        self.renderPanel();
        return d;
      },
    });
    new Panel().addTo(this.map);
    const Tools = L.Control.extend({
      options: { position: "topleft" },
      onAdd() {
        const d = L.DomUtil.create("div", "glt leaflet-bar");
        d.innerHTML = `<a href="#" data-t="world" title="Whole world" aria-label="Zoom to whole world">🌐</a><a href="#" data-t="india" title="India" aria-label="Zoom to India">IN</a><a href="#" data-t="full" title="Full screen" aria-label="Toggle full screen">⛶</a>`;
        L.DomEvent.disableClickPropagation(d);
        d.addEventListener("click", e => {
          const a = e.target.closest("[data-t]"); if (!a) return; e.preventDefault();
          if (a.dataset.t === "world") self.map.flyTo([20, 60], 2.5, { duration: 0.8 });
          if (a.dataset.t === "india") self.map.flyToBounds([[6, 67], [36, 98]], { duration: 0.8 });
          if (a.dataset.t === "full") self.toggleFull();
        });
        return d;
      },
    });
    new Tools().addTo(this.map);
    const Coord = L.Control.extend({ options: { position: "bottomleft" }, onAdd() { const d = L.DomUtil.create("div", "glcoord"); self.coordEl = d; d.textContent = "Move over the map for coordinates"; return d; } });
    new Coord().addTo(this.map);
  }

  toggleFull() {
    const box = this.host;
    const on = !box.classList.contains("globe-full");
    box.classList.toggle("globe-full", on);
    document.body.classList.toggle("globe-full-lock", on);
    if (on && box.requestFullscreen) box.requestFullscreen().catch(() => {});
    else if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
    if (!this._fsHook) {
      this._fsHook = true;
      document.addEventListener("fullscreenchange", () => {
        if (!document.fullscreenElement && box.classList.contains("globe-full")) { box.classList.remove("globe-full"); document.body.classList.remove("globe-full-lock"); }
        setTimeout(() => this.map.invalidateSize(), 60);
      });
    }
    setTimeout(() => this.map.invalidateSize(), 60);
  }

  renderPanel() {
    if (!this.panel) return;
    const groups = [...new Set(LAYERS.map(l => l.group))];
    const row = l => {
      const n = this.counts[l.key], a = this.asof[l.key];
      return `<label class="glc-row" title="${esc(a ? a.src + (a.when ? " · " + a.when : "") : "")}">
        <input type="checkbox" data-l="${l.key}" ${this.state[l.key] ? "checked" : ""}>
        <i class="sw" style="background:${l.col}"></i><span class="nm">${esc(l.label)}</span>
        <span class="ct">${n == null ? (this.state[l.key] && l.file && !this.files[l.file] ? "…" : "") : num(n)}</span></label>
        ${a && a.when ? `<div class="glc-asof">${esc(a.when)}</div>` : ""}`;
    };
    this.panel.innerHTML = `<button class="glc-tog" aria-expanded="${this.panelOpen}">${this.panelOpen ? "Layers ▾" : "Layers ▸"}</button>
      <div class="glc-body" ${this.panelOpen ? "" : "hidden"}>
        <div class="glc-base">${[["dark", "Dark"], ["sat", "Satellite"], ["street", "Street"]].map(([k, t]) => `<button data-b="${k}" class="${this.base === k ? "on" : ""}">${t}</button>`).join("")}</div>
        ${groups.map(g => `<div class="glc-g">${esc(g)}</div>${LAYERS.filter(l => l.group === g).map(row).join("")}`).join("")}
        ${this.state.power ? `<div class="glc-key">${Object.entries(FUEL_COL).map(([f, c]) => `<span><i style="background:${c}"></i>${f}</span>`).join("")}</div>` : ""}
        <p class="glc-note">Every layer is real published data; hover a row for its source and time. Nothing here is a forecast.</p>
      </div>`;
    this.panel.querySelector(".glc-tog").onclick = () => { this.panelOpen = !this.panelOpen; store.set("globe.panel", this.panelOpen); this.renderPanel(); };
    this.panel.querySelectorAll("[data-b]").forEach(b => b.onclick = () => this.setBase(b.dataset.b));
    this.panel.querySelectorAll("input[data-l]").forEach(cb => cb.onchange = () => this.toggle(cb.dataset.l, cb.checked));
  }
  setBase(k) {
    if (!this.bases[k] || k === this.base) return;
    this.map.removeLayer(this.bases[this.base]); this.bases[k].addTo(this.map); this.base = k;
    store.set("globe.base", k); this.renderPanel();
  }
  toggle(key, on) {
    this.state[key] = on; store.set("globe.layers", this.state);
    const lg = this.layers[key];
    if (on) { lg.addTo(this.map); const l = LAYERS.find(x => x.key === key); if (l.file) this.loadFileLayer(l); }
    else this.map.removeLayer(lg);
    this.renderPanel();
  }

  async file(name) {
    if (!this.files[name]) this.files[name] = fetch(`globe/layers/${name}.json`, { cache: "default" }).then(r => r.ok ? r.json() : null).catch(() => null);
    return this.files[name];
  }
  async loadFileLayer(l) {
    if (l.key === "company") { if (this.company) this.drawCompany(); return; }
    if (this.layers[l.key].getLayers().length) return;
    this.renderPanel();
    const d = await this.file(l.file);
    if (!d) { this.counts[l.key] = 0; this.asof[l.key] = { src: "Not published yet", when: "Not published yet" }; this.renderPanel(); return; }
    const L = window.L, lg = this.layers[l.key];
    if (l.key === "lanes") {
      const sty = { Major: { weight: 2, opacity: 0.55 }, Middle: { weight: 1.2, opacity: 0.4 }, Minor: { weight: 0.8, opacity: 0.28, dashArray: "3 4" } };
      for (const ln of d.lines) L.polyline(ln.c, { pane: "lines", color: l.col, interactive: false, ...(sty[ln.t] || sty.Minor) }).addTo(lg);
      this.counts.lanes = d.lines.length;
      this.asof.lanes = { src: d.source, when: "Reference map (CIA 2012, revised 2022)" };
    } else if (l.key === "cables") {
      for (const c of d.cables) L.polyline(c.segs, { pane: "lines", color: c.col || l.col, weight: 1.3, opacity: 0.7 })
        .bindTooltip(esc(c.n)).bindPopup(`<b>${esc(c.n)}</b><br><span class="mut">Submarine cable · TeleGeography</span>${c.id ? `<br><a href="https://www.submarinecablemap.com/submarine-cable/${esc(c.id)}" target="_blank" rel="noopener">Details ↗</a>` : ""}`, { className: "globe-popup" }).addTo(lg);
      for (const p of d.landings) {
        const india = /, India$/.test(p.n || "");
        L.circleMarker([p.lat, p.lon], { radius: india ? 4 : 2.5, color: india ? "#fff" : l.col, weight: india ? 1.5 : 0, fillColor: l.col, fillOpacity: 0.9 })
          .bindTooltip(`${esc(p.n)} · cable landing`).addTo(lg);
      }
      this.counts.cables = d.cables.length;
      this.asof.cables = { src: d.source, when: `Fetched ${agoTxt(d.generated_utc)}` };
    } else if (l.key === "power") {
      for (const p of d.plants) {
        const r = Math.max(3, Math.min(13, Math.sqrt(p.mw) / 6));
        L.circleMarker([p.lat, p.lon], { radius: r, color: "#000", weight: 0.6, fillColor: FUEL_COL[p.f] || "#adb5bd", fillOpacity: 0.85 })
          .bindTooltip(`${esc(p.n)} · ${num(p.mw)} MW ${esc(p.f)}`)
          .bindPopup(`<div class="fp"><h5>${esc(p.n)}</h5>${table([["Capacity", `${num(p.mw)} MW`], ["Primary fuel", esc(p.f)], ["Commissioned", esc(p.y || "—")], ["Owner (as recorded)", esc(p.o || "Not recorded in the database")]])}
            <p class="fp-src">${esc(d.source)}. Reference data, not live.</p></div>`, { className: "globe-popup fp-popup", maxWidth: 280 }).addTo(lg);
      }
      this.counts.power = d.plants.length;
      this.asof.power = { src: d.source, when: "Data vintage 2019–2021" };
    }
    this.renderPanel();
  }

  async update(data) {
    await this.ready;
    if (!this.map) return;
    const L = window.L;
    this.data = data;
    const pw = data.portwatch || null, hz = data.hazards || {};
    this.pwById = new Map(((pw && pw.chokepoints) || []).map(c => [c.id, c]));

    // live aircraft, drawn as planes pointing along their real heading
    const fl = this.layers.flights; fl.clearLayers(); let nf = 0;
    for (const p of data.chokepoints || []) for (const f of (p.flights && p.flights.sample) || []) {
      if (f.lat == null) continue; nf++;
      const airline = airlineOf(f.callsign), emg = f.squawk && EMERGENCY_SQUAWK[f.squawk];
      L.marker([f.lat, f.lon], { icon: L.divIcon({ className: "gplane-wrap", iconSize: [16, 16], iconAnchor: [8, 8],
          html: `<span class="gplane${emg ? " emg" : ""}${f.on_ground ? " gnd" : ""}" style="transform:rotate(${Math.round(f.heading || 0)}deg)">✈</span>` }), keyboard: false })
        .bindTooltip(`${esc(f.callsign || "flight")}${airline ? " · " + esc(airline) : ""}${f.alt_m != null ? " · " + num(f.alt_m) + " m" : ""}`)
        .bindPopup(flightPopup(f), { className: "globe-popup fp-popup", minWidth: 250, maxWidth: 280 })
        .addTo(fl);
    }
    this.counts.flights = nf;
    this.asof.flights = { src: "OpenSky Network, live ADS-B (sample per chokepoint)", when: data.generated_utc ? `Updated ${agoTxt(data.generated_utc)}` : "" };

    // the 7 key chokepoints (pins tied to the cards below the map)
    this.layers.key7.clearLayers(); this.markers.clear();
    for (const p of data.chokepoints || []) {
      const n = (p.flights && p.flights.count) || 0, c = p.portwatch_id && this.pwById.get(p.portwatch_id), st = transitStats(c);
      const m = L.marker([p.lat, p.lon], { icon: pinIcon(this.flagOf(p.id)), keyboard: true, alt: p.name, title: p.name, zIndexOffset: 500 })
        .bindPopup(`<div class="fp"><h5>${esc(p.name)}</h5><p class="why">${esc(p.why)}</p>
          ${table([["Aircraft overhead now", num(n)], ...(st ? [["Ships/day, last 7 days", `${num(st.a7, 1)} (${chgHtml(st.chg)} vs 90d)`]] : [])])}
          ${c ? transitBlock(c) : ""}</div>`, { className: "globe-popup fp-popup", minWidth: 270, maxWidth: 290 })
        .on("click", () => this.select(p.id))
        .addTo(this.layers.key7);
      const elm = m.getElement(); if (elm) elm.setAttribute("data-id", p.id);
      this.markers.set(p.id, m);
    }
    this.counts.key7 = (data.chokepoints || []).length;
    this.asof.key7 = { src: "OpenSky (aircraft) · IMF PortWatch (ships) · GDELT / Google News (headlines)", when: data.generated_utc ? `Updated ${agoTxt(data.generated_utc)}` : "" };

    // ship transits through all 28 chokepoints, sized by the last 7 days' daily average
    const sl = this.layers.ships; sl.clearLayers();
    for (const c of (pw && pw.chokepoints) || []) {
      const st = transitStats(c); const a = st ? st.a7 : 0;
      const col = !st || st.chg == null ? "#ffb347" : st.chg <= -15 ? "#ff4d4d" : st.chg >= 15 ? "#2ecc71" : "#ffb347";
      L.circleMarker([c.lat, c.lon], { radius: Math.max(5, Math.min(22, Math.sqrt(a || 1) * 2.2)), color: col, weight: 2, fillColor: col, fillOpacity: 0.22 })
        .bindTooltip(`${esc(c.name)}${st ? ` · ${num(st.a7, 0)} ships/day (${st.chg == null ? "—" : (st.chg > 0 ? "+" : "") + st.chg.toFixed(0) + "%"} vs 90d)` : ""}`)
        .bindPopup(`<div class="fp"><h5>${esc(c.name)}</h5>${transitBlock(c)}</div>`, { className: "globe-popup fp-popup", minWidth: 270, maxWidth: 290 })
        .addTo(sl);
    }
    this.counts.ships = ((pw && pw.chokepoints) || []).length || null;
    this.asof.ships = pw ? { src: pw.source, when: `Data through ${dayTxt(pw.data_through)}` } : { src: "IMF PortWatch", when: "Not published yet" };

    // India's ports: daily port calls
    const pl = this.layers.ports; pl.clearLayers();
    for (const p of (pw && pw.india_ports) || []) {
      const ci = (p.fields || []).indexOf("portcalls") + 1;
      const s = p.series || [], last7 = ci ? avg(s.slice(-7), ci) : null, prev = ci ? avg(s.slice(-35, -7), ci) : null;
      const chg = last7 != null && prev ? (last7 / prev - 1) * 100 : null;
      L.circleMarker([p.lat, p.lon], { radius: Math.max(4, Math.min(16, Math.sqrt(last7 || p.annual_vessels / 365 || 1) * 2.4)), color: "#4fc3f7", weight: 1.5, fillColor: "#4fc3f7", fillOpacity: 0.35 })
        .bindTooltip(`${esc(p.name)} port${last7 != null ? ` · ${num(last7, 1)} calls/day` : ""}`)
        .bindPopup(`<div class="fp"><h5>${esc(p.name)} port</h5>${table([
            ["Port calls/day, last 7 days", last7 != null ? `${num(last7, 1)} (${chgHtml(chg)} vs the 4 weeks before)` : "—"],
            ["Vessels in a year (reference)", num(p.annual_vessels)],
            ["Top cargo by trade value", esc((p.industries || []).join(", ") || "—")],
          ])}${ci ? `<div class="gsp-lg"><i class="l-tot"></i>Port calls per day</div>${spark(s.slice(-60).map(r => [r[0], r[ci]]), [[1, "l-tot"]])}` : ""}
          <p class="fp-src">IMF PortWatch (satellite AIS)${s.length ? `, data through ${esc(dayTxt(s[s.length - 1][0]))}` : ""}.</p></div>`, { className: "globe-popup fp-popup", minWidth: 270, maxWidth: 290 })
        .addTo(pl);
    }
    this.counts.ports = ((pw && pw.india_ports) || []).length || null;
    this.asof.ports = pw ? { src: pw.source, when: `Data through ${dayTxt(pw.data_through)}` } : { src: "IMF PortWatch", when: "Not published yet" };

    // port-disrupting events (PortWatch's own list, from GDACS)
    const dl = this.layers.disrupt; dl.clearLayers();
    for (const d of (pw && pw.disruptions) || []) {
      const col = ALERT_COL[d.alert] || "#ff9f1c";
      L.marker([d.lat, d.lon], { icon: L.divIcon({ className: "gdis-wrap", iconSize: [18, 18], iconAnchor: [9, 9], html: `<span class="gdis" style="border-color:${col};color:${col}">!</span>` }) })
        .bindTooltip(esc(d.name))
        .bindPopup(`<div class="fp"><h5>${esc(d.name)}</h5>${table([["Alert level", `<span style="color:${col}">${esc(d.alert || "—")}</span>`], ["Type", esc(GDACS_TYPE[d.type] || d.type || "—")],
          ["Severity", esc(d.severity || "—")], ["Dates", `${esc(dayTxt(d.from))} → ${esc(dayTxt(d.to))}`], ["Ports affected", num(d.ports_hit)]])}
          <p class="fp-src">IMF PortWatch disruptions list.</p></div>`, { className: "globe-popup fp-popup", maxWidth: 290 }).addTo(dl);
    }
    this.counts.disrupt = ((pw && pw.disruptions) || []).length;
    this.asof.disrupt = pw ? { src: "IMF PortWatch disruptions (GDACS-based)", when: `Fetched ${agoTxt(pw.fetched_utc)}` } : { src: "IMF PortWatch", when: "Not published yet" };

    // earthquakes
    const ql = this.layers.quakes; ql.clearLayers();
    const qs = (hz.quakes && hz.quakes.items) || [];
    for (const q of qs) {
      const col = q.mag >= 6.5 ? "#ff4d4d" : q.mag >= 5.5 ? "#ff9f1c" : "#ffd166";
      L.circleMarker([q.lat, q.lon], { radius: Math.max(3, (q.mag - 4) * 4), color: col, weight: 1, fillColor: col, fillOpacity: 0.45 })
        .bindTooltip(`M${q.mag} · ${esc(q.place || "")}`)
        .bindPopup(`<div class="fp"><h5>M${esc(q.mag)} earthquake</h5>${table([["Where", esc(q.place || "—")], ["When", `${esc(new Date(q.time_utc).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }))} IST (${agoTxt(q.time_utc)})`],
          ["Depth", `${num(q.depth_km)} km`], ["Tsunami flag", q.tsunami ? "Yes" : "No"], ["USGS impact alert", esc(q.alert || "none")]])}
          ${q.url ? `<a href="${esc(q.url)}" target="_blank" rel="noopener">USGS event page ↗</a>` : ""}</div>`, { className: "globe-popup fp-popup", maxWidth: 290 }).addTo(ql);
    }
    this.counts.quakes = qs.length;
    this.asof.quakes = hz.quakes ? { src: "USGS Earthquake Hazards Program", when: `Fetched ${agoTxt(hz.quakes.fetched_utc)}` } : { src: "USGS", when: "Not published yet" };

    // GDACS alerts
    const gl = this.layers.gdacs; gl.clearLayers();
    const gs = (hz.gdacs && hz.gdacs.items) || [];
    for (const g of gs) {
      const col = ALERT_COL[g.alert] || "#2ecc71";
      L.circleMarker([g.lat, g.lon], { radius: g.alert === "Red" ? 9 : g.alert === "Orange" ? 7 : 5, color: col, weight: 2, fillColor: col, fillOpacity: 0.15, dashArray: "2 2" })
        .bindTooltip(`${esc(GDACS_TYPE[g.type] || g.type)} · ${esc(g.name || g.country || "")} · ${esc(g.alert || "")}`)
        .bindPopup(`<div class="fp"><h5>${esc(GDACS_TYPE[g.type] || g.type)}: ${esc(g.name || "")}</h5>${table([["Alert level", `<span style="color:${col}">${esc(g.alert || "—")}</span>`], ["Country", esc(g.country || "—")],
          ["Severity", esc(g.severity || "—")], ["Dates", `${esc(dayTxt(g.from))} → ${esc(dayTxt(g.to))}`]])}${g.url ? `<a href="${esc(g.url)}" target="_blank" rel="noopener">GDACS report ↗</a>` : ""}</div>`, { className: "globe-popup fp-popup", maxWidth: 290 }).addTo(gl);
    }
    this.counts.gdacs = gs.length;
    this.asof.gdacs = hz.gdacs ? { src: "GDACS (UN / European Commission)", when: `Fetched ${agoTxt(hz.gdacs.fetched_utc)}` } : { src: "GDACS", when: "Not published yet" };

    // NASA EONET
    const el = this.layers.eonet; el.clearLayers();
    const es = (hz.eonet && hz.eonet.items) || [];
    for (const e of es) {
      const col = EONET_COL[e.cat] || "#adb5bd";
      if (e.track && e.track.length > 1) L.polyline(e.track, { color: col, weight: 1.5, opacity: 0.6, dashArray: "4 3", interactive: false }).addTo(el);
      L.circleMarker([e.lat, e.lon], { radius: 4, color: col, weight: 1, fillColor: col, fillOpacity: 0.8 })
        .bindTooltip(`${esc(e.cat)} · ${esc(e.title)}`)
        .bindPopup(`<div class="fp"><h5>${esc(e.title)}</h5>${table([["Category", esc(e.cat)], ["Last observed", e.date ? `${esc(dayTxt(e.date.slice(0, 10)))} (${agoTxt(e.date)})` : "—"]])}
          ${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">Source ↗</a>` : ""}<p class="fp-src">NASA EONET.</p></div>`, { className: "globe-popup fp-popup", maxWidth: 290 }).addTo(el);
    }
    this.counts.eonet = es.length;
    this.asof.eonet = hz.eonet ? { src: "NASA Earth Observatory Natural Event Tracker", when: `Fetched ${agoTxt(hz.eonet.fetched_utc)}` } : { src: "NASA EONET", when: "Not published yet" };

    this.renderPanel();
  }

  /* the open stock's physical footprint, from Wikidata */
  async setCompany(sym, name) {
    this.company = sym ? { sym, name } : null;
    await this.ready;
    if (!this.map) return;
    if (this.state.company) this.drawCompany();
  }
  async drawCompany(fly = false) {
    const L = window.L, lg = this.layers.company; lg.clearLayers();
    const co = this.company;
    if (!co) { this.coEl.hidden = true; this.counts.company = null; this.renderPanel(); return; }
    const d = await this.file("companies");
    if (this.company !== co) return;
    const rec = d && d.companies ? d.companies[co.sym] : null;
    this.asof.company = d ? { src: d.source, when: `Fetched ${agoTxt(d.generated_utc)}` } : { src: "Wikidata", when: "Not published yet" };
    const pts = [];
    if (rec && rec.hq) {
      L.marker([rec.hq.lat, rec.hq.lon], { icon: L.divIcon({ className: "gco-wrap", iconSize: [20, 20], iconAnchor: [10, 10], html: '<span class="gco hq">★</span>' }), zIndexOffset: 900 })
        .bindTooltip(`${esc(co.sym)} headquarters · ${esc(rec.hq.n || "")}`).addTo(lg);
      pts.push([rec.hq.lat, rec.hq.lon]);
    }
    for (const s of (rec && rec.sites) || []) {
      L.marker([s.lat, s.lon], { icon: L.divIcon({ className: "gco-wrap", iconSize: [14, 14], iconAnchor: [7, 7], html: '<span class="gco"></span>' }), zIndexOffset: 800 })
        .bindTooltip(esc(s.n || s.q))
        .bindPopup(`<div class="fp"><h5>${esc(s.n || s.q)}</h5>${table([["Company", esc(co.sym)], ["Type", esc((s.types || []).join(", ") || "—")],
          ["Link", esc(s.rel === "via subsidiary" ? `via subsidiary ${s.via || ""}` : s.rel === "operator" ? "operated by the company" : "owned by the company")]])}
          <a href="https://www.wikidata.org/wiki/${esc(s.q)}" target="_blank" rel="noopener">Wikidata ↗</a></div>`, { className: "globe-popup fp-popup", maxWidth: 280 }).addTo(lg);
      pts.push([s.lat, s.lon]);
    }
    this.counts.company = pts.length;
    const nm = co.name || (rec && rec.name) || co.sym;
    this.coEl.hidden = false;
    this.coEl.innerHTML = !d ? `<b>${esc(co.sym)}</b> · company sites layer not published yet`
      : !rec ? `<b>${esc(co.sym)}</b> · Wikidata has no mapped locations for ${esc(nm)}`
      : `<b>${esc(co.sym)}</b> · ${rec.hq ? "HQ" : "no HQ"} + ${num((rec.sites || []).length)} site${(rec.sites || []).length === 1 ? "" : "s"} on Wikidata
         ${pts.length ? `<button data-fly>Show on map</button>` : ""}
         ${(rec.sites || []).length ? `<details><summary>List</summary><ul>${rec.sites.slice(0, 60).map((s, i) => `<li><a href="#" data-i="${i}">${esc(s.n || s.q)}</a> <span>${esc((s.types || [])[0] || "")}</span></li>`).join("")}</ul></details>` : ""}`;
    const b = this.coEl.querySelector("[data-fly]");
    const fit = () => pts.length === 1 ? this.map.flyTo(pts[0], 8, { duration: 0.8 }) : this.map.flyToBounds(pts, { padding: [40, 40], maxZoom: 9, duration: 0.8 });
    if (b) b.onclick = fit;
    this.coEl.querySelectorAll("[data-i]").forEach(a => a.onclick = e => { e.preventDefault(); const s = rec.sites[+a.dataset.i]; this.map.flyTo([s.lat, s.lon], 10, { duration: 0.8 }); });
    if (fly && pts.length) fit();
    this.renderPanel();
  }

  flagOf(id) {                                              // "active"/"quiet": this run's own count vs. the 7-point average (see terminal.js activityFlag)
    const pts = (this.data && this.data.chokepoints) || [];
    const counts = pts.map(p => (p.flights && p.flights.count) || 0), av = counts.reduce((a, b) => a + b, 0) / (counts.length || 1);
    const n = (pts.find(p => p.id === id)?.flights?.count) || 0;
    const cls = av <= 0 ? "" : n >= av * 1.5 ? "active" : n <= av * 0.3 ? "quiet" : "";
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
    if (this.sel && this.map) { const p = (this.data.chokepoints || []).find(x => x.id === this.sel); if (p) this.map.flyTo([p.lat, p.lon], Math.max(this.map.getZoom(), 6), { duration: 0.8 }); }
    this.hooks.onSelect?.(this.sel);
  }
}
