# Phase 0 audit: immersive site (read-only; no site code changed)

Branch: `feature/aladin-nexus-desk` (CLAUDE.md branch rule). Decisions (owner): public pages keep the flat Midnight Slate palette and gain motion/interactivity only (no glow, blur, gradients, grain); terminal stays dark slate and gets only a boot sequence + transitions.
Screenshots: `docs/shots/phase0/<page>_<1440|390>.png` (landing, sandbox, a days/ page, advanced, auth, terminal).

## Baseline numbers (local preview server, Lighthouse mobile profile, simulated throttling)
| Page | Perf | A11y | LCP | CLS |
|---|---|---|---|---|
| index | 90 | 94 | 2.9 s | 0 |
| sandbox | 72 | 92 | 4.5 s | 0 |
| advanced | 64 | 97 | 5.9 s | 0 |
| auth | 76 | 96 | 4.6 s | 0.038 |

The targets (landing >= 85, others >= 80) are already missed on sandbox, advanced and auth *before* any motion is added. Cause: ~212 KB and ~128 KB of inline CSS/JS plus embedded JSON in the HTML. Budget plan: lazy-init all effects, no new render-blocking assets, and (optional, needs approval) moving embedded data into deferred JSON would help but touches `build_site.py` embed keys, which the brief forbids. So perf targets for sandbox/advanced may need to be "no worse than baseline".

## Console / layout at load (JS on)
No console errors or warnings on any of the six pages at either viewport. Horizontal overflow: **advanced at 390 px scrolls sideways (490 px)** (existing: wide matrix table + top bar). All other pages fit.

## Pages and what exists
| Page | Source | Scripts | Hex literals in page CSS | Notes |
|---|---|---|---|---|
| Landing | index.html, landing.css, landing.js | GSAP 3.15.0 + ScrollTrigger (cdnjs), landing.js, mode-dock.js | 24 in landing.css | `motion` class opt-in already present; orbs/gradients removed in slate pass |
| Main / archive | dashboard.html -> sandbox.html, days/*.html (9 saved days) | Chart.js 4.5.1 (cdnjs) + big inline JS, mode-dock.js | 60 inline | data in `dashboard-status/-sessions/-meta/-data` JSON blocks |
| Advanced | advanced.html | inline JS (innerHTML renders: weather(), matrix(), watch(), detail()), mode-dock.js | 56 inline | embedded `screener-data`, `live-data`, `institutional-data` |
| Gate | auth.html + auth-check.js + config.js | ES module, Firebase loaded via auth-check.js | 21 inline | auth logic must stay untouched |
| Terminal | expert-terminal.html, terminal.css/js, desk-*.js, chart-engine.js | lightweight-charts 5.2.1 (jsDelivr) | 20 in terminal.css (all in :root) | CLAUDE.md: no colour literals outside :root |

## DOM-touching scripts to wrap, not rewrite
- landing.js (ScrollTrigger scenes), mode-dock.js (injects fixed buttons; must not cover the new nav on mobile), reload-home.js.
- advanced.html inline renderers re-run every minute (any wrapper effect must be idempotent: the ratio "View details" panel already loses open state on refresh).
- terminal.js tab switching (`go()`), desk-*.js view renderers, my calm-desk block at the end of terminal.js.

## Not present yet (to create)
404.html, manifest.webmanifest, og:/twitter meta, site.css, fx.js, transitions.js, site-nav.js, styleguide.html, docs/DESIGN_SYSTEM.md, shared footer. Data files available for real numbers: live.json, screener.json, status.json, predict.json, news.json, houses.json (all in site/).

## Concept board (flat slate, motion only)
- **Landing:** hero tape (real indices from live.json, marquee), Canvas 2D drifting candle field in flat greys with bull/bear accents only, clip-mask line reveals, pinned horizontal pillars (desktop), real funnel from screener.json with hover rules, F-Score slider scene, "A day in the lab" timeline from the real workflow schedule, count-ups from real data.
- **Main/archive:** split-reveal session date, count-up stats, staggered mover cards with tilt + cursor spotlight (flat border highlight, no glow), drawing sparklines, sticky condensing header, session scrubber (arrow keys, View Transitions).
- **Advanced:** interactive funnel (real counts, hover = rule, click = scroll), reveal-on-scroll sections, sticky filter bar, row spotlight, number tick on live values. Fix the 390 px overflow while there.
- **Gate:** flat card, animated 1px border, focus states, caps-lock hint, unlock animation + curtain. No auth logic edits.
- **Terminal:** skippable once-per-session boot line, 160 ms view cross-fade, skeleton while loading.
- **Shared:** one slim nav (brand, Main, Archive picker, Advanced, Expert access, progress line), one footer with disclaimer + last refresh from status.json.

## Decisions / risks for you
1. Perf targets on sandbox/advanced/auth are already missed at baseline (table above). OK to set "no worse than baseline, landing >= 85"?
2. Flat-slate means several brief items are dropped by design: gradient mesh, grain, glass blur, glow-following cards, perspective grid floor, gradient border. They become flat equivalents (1px border highlight on hover, tilt, spotlight as a subtle fill change).
3. Phase 1 adds new files only plus a few lines in `build_site.py` (`STATIC`/`ASSETS`). OK.
