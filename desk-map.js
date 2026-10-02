/* MAP: geopolitical NEWS ATTENTION, as a layer of the existing Globe tab (not a separate tab: the Globe already holds
   the real vessel / hazard / news layers). geo.json (scripts/geo_tension.py) is fetched when the layer is first
   switched on or its button pressed; the Brief's regime strip also reads it a few seconds after start (preload()).
   What it shows: how much, and in what tone, the news is talking about a region versus that region's own recent
   normal. It is not a measure of events. Until a region has built its baseline there is no score, only headlines. */
let ctx = null, gm = null, layer = null, loading = null, failed = null;
let sel = null;
const LV = { Low: "low", Guarded: "guarded", Elevated: "elevated", High: "high", Severe: "severe" };
const lvClass = r => r.score == null ? "none" : LV[r.level] || "none";

export function init(c) { ctx = c; }

/* ---------- loading ---------- */
function available() { return !!(ctx && ctx.S.deskMan && ctx.S.deskMan.geo); }
export async function preload() {
  if (!available() || ctx.S.geo) return ctx.S.geo || null;
  loading = loading || ctx.getJSON("geo.json").then(j => { ctx.S.geo = j; }, e => { failed = e.message; }).finally(() => { loading = null; });
  await loading;
  return ctx.S.geo || null;
}
export async function refresh() {                       // called by the page's slow poll once geo.json has been loaded
  if (!ctx || !ctx.S.geo || !available()) return;
  try {
    const j = await ctx.getJSON("geo.json");
    if (j.generated_utc !== ctx.S.geo.generated_utc) { ctx.S.geo = j; drawMarkers(); renderGeo(); ctx.renderRegimeBrief && ctx.renderRegimeBrief(); }
  } catch (e) { /* keep what is on screen */ }
}

/* ---------- map layer ---------- */
export async function attach(globeMap) {
  gm = globeMap;
  layer = await gm.addLazyOverlay("Geopolitical news attention", async () => { await preload(); drawMarkers(); renderGeo(); });
  renderGeo();
}

function drawMarkers() {
  const G = ctx.S.geo; if (!layer || !G || !window.L) return;
  layer.clearLayers();
  for (const r of G.regions) {
    const size = r.score == null ? 14 : Math.round(10 + r.score / 5), cls = `geo-dot lv-${lvClass(r)} k-${r.kind}${r.stale ? " stale" : ""}${r.level === "Severe" ? " pulse" : ""}`;
    const m = window.L.marker([r.lat, r.lon], { icon: window.L.divIcon({ className: "geo-dot-wrap", html: `<span class="${cls}" style="width:${size}px;height:${size}px"></span>`, iconSize: [size, size] }), keyboard: true, alt: r.name, title: r.name });
    m.bindTooltip(`${r.name} · ${r.score == null ? "building baseline" : r.level + " " + r.score}`);
    m.on("click", () => selectRegion(r.id));
    m.addTo(layer);
  }
}

/* ---------- panel under the map ---------- */
const spark = vals => {
  const pts = vals.map((v, i) => [i, v]).filter(p => p[1] != null);
  if (pts.length < 2) return '<span class="mut">history building</span>';
  const w = 220, h = 36, max = Math.max(...pts.map(p => p[1])) || 1, x = i => i / (vals.length - 1) * w, y = v => h - 3 - v / max * (h - 6);
  return `<svg class="geo-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="Headlines per hour, last 30 days"><polyline fill="none" stroke="var(--acc)" stroke-width="1.5" points="${pts.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}"/></svg>`;
};

export function selectRegion(id) { sel = sel === id ? null : id; drawPanel(); }

function exposureRows(r) {
  const { esc, S } = ctx, rows = [];
  const arrow = d => d === "+" ? '<span class="up" title="Tends to gain when attention on this region rises">▲</span>' : '<span class="down" title="Tends to lose when attention on this region rises">▼</span>';
  const line = (s, d, why) => { const x = ctx.q(s), u = S.map.get(s); if (!u) return ""; return `<tr data-s="${esc(s)}"${why ? ` title="${esc(why)}"` : ""}><td>${arrow(d)}</td><td class="sym">${esc(s)}</td><td class="co">${esc(u.n)}</td><td class="num">${x ? ctx.inr(x.p) : "—"}</td><td class="num ${x ? ctx.ud(x.pct) : "mut"}">${x && x.pct != null ? ctx.sg(x.pct) + "%" : "—"}</td></tr>`; };
  for (const e of r.exposure) {
    if (e.sym) rows.push(line(e.sym, e.dir, e.why));
    else {
      const top = S.uni.stocks.filter(s => s.ind === e.ind && s.board === "Main" && !s.etf && s.val_cr != null).sort((a, b) => b.val_cr - a.val_cr).slice(0, 8);
      rows.push(`<tr class="geo-sec"><td>${arrow(e.dir)}</td><td colspan="4"><b>${esc(e.ind)}</b> sector <span class="mut">· ${esc(e.why)} · its 8 most-traded stocks:</span></td></tr>`);
      for (const s of top) rows.push(line(s.s, e.dir, ""));
    }
  }
  return rows.join("");
}

