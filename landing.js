/* The B-Lab Cohort: landing page motion (GSAP + ScrollTrigger).
   If GSAP fails to load or the visitor prefers reduced motion, the page stays fully readable and static. */
(function () {
  "use strict";
  var root = document.documentElement;
  var bar = document.getElementById("progress-bar");
  var enter = document.getElementById("enter");
  var curtain = document.getElementById("curtain");

  // Reading-progress bar (works with or without GSAP)
  function onScroll() {
    var h = document.documentElement.scrollHeight - innerHeight;
    if (bar) bar.style.width = (h > 0 ? (scrollY / h) * 100 : 0) + "%";
  }
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // "Enter the Cohort": circular curtain wipe, then go to the main page (sandbox.html)
  if (enter) {
    enter.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
      e.preventDefault();
      var href = enter.getAttribute("href");
      if (window.gsap && root.classList.contains("motion")) {
        var r = enter.getBoundingClientRect();
        var x = ((r.left + r.width / 2) / innerWidth) * 100, y = ((r.top + r.height / 2) / innerHeight) * 100;
        gsap.timeline({ onComplete: function () { location.href = href; } })
          .to(enter, { scale: 0.94, duration: 0.12, ease: "power2.in" })
          .fromTo(curtain, { clipPath: "circle(0% at " + x + "% " + y + "%)" },
            { clipPath: "circle(150% at " + x + "% " + y + "%)", duration: 0.75, ease: "power3.inOut" }, "<0.05");
      } else {
        location.href = href;
      }
    });
  }

  if (!window.gsap || !window.ScrollTrigger || !root.classList.contains("motion")) return;
  gsap.registerPlugin(ScrollTrigger);
  root.classList.add("gsap");

  /* ---------- 1. hero: layered title fades/rises in on load ---------- */
  var intro = gsap.timeline({ defaults: { ease: "power3.out" } });
  intro.fromTo(".t-main", { opacity: 0, y: 60, filter: "blur(14px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 1.3, stagger: 0.18 })
       .fromTo(".t-shadow", { opacity: 0, x: -20, y: -20 }, { opacity: 1, x: 0, y: 0, duration: 1.4, stagger: 0.08 }, 0.25)
       .fromTo(".hero-in", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 1, stagger: 0.14 }, 0.55);

  /* ---------- 2. hero depth: layers move at different speeds, title recedes ---------- */
  var heroST = { trigger: "#hero", start: "top top", end: "bottom top", scrub: true };
  gsap.to(".layer-back", { yPercent: 18, ease: "none", scrollTrigger: heroST });
  gsap.to(".layer-mid", { yPercent: 42, ease: "none", scrollTrigger: heroST });
  gsap.to(".ticker-ghost", { xPercent: -30, ease: "none", scrollTrigger: heroST });
  gsap.to(".hero-content", { yPercent: -35, scale: 0.86, opacity: 0, ease: "none", scrollTrigger: heroST });
  gsap.to(".t-stack .t-shadow.s2", { x: 26, y: 26, ease: "none", scrollTrigger: heroST });
  gsap.to(".t-stack .t-shadow:not(.s2)", { x: 12, y: 12, ease: "none", scrollTrigger: heroST });

  /* ---------- 3. statement: each line wipes in with a clipping mask tied to scroll ---------- */
  gsap.utils.toArray(".reveal-line").forEach(function (line) {
    gsap.fromTo(line,
      { clipPath: "inset(0 100% 0 0)", opacity: 0.2, y: 30 },
      { clipPath: "inset(0 0% 0 0)", opacity: 1, y: 0, ease: "none",
        scrollTrigger: { trigger: line, start: "top 85%", end: "top 45%", scrub: 0.6 } });
  });

  /* ---------- 4. showcase: pinned, the "screen" scales up from the distance ---------- */
  var mm = gsap.matchMedia();
  mm.add("(min-width: 721px)", function () {
    var tl = gsap.timeline({ scrollTrigger: { trigger: ".showcase", start: "top top", end: "+=140%", scrub: 0.8, pin: ".showcase-pin" } });
    tl.fromTo("#device", { scale: 0.55, rotateX: 28, y: 120, opacity: 0.3, transformPerspective: 1200 },
                         { scale: 1, rotateX: 0, y: 0, opacity: 1, ease: "power2.out", duration: 1 })
      .fromTo(".showcase-copy", { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.5 }, 0)
      .fromTo(".mini-funnel div", { xPercent: -12, opacity: 0 }, { xPercent: 0, opacity: 1, stagger: 0.08, duration: 0.4 }, 0.45)
      .fromTo(".mc-line", { strokeDasharray: 800, strokeDashoffset: 800 }, { strokeDashoffset: 0, duration: 0.6 }, 0.55);
  });
  mm.add("(max-width: 720px)", function () {
    gsap.fromTo("#device", { scale: 0.85, opacity: 0.3 }, { scale: 1, opacity: 1, ease: "none",
      scrollTrigger: { trigger: "#device", start: "top 95%", end: "top 40%", scrub: true } });
  });

  /* ---------- 5. pillars slide in from alternating sides ---------- */
  gsap.utils.toArray(".pillar").forEach(function (p) {
    var fromLeft = p.classList.contains("from-left");
    gsap.fromTo(p, { x: fromLeft ? -140 : 140, opacity: 0 },
      { x: 0, opacity: 1, ease: "none", scrollTrigger: { trigger: p, start: "top 92%", end: "top 55%", scrub: 0.7 } });
  });

  /* ---------- 6. numbers count up ---------- */
  gsap.utils.toArray(".num-card b").forEach(function (b) {
    var end = +b.dataset.count, obj = { v: 0 };
    gsap.fromTo(b.parentNode, { y: 60, opacity: 0 }, { y: 0, opacity: 1, ease: "power2.out", duration: 0.9,
      scrollTrigger: { trigger: b.parentNode, start: "top 90%" } });
    gsap.to(obj, { v: end, duration: 1.4, ease: "power2.out", scrollTrigger: { trigger: b, start: "top 90%" },
      onUpdate: function () { b.textContent = Math.round(obj.v); } });
  });

  /* ---------- 7. finale: pinned; the glow swells and the button rises to the centre ---------- */
  var fin = gsap.timeline({ scrollTrigger: { trigger: ".finale", start: "top top", end: "+=90%", scrub: 0.8, pin: ".finale-pin" } });
  fin.fromTo(".finale-glow", { scale: 0.3, opacity: 0 }, { scale: 1.15, opacity: 1, ease: "none", duration: 1 })
     .fromTo(".finale .eyebrow", { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.3 }, 0.1)
     .fromTo(".finale-title", { opacity: 0, scale: 0.9, y: 40 }, { opacity: 1, scale: 1, y: 0, duration: 0.5 }, 0.15)
     .fromTo(".cta", { opacity: 0, y: 50, scale: 0.8 }, { opacity: 1, y: 0, scale: 1, duration: 0.45, ease: "back.out(1.6)" }, 0.45)
     .fromTo(".finale-note", { opacity: 0 }, { opacity: 1, duration: 0.2 }, 0.8);

  addEventListener("load", function () { ScrollTrigger.refresh(); });
})();
