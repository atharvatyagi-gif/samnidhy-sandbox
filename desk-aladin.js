/* TOOLS tab / ALADIN: probability model view. Phase-1 stub: ctx wiring, lazy-open flag and the filter hook the
   command line uses ("RELIANCE ALADIN"). The table, expansion and live patching arrive in the ALADIN UI phase. */
let ctx = null, opened = false, filterSym = null;
export function init(c) { ctx = c; }
export function setAladinFilter(sym) { filterSym = sym || null; }
export function renderAladin() {
  if (!ctx) return;
  const el = ctx.$("#aladin"); if (!el) return;
  if (!opened) opened = true;          // first open: aladin.json / sentiment.json are read here, not at page load
  el.innerHTML = `<p class="empty">ALADIN is not built yet${filterSym ? ` (asked for ${ctx.esc(filterSym)})` : ""}.</p>
    <p class="note">ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice.</p>`;
}
export function renderAladinMini(sym) { return ""; }          // Details-rail block; empty until the model exists
