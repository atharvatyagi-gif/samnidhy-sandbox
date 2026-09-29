/* The B-Lab Cohort: shared Firebase setup + the Expert access guard.
   Used by auth.html (sign-in page) and expert-terminal.html.

   On a protected page, import it with:   <script type="module" src="auth-check.js" data-guard></script>
   The page stays hidden until a signed-in @learner.manipal.edu user with a completed registration
   (an ExpertUsers document) is confirmed; otherwise the visitor is sent to auth.html immediately.
   When access is confirmed it fires an "expert-ready" event with the user. */

import { firebaseConfig, ALLOWED_DOMAIN, ALLOWLIST_SALT, USERS_COLLECTION, FIREBASE_VERSION, isConfigured } from "./config.js";

const CDN = `https://www.gstatic.com/firebasejs/${FIREBASE_VERSION}`;

// Exactly <something>@learner.manipal.edu, nothing after it (case-insensitive).
export const TAPMI_EMAIL = new RegExp(`^[A-Za-z0-9._%+-]+@${ALLOWED_DOMAIN.replace(/\./g, "\\.")}$`, "i");
export const DOMAIN_ERROR = "Only Manipal learner email addresses (@learner.manipal.edu) are authorized for Expert Access to The B-Lab Cohort:.";

export function isTapmiEmail(email) {
  return TAPMI_EMAIL.test(String(email || "").trim());
}

// Same key as scripts/student_allowlist.py: SHA-256("blab-v1|<ROLL>|<YYYY-MM-DD>")
export async function studentKey(roll, dobIso) {
  const r = String(roll || "").replace(/\s+/g, "").toUpperCase();
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${ALLOWLIST_SALT}|${r}|${dobIso}`));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

let cache = null;
export async function firebase() {
  if (cache) return cache;
  if (!isConfigured()) throw new Error("not-configured");
  const [appMod, authMod, dbMod] = await Promise.all([
    import(`${CDN}/firebase-app.js`), import(`${CDN}/firebase-auth.js`), import(`${CDN}/firebase-firestore.js`),
  ]);
  const app = appMod.initializeApp(firebaseConfig);
  cache = { app, auth: authMod.getAuth(app), db: dbMod.getFirestore(app), authMod, dbMod };
  return cache;
}

/* ---------------- guard (only on pages that include data-guard) ---------------- */
const isGuarded = !!document.querySelector('script[src$="auth-check.js"][data-guard]');

if (isGuarded) {
  document.documentElement.style.visibility = "hidden";          // nothing shows before the check
  const deny = reason => window.location.replace("auth.html" + (reason ? "?reason=" + reason : ""));
  (async () => {
    let fb;
    try { fb = await firebase(); } catch (e) { deny(e.message === "not-configured" ? "setup" : "offline"); return; }
    fb.authMod.onAuthStateChanged(fb.auth, async user => {
      if (!user) { deny("signin"); return; }
      if (!isTapmiEmail(user.email)) { await fb.authMod.signOut(fb.auth); deny("domain"); return; }
      // a completed registration (checked against the student list) is required, not just an account
      try {
        const snap = await fb.dbMod.getDoc(fb.dbMod.doc(fb.db, USERS_COLLECTION, user.uid));
        if (!snap.exists()) { await fb.authMod.signOut(fb.auth); deny("notregistered"); return; }
      } catch (e) { await fb.authMod.signOut(fb.auth); deny("notregistered"); return; }
      window.expertUser = user;
      document.documentElement.style.visibility = "";
      document.documentElement.classList.remove("locked");      // the page's own pre-paint lock
      document.dispatchEvent(new CustomEvent("expert-ready", { detail: { user, signOut: () => fb.authMod.signOut(fb.auth) } }));
    });
  })();
}
