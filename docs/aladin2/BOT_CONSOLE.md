# ALADIN BOT console: a page locked by an access code

Written for: the project owner, who asked for a bot-dashboard page that shows what ALADIN is doing, with graphs, reachable only with a code.

## What the page shows (tab "ALADIN BOT")
- **Status strip and five KPI cards**, in the spirit of a trading-bot dashboard but with real, labelled numbers: forecasts made, signals this week (positive / negative / none), past hit rate (historical simulation), the positive signals' weekly edge over the market after costs, and the live record (none resolved yet).
- **"What the bot does, in order"**: seven clickable stages (read the market, score every stock, rank and apply the rule, turn rank into a chance, forecast the range, plan the trade and the risk, keep a record and learn). Each shows what it does, how, real numbers from the last run, and a chart for that stage (score histogram with the two cut-offs, return by score decile, chance by rank bucket, forecast coverage, strategies on trial).
- **"Watch it decide"**: pick any of this week's signal stocks and press *Run the decision*: the six steps light up one by one with that stock's own numbers (rank, band, measured chance, cost, exit level and time limit, position size), next to a chart of its recent closes, 5-day range, entry zone and exit level.
- **The evidence** (all labelled historical simulation): weekly edge summed over 13 years, the worst-ranked 5%'s cumulative shortfall, results by year for both sides.
- **What it did lately**: forecast batches written, weekly books, step timings, and the latest journal events.
What it does NOT show: a fake balance, live profit or invented trades. Nothing here is live money. The reel you linked could not be opened in full (Instagram blocks it); from its text it is a bot dashboard with an account balance, win rate, predictions count and sample trades, and the claims were widely doubted. This page keeps the layout idea and drops anything that cannot be backed by the ledger.

## How the lock works, and its limits
- The site is static files, so a password box alone would only hide the page. The page's **data** is encrypted (`aladin2/bot.enc.json`): AES-256-GCM, key from your code by PBKDF2-SHA256 with 600,000 rounds. The file is public but unreadable without the code; the browser derives the key from what you type and decrypts in memory. A wrong code, or a file altered by anyone, fails the authentication check. Wrong attempts add a growing delay.
- The code is 99 bits of randomness, so guessing it offline is not realistic. **If you set your own, make it long and random.**
- Limits: anyone who has the code can read the data and share it (to revoke, make a new code and rebuild); the page's JavaScript is public (it holds no data, only the drawing code, which describes the same method as the public methodology); the signal data itself is also published on the Weekly signals page, so this console protects the *explanations, traces and evidence*, not the list of signals.
- The desk itself already sits behind your student sign-in; the code is a second lock on top.

## Operating it
- Make a code: `python -m scripts.aladin2.bot --new-code` (prints, writes nothing).
- Build the data: `ALADIN_BOT_CODE=<code> python -m scripts.aladin2.bot --build` writes `data/aladin2/bot.enc.json`.
- The nightly job rebuilds it in its `bot` step using the GitHub secret **`ALADIN_BOT_CODE`** (add the same code there; without the secret the step is skipped and the last encrypted file stays, showing its own "as of" date after unlocking). The site build only copies the encrypted file.
- Rotate: new code, update the secret, rebuild. The old code stops working once the new file is published.
