// node --test tests/js/cmd.test.mjs   (the command grammar is a pure function: no page needed)
import test from "node:test";
import assert from "node:assert/strict";
import { parseCmd, tokens, closest, COMMANDS } from "../../desk-cmd.js";

const STOCKS = { RELIANCE: "Reliance Industries", TCS: "Tata Consultancy Services", TATAMOTORS: "Tata Motors", TATASTEEL: "Tata Steel", HDFCBANK: "HDFC Bank", INFY: "Infosys" };
const ctx = (over = {}) => ({
  resolve: q => {
    const j = q.replace(/\s+/g, "").toUpperCase();
    if (STOCKS[j]) return { sym: j };
    const hits = Object.entries(STOCKS).filter(([s, n]) => q.toUpperCase().split(/\s+/).every(w => n.toUpperCase().split(/\s+/).some(p => p.startsWith(w)) || s.startsWith(w))).map(([s]) => s);
    return hits.length === 1 ? { sym: hits[0] } : hits.length > 1 ? { matches: hits } : null;
  },
  suggest: (q, n) => Object.keys(STOCKS).filter(s => s.startsWith(q.toUpperCase().slice(0, 2))).slice(0, n),
  selected: null,
  houses: [{ id: "tata", name: "Tata Group" }, { id: "reliance", name: "Reliance Group" }, { id: "adani", name: "Adani Group" }],
  sectors: ["Banks", "Software & IT Services", "Oil & Gas"],
  regions: [{ id: "hormuz", name: "Strait of Hormuz" }, { id: "redsea", name: "Red Sea" }],
  legacy: new Set(["OV", "CH", "ID", "MOV", "SEC", "FII", "NEWS", "OUT", "WATCH", "TICKS", "HOUSES", "TOOLS"]),
  flights: null, vessels: null, snapAge: "7 min", sweepAvailable: false, ...over,
});
const act = (t, c) => { const r = parseCmd(t, c || ctx()); return r.action ? [r.action, r.args] : ["error", r]; };

test("tokens: case, spaces, <EQUITY>, <GO>", () => {
  assert.deepEqual(tokens("  reliance   <equity>  splc  tier2 <go> "), ["RELIANCE", "SPLC", "TIER2"]);
  assert.deepEqual(tokens("go"), ["GO"]);                                    // a lone GO is not swallowed
  assert.deepEqual(tokens(""), []);
});

test("SYM [<EQUITY>] SPLC [TIERn] [<GO>]", () => {
  assert.deepEqual(act("RELIANCE SPLC"), ["splc", { sym: "RELIANCE", tier: 1 }]);
  assert.deepEqual(act("reliance <EQUITY> splc tier2 <GO>"), ["splc", { sym: "RELIANCE", tier: 2 }]);
  assert.deepEqual(act("RELIANCE SPLC TIER3"), ["splc", { sym: "RELIANCE", tier: 3 }]);
  assert.deepEqual(act("  tcs   splc   tier1   "), ["splc", { sym: "TCS", tier: 1 }]);
  assert.deepEqual(act("HDFC BANK SPLC TIER2"), ["splc", { sym: "HDFCBANK", tier: 2 }]);       // a company name works too
  assert.equal(act("RELIANCE SPLC TIER4")[0], "error");                                          // not a tier
  assert.match(act("RELIANCE SPLC FOO")[1].error, /Unexpected/);
});

test("SPLC alone uses the selected symbol, otherwise says so", () => {
  assert.deepEqual(act("SPLC TIER2", ctx({ selected: "INFY" })), ["splc", { sym: "INFY", tier: 2 }]);
  const e = act("SPLC")[1];
  assert.match(e.error, /Select a symbol first/);
  assert.ok(e.hints.length > 0);
  assert.deepEqual(act("SPLC TCS TIER2"), ["splc", { sym: "TCS", tier: 2 }]);
});

test("SYM [<EQUITY>] [<GO>] opens the symbol", () => {
  assert.deepEqual(act("INFY"), ["symbol", { sym: "INFY" }]);
  assert.deepEqual(act("infy <equity> <go>"), ["symbol", { sym: "INFY" }]);
  assert.deepEqual(act("Infosys"), ["symbol", { sym: "INFY" }]);
});

test("ALADIN [SYM] and SYM ALADIN", () => {
  assert.deepEqual(act("ALADIN"), ["aladin", { sym: null }]);
  assert.deepEqual(act("aladin tcs <go>"), ["aladin", { sym: "TCS" }]);
  assert.deepEqual(act("TCS ALADIN"), ["aladin", { sym: "TCS" }]);
  assert.equal(act("ALADIN NOSUCH")[0], "error");
});

test("SWEEP depends on the local daemon", () => {
  assert.deepEqual(act("SWEEP", ctx({ sweepAvailable: true })), ["sweep", {}]);
  const e = act("SWEEP")[1];
  assert.equal(e.error, "Sweep data needs the local daemon (not running).");
  assert.deepEqual(e.hints, ["TICKS ON"]);
  assert.equal(act("SWEEP NOW", ctx({ sweepAvailable: true }))[0], "error");
});

