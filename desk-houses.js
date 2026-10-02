/* HOUSES tab: business-house market-cap league. Phase-1 stub - the shell, lazy-open flag and ctx wiring only;
   data (houses.json, loaded on first open, never at page load) and the table arrive in the HOUSES phase. */
let ctx = null, opened = false;
export function init(c) { ctx = c; }
export function renderHouses() {
  if (!ctx) return;
  const el = ctx.$("#houses"); if (!el) return;
  if (!opened) opened = true;          // first open: this is where houses.json will be fetched, not before
  el.innerHTML = '<p class="empty">Business-house data is not built yet.</p>';
}
