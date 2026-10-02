/* MAP: geopolitical tension, folded into the existing Globe tab as a layer (not a separate tab - the Globe already
   holds the real vessel/hazard/news layers). Phase-1 stub: ctx wiring and the lazy-load hook only; geo.json
   (and nothing from d3/topojson, which this no longer needs) loads when the layer is first switched on. */
let ctx = null;
export function init(c) { ctx = c; }
export function renderGeo() { return ctx ? "" : ""; }
