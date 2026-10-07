/* terminal-fx.js: the expert terminal's entrance sequence. Presentation only: no hotkey, search, chart or tick logic is touched.
   The boot screen shows once per browser session, lasts about a second, and any key, click or Esc skips it (that first key is swallowed so it does not trigger a hotkey). */
(function () {
  "use strict";
  var root = document.documentElement;
  function done() { root.classList.remove("fx-boot"); }
  if (!root.classList.contains("fx-boot")) return;                       // the head snippet decided: no boot (seen already, or reduced motion)
  try {
    var ov = document.createElement("div"); ov.className = "fx-boot-ov"; ov.setAttribute("role", "status");
    ov.innerHTML = '<b>B-LAB DESK</b><span>Connecting to the tape</span><div class="fx-boot-bar"><i></i></div><kbd>press any key to skip</kbd>';
    document.body.appendChild(ov);
    var closed = false;
    var close = function () {
      if (closed) return; closed = true;
      removeEventListener("keydown", onKey, true); removeEventListener("pointerdown", close, true);
      done(); ov.classList.add("out"); setTimeout(function () { if (ov.parentNode) ov.parentNode.removeChild(ov); }, 300);
    };
    var onKey = function (e) { e.stopPropagation(); if (e.key !== "Tab") e.preventDefault(); close(); };
    addEventListener("keydown", onKey, true); addEventListener("pointerdown", close, true);
    setTimeout(close, 1000);
  } catch (e) { done(); }
})();
