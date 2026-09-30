/* B-LAB globe: a self-contained world-map renderer. No API key, no billing, no tile server.
   - The world outline is real country geometry (Natural Earth via the "world-atlas" npm package, ISC-licensed,
     loaded once from jsdelivr and cached) decoded with "topojson-client" (also from jsdelivr, ISC-licensed) -
     the same trusted-CDN pattern this app already uses for Lightweight Charts.
   - Coordinates are projected with a plain equirectangular formula (no map-tile dependency, works offline
     once the two files above are cached), so every marker (chokepoints, live flights) sits on the same map.
   - Data (data/globe/latest.json, from scripts/globe_data.py): real live flight positions near each of 7
     shipping/oil chokepoints (OpenSky Network) and real news about each one and about world events generally
     (GDELT Project). There is no free live cargo-ship position source, so ships are not drawn; each
     chokepoint's card carries real news instead. "Why it matters" lines are static reference facts, shown
     separately from the live flight/news data next to them. */

const TOPOJSON_SRC = "https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js";
const WORLD_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";
let topoLoad = null;
function loadTopojsonLib() {
  if (window.topojson) return Promise.resolve();
  if (topoLoad) return topoLoad;
  topoLoad = new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = TOPOJSON_SRC; s.onload = res; s.onerror = () => rej(new Error("topojson-client failed to load"));
    document.head.appendChild(s);
  });
  return topoLoad;
}
let worldGeo = null;
async function loadWorld() {
  if (worldGeo) return worldGeo;
  await loadTopojsonLib();
  const topo = await fetch(WORLD_URL).then(r => { if (!r.ok) throw new Error("world map: " + r.status); return r.json(); });
  worldGeo = window.topojson.feature(topo, topo.objects.countries);
  return worldGeo;
}

const project = (lon, lat, W, H) => [(lon + 180) / 360 * W, (90 - lat) / 180 * H];
function ringPath(ring, W, H) {
  let d = "";
  for (let i = 0; i < ring.length; i++) { const [x, y] = project(ring[i][0], ring[i][1], W, H); d += (i ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1); }
  return d + "Z";
}
function geomPath(geom, W, H) {
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
  return polys.map(poly => poly.map(ring => ringPath(ring, W, H)).join(" ")).join(" ");
}

export class GlobeMap {
  constructor(host, hooks = {}) {
    this.host = host; this.hooks = hooks; this.W = 960; this.H = 500; this.sel = null;
    host.innerHTML = '<div class="globe-wrap"><svg class="globe-svg" viewBox="0 0 960 500" preserveAspectRatio="xMidYMid meet"></svg><div class="globe-msg">Loading the world map…</div></div>';
    this.svg = host.querySelector(".globe-svg"); this.msg = host.querySelector(".globe-msg");
    this.ready = this.buildBase();
  }
  async buildBase() {
    try {
      const geo = await loadWorld();
      const { W, H } = this;
      const ocean = `<rect class="globe-ocean" x="0" y="0" width="${W}" height="${H}"/>`;
      const grat = this.graticule();
      const land = geo.features.map(f => `<path class="globe-country" d="${geomPath(f.geometry, W, H)}"><title>${(f.properties && f.properties.name) || ""}</title></path>`).join("");
      this.svg.innerHTML = `${ocean}${grat}<g class="globe-land">${land}</g><g class="globe-flights"></g><g class="globe-chokes"></g>`;
      this.msg.hidden = true;
    } catch (e) {
      this.msg.textContent = "The world map couldn't load (needs an internet connection the first time). Chokepoint cards below still work.";
    }
  }
  graticule() {
    const { W, H } = this; let d = "";
    for (let lon = -180; lon <= 180; lon += 30) { const [x] = project(lon, 0, W, H); d += `M${x.toFixed(1)},0L${x.toFixed(1)},${H} `; }
    for (let lat = -60; lat <= 60; lat += 30) { const [, y] = project(0, lat, W, H); d += `M0,${y.toFixed(1)}L${W},${y.toFixed(1)} `; }
    return `<path class="globe-grid" d="${d}"/>`;
  }
  async update(data) {
    await this.ready;
    const { W, H } = this;
    this.data = data;
    const fg = this.svg.querySelector(".globe-flights"), cg = this.svg.querySelector(".globe-chokes");
    if (!fg || !cg) return;                            // base map failed to load; cards below still render from renderCards()
    const flights = [];
    for (const p of data.chokepoints || []) for (const f of (p.flights && p.flights.sample) || []) flights.push(f);
    fg.innerHTML = flights.map(f => { const [x, y] = project(f.lon, f.lat, W, H), r = ((f.heading || 0) - 90); return f.lat == null ? "" :
      `<path class="globe-plane" transform="translate(${x.toFixed(1)},${y.toFixed(1)}) rotate(${r.toFixed(0)})" d="M-3,0 L4,-2 L4,2 Z"><title>${esc(f.callsign || "flight")} · ${f.alt_m != null ? Math.round(f.alt_m) + " m" : ""}</title></path>`; }).join("");
    const pts = data.chokepoints || [];
    const counts = pts.map(p => (p.flights && p.flights.count) || 0), avg = counts.reduce((a, b) => a + b, 0) / (counts.length || 1);
    const flag = n => avg <= 0 ? "" : n >= avg * 1.5 ? " active" : n <= avg * 0.3 ? " quiet" : "";  // same-run comparison, see terminal.js activityFlag()
    cg.innerHTML = pts.map(p => { const [x, y] = project(p.lon, p.lat, W, H), n = (p.flights && p.flights.count) || 0;
      return `<g class="globe-choke${flag(n)}${this.sel === p.id ? " on" : ""}" data-id="${esc(p.id)}" transform="translate(${x.toFixed(1)},${y.toFixed(1)})" tabindex="0" role="button" aria-label="${esc(p.name)}">
        <circle class="hit" r="14"/><circle class="ring" r="10"/><circle class="dot" r="4"/><text x="9" y="-8">${esc(p.name)}${n ? ` · ${n}` : ""}</text></g>`; }).join("");
    cg.querySelectorAll(".globe-choke").forEach(g => {
      g.onclick = g.onkeydown = e => { if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return; this.select(g.dataset.id); };
    });
  }
  select(id) {
    this.sel = this.sel === id ? null : id;
    this.svg.querySelectorAll(".globe-choke").forEach(g => g.classList.toggle("on", g.dataset.id === this.sel));
    this.hooks.onSelect?.(this.sel);
  }
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
