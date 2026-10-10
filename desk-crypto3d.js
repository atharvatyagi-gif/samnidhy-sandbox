/* Crypto tab, 3D view: every REAL trade on Binance appears as a particle the moment it happens.
   Time runs along the horizontal axis (now at the right edge, the last minute streams away to the left), price is height, and the two sides of the market sit in two lanes: aggressive BUYERS in the front lane (green),
   aggressive SELLERS in the back lane (red). Bigger trades are bigger, brighter particles; very large ones send out a ring. The order book is the ladder reaching out to the right of "now": resting buy size under the price, resting sell size above (one bar per slice of the 1,000 nearest levels, not to price scale).
   When the paper account itself buys or sells, a burst of white particles leaves the price level, and its open positions are drawn as lines (entry and stop).
   Everything comes from desk-cryptofeed.js (live Binance data) and the engine's live.json. Nothing is simulated. If WebGL is missing, the 2D panels remain. Educational analysis only, not investment advice. */
import { loadThree } from "./desk-globe3d.js";
import { feed, onTrade, bucketBook, fetchBook, flowWindow, ASSETS } from "./desk-cryptofeed.js";

export const K = 1.1;                                   // world units of height per basis point away from the reference price
export const NOW_X = 24, SPEED = 0.8;                   // the "now" plane and how fast particles stream away from it (units per second): a minute is about 48 units
export const BIG_USD = 250_000;                         // a trade this large sends out a ring
export const priceToY = (p, ref) => (p / ref - 1) * 1e4 * K;
/* size and brightness of a trade's particle from its dollar value */
export const tradeLook = usd => ({ size: 0.7 + 0.8 * Math.log10(1 + usd / 150), glow: Math.min(1, 0.7 + Math.log10(1 + usd / 2000) * 0.2), big: usd >= BIG_USD });

/* A fixed pool of particles in typed arrays; the oldest is overwritten when it is full. No three.js in here, so it can be tested alone. */
export class ParticlePool {
  constructor(n) {
    this.n = n; this.head = 0; this.pos = new Float32Array(n * 3); this.vel = new Float32Array(n * 3); this.col = new Float32Array(n * 3); this.size = new Float32Array(n); this.alpha = new Float32Array(n); this.life = new Float32Array(n); this.max = new Float32Array(n); this.glow = new Float32Array(n); this.base = new Float32Array(n);
  }
  spawn(o) {
    const i = this.head; this.head = (this.head + 1) % this.n; const k = i * 3;
    this.pos[k] = o.x; this.pos[k + 1] = o.y; this.pos[k + 2] = o.z; this.vel[k] = o.vx || 0; this.vel[k + 1] = o.vy || 0; this.vel[k + 2] = o.vz || 0;
    this.col[k] = o.r; this.col[k + 1] = o.g; this.col[k + 2] = o.b; this.size[i] = this.base[i] = o.size * 3; this.life[i] = this.max[i] = o.life; this.glow[i] = o.glow ?? 1; this.alpha[i] = this.glow[i]; return i;
  }
  /* advance by dt seconds; shiftY moves everything down when the reference price rises, so a price level keeps its height. -> number alive */
  update(dt, shiftY = 0) {
    let alive = 0; const g = this.glow;
    for (let i = 0; i < this.n; i++) {
      if (this.life[i] <= 0) { this.alpha[i] = 0; continue; }
      this.life[i] -= dt; const k = i * 3; this.pos[k] += this.vel[k] * dt; this.pos[k + 1] += this.vel[k + 1] * dt - shiftY; this.pos[k + 2] += this.vel[k + 2] * dt;
      const f = Math.max(0, this.life[i] / this.max[i]); this.size[i] = this.base[i] * (1 + 1.6 * Math.exp(-(this.max[i] - this.life[i]) * 5)) / 3; this.alpha[i] = this.life[i] > 0 ? g[i] * Math.min(1, f * 3) * (0.35 + 0.65 * f) : 0; if (this.life[i] > 0) alive++;
    }
    return alive;
  }
}

const css = (name, fb) => { try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fb; } catch (e) { return fb; } };