function drawPanel() {
  const el = ctx && ctx.$("#geo-panel"); if (!el) return;
  const G = ctx.S.geo, { esc } = ctx, r = G && G.regions.find(x => x.id === sel);
  if (!r) { el.innerHTML = G ? '<p class="empty">Click a region on the map or in the table to see what is being reported and which listed companies it touches.</p>' : ""; return; }
  const b = r.baseline || {};
  const head = r.score == null
    ? `<b class="geo-big">—</b><span class="tag">Building baseline</span><p class="note">${b.n || 0} of ${b.need || 48} samples over ${b.days || 0} of ${b.need_days || 3} days. The score appears once this region has its own normal to compare with.</p>`
    : `<b class="geo-big">${r.score}</b><span class="tag ${r.score >= 50 ? "warn" : ""}">${esc(r.level)}</span><p class="note">Volume z ${r.z_vol >= 0 ? "+" : ""}${r.z_vol}, tone z ${r.z_tone >= 0 ? "+" : ""}${r.z_tone} versus the last 30 days of this index.</p>`;
  const heads = (r.heads || []).map(h => `<li><a href="${esc(h.url)}" target="_blank" rel="noopener noreferrer">${esc(h.title)}</a><span class="mut"> · ${esc(h.source || "")}${h.seen_utc ? " · " + esc(ctx.agoTxt(ctx.minsAgo(h.seen_utc))) : ""}</span></li>`).join("") || '<li class="mut">No headlines in the last 24 hours.</li>';
  el.innerHTML = `<div class="geo-detail"><div class="geo-col"><h3>${esc(r.name)}</h3><p class="kick">${esc(r.kind)}</p>${head}
      <div class="geo-sp"><span class="mut">Headlines per hour, 30 days</span>${spark(r.spark || [])}</div>
      <p class="mut">Last 24 h: ${r.n24 ?? "—"} headlines${r.capped ? " (busy: the feed's 100-item cap was hit, so volume is a lower bound)" : ""} · headline tone ${r.tone == null ? "—" : (r.tone > 0 ? "+" : "") + r.tone.toFixed(2)}${r.stale ? " · <b>stale: last fetch failed, showing the previous values</b>" : ""}</p></div>
    <div class="geo-col"><h3>Exposed on NSE</h3><div class="tablecard"><table class="tbl geo-exp"><tbody>${exposureRows(r)}</tbody></table></div>
      <p class="note">▲ tends to gain, ▼ tends to lose when attention on this region rises. A rule of thumb, not measured here and not a forecast.</p></div>
    <div class="geo-col"><h3>Latest headlines</h3><ul class="geo-heads">${heads}</ul></div></div>`;
  el.querySelectorAll("tr[data-s]").forEach(tr => tr.onclick = () => { ctx.openSec(tr.dataset.s); ctx.go("terminal"); });
}

