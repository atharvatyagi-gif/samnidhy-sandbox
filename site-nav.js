/* site-nav.js: the shared slim nav, reading-progress line and footer for every public page.
   Opt in with <html data-site-nav>. Paths are computed from this script's own URL, so it works from / , /days/ and under /samnidhy-sandbox/.
   Archive picker: lists the saved sessions from days.json (written by scripts/build_site.py); arrow keys move, Esc closes. */
(function () {
  "use strict";
  var me = document.currentScript, src = me && me.src ? me.src : location.href;
  var base = src.replace(/[?#].*$/, "").replace(/[^/]*$/, "");
  var here = location.pathname.split("/").pop() || "index.html";
  var inDays = /\/days\//.test(location.pathname);
  var links = [["Main", "sandbox.html"], ["Advanced", "advanced.html"], ["Expert access", "auth.html"]];
  function el(tag, attrs, text) { var n = document.createElement(tag); for (var k in attrs) n.setAttribute(k, attrs[k]); if (text) n.textContent = text; return n; }

  function build() {
    if (!document.documentElement.hasAttribute("data-site-nav") || document.querySelector(".fx-nav")) return;
    var keepOwn = document.documentElement.getAttribute("data-site-nav") === "static";   // pages with their own sticky header and progress bar
    var prog = el("div", { "class": "fx-progress", "data-fx": "progress", "aria-hidden": "true" });
    var nav = el("div", { "class": "fx-nav" + (keepOwn ? " fx-static" : "") });          // a <div> so it never adds a second banner landmark
    var bar = el("nav", { "aria-label": "Site", style: "display:contents" });
    bar.appendChild(el("a", { "class": "fx-brand", href: base + "index.html" }, "B-Lab Cohort"));
    links.slice(0, 1).forEach(function (l) { bar.appendChild(el("a", Object.assign({ href: base + l[1] }, here === l[1] ? { "aria-current": "page" } : {}), l[0])); });
    var wrap = el("span", { "class": "fx-has-days" });
    var btn = el("button", { type: "button", "aria-haspopup": "true", "aria-expanded": "false" }, "Archive");
    var menu = el("div", { "class": "fx-days", role: "menu", hidden: "" });
    wrap.appendChild(btn); wrap.appendChild(menu); bar.appendChild(wrap);
    links.slice(1).forEach(function (l) { bar.appendChild(el("a", Object.assign({ href: base + l[1] }, here === l[1] ? { "aria-current": "page" } : {}), l[0])); });
    nav.appendChild(bar);
    document.body.insertBefore(nav, document.body.firstChild); if (!keepOwn) document.body.insertBefore(prog, document.body.firstChild);
    if (window.FX) window.FX.init(document.body);

    var loaded = false;
    function items() { return Array.prototype.slice.call(menu.querySelectorAll("a")); }
    function open(v) { menu.hidden = !v; btn.setAttribute("aria-expanded", String(v)); if (v) { var f = items()[0]; if (f) f.focus(); } }
    function load() {
      if (loaded) return; loaded = true;
      fetch(base + "days.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : []; }).then(function (days) {
        if (!days.length) { menu.appendChild(el("span", { style: "padding:8px 12px;display:block;color:#8b8b94" }, "No saved sessions yet")); return; }
        days.forEach(function (d) {
          var a = el("a", Object.assign({ href: base + "days/" + d.date + ".html", role: "menuitem" }, inDays && here === d.date + ".html" ? { "aria-current": "page" } : {}));
          a.appendChild(el("span", {}, d.date)); if (d.label) a.appendChild(el("span", { style: "color:#8b8b94" }, d.label));
          menu.appendChild(a);
        });
      }).catch(function () { menu.appendChild(el("span", { style: "padding:8px 12px;display:block;color:#8b8b94" }, "Archive list not available")); });
    }
    btn.addEventListener("click", function () { load(); open(menu.hidden); });
    menu.addEventListener("keydown", function (e) {
      var l = items(), i = l.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); (l[i + 1] || l[0]).focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); (l[i - 1] || l[l.length - 1]).focus(); }
      else if (e.key === "Escape") { open(false); btn.focus(); }
    });
    document.addEventListener("click", function (e) { if (!wrap.contains(e.target)) open(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !menu.hidden) { open(false); btn.focus(); } });
  }

  function footer() {
    if (!document.documentElement.hasAttribute("data-site-nav") || document.querySelector(".fx-footer") || document.querySelector("footer")) return;   // pages with their own footer keep it (site-footer.js adds the refresh time)
    var f = el("footer", { "class": "fx-footer" });
    var p = el("p", {}, "Educational analysis only. Not investment advice."); f.appendChild(p);
    var t = el("p", { "class": "fx-num" }); f.appendChild(t);
    document.body.appendChild(f);
    fetch(base + "status.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (s) {
      if (s && s.last_success_ist) t.textContent = "Data last refreshed " + s.last_success_ist;
    }).catch(function () { /* footer simply omits the time */ });
  }

  function start() { try { build(); footer(); } catch (e) { if (window.console && console.warn) console.warn("site-nav:", e.message); } }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
