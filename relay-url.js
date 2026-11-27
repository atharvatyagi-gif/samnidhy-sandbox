/* Where the terminal looks for real-time Angel One prices.
   - The owner's personal link (the server, opened through its Cloudflare tunnel, password-protected): the server's own relay at
     /ws/ticks on the same address; the owner's PC bridge feeds it (Angel One data never reaches anyone else).
   - Anywhere else (the public pages.dev site, a local preview): the owner's PC daemon at ws://127.0.0.1:8787, if one is running.
   A configured LIVE_RELAY_URL always wins. */
export const PC_DAEMON = "ws://127.0.0.1:8787/ws/ticks";
const PERSONAL = [/\.trycloudflare\.com$/, /^20\.196\.218\.57$/];

export function relayUrl(loc, configured = "") {
  if (configured) return configured;
  if (loc && PERSONAL.some(r => r.test(loc.hostname))) return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws/ticks`;
  return PC_DAEMON;
}
