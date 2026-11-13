/* Open mode (owner, 2026-11-13: "make the aladin bot accessible without any code"): legacy/meta.json {"open": true} unlocks everything for
   every visitor, and the earlier models' files are read as plain JSON. Runs in its own file: the module keeps its state. */
import test from "node:test";
import assert from "node:assert/strict";

const classes = new Set();
globalThis.document = { documentElement: { classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) } } };
const asked = [];
globalThis.fetch = async url => { asked.push(url); const body = url === "legacy/meta.json" ? { v: 1, open: true } : url === "aladin.json" ? { plain: true } : null;
  return { ok: body !== null, status: body ? 200 : 404, json: async () => body }; };
const L = await import("../../desk-legacy.js");

test("open mode: no code, everything unlocked, files read plain, and lock() cannot close it", async () => {
  assert.equal(L.unlocked(), false);
  let told = null; L.onChange(on => { told = on; });
  assert.equal(await L.resume(), true);
  assert.ok(L.unlocked() && L.isOpen() && classes.has("legacy-on") && told === true);
  assert.equal(await L.published(), true);
  assert.deepEqual(await L.get("aladin.json"), { plain: true });
  assert.ok(asked.includes("aladin.json") && !asked.some(u => u.endsWith(".enc")), "plain file, no encrypted copy");
  L.lock();
  assert.ok(L.unlocked() && classes.has("legacy-on"));
});
