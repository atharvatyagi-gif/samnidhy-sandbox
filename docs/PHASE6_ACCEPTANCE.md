# Immersive site: acceptance results (branch feature/aladin-nexus-desk)

Flat Midnight Slate palette per the owner's decision (no glow, blur, gradients, grain). Local preview, Playwright + Lighthouse 12 (mobile, simulated throttling) + axe-core.

| # | Check | Result |
|---|---|---|
| 1 | Console, 7 pages x 2 viewports x (motion, reduced motion) | 0 errors/warnings from new code. One transient `ERR_CONNECTION_REFUSED` on advanced (reduced, 1440) in a single run; not reproducible in 4 follow-up loads (no failed requests). |
| 2 | No-JS and reduced motion | Every public page renders its content (text length > 200 chars). The expert terminal is a script-driven app and is empty without JavaScript, as before. Screenshots: `docs/shots/phase6/`. |
| 3 | Data integrity | All embedded JSON blocks byte-identical to the Phase 0 build on sandbox, a days/ page and advanced (4/4, 4/4, 3/3). Rendered text of advanced differs only by the new funnel caption. sandbox/days render random lesson content, so two loads of the *old* code already differ; same length, digits only. |
| 4 | Auth untouched | `git diff` of auth.html: CSS, two script tags and an icon link only; 0 lines touching firebase / redirect / allowlist code. Unauthenticated terminal visit still redirects (e2e). |
| 5 | Performance (Lighthouse mobile) | After making the Google Fonts stylesheet non-blocking: **landing 98-100** (first audit 90), **advanced 82**, **auth 98**, **sandbox 65** (baseline 72, runs vary 62-72; below 80 before this work because of ~212 KB of inline data; moving Chart.js lower made it worse, so it stays). CLS <= 0.04. New JS+CSS total 18.6 KB gzipped (budget 60 KB). |
| 6 | Frame rate | Landing hero canvas: 60 fps median (p95 16.7 ms) on desktop and at 4x CPU throttle; canvas stops drawing when the hero is off-screen or the tab is hidden. |
| 7 | Accessibility | axe-core: 0 serious/critical on landing, sandbox, days/, advanced, auth, 404, styleguide at 1440 and 390. Fixed along the way: unlabeled range sliders, scrollable regions without keyboard access, red chip contrast, brand link name, gate tab contrast. |
| 8 | Responsive | No horizontal overflow at 390 / 768 / 1024 / 1440 / 1920 on all pages (fixed advanced at 390 and sandbox nav at 1024). |
| 9 | Paths | Pages and assets resolve from `/` and `days/`; 404.html resolves from the site root at any depth; asset stamps work in `days/`. Sub-path hosting uses relative URLs only. |
| 10 | Terminal safety | e2e: cmd_check 32/0, movers_check 45/0, globe_check 34/0, nexus_check 33/0 (ok/fail); ticks_check had 2 failures in one run that did not reproduce. `/` and Ctrl+K still work after the boot screen; colours unchanged. |
| 11 | Transitions | Normal click navigates in ~310 ms; back works; Ctrl-click opens a new tab; reduced motion disables the curtain. |
| 12 | Build/tests/words | `build_site.py` succeeds; 410 unit tests pass; `check_banned.py` ok; new strings contain none of the banned words (only code identifiers such as `e.target`). |

## Deviations (owner-approved or unavoidable)
Flat palette instead of gradient/glow/glass; "Try the screen" scene omitted (the F-Score distribution is not published); shared nav not added to pages that already have their own sticky header; terminal right-rail animation not done.