const VERT = `attribute float size; attribute vec3 color; attribute float alpha; varying vec3 vC; varying float vA;
void main(){ vC = color; vA = alpha; vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_PointSize = size * (820.0 / -mv.z); gl_Position = projectionMatrix * mv; }`;
const FRAG = `varying vec3 vC; varying float vA; void main(){ float d = length(gl_PointCoord - vec2(0.5)); if (d > 0.5) discard; float a = smoothstep(0.5, 0.0, d) * vA; gl_FragColor = vec4(vC, a); }`;

/* host: an empty element. opts: {onHud(stats), reduced}. -> controller, or null when WebGL is not available */
export async function mount3d(host, opts = {}) {
  let T; try { T = await loadThree(); } catch (e) { return null; }
  const canvas = document.createElement("canvas"); canvas.className = "cx3-canvas"; canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", "3D view: every Binance trade as a particle, buyers in the front lane and sellers in the back lane, with the order book as a ladder");
  host.appendChild(canvas); let R; try { R = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" }); } catch (e) { canvas.remove(); return null; }
  R.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); R.setClearColor(0x000000, 0);
  const col = n => new T.Color(css(n, n === "--up" ? "#22c55e" : n === "--down" ? "#ef4444" : "#fafafa")), UP = col("--up"), DN = col("--down"), INK = col("--ink"), WARN = new T.Color(css("--warn", "#f59e0b"));
  const scene = new T.Scene(), cam = new T.PerspectiveCamera(48, 1, 0.1, 400), target = new T.Vector3(14, 0, 0); let az = 0.95, el = 0.32, rad = 58, userAt = 0, auto = !opts.reduced, paused = false;
  const pool = new ParticlePool(7000), geo = new T.BufferGeometry();
  const A = (name, arr, n) => { const a = new T.BufferAttribute(arr, n); a.setUsage(T.DynamicDrawUsage); geo.setAttribute(name, a); return a; };
  const aPos = A("position", pool.pos, 3), aCol = A("color", pool.col, 3), aSize = A("size", pool.size, 1), aAlpha = A("alpha", pool.alpha, 1);
  geo.boundingSphere = new T.Sphere(new T.Vector3(0, 0, 0), 1e4);
  const pts = new T.Points(geo, new T.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, blending: T.AdditiveBlending })); scene.add(pts);
  // frame: floor grid, the "now" plane outline and a faint price axis
  const lineMat = new T.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.16 }), box = new T.Group(); scene.add(box);
  const seg = (a, b) => { const g = new T.BufferGeometry().setFromPoints([new T.Vector3(...a), new T.Vector3(...b)]); box.add(new T.Line(g, lineMat)); };
  for (let x = -30; x <= 42; x += 6) seg([x, -22, -9], [x, -22, 9]); for (let z = -9; z <= 9; z += 3) seg([-30, -22, z], [42, -22, z]);
  seg([NOW_X, -22, -9], [NOW_X, 22, -9]); seg([NOW_X, 22, -9], [NOW_X, 22, 9]); seg([NOW_X, 22, 9], [NOW_X, -22, 9]); seg([NOW_X, -22, 9], [NOW_X, -22, -9]);
  const mid = new T.Line(new T.BufferGeometry().setFromPoints([new T.Vector3(-30, 0, 0), new T.Vector3(NOW_X, 0, 0)]), new T.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.35 })); scene.add(mid);
  // order-book ladder: one bar per price bucket, length = resting dollars
  const NB = 24, ladder = new T.InstancedMesh(new T.BoxGeometry(1, 0.7, 1.6), new T.MeshBasicMaterial({ transparent: true, opacity: 0.45, depthWrite: false }), NB * 2), tmp = new T.Object3D(), len = new Float32Array(NB * 2), want = new Float32Array(NB * 2); scene.add(ladder); ladder.frustumCulled = false;
  for (let i = 0; i < NB * 2; i++) ladder.setColorAt(i, i < NB ? UP : DN);
  // the account's own positions: entry and stop lines
  const mkLine = c => { const l = new T.Line(new T.BufferGeometry().setFromPoints([new T.Vector3(-30, 0, 0), new T.Vector3(42, 0, 0)]), new T.LineDashedMaterial({ color: c, dashSize: 1.2, gapSize: 0.8, transparent: true, opacity: 0.85 })); l.computeLineDistances(); l.visible = false; scene.add(l); return l; };
  const entryLine = mkLine(INK), stopLine = mkLine(WARN);
  // rings for large trades and for the account's own fills
  const rings = []; const ringGeo = new T.RingGeometry(0.9, 1, 56);
  const ring = (x, y, z, c, scale, life) => { let r = rings.find(q => !q.active); if (!r) { if (rings.length >= 14) return; r = { m: new T.Mesh(ringGeo, new T.MeshBasicMaterial({ transparent: true, depthWrite: false, side: T.DoubleSide, blending: T.AdditiveBlending })), active: false }; rings.push(r); scene.add(r.m); }
    r.active = true; r.t = 0; r.life = life; r.scale = scale; r.m.position.set(x, y, z); r.m.material.color.copy(c); r.m.visible = true; };
  let ref = null, sel = feed.sel, lastBook = 0, book = null, destroyed = false, pos = {}, prices = {};
  const mapY = p => priceToY(p, ref);
  const off = onTrade(m => {
    if (m.sym !== sel || ref == null || paused) return; const look = tradeLook(m.usd), buy = m.buy, c = buy ? UP : DN, lane = (buy ? 1 : -1) * (2 + Math.random() * 5);
    pool.spawn({ x: NOW_X, y: mapY(m.p) + (Math.random() - 0.5) * 0.12, z: lane, vx: -SPEED * (0.9 + Math.random() * 0.2), vy: (buy ? 0.12 : -0.12) * (0.5 + Math.random()), vz: (Math.random() - 0.5) * 0.15, r: c.r, g: c.g, b: c.b, size: look.size, life: 60, glow: look.glow });
    if (look.big && !opts.reduced) ring(NOW_X, mapY(m.p), lane, c, 3 + Math.min(6, Math.log10(m.usd / BIG_USD + 1) * 8), 1.4);
  });
  function burst(side, label, price) {
    if (ref == null) return; const y = mapY(price), c = side === "buy" ? UP : DN;
    for (let i = 0; i < 260; i++) { const a = Math.random() * 6.283, b = Math.acos(2 * Math.random() - 1), s = 2 + Math.random() * 5; pool.spawn({ x: NOW_X, y, z: 0, vx: Math.cos(a) * Math.sin(b) * s - 1, vy: Math.cos(b) * s, vz: Math.sin(a) * Math.sin(b) * s, r: 1, g: 1, b: 1, size: 0.9, life: 3.2, glow: 1 }); }
    ring(NOW_X, y, 0, INK, 12, 2.4); ring(NOW_X, y, 0, c, 8, 1.8); if (opts.onToast) opts.onToast(label);
  }
  function resize() { const w = host.clientWidth || 600, h = host.clientHeight || 420; R.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); }
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null; if (ro) ro.observe(host); resize();
  // orbit by dragging, zoom with the wheel or a pinch
  let drag = null; const down = e => { drag = { x: e.clientX, y: e.clientY }; userAt = performance.now(); canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId); };
  const move = e => { if (!drag) return; az -= (e.clientX - drag.x) * 0.006; el = Math.max(-0.2, Math.min(1.25, el + (e.clientY - drag.y) * 0.005)); drag = { x: e.clientX, y: e.clientY }; userAt = performance.now(); };
  const up = () => { drag = null; }; const wheel = e => { e.preventDefault(); rad = Math.max(22, Math.min(120, rad * (1 + Math.sign(e.deltaY) * 0.08))); userAt = performance.now(); };
  canvas.addEventListener("pointerdown", down); canvas.addEventListener("pointermove", move); canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up); canvas.addEventListener("wheel", wheel, { passive: false });
  async function pollBook() {
    if (destroyed || document.hidden) return; const sym = sel;
    try { const d = await fetchBook(sym), m = (+d.bids[0][0] + +d.asks[0][0]) / 2; book = bucketBook(d.bids, d.asks, m); book.mid = m; book.sym = sym; } catch (e) { /* the ladder keeps its last shape */ }
  }
  const bookTimer = setInterval(pollBook, 2000); pollBook();
  let last = performance.now(), hudAt = 0, raf = 0;
  function frame(now) {
    if (destroyed) return; raf = requestAnimationFrame(frame); if (!host.isConnected) { destroy(); return; } if (document.hidden) { last = now; return; }
    const dt = Math.min(0.1, (now - last) / 1000); last = now; const px = feed.price[sel];
    if (px != null) { if (ref == null) ref = px; const k = 1 - Math.exp(-dt / 30), nr = ref + (px - ref) * k, shift = priceToY(nr, ref); ref = nr; pool.update(paused ? 0 : dt, shift); } else pool.update(0, 0);
    if (auto && !opts.reduced && now - userAt > 8000) az += dt * 0.05; else if (!auto && now - userAt > 8000) { /* manual mode: stay where the viewer left it */ }
    cam.position.set(target.x + rad * Math.cos(el) * Math.sin(az), target.y + rad * Math.sin(el), target.z + rad * Math.cos(el) * Math.cos(az)); cam.lookAt(target);
    // ladder: bids hang under the price, asks above, bars reach to the right of "now"
    if (book && book.sym === sel && ref != null) {
      const maxQ = Math.max(1, ...book.bids, ...book.asks);
      for (let i = 0; i < NB; i++) { want[i] = book.bids[i] / maxQ * 16; want[NB + i] = book.asks[i] / maxQ * 16; }
      for (let i = 0; i < NB * 2; i++) { len[i] += (want[i] - len[i]) * Math.min(1, dt * 6); const side = i < NB ? -1 : 1, j = i % NB, y = mapY(book.mid) + side * (j + 0.6) * 0.9; tmp.position.set(NOW_X + 0.5 + len[i] / 2, y, 0); tmp.scale.set(Math.max(0.05, len[i]), 1, 1); tmp.updateMatrix(); ladder.setMatrixAt(i, tmp.matrix); }
      ladder.instanceMatrix.needsUpdate = true; ladder.visible = true;
    } else ladder.visible = false;
    // account lines
    const p = pos[sel]; if (p && ref != null) { entryLine.position.y = mapY(p.entry); stopLine.position.y = mapY(p.stop); entryLine.visible = stopLine.visible = Math.abs(mapY(p.entry)) < 40; } else entryLine.visible = stopLine.visible = false;
    if (ref != null) mid.position.y = 0;
    for (const r of rings) if (r.active) { r.t += dt; const f = r.t / r.life; if (f >= 1) { r.active = false; r.m.visible = false; continue; } r.m.scale.setScalar(0.5 + f * r.scale); r.m.material.opacity = (1 - f) * 0.9; r.m.quaternion.copy(cam.quaternion); }
    aPos.needsUpdate = aCol.needsUpdate = aSize.needsUpdate = aAlpha.needsUpdate = true; R.render(scene, cam);
    if (opts.onHud && now - hudAt > 500) { hudAt = now; const w = flowWindow(feed.trades[sel], Date.now()); opts.onHud({ sym: sel, price: px, ref, ...w, particles: pool.life.reduce((a, v) => a + (v > 0 ? 1 : 0), 0) }); }
  }
  raf = requestAnimationFrame(frame);
  function destroy() { if (destroyed) return; destroyed = true; cancelAnimationFrame(raf); clearInterval(bookTimer); off(); if (ro) ro.disconnect(); canvas.remove(); try { R.dispose(); geo.dispose(); } catch (e) { /* already gone */ } }
  return {
    destroy, burst, setAsset(s) { if (ASSETS[s]) { sel = s; feed.sel = s; ref = null; book = null; pool.life.fill(0); pollBook(); } },
    setPositions(sleeves, p) { pos = {}; prices = p || {}; for (const s of Object.values(sleeves || {})) if (s.qty > 0 && s.entry != null) pos[s.asset] = { entry: s.entry, stop: s.stop }; },
    toggleRotate() { auto = !auto; userAt = 0; return auto; }, resetView() { az = 0.95; el = 0.32; rad = 58; userAt = 0; }, togglePause() { paused = !paused; return paused; },
  };
}
