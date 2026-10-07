/* auth-fx.js: motion and small helpers for the Expert access page. Presentation only.
   It never reads or changes the sign-in logic: it watches the alert box that the page already shows,
   and when a success message appears it plays a short "unlock" wipe while the page's own redirect (500 ms) runs as before. */
(function () {
  "use strict";
  var reduce = window.FX ? window.FX.reduced : (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  function $(s) { return document.querySelector(s); }

  /* caps-lock hint under password fields */
  document.querySelectorAll('input[type="password"]').forEach(function (inp) {
    var hint = document.createElement("div"); hint.className = "hint caps"; hint.textContent = "Caps Lock is on."; hint.hidden = true; hint.setAttribute("role", "status");
    inp.parentNode.insertBefore(hint, inp.nextSibling);
    var check = function (e) { if (e.getModifierState) hint.hidden = !e.getModifierState("CapsLock"); };
    inp.addEventListener("keydown", check); inp.addEventListener("keyup", check); inp.addEventListener("blur", function () { hint.hidden = true; });
  });

  /* unlock wipe when the success alert shows */
  var alertBox = $(".alert");
  if (alertBox && !reduce && window.MutationObserver) {
    var played = false;
    new MutationObserver(function () {
      if (played || !alertBox.classList.contains("ok") || !alertBox.classList.contains("show")) return;
      played = true;
      var card = $(".card"), r = card.getBoundingClientRect(), c = document.createElement("div");
      c.className = "fx-unlock"; c.style.setProperty("--cx", (r.left + r.width / 2) + "px"); c.style.setProperty("--cy", (r.top + r.height / 2) + "px");
      document.body.appendChild(c); card.classList.add("unlocked");
      void c.offsetWidth; c.classList.add("go");
    }).observe(alertBox, { attributes: true, attributeFilter: ["class"] });
  }
})();
