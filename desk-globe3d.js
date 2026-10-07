/* The WebGL globe (V4 8.8): a Three.js scene with a Globe | Flat toggle, dead-reckoned flights and vessels, fading trails, picking and a performance governor.
   Loaded only when someone opens Globe or Flat (three.js itself is imported then, from jsDelivr, pinned). If WebGL is missing or the context is lost, desk-globe.js falls back to
   its flat D3 canvas with a one-line notice. The moving parts that can be tested without a browser (prediction, smoothing, trails, picking, governor) live in desk-kin-live.js.
   Colours are read from the CSS variables at runtime: there are no colour literals here. ALADIN is a statistical model built by students. It is often wrong. Educational
   analysis only, not investment advice. */
import { makeEntity, applyFix, renderPos, isGhost, isGone, isStill, Trail, PickGrid, Governor, TELE } from "./desk-kin-live.js";
import { hotspotColor, hotspotRadius } from "./desk-lanes.js";

export const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.min.js";
const RAD = Math.PI / 180, R = 1;
const INDIA = [22, 79];
let THREE_P = null;
export const loadThree = () => THREE_P || (THREE_P = import(THREE_URL));

/* true when the browser draws WebGL in software (SwiftShader, llvmpipe, "Microsoft Basic Render"): multisampling there multiplies the cost, so it is left off */
export function softwareGL() {
  try {
    const c = document.createElement("canvas"), g = c.getContext("webgl2") || c.getContext("webgl"), e = g && g.getExtension("WEBGL_debug_renderer_info");
    const name = e ? String(g.getParameter(e.UNMASKED_RENDERER_WEBGL)) : "";
    return /swiftshader|llvmpipe|software|basic render/i.test(name);
  } catch (err) { return false; }
}
export function webglOk() {
  try { const c = document.createElement("canvas"); return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"))); } catch (e) { return false; }
}

/* lat/lon (degrees) -> position on the unit sphere. lon 0 faces +x, north is +y. */
export const sphere = (lat, lon, r = R) => [r * Math.cos(lat * RAD) * Math.cos(lon * RAD), r * Math.sin(lat * RAD), -r * Math.cos(lat * RAD) * Math.sin(lon * RAD)];
/* lat/lon -> the equirectangular plane (2 x 1 units) */
export const plane = (lat, lon) => [lon / 180, lat / 180, 0];

const MARKER_VS = `
attribute float aSize; attribute vec3 aColor; attribute float aAlpha; attribute float aRing;
uniform float uPx; uniform float uGlobe; uniform vec3 uCam;
varying vec3 vColor; varying float vAlpha; varying float vRing;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  float vis = 1.0;
  if (uGlobe > 0.5) vis = step(0.06, dot(normalize(wp.xyz), normalize(uCam)));
  vec4 mv = viewMatrix * wp;
  gl_Position = projectionMatrix * mv;
  float att = uGlobe > 0.5 ? clamp(3.4 / max(0.3, -mv.z), 0.7, 1.7) : 1.0;
  gl_PointSize = aSize * uPx * att;
  vColor = aColor; vAlpha = aAlpha * vis; vRing = aRing;
}`;
const MARKER_FS = `
precision highp float; uniform float uShape;
varying vec3 vColor; varying float vAlpha; varying float vRing;
void main() {
  vec2 c = gl_PointCoord - 0.5;
  float d = uShape < 0.5 ? length(c) * 2.0 : (uShape < 1.5 ? max(abs(c.x), abs(c.y)) * 2.0 : (abs(c.x) + abs(c.y)) * 1.6);
  float fill = smoothstep(1.0, 0.82, d);
  if (vRing > 0.5) fill *= smoothstep(0.5, 0.68, d);
  float a = fill * vAlpha;
  if (a < 0.02) discard;
  gl_FragColor = vec4(vColor, a);
}`;
const TRAIL_VS = `
attribute float aT; attribute vec3 aColor;
uniform float uNow; uniform float uFade; uniform float uGlobe; uniform float uSel; uniform vec3 uCam;
varying vec3 vColor; varying float vAlpha;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  float vis = 1.0;
  if (uGlobe > 0.5) vis = step(0.04, dot(normalize(wp.xyz), normalize(uCam)));
  gl_Position = projectionMatrix * viewMatrix * wp;
  float fade = uSel > 0.5 ? 1.0 : clamp(1.0 - (uNow - aT) / uFade, 0.0, 1.0);
  vColor = aColor; vAlpha = fade * vis * 0.85;
}`;
const TRAIL_FS = `
precision highp float; varying vec3 vColor; varying float vAlpha;
void main() { if (vAlpha < 0.02) discard; gl_FragColor = vec4(vColor, vAlpha); }`;

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888888";

/* ---------------------------------------------------------------------------------------------------------------------------------------------- */
export async function create(opts) {
  const THREE = await loadThree();
  return new Globe3D(THREE, opts);
}

class Globe3D {
  /* opts: { canvas, wrap, ctx, lib (d3 libs + land/countries/india), hooks: { pick(e), hover(e, x, y), governor(g), lost() } } */
  constructor(THREE, opts) {
    this.T = THREE; this.o = opts; this.hooks = opts.hooks || {};
    this.canvas = opts.canvas;
    this.software = softwareGL();
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: !this.software, alpha: false, powerPreference: "high-performance" });
    this.renderer.setClearColor(new THREE.Color(css("--paper")), 1);
    this.canvas.addEventListener("webglcontextlost", e => { e.preventDefault(); this.lost = true; this.stop(); this.hooks.lost && this.hooks.lost(); });
    this.reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.mode = "globe"; this.opened = false; this.lost = false;
    this.gov = new Governor();
    this.live = new Map(); this.statics = []; this.layers = {}; this.lanes = null;
    this.view = { lat: INDIA[0], lon: INDIA[1], zoom: 1, panX: 0, panY: 0, vLat: 0, vLon: 0 };      // vLat / vLon: inertia (degrees per second)
    this.grid = new PickGrid(); this.gridT = 0; this.listPts = [];
    this.sel = null; this.follow = false; this.t0 = Math.floor(Date.now() / 1000);
    this.frames = []; this.js = []; this.fps = 0; this.lastFrame = 0; this.raf = 0; this.idleSince = performance.now();
    this.trails = new Map(); this.trailBuilt = 0;
    this.W = 1; this.H = 1;
  }

  now() { return this.o.ctx && this.o.ctx.serverNow ? this.o.ctx.serverNow() : Date.now() / 1000; }

  /* ---------- scene ---------- */
  open(mode) {
    const T = this.T;
    this.mode = mode;
    if (!this.opened) {
      this.opened = true;
      this.scene = new T.Scene();
      this.group = new T.Group(); this.scene.add(this.group);
      this.persp = new T.PerspectiveCamera(35, 1, 0.05, 20);
      this.ortho = new T.OrthographicCamera(-1, 1, 0.5, -0.5, -5, 5);
      this.bake();
      this.buildBodies();
      this.bind();
    }
    this.setMode(mode);
    this.resize();
    this.start();
  }
  /* the land, borders, India and a faint graticule, drawn once into a 4096 x 2048 texture with d3-geo (equirectangular) */
  bake() {
    const T = this.T, { geo, land, countries, india } = this.o.lib;
    const W = 4096, H = 2048, c = document.createElement("canvas"); c.width = W; c.height = H;
    const g = c.getContext("2d"), proj = geo.geoEquirectangular().fitExtent([[0, 0], [W, H]], { type: "Sphere" }), path = geo.geoPath(proj, g);
    g.fillStyle = css("--card"); g.fillRect(0, 0, W, H);
    g.beginPath(); path(geo.geoGraticule10()); g.strokeStyle = css("--rule"); g.globalAlpha = 0.5; g.lineWidth = 1; g.stroke(); g.globalAlpha = 1;
    g.beginPath(); path(land); g.fillStyle = css("--sunken"); g.fill();
    g.beginPath(); for (const f of countries.features) path(f); g.strokeStyle = css("--rule-2"); g.lineWidth = 1.2; g.stroke();
    if (india) { g.beginPath(); path(india); g.strokeStyle = css("--acc"); g.lineWidth = 2.6; g.stroke(); }
    this.tex = new T.CanvasTexture(c); this.tex.colorSpace = T.SRGBColorSpace; this.tex.anisotropy = this.software ? 1 : Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
  }
  buildBodies() {
    const T = this.T;
    const mat = new T.MeshBasicMaterial({ map: this.tex });
    this.globeMesh = new T.Mesh(new T.SphereGeometry(R, 96, 64), mat);
    this.flatMesh = new T.Mesh(new T.PlaneGeometry(2, 1), mat);
    this.group.add(this.globeMesh); this.scene.add(this.flatMesh);
    const base = { transparent: true, depthWrite: false, depthTest: false };         // no depth test: a camera-facing sprite on a tilted sphere would be cut by the surface; the back hemisphere is culled in the shader instead
    const marker = shape => new T.ShaderMaterial({ ...base, vertexShader: MARKER_VS, fragmentShader: MARKER_FS, uniforms: { uPx: { value: 1 }, uGlobe: { value: 1 }, uCam: { value: new T.Vector3(0, 0, 3.5) }, uShape: { value: shape } } });
    this.matCircle = marker(0); this.matSquare = marker(1); this.matDiamond = marker(2);
    this.trailMat = new T.ShaderMaterial({ ...base, vertexShader: TRAIL_VS, fragmentShader: TRAIL_FS, uniforms: { uNow: { value: 0 }, uFade: { value: TELE.trailFadeS }, uGlobe: { value: 1 }, uSel: { value: 0 }, uCam: { value: new T.Vector3(0, 0, 3.5) } } });
    this.selTrailMat = this.trailMat.clone(); this.selTrailMat.uniforms = { uNow: { value: 0 }, uFade: { value: TELE.trailFadeS }, uGlobe: { value: 1 }, uSel: { value: 1 }, uCam: this.trailMat.uniforms.uCam };
    this.dyn = new T.Group(); this.group.add(this.dyn);      // everything that is rebuilt on a data or layer change; geometries are disposed with it
    this.points = { cargo: this.mkPoints(this.matCircle), air: this.mkPoints(this.matCircle), ship: this.mkPoints(this.matSquare) };
    for (const p of Object.values(this.points)) this.group.add(p.obj);
    this.trailObj = new T.LineSegments(new T.BufferGeometry(), this.trailMat); this.trailObj.frustumCulled = false; this.group.add(this.trailObj);
    this.selTrailObj = new T.LineSegments(new T.BufferGeometry(), this.selTrailMat); this.selTrailObj.frustumCulled = false; this.group.add(this.selTrailObj);
  }
  mkPoints(material) {
    const T = this.T, geom = new T.BufferGeometry();
    const p = { geom, obj: new T.Points(geom, material), cap: 0 };
    p.obj.frustumCulled = false;
    return p;
  }
  ensureCap(p, n) {
    if (p.cap >= Math.max(n, 1)) return;
    const T = this.T, cap = Math.max(64, 1 << Math.ceil(Math.log2(n)));
    p.cap = cap; p.pos = new Float32Array(cap * 3); p.col = new Float32Array(cap * 3); p.size = new Float32Array(cap); p.alpha = new Float32Array(cap); p.ring = new Float32Array(cap);
    p.geom.setAttribute("position", new T.BufferAttribute(p.pos, 3).setUsage(T.DynamicDrawUsage));
    p.geom.setAttribute("aColor", new T.BufferAttribute(p.col, 3).setUsage(T.DynamicDrawUsage));
    p.geom.setAttribute("aSize", new T.BufferAttribute(p.size, 1).setUsage(T.DynamicDrawUsage));
    p.geom.setAttribute("aAlpha", new T.BufferAttribute(p.alpha, 1).setUsage(T.DynamicDrawUsage));
    p.geom.setAttribute("aRing", new T.BufferAttribute(p.ring, 1).setUsage(T.DynamicDrawUsage));
  }

  /* ---------- data: what desk-globe.js hands over (flights, vessels, hotspots, chokepoints, plants) ---------- */
  sync(entities, lanes, layers) {
    this.lanes = lanes; this.layers = layers || {}; this.syncs = (this.syncs || 0) + 1;
    const now = this.now(), seen = new Set();
    for (const e of entities) {
      if (!e.kin) continue;
      seen.add(e.id);
      const f = { lat: e.kin.lat, lon: e.kin.lon, fix: e.kin.fix, v: e.kin.vel, hdg: e.kin.trk };
      let E = this.live.get(e.id);
      if (!E) { E = makeEntity(e.type === "vessel" ? "vessel" : "flight", e.id, f.lat, f.lon, f.fix, f.v, f.hdg, { layer: e.layer, name: e.name, ent: e, born: now, alt: e.row && e.type === "flight" ? e.row[4] : null }); this.live.set(e.id, E); }
      else { E.layer = e.layer; E.ent = e; E.name = e.name; if (E.fix !== f.fix) { applyFix(E, f, now); if (E.snapped) E.born = now; } }
    }
    for (const id of [...this.live.keys()]) if (!seen.has(id)) { this.live.delete(id); this.trails.delete(id); if (this.sel === id) this.select(null); }
    this.statics = entities.filter(e => !e.kin);
    this.rebuildStatics();
    this.wake();
  }
  rebuildStatics() {
    const T = this.T;
    for (const ch of [...this.dyn.children]) { this.dyn.remove(ch); ch.geometry && ch.geometry.dispose(); }
    const groups = { hot: [], hotChoke: [], choke: [], plantExact: [], plantRing: [] };
    for (const e of this.statics) {
      if (e.type === "hotspot") (e.kind === "chokepoint" ? groups.hotChoke : groups.hot).push(e);
      else if (e.type === "chokepoint") groups.choke.push(e);
      else if (e.type === "facility") (e.prec === "exact" ? groups.plantExact : groups.plantRing).push(e);
    }
    this.staticGroups = groups;
    const mk = (list, material, size, color, ring, alpha = 1) => {
      if (!list.length) return;
      const g = new T.BufferGeometry(), n = list.length, pos = new Float32Array(n * 3), col = new Float32Array(n * 3), sz = new Float32Array(n), al = new Float32Array(n).fill(alpha), rg = new Float32Array(n).fill(ring ? 1 : 0);
      list.forEach((e, i) => { const c = new T.Color(typeof color === "function" ? color(e) : color); col.set([c.r, c.g, c.b], i * 3); sz[i] = typeof size === "function" ? size(e) : size; e._i = i; });
      g.setAttribute("position", new T.BufferAttribute(pos, 3)); g.setAttribute("aColor", new T.BufferAttribute(col, 3)); g.setAttribute("aSize", new T.BufferAttribute(sz, 1)); g.setAttribute("aAlpha", new T.BufferAttribute(al, 1)); g.setAttribute("aRing", new T.BufferAttribute(rg, 1));
      const obj = new T.Points(g, material); obj.frustumCulled = false; obj.userData.list = list; this.dyn.add(obj);
    };
    const P = { quiet: css("--ink-4"), gold: css("--gold"), hot: css("--down") };
    const hs = e => hotspotRadius(e.score) * 2.1, hc = e => hotspotColor(e.score, P.quiet, P.gold, P.hot);
    mk(groups.hot, this.matCircle, hs, hc, false, 0.78); mk(groups.hotChoke, this.matDiamond, hs, hc, false, 0.78);
    mk(groups.choke, this.matSquare, 9, css("--ink"), false); mk(groups.plantExact, this.matCircle, 9, css("--acc"), false); mk(groups.plantRing, this.matCircle, 10, css("--acc"), true);
    if (this.layers.lane && this.lanes) {
      for (const l of this.lanes.lanes || []) {
        const pts = [];
        for (let i = 0; i + 1 < l.path.length; i++) {            // great-circle-ish arcs: subdivide each leg and lift the middle a little
          const [lo0, la0] = l.path[i], [lo1, la1] = l.path[i + 1];
          for (let s = 0; s <= 12; s++) { const t = s / 12; pts.push([la0 + (la1 - la0) * t, lo0 + (lo1 - lo0) * t, 1 + 0.01 * Math.sin(Math.PI * t)]); }
        }
        const g = new T.BufferGeometry(); g.userData.lane = pts;
        const line = new T.Line(g, new T.LineBasicMaterial({ color: new T.Color(l.kind === "air" ? css("--ink-3") : css("--gold")), transparent: true, opacity: 0.55 }));
        line.userData.lane = pts; line.frustumCulled = false; this.dyn.add(line);
      }
    }
    this.positionStatics();
  }
  place(lat, lon, r = R, out = [0, 0, 0]) { const p = this.mode === "flat" ? plane(lat, lon) : sphere(lat, lon, r); out[0] = p[0]; out[1] = p[1]; out[2] = p[2]; return out; }
  positionStatics() {
    const tmp = [0, 0, 0];
    for (const o of this.dyn.children) {
      if (o.userData.list) {
        const a = o.geometry.attributes.position;
        o.userData.list.forEach((e, i) => { this.place(e.lat, e.lon, R + 0.004, tmp); a.setXYZ(i, tmp[0], tmp[1], tmp[2] + (this.mode === "flat" ? 0.01 : 0)); });
        a.needsUpdate = true; o.visible = true;
      } else if (o.userData.lane) {
        const pts = o.userData.lane, arr = new Float32Array(pts.length * 3);
        pts.forEach(([la, lo, r], i) => { this.place(la, lo, R * r, tmp); arr.set(tmp, i * 3); });
        o.geometry.setAttribute("position", new this.T.BufferAttribute(arr, 3)); o.geometry.computeBoundingSphere();
      }
    }
  }

  /* ---------- mode, camera, size ---------- */
  setMode(mode) {
    this.mode = mode;
    const globe = mode === "globe";
    this.globeMesh.visible = globe; this.flatMesh.visible = !globe;
    for (const m of [this.matCircle, this.matSquare, this.matDiamond]) m.uniforms.uGlobe.value = globe ? 1 : 0;
    this.trailMat.uniforms.uGlobe.value = this.selTrailMat.uniforms.uGlobe.value = globe ? 1 : 0;
    this.group.rotation.set(0, 0, 0);
    this.trailBuilt = 0;
    this.positionStatics(); this.camera(); this.wake();
  }
  recentre() { this.view.lat = INDIA[0]; this.view.lon = INDIA[1]; this.view.panX = this.view.panY = 0; this.view.zoom = 1; this.view.vLat = this.view.vLon = 0; this.camera(); this.wake(); }
  camera() {
    const v = this.view, T = this.T;
    if (this.mode === "globe") {
      const D = Math.max(1.15, 3.5 / v.zoom);
      this.persp.position.set(0, 0, D); this.persp.lookAt(0, 0, 0); this.persp.aspect = this.W / this.H; this.persp.updateProjectionMatrix();
      this.group.rotation.set(v.lat * RAD, -(v.lon * RAD + Math.PI / 2), 0, "XYZ");
      this.cam = this.persp;
    } else {
      const h = 0.5 / Math.max(0.8, v.zoom) * 1.02, w = h * this.W / this.H;
      this.ortho.left = -w; this.ortho.right = w; this.ortho.top = h; this.ortho.bottom = -h;
      const cx = Math.max(-1 + w, Math.min(1 - w, v.lon / 180 - v.panX / (this.W / (2 * w)))), cy = Math.max(-0.5 + h, Math.min(0.5 - h, v.lat / 180 + v.panY / (this.H / (2 * h))));
      this.ortho.position.set(isFinite(cx) ? cx : 0, isFinite(cy) ? cy : 0, 3); this.ortho.updateProjectionMatrix(); this.cam = this.ortho;
    }
    this.group.updateMatrixWorld(true); this.cam.updateMatrixWorld(true);
    this.matCircle.uniforms.uCam.value.copy(this.persp.position);
  }
  resize() {
    if (!this.opened) return;
    const wrap = this.o.wrap, w = Math.max(280, wrap.clientWidth || 600), h = Math.round(Math.min(Math.max(320, w * (this.mode === "flat" ? 0.52 : 0.72)), 720));
    const pr = Math.min(window.devicePixelRatio || 1, this.gov.pixelRatioCap);
    this.W = w; this.H = h; this.pr = pr;
    this.renderer.setPixelRatio(pr); this.renderer.setSize(w, h, false);
    this.canvas.style.width = w + "px"; this.canvas.style.height = h + "px";
    for (const m of [this.matCircle, this.matSquare, this.matDiamond]) m.uniforms.uPx.value = pr;
    this.camera(); this.wake();
  }

  /* ---------- the frame ---------- */
  start() { if (!this.raf && !this.lost) { this.lastFrame = performance.now(); this.raf = requestAnimationFrame(t => this.frame(t)); } }
  stop() { if (this.raf) cancelAnimationFrame(this.raf); this.raf = 0; }
  wake() { this.idleSince = performance.now(); this.dirty = true; this.start(); }
  moving() {
    for (const E of this.live.values()) if (!isStill(E) && !isGhost(E, this.now())) return true;
    return false;
  }
  frame(tm) {
    this.raf = 0;
    if (!this.opened || this.lost) return;
    if (document.hidden) { this.raf = requestAnimationFrame(t => this.frame(t)); return; }       // paused while the tab is hidden
    const dt = Math.min(0.1, (tm - this.lastFrame) / 1000); this.lastFrame = tm;
    const v = this.view, active = this.drag || Math.abs(v.vLat) > 0.01 || Math.abs(v.vLon) > 0.01 || this.follow || this.dirty;
    if (this.mode === "globe") {                                    // inertia, optional follow, slow idle spin
      if (!this.drag && (Math.abs(v.vLat) > 0.01 || Math.abs(v.vLon) > 0.01)) {
        v.lat = Math.max(-80, Math.min(80, v.lat + v.vLat * dt)); v.lon += v.vLon * dt; const k = Math.exp(-dt * 3); v.vLat *= k; v.vLon *= k;
      }
      if (this.follow && this.sel) { const E = this.live.get(this.sel); if (E) { const [la, lo] = renderPos(E, this.now()); v.lat += (la - v.lat) * Math.min(1, dt * 4); let d = lo - v.lon; d = ((d + 540) % 360) - 180; v.lon += d * Math.min(1, dt * 4); } }
      else if (!this.reduced && !this.sel && !this.drag && performance.now() - this.idleSince > 8000 && this.layers.spin !== false) { v.lon += 2 * dt; this.dirty = true; }
    }
    let drew = false;
    if (active || this.moving() || this.dirty) { const t0 = performance.now(); this.render(tm); this.dirty = false; drew = true; this.js.push(performance.now() - t0); if (this.js.length > 120) this.js.shift(); }
    if (drew) this.measure(tm, dt);                                 // only frames that were really drawn feed the governor and the fps figure
    const keep = active || this.moving() || this.follow || (!this.reduced && !this.sel && this.mode === "globe" && performance.now() - this.idleSince > 8000);
    this.raf = requestAnimationFrame(t => this.frame(t));
    if (!keep && !this.dirty) { cancelAnimationFrame(this.raf); this.raf = 0; this.fps = 0; }       // nothing is moving: no frames until something wakes it
  }
  render(tm) {
    const now = this.now(), T = this.T, tmp = [0, 0, 0], reduced = this.reduced;
    this.camera();
    const gov = this.gov, cap = gov.maxEntities;
    // choose what to draw: at most `cap` entities (nearest to the view centre when the governor has cut the cap)
    if (!this.liveList || this.liveListN !== this.live.size || this.liveListV !== this.syncs) { this.liveList = [...this.live.values()]; this.liveListN = this.live.size; this.liveListV = this.syncs; }
    let list = this.liveList.filter(E => this.layerOn(E) && !isGone(E, now));
    if (list.length > cap) { const c = this.view; list.sort((a, b) => (Math.abs(a.lat0 - c.lat) + Math.abs(a.lon0 - c.lon)) - (Math.abs(b.lat0 - c.lat) + Math.abs(b.lon0 - c.lon))); list = list.slice(0, cap); }
    const by = { cargo: [], air: [], ship: [] };
    for (const E of list) by[E.layer === "ship" ? "ship" : E.layer === "cargo" ? "cargo" : "air"].push(E);
    const colors = this.colors || (this.colors = { cargo: new T.Color(css("--gold")), air: new T.Color(css("--ink-3")), ship: new T.Color(css("--acc")) }), sizes = { cargo: 11, air: 6, ship: 7 };
    const doPick = tm - this.gridT > 100;
    if (doPick) { this.gridT = tm; this.grid.clear(); this.listPts.length = 0; }          // the picking grid is rebuilt about ten times a second
    for (const key of ["cargo", "air", "ship"]) {
      const p = this.points[key], arr = by[key];
      this.ensureCap(p, arr.length);
      arr.forEach((E, i) => {
        const [la, lo] = reduced ? [E.lat0, E.lon0] : renderPos(E, now);
        const lift = E.kind === "flight" ? 0.006 + Math.min(Math.max(E.alt || 0, 0), 13000) / 13000 * 0.012 : 0.001;
        this.place(la, lo, R + lift, tmp);
        p.pos[i * 3] = tmp[0]; p.pos[i * 3 + 1] = tmp[1]; p.pos[i * 3 + 2] = tmp[2] + (this.mode === "flat" ? 0.02 : 0);
        const c = colors[key], ghost = isGhost(E, now), age = now - E.born, fadeIn = Math.min(1, Math.max(0, age / 0.6));
        p.col[i * 3] = c.r; p.col[i * 3 + 1] = c.g; p.col[i * 3 + 2] = c.b;
        p.size[i] = sizes[key] * (E.id === this.sel ? 1.7 : 1);
        p.alpha[i] = (ghost ? 0.35 : 1) * (reduced ? 1 : fadeIn); p.ring[i] = ghost ? 1 : 0;
        if (!reduced && !ghost && gov.trails && this.trailsOn()) this.pushTrail(E, la, lo, now);
        if (doPick) this.collect(E, tmp);
      });
      p.geom.setDrawRange(0, arr.length);
      for (const a of ["position", "aColor", "aSize", "aAlpha", "aRing"]) p.geom.attributes[a].needsUpdate = true;
    }
    if (doPick) this.collectStatics();
    this.trailObj.visible = gov.trails && !reduced && this.trailsOn();
    this.updateTrailGeometry(now, tm);
    this.trailMat.uniforms.uNow.value = this.selTrailMat.uniforms.uNow.value = now - this.t0;
    this.renderer.render(this.scene, this.cam);
    const el = this.canvas; el.dataset.items = String(this.listPts.length); el.dataset.mode = this.mode; el.dataset.engine = "webgl";
  }
  layerOn(E) { return this.layers[E.layer] !== false; }
  trailsOn() { return this.layers.trails !== false; }

  /* ---------- trails ---------- */
  pushTrail(E, la, lo, now) {
    let t = this.trails.get(E.id);
    if (!t) { t = new Trail(); this.trails.set(E.id, t); }
    if (t.push(la, lo, now)) this.trailDirty = true;
  }
  updateTrailGeometry(now, tm) {
    if (!this.trailObj.visible && !this.sel) return;
    if (!this.trailDirty && tm - this.trailBuilt < 500) return;           // rebuilt at most twice a second; the fade itself runs in the shader
    this.trailBuilt = tm; this.trailDirty = false;
    const T = this.T, tmp = [0, 0, 0];
    const flatZ = this.mode === "flat" ? 0.015 : 0;
    const build = (ids, material, obj, colorOf) => {
      let n = 0; for (const id of ids) { const t = this.trails.get(id); if (t && t.n > 1) n += t.n - 1; }
      let buf = obj.userData.buf;
      if (!buf || buf.cap < n) {                                              // allocated once and grown by doubling: no new arrays at every rebuild
        const cap = Math.max(256, 1 << Math.ceil(Math.log2(Math.max(1, n))));
        buf = obj.userData.buf = { cap, pos: new Float32Array(cap * 6), col: new Float32Array(cap * 6), at: new Float32Array(cap * 2) };
        obj.geometry.dispose(); const g = new T.BufferGeometry();
        g.setAttribute("position", new T.BufferAttribute(buf.pos, 3).setUsage(T.DynamicDrawUsage)); g.setAttribute("aColor", new T.BufferAttribute(buf.col, 3).setUsage(T.DynamicDrawUsage)); g.setAttribute("aT", new T.BufferAttribute(buf.at, 1).setUsage(T.DynamicDrawUsage));
        obj.geometry = g;
      }
      let k = 0;
      for (const id of ids) {
        const t = this.trails.get(id); if (!t || t.n < 2) continue;
        const c = colorOf(id), len = t.len, pts = t.pts;
        let prev = -1;
        for (let q = 0; q < t.n; q++) {
          const j = ((t.head - t.n + q + len * 2) % len) * 3;
          if (prev >= 0 && Math.abs(pts[prev + 1] - pts[j + 1]) <= 180) {      // never draw a line across the date line on the flat map
            for (let e = 0; e < 2; e++) {
              const jj = e ? j : prev, o = (k * 2 + e) * 3;
              this.place(pts[jj], pts[jj + 1], R + 0.008, tmp);
              buf.pos[o] = tmp[0]; buf.pos[o + 1] = tmp[1]; buf.pos[o + 2] = tmp[2] + flatZ; buf.col[o] = c.r; buf.col[o + 1] = c.g; buf.col[o + 2] = c.b; buf.at[k * 2 + e] = pts[jj + 2] - this.t0;
            }
            k++;
          }
          prev = j;
        }
      }
      obj.geometry.setDrawRange(0, k * 2);
      for (const a of ["position", "aColor", "aT"]) obj.geometry.attributes[a].needsUpdate = true;
    };
    const gold = new T.Color(css("--gold")), ink = new T.Color(css("--ink-3")), acc = new T.Color(css("--acc"));
    const ids = [...this.trails.keys()].filter(id => { const E = this.live.get(id); return E && id !== this.sel && this.layerOn(E); });
    build(ids, this.trailMat, this.trailObj, id => { const E = this.live.get(id); return E.layer === "cargo" ? gold : E.layer === "ship" ? acc : ink; });
    build(this.sel ? [this.sel] : [], this.selTrailMat, this.selTrailObj, id => { const E = this.live.get(id); return E && E.layer === "cargo" ? gold : E && E.layer === "ship" ? acc : ink; });
  }

  /* ---------- picking ---------- */
  project(p) {
    const v = this._pv || (this._pv = new this.T.Vector3());
    v.set(p[0], p[1], p[2]).applyMatrix4(this.group.matrixWorld);
    if (this.mode === "globe") { const cam = this.persp.position, len = Math.hypot(v.x, v.y, v.z) * cam.length() || 1; if ((v.x * cam.x + v.y * cam.y + v.z * cam.z) / len < 0.06) return null; }
    v.project(this.cam);
    return [(v.x * 0.5 + 0.5) * this.W, (-v.y * 0.5 + 0.5) * this.H];
  }
  collect(E, p) { const s = this.project(p); if (!s) return; const idx = this.listPts.length; this.listPts.push({ x: s[0], y: s[1], type: E.ent.type, id: E.id, kind: E.ent.kind, ent: E.ent }); this.grid.add(s[0], s[1], idx); }
  collectStatics() {
    const tmp = [0, 0, 0];
    for (const e of this.statics) {
      if (e.type !== "hotspot" && e.type !== "chokepoint" && e.type !== "facility") continue;
      this.place(e.lat, e.lon, R + 0.004, tmp); const s = this.project(tmp); if (!s) continue;
      const idx = this.listPts.length; this.listPts.push({ x: s[0], y: s[1], type: e.type, id: e.id, kind: e.kind, ent: e }); this.grid.add(s[0], s[1], idx);
    }
  }
  pick(x, y, touch) { const i = this.grid.nearest(x, y, touch ? 16 : 10); return i == null ? null : this.listPts[i]; }
  select(id) { this.sel = id; this.trailDirty = true; this.trailBuilt = 0; this.hooks.select && this.hooks.select(id); this.wake(); }
  setFollow(on) { this.follow = !!on; this.wake(); }

  /* ---------- pointer, wheel, pinch, double click ---------- */
  bind() {
    const c = this.canvas, ptr = new Map();
    let pinch = 0;
    this.ac = new AbortController();
    const sig = { signal: this.ac.signal };
    c.style.touchAction = "none";
    c.addEventListener("pointerdown", e => { ptr.set(e.pointerId, { x: e.clientX, y: e.clientY }); this.drag = ptr.size === 1; this.moved = 0; this.view.vLat = this.view.vLon = 0; try { c.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointers */ } if (ptr.size === 2) { const [a, b] = [...ptr.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y); } this.wake(); }, sig);
    c.addEventListener("pointermove", e => {
      const rc = c.getBoundingClientRect(), x = e.clientX - rc.left, y = e.clientY - rc.top, p = ptr.get(e.pointerId);
      if (p) {
        const dx = e.clientX - p.x, dy = e.clientY - p.y; p.x = e.clientX; p.y = e.clientY; this.moved += Math.abs(dx) + Math.abs(dy);
        if (ptr.size === 2) { const [a, b] = [...ptr.values()], d = Math.hypot(a.x - b.x, a.y - b.y); if (pinch) this.view.zoom = Math.max(0.8, Math.min(6, this.view.zoom * d / pinch)); pinch = d; }
        else if (this.mode === "globe") { const k = 0.3 / this.view.zoom; this.view.lon -= dx * k; this.view.lat = Math.max(-80, Math.min(80, this.view.lat + dy * k)); this.view.vLon = -dx * k * 60; this.view.vLat = dy * k * 60; }
        else { this.view.panX += dx; this.view.panY += dy; }
        if (this.follow) { this.follow = false; this.hooks.follow && this.hooks.follow(false); }
        this.hooks.hover && this.hooks.hover(null); this.wake(); return;
      }
      const hit = this.pick(x, y, e.pointerType === "touch"); c.style.cursor = hit ? "pointer" : "grab"; this.hooks.hover && this.hooks.hover(hit && hit.ent, x, y);
    }, sig);
    const up = e => {
      const was = ptr.get(e.pointerId); ptr.delete(e.pointerId); this.drag = ptr.size === 1; if (ptr.size < 2) pinch = 0;
      if (!was || this.moved > 5) { this.wake(); return; }
      const rc = c.getBoundingClientRect(), hit = this.pick(e.clientX - rc.left, e.clientY - rc.top, e.pointerType === "touch");
      if (hit) { this.select(hit.ent && (hit.ent.kin || hit.ent.type === "flight" || hit.ent.type === "vessel") ? hit.id : null); this.hooks.pick && this.hooks.pick(hit.ent); } else if (this.sel) this.select(null);
    };
    c.addEventListener("pointerup", up, sig); c.addEventListener("pointercancel", up, sig);
    c.addEventListener("pointerleave", () => { this.hooks.hover && this.hooks.hover(null); }, sig);
    c.addEventListener("wheel", e => { e.preventDefault(); this.view.zoom = Math.max(0.8, Math.min(6, this.view.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12))); this.wake(); }, { passive: false, signal: this.ac.signal });
    c.addEventListener("dblclick", () => this.recentre(), sig);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) this.wake(); }, sig);
  }

  /* ---------- the governor and the numbers the tests read ---------- */
  measure(tm, dt) {
    const ms = dt * 1000; if (ms <= 0) return;
    this.frames.push(ms); if (this.frames.length > 240) this.frames.shift();
    const lv = this.gov.frame(ms, tm / 1000);
    if (lv != null) { this.resize(); this.trailDirty = true; this.hooks.governor && this.hooks.governor(this.gov); }
    if (this.frames.length >= 5) { const s = this.frames.slice().sort((a, b) => a - b); this.fps = 1000 / s[s.length >> 1]; }
  }
  stats() {
    const info = this.renderer.info, s = this.frames.slice().sort((a, b) => a - b);
    const j = this.js.slice().sort((a, b) => a - b);
    return { fps: this.fps, medianMs: s.length ? s[s.length >> 1] : null, jsMs: j.length ? j[j.length >> 1] : null, level: this.gov.name, entities: this.live.size, geometries: info.memory.geometries, textures: info.memory.textures, drawCalls: info.render.calls, mode: this.mode, reduced: this.gov.reduced, software: this.software };
  }

  /* ---------- leaving the view: free everything the scene owns (the renderer itself is kept for the next visit) ---------- */
  close() {
    this.stop();
    if (!this.opened) return;
    this.ac && this.ac.abort();                                         // every listener of this visit goes with it
    this.scene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) { for (const m of [].concat(o.material)) m.dispose(); } });
    this.tex.dispose(); this.matCircle.dispose(); this.matSquare.dispose(); this.matDiamond.dispose(); this.trailMat.dispose(); this.selTrailMat.dispose();
    this.scene.clear(); this.live.clear(); this.trails.clear(); this.statics = [];
    this.opened = false;
  }
  destroy() { this.close(); this.renderer.dispose(); try { this.renderer.forceContextLoss(); } catch (e) { /* already gone */ } }
}
