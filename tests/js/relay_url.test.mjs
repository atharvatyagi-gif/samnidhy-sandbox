// node --test tests/js/relay_url.test.mjs
// The personal link must use the server's relay (it only ever tried the PC daemon, so it stayed on delayed prices, 27 Nov 2026).
import test from "node:test";
import assert from "node:assert/strict";
import { relayUrl, PC_DAEMON } from "../../relay-url.js";

const loc = href => { const u = new URL(href); return { hostname: u.hostname, host: u.host, protocol: u.protocol }; };

test("personal link (Cloudflare tunnel, any name) -> the same address's relay over wss", () => {
  assert.equal(relayUrl(loc("https://being-tucson-releases-assign.trycloudflare.com/expert-terminal")), "wss://being-tucson-releases-assign.trycloudflare.com/ws/ticks");
  assert.equal(relayUrl(loc("https://another-name-here.trycloudflare.com/")), "wss://another-name-here.trycloudflare.com/ws/ticks");
});

test("the server's own address over plain http -> ws", () => {
  assert.equal(relayUrl(loc("http://20.196.218.57/expert-terminal")), "ws://20.196.218.57/ws/ticks");
});

test("public site and local previews never reach the server relay", () => {
  assert.equal(relayUrl(loc("https://blab-cohort.pages.dev/expert-terminal")), PC_DAEMON);
  assert.equal(relayUrl(loc("http://127.0.0.1:8765/expert-dev.html")), PC_DAEMON);
  assert.equal(relayUrl(loc("https://evil.trycloudflare.com.example.org/")), PC_DAEMON);
  assert.equal(relayUrl(undefined), PC_DAEMON);
});

test("a configured relay address always wins", () => {
  assert.equal(relayUrl(loc("https://x.trycloudflare.com/"), "wss://relay.example/ws"), "wss://relay.example/ws");
});
