# ALADIN audit, Phase 6: model E on the site, earlier models behind ALADIN BOT

Written 2026-11-10. Everything is on the `aladin-audit` branch. Nothing is on the live site until you write "approved phase 6".

## What changed

### Public site: one model
Every public page now shows only model E (momentum with a daily risk check).

| Page | What a visitor sees now |
|---|---|
| Terminal, ALADIN tab | The market strip: NIFTY 500 against its 200-day average, the share invested, India VIX, breadth and 20 days of FII/DII flows. Alerts appear when there is something to report. A search for any stock. The ranked list shows, for each stock: its rank, its 6-month move, a state ("In the portfolio" or "No signal"), its group's record with 95% ranges, the expected lead after costs, and the size for your capital. Clicking a row gives 3 to 5 plain reasons. Below the list: a model-health panel with a calibration chart, and the paper account. |
| Terminal, Details panel | A short ALADIN block, e.g. "No signal · rank 35 of 500 · +64.5% in 6 months". |
| Home page | The ALADIN card shows E's rank and state. |
| Movers | The "quant" column shows E's block. |
| NEXUS | Does not show the Quant tab. |

No price level to aim for is shown anywhere. Every percentage comes with its range. The words buy, sell, target, recommendation and guaranteed do not appear (the check passes).

### Earlier models: still running, now private
As you asked, nothing was archived:
- **These all keep running and learning every night:** ALADIN 1, Outlook, ALADIN 2.0 (with its research pages), the old weekly signal, the movers model and the old paper bots.
- **What changed is only where their results are published.**
  - When the site is built, every file of theirs is encrypted with the ALADIN BOT access code.
  - The encryption is AES-256-GCM. The key is made from the code with PBKDF2-SHA256 at 600,000 rounds.
  - The readable copies are then deleted from the site.
  - For example, `aladin.json` now returns "not found" to the public.
- **When the bot is locked (every visitor):**
  - Their tabs and buttons are hidden.
  - None of their files is downloaded.
  - An old link such as `#v=lab` opens ALADIN BOT instead.
- **After you unlock ALADIN BOT with the same code:** an "Earlier ALADIN models" panel appears. It opens:
  - the old weekly signal and its paper bots
  - Tools (ALADIN 1)
  - Outlook
  - ALADIN 2.0's research pages
  
  "ALADIN probability" also comes back in Movers, as does an "Earlier models" block in the terminal's Details panel.
- **"Lock again" hides all of it** and makes this browser tab forget the code.
- **If the code is not set** in GitHub, the files are still removed, and the bot says they are not published. Nothing leaks.

### Automation (no manual steps)
- The daily update runs `scripts/aladin_e.py` every evening, after the prices are saved.
- Both site builds (daily update and live prices) get the access code from the existing GitHub secret `ALADIN_BOT_CODE`. It is the same secret the bot already uses, and it is never printed or saved.

## Problems found while checking, and fixed
1. **The old weekly signal stayed on "Loading…" after unlocking.**
   - Cause: two parts of the page each loaded their own copy of the unlock code.
   - Why: the site build stamps each script with a version, and the new unlock script was listed after a file that uses it, so the two got different addresses.
   - Effect: one copy was unlocked and the other was not.
   - Fix: the build order is corrected. The existing test `test_build_assets.py` now passes on the new build.
2. **Outlook said "not published yet" after unlocking.**
   - Cause: its data arrived, but the Outlook page was never redrawn.
   - Fix: it now redraws when the bot is unlocked and whenever the tab is opened.
3. **There was no way to lock again** when the bot's own console file can't be opened but the earlier models can. This happened in my local preview, which used a test code.
   - Fix: added a "Lock again" button to the earlier-models panel.

## Tests

| Suite | Result |
|---|---|
| Python (pytest), all tests | 665 passed, 2 failed. Both also fail on the current main code without my changes (see below). |
| New: `tests/test_aladin_legacy.py` | 3 passed: files are encrypted with no readable copy left; a wrong code can't open them; with no code the files are removed. |
| `tests/test_aladin_e.py` | 12 passed |
| JavaScript (node --test), all tests | 150 passed, 0 failed (6 new, for the ALADIN page and the lock) |
| Banned-word and disclaimer check | ok |
| New browser check: `tests/e2e/aladin_e_check.py` | 19 of 19 passed |
| Updated browser checks (`predicted_check`, `nexus_check`, `aladin2_check`, `acceptance`) | These now unlock the bot with a test code before checking the earlier models. Every content check passes. The only failures are "0 console errors" lines, all caused by 404s for files this test copy lacks (`live.json`, `news.json`, `nse_live.json`, `t/quotes.json`, `t/fund.json`). Your main copy has those files. I will re-run these checks there before merging. |

The two Python failures that were already there before:
- `test_fundamentals_fetch_stops_on_its_time_budget…`: it depends on how fast this computer writes files.
- `test_probabilities_exist_exactly_for_securities…`: three newly listed stocks (ARHAM, MONEYBOXX, GROWWSC250) don't match the saved data.

Neither touches model E or the lock. I am not sure the first one fails on GitHub's servers too.

Browser checks used a made-up test code only, never your real one.

## Facts you should know
- **Model E as of the 9 Nov 2026 close:**
  - The NIFTY 500 is 3.5% above its 200-day average, so E is 70% invested.
  - Its portfolio is 25 stocks, with the next change in 63 sessions.
  - The paper account (₹1,00,000) places its first orders at the open after its first evening run on GitHub.
- **Size:** the encrypted files take about 32 MB on the site, against 20.5 MB readable, because encryption output is stored as text. That is well inside GitHub Pages' limit.
- **Survivorship bias:** the free data still only covers stocks listed today, so E's back-test is flattered (Phase 4). The 4-week forward test in Phase 7 is the honest check.

## How to undo
Revert the Phase 6 commit on `aladin-audit`. If it has been merged, revert the merge commit on main. The earlier models were never changed or deleted, so they come back as they were.

## Next
1. You write "approved phase 6".
2. I re-run the acceptance checks in the main copy and paste the results here.
3. If every check passes, I merge to main. Model E then goes live with the next daily update, and the earlier models move behind the bot.
4. Phase 7 then starts: 4 weeks of automatic daily paper trading, a plain-language report every Friday, and at the end a recommendation to Continue, Fix or Stop.
