/* The desk's command grammar, as a pure function (no DOM, no network): parseCmd(text, ctx) -> { action, args } | { error, hints }.
   It extends the "/" command line; it does not replace it. Anything that is not new grammar comes back as { action: "legacy" } so the page's
   existing handling (SYMBOL CODE, TICKS ON, function keys) keeps working exactly as before.

   Grammar (case-insensitive, extra spaces ignored, an optional <EQUITY> after a symbol and an optional trailing <GO> are dropped):
     SYM [<EQUITY>] SPLC [TIER1|TIER2|TIER3] [<GO>]   open SYM and its supply chain to that depth (default TIER1)
     SPLC [TIERn]                                     same for the symbol already selected
     SYM [<EQUITY>] [<GO>]                            open the symbol
     ALADIN [SYM]    SYM ALADIN                       the ALADIN table, optionally on one symbol
     SWEEP                                            ALADIN rows that have a liquidity sweep today (needs the local tick program)
     FLIGHT <callsign|digits>   VESSEL <name|MMSI>    exact match in the current snapshot only; nothing is ever guessed
     HOUSE <name>   SECTOR <name>   GEO <region>      jump to a business house / sector / Globe region
     MOVERS [PRICE|ALADIN|SHOCK]   MAP   HELP [text]
   ctx supplies everything that comes from the page, so the parser can be tested on its own:
     resolve(q) -> { sym } | { matches: [sym...] } | null      selected -> symbol or null         suggest(q, n) -> [sym...]
     houses [{id, name}]   sectors [name]   regions [{id, name}]   legacy: Set of old function codes
     flights / vessels: array or null (null = no snapshot published)   snapAge: text   sweepAvailable: boolean                                     */

export const COMMANDS = ["SPLC", "SWEEP", "FLIGHT", "VESSEL", "HOUSE", "SECTOR", "GEO", "MOVERS", "MAP", "HELP", "ALADIN"];
const FIRST = new Set(COMMANDS);
const MOVERS_MODES = ["PRICE", "ALADIN", "SHOCK"];

export function tokens(text) {
  let t = String(text || "").toUpperCase().replace(/[<>]/g, " ").split(/\s+/).filter(Boolean);
  if (t.length > 1 && t[t.length - 1] === "GO") t.pop();                   // <GO> is Enter; typing it is optional
  if (t.length > 1) t = t.filter((w, i) => !(w === "EQUITY" && i > 0));    // <EQUITY> after the symbol is optional
  return t;
}

/* edit distance, only to suggest "did you mean" for typos */
function dist(a, b) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return d[a.length][b.length];
}
export function closest(word, list, n = 3) {
  return list.map(x => [x.startsWith(word) ? 0 : dist(word, x), x]).filter(([d]) => d <= 2).sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1])).slice(0, n).map(([, x]) => x);
}

const err = (error, hints = []) => ({ error, hints: hints.slice(0, 3) });
const ok = (action, args = {}) => ({ action, args });

function symbolOf(parts, c) {
  const q = parts.join(" ");
  const r = c.resolve ? c.resolve(q) : null;
  if (r && r.sym) return { sym: r.sym };
  if (r && r.matches && r.matches.length > 1) return { error: err(`"${q}" matches more than one security: pick one.`, r.matches) };
  if (r && r.matches && r.matches.length === 1) return { sym: r.matches[0] };
  const near = [...(c.suggest ? c.suggest(q, 3) : []), ...closest(parts[0] || "", COMMANDS, 2)];
  return { error: err(`No security or command matches "${q}".`, near) };
}
function tierOf(rest) {
  const i = rest.findIndex(w => /^TIER[123]$/.test(w));
  if (i < 0) return { tier: 1, rest };
  return { tier: +rest[i][4], rest: rest.filter((_, k) => k !== i) };
}
function pickBy(rest, items, nameOf, idOf) {
  const q = rest.join(" ");
  if (!q) return { none: true };
  const exact = items.filter(x => idOf(x).toUpperCase() === q || nameOf(x).toUpperCase() === q);
  if (exact.length === 1) return { item: exact[0] };
  const hits = items.filter(x => rest.every(w => nameOf(x).toUpperCase().split(/[^A-Z0-9&]+/).some(p => p.startsWith(w)) || idOf(x).toUpperCase().startsWith(w)));
  if (hits.length === 1) return { item: hits[0] };
  if (hits.length > 1) return { many: hits.slice(0, 3).map(nameOf), q };
  return { near: closest(q, items.map(nameOf).map(s => s.toUpperCase()), 3), q };
}

