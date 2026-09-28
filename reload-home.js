/* Reloading any page takes the visitor back to the home page (the B-Lab Cohort: landing page).
   Only on the website (http/https), so files opened from disk behave normally. */
(function () {
  if (!/^https?:/.test(location.protocol)) return;
  var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
  var reloaded = nav ? nav.type === "reload" : (performance.navigation && performance.navigation.type === 1);
  if (reloaded) {
    var me = document.currentScript;
    location.replace((me && me.getAttribute("data-home")) || "index.html");
  }
})();
