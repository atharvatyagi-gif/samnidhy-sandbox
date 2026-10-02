/* TOOLS tab / ALADIN: probability model view. Phase-1 stub: ctx wiring, lazy-open flag and the filter hook the
   command line uses ("RELIANCE ALADIN"). The table, expansion and live patching arrive in the ALADIN UI phase. */
let ctx = null, opened = false, filterSym = null;
export function init(c) { ctx = c; }

/* The ALADIN combiner. Identical to combine_py() in scripts/aladin_model.py: both must pass tests/fixtures/combiner_cases.json.
   logit(p) = logit(p_tech) + wF F/100 + wS S/100 + wSweep S_sweep/100. A missing front (null/undefined) contributes 0. p is clipped to [0.02, 0.98].
   confidence: Low if |p-0.5| < 0.03, Medium if < 0.07, else High.
   agreement: of the AVAILABLE fronts (F, T, S) how many lean the same way as p (a front leans up above +10, down below -10, with 1e-9 of slack so
   floating-point noise like 200*(0.55-0.5) = 10.000000000000009 does not count as "above 10"): "k/n". */
export function combine(pTech, F, S, sSweep, w) {
  w = w || { wF: 0.20, wS: 0.12, wSweep: 0.18 };
  const T = Math.max(-100, Math.min(100, 200 * (pTech - 0.5)));
  const q = Math.min(0.999999, Math.max(1e-6, pTech));
  const z = Math.log(q / (1 - q)) + w.wF * (F ?? 0) / 100 + w.wS * (S ?? 0) / 100 + w.wSweep * (sSweep ?? 0) / 100;
  const p = Math.min(0.98, Math.max(0.02, 1 / (1 + Math.exp(-z))));
  const fronts = [F, T, S].filter(x => x !== null && x !== undefined);
  const up = p > 0.5, EPS = 1e-9, k = fronts.filter(x => (x > 10 + EPS && up) || (x < -10 - EPS && !up)).length, d = Math.abs(p - 0.5);
  return { p: Math.round(p * 1e4) / 1e4, q: Math.round((1 - p) * 1e4) / 1e4, T: Math.round(T * 10) / 10,
    conf: d < 0.03 ? "Low" : d < 0.07 ? "Medium" : "High", agree: `${k}/${fronts.length}`, agree_k: k, agree_n: fronts.length };
}
export function setAladinFilter(sym) { filterSym = sym || null; }
export function renderAladin() {
  if (!ctx) return;
  const el = ctx.$("#aladin"); if (!el) return;
  if (!opened) opened = true;          // first open: aladin.json / sentiment.json are read here, not at page load
  el.innerHTML = `<p class="empty">ALADIN is not built yet${filterSym ? ` (asked for ${ctx.esc(filterSym)})` : ""}.</p>
    <p class="note">ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice.</p>`;
}
export function renderAladinMini(sym) { return ""; }          // Details-rail block; empty until the model exists