export function parseCmd(text, c = {}) {
  const t = tokens(text);
  if (!t.length) return err("Type a symbol or a command. HELP lists them.", ["HELP"]);
  const w0 = t[0], rest = t.slice(1);

  if (FIRST.has(w0)) {
    switch (w0) {
      case "SPLC": {
        const { tier, rest: r2 } = tierOf(rest);
        if (r2.length) { const s = symbolOf(r2, c); return s.error || ok("splc", { sym: s.sym, tier }); }
        return c.selected ? ok("splc", { sym: c.selected, tier }) : err("Select a symbol first (or type SYMBOL SPLC).", ["RELIANCE SPLC", "TCS SPLC"]);
      }
      case "SWEEP":
        if (rest.length) return err("SWEEP takes no extra words.", ["SWEEP"]);
        return c.sweepAvailable ? ok("sweep") : err("Sweep data needs the local daemon (not running).", ["TICKS ON"]);
      case "FLIGHT": case "VESSEL": {
        const isF = w0 === "FLIGHT", list = isF ? c.flights : c.vessels, q = rest.join("").replace(/\s+/g, "");
        if (!q) return err(isF ? "Give a callsign or its digits, e.g. FLIGHT AI101." : "Give a vessel name or MMSI, e.g. VESSEL 419000123.", []);
        if (list == null) return err(isF ? "No flight snapshot is published yet, so there is nothing to look up. Nothing is guessed." : "Vessel layer off: no AIS key.", []);
        const key = isF ? (f => (f.callsign || "").toUpperCase().replace(/\s+/g, "")) : (v => (v.name || "").toUpperCase().replace(/\s+/g, ""));
        const idOf = isF ? (f => f.icao24) : (v => String(v.mmsi)), lbl = isF ? key : (v => v.name);
        const exact = list.filter(x => key(x) === q || (!isF && idOf(x) === q));
        if (exact.length === 1) return ok(isF ? "flight" : "vessel", { id: idOf(exact[0]), label: lbl(exact[0]) });
        const part = /^\d+$/.test(q) || !isF ? list.filter(x => key(x).includes(q) || idOf(x).includes(q)) : [];
        if (exact.length > 1 || part.length > 1) return { action: "pick", args: { kind: isF ? "flight" : "vessel", matches: (exact.length ? exact : part).slice(0, 8).map(x => ({ id: idOf(x), label: lbl(x) })) } };
        if (part.length === 1) return ok(isF ? "flight" : "vessel", { id: idOf(part[0]), label: lbl(part[0]) });
        return err(`Not in the current snapshot (age ${c.snapAge || "unknown"}).`, []);
      }
      case "HOUSE": {
        const r = pickBy(rest, c.houses || [], h => h.name, h => h.id);
        if (r.none) return err("Give a group name, e.g. HOUSE TATA.", (c.houses || []).slice(0, 3).map(h => h.name));
        if (r.item) return ok("house", { id: r.item.id, name: r.item.name });
        return r.many ? err(`"${r.q}" matches several groups: be more specific.`, r.many) : err(`No business house matches "${r.q}".`, r.near);
      }
      case "SECTOR": {
        const r = pickBy(rest, c.sectors || [], s => s, s => s);
        if (r.none) return err("Give a sector name, e.g. SECTOR BANKS.", (c.sectors || []).slice(0, 3));
        if (r.item) return ok("sector", { name: r.item });
        return r.many ? err(`"${r.q}" matches several sectors: be more specific.`, r.many) : err(`No sector matches "${r.q}".`, r.near);
      }
      case "GEO": {
        const r = pickBy(rest, c.regions || [], g => g.name, g => g.id);
        if (r.none) return err("Give a Globe region, e.g. GEO HORMUZ.", (c.regions || []).slice(0, 3).map(g => g.name));
        if (r.item) return ok("geo", { id: r.item.id, name: r.item.name });
        return r.many ? err(`"${r.q}" matches several regions: be more specific.`, r.many) : err(`No Globe region matches "${r.q}".`, r.near);
      }
      case "MOVERS": {
        if (!rest.length) return ok("movers", { mode: "PRICE" });
        const m = MOVERS_MODES.find(x => x === rest[0]);
        return m && rest.length === 1 ? ok("movers", { mode: m }) : err(`MOVERS takes PRICE, ALADIN or SHOCK, not "${rest.join(" ")}".`, MOVERS_MODES);
      }
      case "MAP": return rest.length ? err("MAP takes no extra words.", ["MAP"]) : ok("map");
      case "HELP": return ok("help", { filter: rest.join(" ") });
      case "ALADIN": {
        if (!rest.length) return ok("aladin", { sym: null });
        const s = symbolOf(rest, c);
        return s.error || ok("aladin", { sym: s.sym });
      }
    }
  }

  const iS = t.indexOf("SPLC");
  if (iS > 0) {                                                            // SYM [<EQUITY>] SPLC [TIERn]
    const s = symbolOf(t.slice(0, iS), c);
    if (s.error) return s.error;
    const { tier, rest: r2 } = tierOf(t.slice(iS + 1));
    return r2.length ? err(`Unexpected "${r2.join(" ")}" after SPLC. Use SPLC, SPLC TIER2 or SPLC TIER3.`, [`${s.sym} SPLC TIER2`]) : ok("splc", { sym: s.sym, tier });
  }
  if (t.length > 1 && t[t.length - 1] === "ALADIN") {                      // the older SYMBOL ALADIN order
    const s = symbolOf(t.slice(0, -1), c);
    return s.error || ok("aladin", { sym: s.sym });
  }
  const legacy = c.legacy || new Set();
  if (legacy.has(t[t.length - 1]) || legacy.has(w0)) return ok("legacy");
  const s = symbolOf(t, c);
  return s.error || ok("symbol", { sym: s.sym });
}
