"""
Model E's "chance" table: for each rank group of the 126-day return (among the day's 500 most-traded stocks), how often a stock in
that group beat the average stock of the universe over the next 63 trading days (entry at the next open), and how often it simply
closed higher, with 95% ranges from a bootstrap that resamples whole dates (stocks on the same date move together).
Also (added 2026-11-13 for the signals' expected price range): the spread of the plain 63-day price change of one stock in each
group, open to open, before costs: 10th, 25th, 50th (typical), 75th and 90th percentiles.

  python aladin-audit/scripts/e_calibration.py --panel <panel.pkl>   -> data/config/aladin_e_calibration.json (written into the main copy by the caller)

Period: 2010-01 to 2026-02 signal dates (outcomes end before the hold-out starts on 2026-05-08). Survivorship: only companies
listed today; the table says so.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import phase4_engine as E

BUCKETS = [(0.95, 1.0001, "best 5% (in the portfolio)"), (0.90, 0.95, "next 5%"), (0.80, 0.90, "80th-90th percentile"), (0.50, 0.80, "50th-80th"),
           (0.20, 0.50, "20th-50th"), (0.0, 0.20, "worst 20%")]
H, L = 63, 126


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ctx = E.Ctx(pd.read_pickle(a.panel))
    D = ctx.dates
    t0, t1 = int(D.searchsorted(pd.Timestamp("2010-01-01"))), int(D.searchsorted(pd.Timestamp("2026-02-01")))
    rows = []
    for t in range(t0, t1, 5):
        if t + 1 + H >= len(D) or D[t + 1 + H] >= pd.Timestamp("2026-05-08"):
            break
        ids = ctx.universe(t)
        s = ctx.ret(t, L, 0)[ids]
        ok = np.isfinite(s)
        ids, s = ids[ok], s[ok]
        o0, o1 = ctx.O[t + 1, ids], ctx.O[t + 1 + H, ids]
        r = o1 / o0 - 1
        good = np.isfinite(r) & (o0 > 0)
        if good.sum() < 50:
            continue
        rk = pd.Series(s[good]).rank(pct=True).values
        rr = r[good]
        mkt = rr.mean()
        for p, x in zip(rk, rr):
            rows.append((t, p, x > 0, x > mkt, x - mkt, x))
    df = pd.DataFrame(rows, columns=["t", "pct", "up", "beat", "ex", "ret"])
    rng = np.random.default_rng(7)
    dates = df["t"].unique()
    out = []
    for lo, hi, name in BUCKETS:
        b = df[(df["pct"] >= lo) & (df["pct"] < hi)]
        g = b.groupby("t").agg(up=("up", "sum"), beat=("beat", "sum"), n=("up", "size"), ex=("ex", "sum"))
        boot_b, boot_u, boot_e = [], [], []
        for _ in range(1000):
            pick = rng.choice(len(g), len(g))
            s = g.iloc[pick].sum()
            boot_b.append(s["beat"] / s["n"]); boot_u.append(s["up"] / s["n"]); boot_e.append(s["ex"] / s["n"])
        out.append({"from": lo, "to": min(1.0, hi), "label": name, "n_stock_quarters": int(len(b)), "dates": int(len(g)),
                    "beat_market": round(float(b["beat"].mean()), 4), "beat_market_ci95": [round(float(np.percentile(boot_b, 2.5)), 4), round(float(np.percentile(boot_b, 97.5)), 4)],
                    "mean_excess_pct": round(float(b["ex"].mean() * 100), 2), "mean_excess_ci95_pct": [round(float(np.percentile(boot_e, 2.5) * 100), 2), round(float(np.percentile(boot_e, 97.5) * 100), 2)],
                    "median_excess_pct": round(float(b["ex"].median() * 100), 2), "sd_excess_pct": round(float(b["ex"].std() * 100), 2),
                    "price_change_pct": {f"p{q}": round(float(np.percentile(b["ret"], q) * 100), 1) for q in (10, 25, 50, 75, 90)},
                    "closes_higher": round(float(b["up"].mean()), 4), "closes_higher_ci95": [round(float(np.percentile(boot_u, 2.5)), 4), round(float(np.percentile(boot_u, 97.5)), 4)]})
    doc = {"model": "aladin-e-1", "what": "share of stocks in each rank group of the 126-day return that beat the average stock of the universe over the next 63 trading days (entry at the next open), and that closed higher",
           "period": f"signal dates {pd.Timestamp(D[t0]).date()} to {pd.Timestamp(D[df['t'].max()]).date()}, every 5 trading days", "signal_dates": int(len(dates)),
           "caveats": ["Momentum's edge is in the size of the wins, not how often: the best group beats the average stock less than half the time, yet by more on average.", "Only companies listed today (survivorship): the best groups are likely flattered.", "Before costs; a frequency over many stocks and dates, not a forecast for one stock.", "price_change_pct: how far one stock of the group moved over 63 trading days; 8 in 10 ended between p10 and p90."],
           "buckets": out}
    Path(a.out).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    for b in out:
        print(b["label"], b["n_stock_quarters"], "beat", b["beat_market"], b["beat_market_ci95"], "mean ex", b["mean_excess_pct"], b["mean_excess_ci95_pct"], "median ex", b["median_excess_pct"], "up", b["closes_higher"], "price", b["price_change_pct"])


if __name__ == "__main__":
    main()
