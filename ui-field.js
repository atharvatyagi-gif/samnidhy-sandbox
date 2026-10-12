/* The market field behind the search: every NIFTY 500 stock is a dot. Size = value traded in the last session, colour = its move (green up, red down,
   brighter = bigger), grouped by industry in small clusters around the edge of the screen so the middle stays clear for the search.
   The dots drift slowly; near the pointer they brighten and the closest shows its name and move; a click opens that stock's story.
   Real data only (the published stock list); reduced motion = a still picture. Pure drawing on one canvas, no library. */
export function marketField(canvas, stocks, quoteOf, onPick) {
  const ctx = canvas.getContext("2d"), still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const tip = document.createElement("div"); tip.className = "hx-tip"; tip.hidden = true; canvas.parentElement.appendChild(tip);
  let W = 0, H = 0, dpr = 1, dots = [], labels = [], dim = 1, px = -1e4, py = -1e4, hover = null, t0 = performance.now(), raf = 0, visible = true;
  const n500 = stocks.filter(e => e.n500 && !e.etf);
  const groups = new Map(); n500.forEach(e => { const k = e.ind || "Other"; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(e); });
  const clusters = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  const maxV = Math.max(...n500.map(e => e.val_cr || 0), 1);

  function layout() {
    dpr = Math.min(2, devicePixelRatio || 1); W = canvas.clientWidth; H = canvas.clientHeight; canvas.width = W * dpr; canvas.height = H * dpr; dim = W < 700 ? 0.5 : 1;
    const small = W < 700, rx = W * (small ? 0.42 : 0.42), ry = H * (small ? 0.40 : 0.36), cx = W / 2, cy = H * 0.52; dots = []; labels = [];
    clusters.forEach(([ind, list], ci) => {
      const ang = (ci / clusters.length) * Math.PI * 2 - Math.PI / 2 + 0.3, gx = cx + Math.cos(ang) * rx, gy = Math.max(110, cy + Math.sin(ang) * ry), sp = small ? 5.5 : 7.5;
      if (!small && list.length >= 6 && gy < H * 0.72) labels.push({ ind, x: gx, y: gy + sp * Math.sqrt(list.length) + 14, avg: list.reduce((t, e) => t + (quoteOf(e).pct || 0), 0) / list.length });
      list.sort((a, b) => (b.val_cr || 0) - (a.val_cr || 0)).forEach((e, i) => {
        const a = i * 2.39996, r = sp * Math.sqrt(i + 0.5), q = quoteOf(e), p = q.pct == null ? 0 : q.pct;   // sunflower packing inside each cluster
        dots.push({ e, ind, bx: gx + Math.cos(a) * r, by: gy + Math.sin(a) * r, x: 0, y: 0, ph: Math.random() * 6.28, sz: (small ? 1.1 : 1.6) + (small ? 3 : 5) * Math.sqrt((e.val_cr || 0) / maxV), p });
      });
    });
  }
  const col = (p, a) => p > 0 ? `rgba(52,211,153,${a})` : p < 0 ? `rgba(248,113,113,${a})` : `rgba(161,161,170,${a})`;
  function frame(now) {
    const t = (now - t0) / 1000; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    let best = null, bd = 26 * 26;
    for (const d of dots) {
      d.x = d.bx + (still ? 0 : Math.sin(t * 0.35 + d.ph) * 3); d.y = d.by + (still ? 0 : Math.cos(t * 0.3 + d.ph * 1.3) * 3);
      const dx = d.x - px, dy = d.y - py, dd = dx * dx + dy * dy, near = Math.max(0, 1 - Math.sqrt(dd) / 160);
      const mag = Math.min(1, Math.abs(d.p) / 4), a = (0.18 + 0.35 * mag) * dim + 0.45 * near;
      ctx.beginPath(); ctx.arc(d.x, d.y, d.sz * (1 + near * 0.6), 0, 6.283); ctx.fillStyle = col(d.p, a); ctx.fill();
      if (dd < bd) { bd = dd; best = d; }
    }
    ctx.font = "500 10px Inter, sans-serif"; ctx.textAlign = "center";
    for (const l of labels) { ctx.fillStyle = "rgba(161,161,170,0.55)"; ctx.fillText(l.ind.length > 24 ? l.ind.slice(0, 23) + "…" : l.ind, l.x, l.y); ctx.fillStyle = l.avg >= 0 ? "rgba(52,211,153,0.7)" : "rgba(248,113,113,0.7)"; ctx.fillText((l.avg >= 0 ? "+" : "") + l.avg.toFixed(1) + "%", l.x, l.y + 12); }
    if (best !== hover) { hover = best; canvas.style.cursor = best ? "pointer" : "default"; }
    if (hover) {
      ctx.beginPath(); ctx.arc(hover.x, hover.y, hover.sz * 1.6 + 5, 0, 6.283); ctx.strokeStyle = col(hover.p, 0.9); ctx.lineWidth = 1.5; ctx.stroke();
      tip.hidden = false; tip.style.transform = `translate(${Math.round(hover.x + 14)}px, ${Math.round(hover.y - 14)}px)`;
      tip.innerHTML = `<b>${hover.e.s}</b> <span class="${hover.p > 0 ? "up" : hover.p < 0 ? "down" : "flat"}">${hover.p > 0 ? "+" : ""}${hover.p.toFixed(2)}%</span><small>${(hover.e.n || "").replace(/</g, "")}</small>`;
    } else tip.hidden = true;
    if (!still && visible) raf = requestAnimationFrame(frame);
  }
  const start = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); };
  layout(); start();
  addEventListener("resize", () => { layout(); start(); });
  addEventListener("pointermove", e => { const r = canvas.getBoundingClientRect(); px = e.clientX - r.left; py = e.clientY - r.top; if (still) start(); }, { passive: true });
  document.addEventListener("pointerleave", () => { px = py = -1e4; });
  canvas.addEventListener("click", () => { if (hover) onPick(hover.e.s); });
  document.addEventListener("visibilitychange", () => { visible = !document.hidden; if (visible) start(); });
  return { count: n500.length, clusters: clusters.length, pause: () => { visible = false; }, resume: () => { visible = true; start(); } };
}
