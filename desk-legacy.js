/* The earlier ALADIN models (ALADIN 1, Outlook, ALADIN 2.0, the weekly signal, movers, the old paper bots), kept running and learning
   but shown only inside ALADIN BOT (owner, 2026-11-10). Their published files are ENCRYPTED (scripts/aladin2/legacy.py: AES-256-GCM, key from
   the bot's access code with PBKDF2-SHA256); this module derives the key once when the bot is unlocked and decrypts files on request.
   While locked, a request for one of these files is refused here, before any network request is made. The page's JavaScript holds no data.
   OPEN MODE (owner, 2026-11-13: "make the aladin bot accessible without any code"): when legacy/meta.json says {"open": true} the files are
   published readable, everything counts as unlocked for every visitor, and get() reads the plain files. */

export const LEGACY = /^(aladin\.json|predict\.json|aladin_moves\.json|aladin_movers\.json|paper\.json|aladin_method\.json|aladin2\/(?!bot\.enc\.json$).+)$/;
const SS = "aladin2.bot.code";
let key = null, meta = null, metaP = null, open = false;
const listeners = new Set();

export const normalise = c => String(c || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
export const isLegacy = url => LEGACY.test(String(url || "").split("?")[0].replace(/^\.?\//, ""));
export const unlocked = () => !!key || open;
export const isOpen = () => open;
export const onChange = f => listeners.add(f);

async function loadMeta() {
  metaP = metaP || fetch("legacy/meta.json", { cache: "no-store" }).then(r => r.ok ? r.json() : null).catch(() => null);
  meta = await metaP;
  return meta;
}
export async function published() { const m = await loadMeta(); return !!(m && (m.open || (!m.missing && m.salt))); }

const raw = s => Uint8Array.from(atob(s), ch => ch.charCodeAt(0));

/* Derive the key from the code and prove it on the small check value. -> true / false. */
export async function unlock(code, subtle = globalThis.crypto && globalThis.crypto.subtle) {
  const m = await loadMeta();
  if (!m || m.missing || !subtle) return false;
  try {
    const enc = new TextEncoder();
    const km = await subtle.importKey("raw", enc.encode(normalise(code)), "PBKDF2", false, ["deriveKey"]);
    const k = await subtle.deriveKey({ name: "PBKDF2", salt: raw(m.salt), iterations: m.iter, hash: "SHA-256" }, km, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    const ok = new TextDecoder().decode(await subtle.decrypt({ name: "AES-GCM", iv: raw(m.check.iv), additionalData: enc.encode(m.aad) }, k, raw(m.check.ct)));
    if (ok !== "legacy-ok") return false;
    key = k;
    try { sessionStorage.setItem(SS, code); } catch { /* private window */ }
    document.documentElement.classList.add("legacy-on");
    listeners.forEach(f => { try { f(true); } catch { /* a view's own problem */ } });
    return true;
  } catch { return false; }
}

export function lock() {
  if (open) return;                                                  // open mode: there is nothing to lock
  key = null;
  document.documentElement.classList.remove("legacy-on");
  listeners.forEach(f => { try { f(false); } catch { /* fine */ } });
}

/* Unlock again from the code kept for this browser tab (the bot keeps it under the same name). */
export async function resume() {
  const m = await loadMeta();
  if (m && m.open) {                                                 // open mode: unlocked for everyone, no code
    if (!open) { open = true; document.documentElement.classList.add("legacy-on"); listeners.forEach(f => { try { f(true); } catch { /* fine */ } }); }
    return true;
  }
  let c = null;
  try { c = sessionStorage.getItem(SS); } catch { /* none */ }
  return c ? unlock(c) : false;
}

/* The decrypted JSON of one legacy file. Throws {locked: true} while locked (no request is made). */
export async function get(url, subtle = globalThis.crypto && globalThis.crypto.subtle) {
  const path = String(url).split("?")[0].replace(/^\.?\//, "");
  if (open) { const r = await fetch(path, { cache: "no-store" }); if (!r.ok) throw new Error(path + " " + r.status); return r.json(); }
  if (!key) throw Object.assign(new Error("locked: open ALADIN BOT with the access code"), { locked: true });
  const r = await fetch("legacy/" + path + ".enc", { cache: "no-store" });
  if (!r.ok) throw new Error(path + " " + r.status);
  const b = await r.json();
  const pt = await subtle.decrypt({ name: "AES-GCM", iv: raw(b.iv), additionalData: new TextEncoder().encode(meta.aad) }, key, raw(b.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
