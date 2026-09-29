"""
Live re-rank of the stock screen, every 15 minutes in market hours (run by the Live prices workflow).

scripts/screener.py does the full NIFTY 500 screen from the annual reports (three times a day) and saves
every stock that passed the fundamentals to data/screener/candidates.json. The Magic Formula's
earnings yield (EBIT / enterprise value) moves with the share price, because enterprise value =
market value + debt - cash. This script:
  1. takes each candidate's latest delayed price (the terminal's quotes, else one Yahoo download),
  2. moves its market value by the same percentage as its price since the screen was run,
  3. recalculates earnings yield, re-ranks all candidates and writes the new top 10 to
     data/screener/latest.json (same format, so the Advanced page redraws on its own).
Return on capital, the F-Score and the funnel come from the annual reports and do not change here.
A candidate without a fresh price keeps the price used by the full screen; nothing is estimated.

  python scripts/screener_live.py
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screener import OUT_DIR, rank  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))


def live_prices(symbols, today):
    """{symbol: price} from today's delayed quotes. Terminal quotes first (already fetched), else Yahoo."""
    out = {}
    qf = ROOT / "data" / "terminal" / "quotes.json"
    if qf.exists():
        q = json.loads(qf.read_text(encoding="utf-8")).get("quotes", {})
        out = {s: q[s]["p"] for s in symbols if s in q and q[s].get("d") == today and q[s].get("p")}
    missing = [s for s in symbols if s not in out]
    if missing:
        try:
            import yfinance as yf
            data = yf.download([s + ".NS" for s in missing], period="1d", interval="5m", group_by="ticker",
                               auto_adjust=False, threads=True, progress=False)
            for s in missing:
                try:
                    c = data[s + ".NS"]["Close"].dropna()
                except KeyError:
                    continue
                if len(c) and c.index[-1].tz_convert(IST).date().isoformat() == today:
                    out[s] = float(c.iloc[-1])
        except Exception as exc:  # Yahoo down: use what we have
            print("Yahoo download failed:", exc)
    return out


def main():
    cf, lf = OUT_DIR / "candidates.json", OUT_DIR / "latest.json"
    if not cf.exists() or not lf.exists():
        print("No full screen saved yet (run scripts/screener.py first); nothing to re-rank.")
        return 0
    cand, latest = json.loads(cf.read_text(encoding="utf-8")), json.loads(lf.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    today = now.astimezone(IST).date().isoformat()
    stocks = cand["stocks"]
    prices = live_prices([c["symbol"] for c in stocks], today)
    moved = []
    for c in stocks:
        c = dict(c)
        p = prices.get(c["symbol"])
        if p and c.get("price") and 0.6 < p / c["price"] < 1.6:      # reject implausible Yahoo prices
            ratio = p / c["price"]
            mcap = c["market_cap_cr"] * ratio
            ev = c["ev_cr"] + (mcap - c["market_cap_cr"])
            if ev <= 0 or not c["ebit_cr"]:
                continue
            c.update(price=round(p, 2), market_cap_cr=round(mcap, 1), ev_cr=round(ev, 1),
                     earnings_yield=round(c["ebit_cr"] / ev, 4), live_price=True)
        else:
            c["live_price"] = False
        moved.append(c)
    picks = rank(moved, cand.get("count", 10))
    old = [p["symbol"] for p in latest.get("picks", [])]
    latest["picks"] = picks
    latest["generated_utc"] = now.isoformat(timespec="seconds")
    latest["generated_ist"] = now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
    latest["ranked_on"] = f"live prices ({sum(1 for c in moved if c['live_price'])} of {len(moved)} candidates)"
    latest["reranked_ist"] = latest["generated_ist"]
    lf.write_text(json.dumps(latest, indent=1, default=str, allow_nan=False), encoding="utf-8")
    new = [p["symbol"] for p in picks]
    print(f"Re-ranked {len(moved)} candidates on {len(prices)} live prices.")
    print("Top 10:", ", ".join(new))
    if set(new) != set(old):
        print("Changes: in", sorted(set(new) - set(old)), "out", sorted(set(old) - set(new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
