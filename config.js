/* The B-Lab Cohort: Firebase settings.
   Paste the values from Firebase console > Project settings > General > "Your apps" > Web app (SDK config).
   These web keys are designed to be public; access is controlled by Firebase Auth and the Firestore rules
   in firestore.rules.template. Never put private/service-account keys here. */

export const firebaseConfig = {
  apiKey: "AIzaSyCDQZRybNdoTyOPk7fuYbcUDVVlTKV6jq4",
  authDomain: "terminal-b-863a0.firebaseapp.com",
  projectId: "terminal-b-863a0",
  storageBucket: "terminal-b-863a0.firebasestorage.app",
  messagingSenderId: "794201977216",
  appId: "1:794201977216:web:a372bee1bdd0c96b19d165",
  measurementId: "G-521BR7ELTW",
};

// Only these email addresses may register or sign in.
export const ALLOWED_DOMAIN = "learner.manipal.edu";   // TAPMI students' Manipal learner accounts

// Registration also requires the student's roll number + date of birth to match the TAPMI student list
// (as one-way keys inside the Firestore rules, see scripts/student_allowlist.py; the list itself is never online).
export const ALLOWLIST_SALT = "blab-v1";              // must match scripts/student_allowlist.py

// Firestore collections.
export const USERS_COLLECTION = "ExpertUsers";        // one document per registered expert
export const CLAIMS_COLLECTION = "Claims";            // one per student key: each student registers once

// Firebase JS SDK version loaded from Google's CDN.
export const FIREBASE_VERSION = "12.19.0";

export function isConfigured() {
  return !Object.values(firebaseConfig).some(v => /YOUR_/.test(String(v)));
}
