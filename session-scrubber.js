/* session-scrubber.js: the "time machine" strip for the main page and every saved-day page.
   Reads the page's own embedded JSON (dashboard-sessions, dashboard-meta, dashboard-data); changes nothing in them.
   - A calendar strip of every saved session; the one on screen is highlighted; clicking opens that day.
   - Left / Right arrow keys step to the previous / next session (not while typing, not with modifier keys).
   - The header condenses after a short scroll; cards get a light tilt and an edge highlight.
   Day pages open through normal links, so the View Transitions API (or the curtain fallback) handles the visual change. */
(function () {
  "use strict";
  function json(id) { var n = document.getElementById(id); try { return n ? JSON.parse(n.textContent || "null") : null; } catch (e) { return null; } }
  var sessions = json("dashboard-sessions") || [], meta = json("dashboard-meta") || {}, data = json("dashboard-data") || {};
  var current = data.session_date, latest = sessions.length ? sessions[0].session_date : current;
  var fmt = function (iso) { var d = new Date(iso + "T00:00:00"); return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }); };
  var wk = function (iso) { var d = new Date(iso + "T00:00:00"); return d.toLocaleDateString("en-IN", { weekday: "short" }); };
  function hrefFor(date) {
    if (date === latest) return meta.view === "archive" ? meta.home : "sandbox.html";     // the newest session is the main page
    return (meta.days_prefix || "days/") + date + ".html";
  }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; }

  function build() {
    var header = document.querySelector(".site-header");
    if (!header || !sessions.length || document.querySelector(".fx-scrub")) return;
    var dates = sessions.map(function (s) { return s.session_date; }).slice().sort();          // oldest to newest, left to right
    var bar = el("nav", "fx-scrub"); bar.setAttribute("aria-label", "Saved sessions");
    var prev = el("button", "fx-scrub-step", "‹"); prev.type = "button"; prev.setAttribute("aria-label", "Previous session");
    var next = el("button", "fx-scrub-step", "›"); next.type = "button"; next.setAttribute("aria-label", "Next session");
    var track = el("div", "fx-scrub-track");
    var cur = null;
    dates.forEach(function (d) {
      var a = el("a", "fx-scrub-day"); a.href = hrefFor(d); a.setAttribute("data-date", d);
      a.appendChild(el("small", "", wk(d))); a.appendChild(el("b", "", fmt(d)));
      if (d === current) { a.setAttribute("aria-current", "page"); cur = a; }
      track.appendChild(a);
    });
    var hint = el("span", "fx-scrub-hint", "← → step through days");
    bar.appendChild(prev); bar.appendChild(track); bar.appendChild(next); bar.appendChild(hint);
    header.parentNode.insertBefore(bar, header.nextSibling);
    if (cur) cur.scrollIntoView({ inline: "center", block: "nearest" });

    function step(delta) {
      var i = dates.indexOf(current); if (i < 0) return;
      var j = i + delta; if (j < 0 || j >= dates.length) return;
      location.href = hrefFor(dates[j]);
    }
    prev.addEventListener("click", function () { step(-1); });
    next.addEventListener("click", function () { step(1); });
    document.addEventListener("keydown", function (e) {
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      var t = e.target, tag = t && t.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); } else if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    });
  }

  function condense() {
    var on = false, tick = function () { var v = window.scrollY > 80; if (v !== on) { on = v; document.body.classList.toggle("fx-condensed", v); } };
    addEventListener("scroll", tick, { passive: true }); tick();
  }

  function cards() {
    if (!window.FX || window.FX.reduced) return;
    document.querySelectorAll(".hero-card, a.past-card").forEach(function (c) { c.setAttribute("data-fx", "tilt spotlight"); c.setAttribute("data-tilt", "3"); });
    window.FX.init(document.body);
  }

  function start() { try { build(); condense(); cards(); } catch (e) { if (window.console && console.warn) console.warn("session-scrubber:", e.message); } }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
