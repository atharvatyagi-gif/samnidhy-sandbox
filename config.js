/* The B-Lab Cohort: Firebase settings.
   Paste the values from Firebase console > Project settings > General > "Your apps" > Web app (SDK config).
   These web keys are designed to be public; access is controlled by Firebase Auth and the Firestore rules
   in firestore.rules. Never put private/service-account keys here. */

export const firebaseConfig = {
  apiKey: "YOUR_API_KEY_HERE",                         // <-- paste apiKey
  authDomain: "YOUR_PROJECT_ID.firebaseapp.com",       // <-- paste authDomain
  projectId: "YOUR_PROJECT_ID",                        // <-- paste projectId
  storageBucket: "YOUR_PROJECT_ID.appspot.com",        // <-- paste storageBucket
  messagingSenderId: "YOUR_SENDER_ID",                 // <-- paste messagingSenderId
  appId: "YOUR_APP_ID",                                // <-- paste appId
};

// Only these email addresses may register or sign in.
export const ALLOWED_DOMAIN = "tapmi.edu.in";

// Firestore collection that gets one document per registered expert.
export const USERS_COLLECTION = "ExpertUsers";

// Firebase JS SDK version loaded from Google's CDN.
export const FIREBASE_VERSION = "12.19.0";

export function isConfigured() {
  return !Object.values(firebaseConfig).some(v => /YOUR_/.test(String(v)));
}