test("FLIGHT: exact callsign, digits, none, and never invented", () => {
  const flights = [{ callsign: "AIC101", icao24: "800abc" }, { callsign: "IGO6E101", icao24: "800def" }, { callsign: "AIC202", icao24: "800123" }];
  assert.deepEqual(act("FLIGHT aic101", ctx({ flights })), ["flight", { id: "800abc", label: "AIC101" }]);
  assert.deepEqual(act("FLIGHT AIC 101", ctx({ flights })), ["flight", { id: "800abc", label: "AIC101" }]);
  const pick = act("FLIGHT 101", ctx({ flights }));
  assert.equal(pick[0], "pick");
  assert.deepEqual(pick[1].matches.map(m => m.label), ["AIC101", "IGO6E101"]);
  assert.deepEqual(act("FLIGHT 202", ctx({ flights })), ["flight", { id: "800123", label: "AIC202" }]);
  const none = act("FLIGHT 999", ctx({ flights }))[1];
  assert.match(none.error, /Not in the current snapshot \(age 7 min\)/);
  assert.match(act("FLIGHT AIC10", ctx({ flights }))[1].error, /Not in the current snapshot/);   // a partial callsign is not a match
  assert.match(act("FLIGHT AIC101")[1].error, /No flight snapshot is published/);                    // no snapshot at all
  assert.match(act("FLIGHT", ctx({ flights }))[1].error, /callsign/);
  const many = Array.from({ length: 12 }, (_, i) => ({ callsign: `XX1${String(i).padStart(2, "0")}`, icao24: `a${i}` }));
  assert.equal(act("FLIGHT 1", ctx({ flights: many }))[1].matches.length, 8);                         // at most 8 are listed
});

test("VESSEL: no feed says so; name or MMSI when there is one", () => {
  assert.equal(act("VESSEL EVER GIVEN")[1].error, "Vessel layer off: no AIS key.");
  const vessels = [{ name: "EVER GIVEN", mmsi: 353136000 }, { name: "MAERSK ALABAMA", mmsi: 338234000 }];
  assert.deepEqual(act("vessel ever given", ctx({ vessels })), ["vessel", { id: "353136000", label: "EVER GIVEN" }]);
  assert.deepEqual(act("VESSEL 338234000", ctx({ vessels })), ["vessel", { id: "338234000", label: "MAERSK ALABAMA" }]);
  assert.match(act("VESSEL NOPE", ctx({ vessels }))[1].error, /Not in the current snapshot/);
});

test("HOUSE, SECTOR, GEO: unique, ambiguous, unknown, missing", () => {
  assert.deepEqual(act("HOUSE adani"), ["house", { id: "adani", name: "Adani Group" }]);
  assert.deepEqual(act("house tata group <go>"), ["house", { id: "tata", name: "Tata Group" }]);
  const amb = act("HOUSE group")[1];
  assert.match(amb.error, /several/);
  assert.equal(amb.hints.length, 3);
  assert.match(act("HOUSE zzz")[1].error, /No business house/);
  assert.match(act("HOUSE")[1].error, /Give a group name/);
  assert.deepEqual(act("SECTOR banks"), ["sector", { name: "Banks" }]);
  assert.deepEqual(act("SECTOR oil"), ["sector", { name: "Oil & Gas" }]);
  assert.match(act("SECTOR zzz")[1].error, /No sector/);
  assert.deepEqual(act("GEO hormuz"), ["geo", { id: "hormuz", name: "Strait of Hormuz" }]);
  assert.deepEqual(act("GEO red sea"), ["geo", { id: "redsea", name: "Red Sea" }]);
  assert.match(act("GEO")[1].error, /Give a Globe region/);
});

test("MOVERS, MAP, HELP", () => {
  assert.deepEqual(act("MOVERS"), ["movers", { mode: "PRICE" }]);
  assert.deepEqual(act("movers aladin"), ["movers", { mode: "ALADIN" }]);
  assert.deepEqual(act("MOVERS SHOCK <GO>"), ["movers", { mode: "SHOCK" }]);
  assert.deepEqual(act("MOVERS price"), ["movers", { mode: "PRICE" }]);
  assert.deepEqual(act("MOVERS NOPE")[1].hints, ["PRICE", "ALADIN", "SHOCK"]);
  assert.deepEqual(act("MAP"), ["map", {}]);
  assert.equal(act("MAP NOW")[0], "error");
  assert.deepEqual(act("HELP"), ["help", { filter: "" }]);
  assert.deepEqual(act("help splc"), ["help", { filter: "SPLC" }]);
});

test("ambiguity: a name that fits several securities asks which one, with up to three hints", () => {
  const r = act("TATA")[1];
  assert.match(r.error, /more than one security/);
  assert.deepEqual(r.hints, ["TCS", "TATAMOTORS", "TATASTEEL"]);
  assert.match(act("TATA SPLC")[1].error, /more than one security/);
});

test("unknown input: a one-line reason and the closest three commands or symbols", () => {
  const r = act("RELIAN")[0];
  assert.ok(["error", "symbol"].includes(r));
  const e = act("ZZZZ QQQQ")[1];
  assert.match(e.error, /No security or command matches/);
  assert.ok(e.hints.length <= 3);
  const typo = act("SPLX")[1];
  assert.ok(typo.hints.includes("SPLC"));
  assert.deepEqual(closest("SWEPT", COMMANDS), ["SWEEP"]);
  assert.match(act("")[1].error, /Type a symbol or a command/);
  assert.match(act("   <GO>  ")[1].error, /Type a symbol or a command|No security/);
});

test("the old grammar passes straight through", () => {
  for (const t of ["RELIANCE CH", "NIFTY MOV", "MOV", "TICKS ON", "WATCH", "HOUSES", "TCS OV <GO>", "SEC"]) assert.deepEqual(act(t), ["legacy", {}], t);
});

test("every command word is documented in the grammar and none uses a banned word", () => {
  for (const c of COMMANDS) assert.ok(!/buy|sell|target|recommendation|guaranteed/i.test(c));
  assert.ok(COMMANDS.includes("SPLC") && COMMANDS.includes("SWEEP") && COMMANDS.includes("FLIGHT") && COMMANDS.includes("VESSEL"));
});
