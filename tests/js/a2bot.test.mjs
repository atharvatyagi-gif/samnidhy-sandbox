// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { decrypt, normalise, barSvg, curveSvg, histSvg, tracePicture } from "../../desk-a2bot.js";

const blob = JSON.parse(fs.readFileSync(new URL("../fixtures/bot_fixture.enc.json", import.meta.url), "utf8"));

test("the browser opens the file the Python side encrypted, and only with the right code", async () => {
  const p = await decrypt(blob, "ALADIN-TEST-TEST-TEST-TEST-TEST"); assert.equal(p.hello, "world"); assert.equal(p.unicode, "₹ 100"); assert.deepEqual(p.n, [1, 2, 3]);
  assert.equal((await decrypt(blob, "aladin test test test test test")).as_of, "2026-01-01");                      // case, spaces and dashes do not matter
  await assert.rejects(() => decrypt(blob, "ALADIN-WRONG-WRONG-WRONG-WRONG-WRONG"));
  await assert.rejects(() => decrypt({ ...blob, ct: blob.ct.slice(0, -4) + "AAAA" }, "ALADIN-TEST-TEST-TEST-TEST-TEST"));      // a changed file fails the authentication check
  await assert.rejects(() => decrypt({ ...blob, aad: "other" }, "ALADIN-TEST-TEST-TEST-TEST-TEST"));
  assert.equal(normalise(" aladin-ab12 "), "ALADINAB12");
});

test("chart helpers draw labelled SVG from the numbers and handle empty input", () => {
  const b = barSvg([{ l: "1", v: -20 }, { l: "2", v: 30 }], { label: "test bars" }); assert.match(b, /aria-label="test bars"/); assert.match(b, /a2b-dn/); assert.match(b, /a2b-up/); assert.match(b, /<title>/);
  const c = curveSvg([{ name: "a", y: [1, 2, 3] }, { name: "b", y: [1, 1, 1] }], { label: "test lines", xl: ["start", "end"] }); assert.match(c, /aria-label="test lines"/); assert.match(c, /start/); assert.equal(curveSvg([{ name: "e", y: [] }]), "");
  const h = histSvg({ counts: [1, 5, 9, 4], edges: [0, 0.25, 0.5, 0.75, 1], cut_bull: 0.75, cut_bear: 0.25, n: 19 }); assert.match(h, /a2b-up/); assert.match(h, /a2b-dn/); assert.match(h, /a2b-mid/);
});

test("the decision picture shows closes, the 5-day range, the entry zone and the exit level, and says so when there is no history", () => {
  const t = { sym: "TST", close: 100, series: { c: Array.from({ length: 30 }, (_, i) => 90 + i / 3) }, range5: [95, 106], entry_zone: [99.5, 100.5], invalidation: 96 };
  const s = tracePicture(t); assert.match(s, /a2-hist/); assert.match(s, /a2b-zone/); assert.match(s, /a2b-stop/); assert.match(s, /exit 96/); assert.match(s, /TST/);
  assert.match(tracePicture({ sym: "NOPE", series: {} }), /No price history for NOPE/);
});