export function renderGeo() {
  const el = ctx && ctx.$("#geo-desk"); if (!el) return;
  const G = ctx.S.geo, { esc } = ctx;
  if (!available()) { el.innerHTML = '<div class="page-head" style="margin-top:28px"><h2 style="font-size:22px">News attention, <span class="acc">by region.</span></h2></div><p class="empty">The geopolitical news index has not been published yet.</p>'; return; }
  if (!G) {
    el.innerHTML = `<div class="page-head" style="margin-top:28px"><p class="kick">— Geopolitical news attention</p><h2 style="font-size:22px">News attention, <span class="acc">by region.</span></h2></div>
      <p class="lede">How much, and in what tone, the news is talking about ten regions that matter to Indian markets, against each region's own recent normal. It measures news, not events. Switch on <b>Geopolitical news attention</b> in the map's layer control, or load it here.</p>
      <p>${failed ? `<span class="mut">Could not load: ${esc(failed)} </span>` : ""}<button class="btn-line" id="geo-load">Load geopolitical news attention</button></p>`;
    const b = el.querySelector("#geo-load"); if (b) b.onclick = async () => { b.disabled = true; await preload(); if (layer && gm && gm.map && !gm.map.hasLayer(layer)) layer.addTo(gm.map); drawMarkers(); renderGeo(); };
    return;
  }
  const regs = G.regions.slice().sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || (b.rate_h ?? 0) - (a.rate_h ?? 0));
  const scored = regs.filter(r => r.score != null).length;
  document.querySelectorAll('[data-asof="geo"]').forEach(a => { a.innerHTML = `News index updated <b>${esc(ctx.istUtc(G.generated_utc))}</b> (${esc(ctx.agoTxt(ctx.minsAgo(G.generated_utc)))}) · source ${esc(G.source)} · refreshed about every hour`; });
  el.innerHTML = `<div class="page-head" style="margin-top:28px"><p class="kick">— Geopolitical news attention</p><h2 style="font-size:22px">News attention, <span class="acc">by region.</span></h2><p class="asof" data-asof="geo"></p></div>
    <p class="note">${esc(G.method)}</p>
    ${scored ? "" : `<p class="note"><b>No region has a score yet.</b> The index compares each region with its own history and has to collect that history first (${(regs[0].baseline || {}).need || 48} samples over ${(regs[0].baseline || {}).need_days || 3} days). Headlines and exposure are real now.</p>`}
    <div id="geo-panel"></div>
    <div class="tablecard"><table class="tbl" id="geo-table"><thead><tr><th>Region</th><th>Kind</th><th>Level</th><th class="r">Score</th><th class="r">24 h headlines</th><th class="r">Per hour</th><th class="r">Tone</th><th>Baseline</th></tr></thead><tbody>${regs.map(r => {
      const b = r.baseline || {};
      return `<tr class="geo-row${sel === r.id ? " on" : ""}" data-id="${esc(r.id)}" tabindex="0"><td class="co"><b>${esc(r.name)}</b>${r.stale ? ' <span class="tag warn">stale</span>' : ""}</td><td class="mut">${esc(r.kind)}</td>
        <td><span class="tag ${r.score != null && r.score >= 50 ? "warn" : ""}">${esc(r.level)}</span></td><td class="num">${r.score ?? "—"}</td><td class="num">${r.n24 ?? "—"}${r.capped ? "+" : ""}</td>
        <td class="num">${r.rate_h == null ? "—" : r.rate_h.toFixed(1) + (r.capped ? "+" : "")}</td><td class="num">${r.tone == null ? "—" : (r.tone > 0 ? "+" : "") + r.tone.toFixed(2)}</td>
        <td class="mut">${b.ready ? "ready" : `${b.n || 0}/${b.need || 48} samples`}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  el.querySelectorAll("tr.geo-row").forEach(tr => { const go = () => { selectRegion(tr.dataset.id); el.querySelectorAll("tr.geo-row").forEach(x => x.classList.toggle("on", x.dataset.id === sel)); }; tr.onclick = go; tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }; });
  drawPanel();
}

/* ---------- Brief / regime strip ---------- */
/* Read the full geo.json once the Globe has loaded it; before that, the tiny geo_summary.json (written by build_site.py) is enough. */
function topRegion() {
  const G = ctx && ctx.S.geo, M = ctx && ctx.S.geo_summary;
  if (G) { const t = G.regions.filter(r => r.score != null).sort((a, b) => b.score - a.score)[0]; return t ? { name: t.name, level: t.level, score: t.score, head: ((t.heads || [])[0] || {}).title } : null; }
  return M && M.top ? M.top : null;
}
export function regimeItem() {
  if (!ctx || !(ctx.S.geo || ctx.S.geo_summary)) return null;
  const top = topRegion();
  return top ? `Geo news attention: ${top.level} · ${top.name}` : "Geo news attention: building baseline";
}
export function briefCard(bcard) {
  const top = topRegion(); if (!top) return "";
  const { esc } = ctx;
  return bcard(top.score >= 65 ? "neg" : "neutral", "Geopolitics · news attention", `${esc(top.name)}: ${esc(top.level)} (${top.score})`, `${esc(top.head || "No headlines in the last 24 hours")}`, "Open globe", 'data-go="globe"');
}