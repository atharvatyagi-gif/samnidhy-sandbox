"""
ALADIN precision study: can a confirmation filter make the weekly BUY / SELL lists right more often, on years the filter never saw?

  python -m scripts.aladin2.precision_study --workers 12      -> data/aladin2/precision_study.json
Same rows, trade and costs as weekly_study.py (Friday signal, next open entry, exit at the open 5 trading days later, full cost model, excess vs the equal-weight liquid market).
Protocol, declared before any result was seen (2026-10-09):
  1. The candidate rules below are the whole list. None is added or changed after a result.
  2. Pick ONE BUY rule and ONE SELL rule on 2013-2020 only (selection years).
     BUY: highest lower 95% bound of net excess per trade, at least 8 trades a year on average.
     SELL: lowest upper 95% bound of gross excess (most reliably below the market), at least 8 trades a year.
  3. Report the picked rules, and the current rules, on 2021-2026 (held-out years) once. That number is the claim.
"Right" for BUY = beat the market that week after costs; for SELL = fell behind the market that week (cash cannot be shorted, so SELL means exit / avoid).
Breadth = share of the week's liquid stocks above their own 200-day average (known at the signal close).
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from .weekly_study import OOS, H, boot

SPLIT = pd.Timestamp("2021-01-01")
MIN_PER_YEAR = 8

BUY_RULES = {
    "B0 current: best 1%": lambda D: D["s"] >= 0.99,
    "B1 best 2%": lambda D: D["s"] >= 0.98,
    "B2 best 1% + stock above its 200-day average": lambda D: (D["s"] >= 0.99) & (D["d_sma200"] > 0),
    "B3 best 2% + stock above its 200-day average": lambda D: (D["s"] >= 0.98) & (D["d_sma200"] > 0),
    "B4 best 1% + market breadth above 50%": lambda D: (D["s"] >= 0.99) & (D["breadth"] > 0.5),
    "B5 best 2% + market breadth above 50%": lambda D: (D["s"] >= 0.98) & (D["breadth"] > 0.5),
    "B6 best 5% + 3-month momentum in the top 30%": lambda D: (D["s"] >= 0.95) & (D["s_mom"] >= 0.7),
    "B7 best 5% + within 10% of its 52-week high": lambda D: (D["s"] >= 0.95) & (D["hi52"] > -0.10),
    "B8 best 2% + calmer than the week's median stock": lambda D: (D["s"] >= 0.98) & (D["vol_rank"] <= 0.5),
    "B9 best 2% + cheapest third to trade": lambda D: (D["s"] >= 0.98) & (D["dec"] >= 7),
    "B10 best 2% + above 200-day + breadth above 50%": lambda D: (D["s"] >= 0.98) & (D["d_sma200"] > 0) & (D["breadth"] > 0.5),
}
SELL_RULES = {
    "S0 current: worst 5%": lambda D: D["s"] <= 0.05,
    "S1 worst 2%": lambda D: D["s"] <= 0.02,
    "S2 worst 5% + stock below its 200-day average": lambda D: (D["s"] <= 0.05) & (D["d_sma200"] < 0),
    "S3 worst 5% + 50-day average falling": lambda D: (D["s"] <= 0.05) & (D["sma50_slope"] < 0),
    "S4 worst 5% + market breadth below 50%": lambda D: (D["s"] <= 0.05) & (D["breadth"] < 0.5),
    "S5 worst 10% + below 200-day + 50-day average falling": lambda D: (D["s"] <= 0.10) & (D["d_sma200"] < 0) & (D["sma50_slope"] < 0),
    "S6 worst 5% + 3-month momentum in the bottom 30%": lambda D: (D["s"] <= 0.05) & (D["s_mom"] <= 0.3),
    "S7 worst 5% + more volatile than the week's median stock": lambda D: (D["s"] <= 0.05) & (D["vol_rank"] > 0.5),
}


def _one(sym_dates):
    sym, dates = sym_dates
    px = L.load_prices(sym)
    if px is None or len(px) < 400:
        return None
    px = L.clean_prices(px); F = L.price_features(px); dt = pd.DatetimeIndex(dates); idx = px.index.searchsorted(dt)
    ok = (idx < len(px) - H - 2) & (px.index[np.minimum(idx, len(px) - 1)] == dt)
    if not ok.any():
        return None
    i = idx[ok]; o = px["o"].values; v = px["v"].values; entry = o[i + 1]; exit_ = o[i + 1 + H]
    sus = px["suspect_action"].values; bad = np.array([sus[a + 1:a + 2 + H].any() or px["post_break"].values[a] for a in i]); vol_ok = (v[i + 1] > 0) & (v[i + 1 + H] > 0)
    adv = ((px["c"] * px["v"]).rolling(250, min_periods=120).mean() / 1e7).values[i]
    d = pd.DataFrame({"sym": sym, "date": px.index[i], "ret": exit_ / entry - 1, "z60": (F["r60"] / (F["vol20"] * np.sqrt(60))).values[i], "vol20": F["vol20"].values[i], "adv": adv,
                      "d_sma200": F["d_sma200"].values[i], "sma50_slope": F["sma50_slope"].values[i], "hi52": F["hi52"].values[i]})
    return d[~bad & vol_ok & (adv >= 2.0) & np.isfinite(d["ret"].values) & (np.abs(d["ret"].values) < 0.6)]


def summarise(g, side):
    if len(g) == 0:
        return {"trades": 0}
    yrs = g.groupby("year")["exn" if side == "buy" else "ex"].mean()
    r = {"trades": int(len(g)), "per_week": round(len(g) / max(g["date"].nunique(), 1), 1), "weeks_with_a_signal": int(g["date"].nunique()), "share_closing_up": round(float((g["ret"] > 0).mean()), 4),
         "gross_excess_bps": round(float(g["ex"].mean() * 1e4), 1), "gross_excess_ci95_bps": boot(g["ex"].values, g["month"].values)}
    if side == "buy":
        r.update({"right_rate": round(float((g["exn"] > 0).mean()), 4), "net_excess_bps": round(float(g["exn"].mean() * 1e4), 1), "net_excess_ci95_bps": boot(g["exn"].values, g["month"].values), "years_positive": f"{int((yrs > 0).sum())}/{len(yrs)}"})
    else:
        r.update({"right_rate": round(float((g["ex"] < 0).mean()), 4), "years_below_market": f"{int((yrs < 0).sum())}/{len(yrs)}"})
    return r


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--out", default="data/aladin2/precision_study.json"); a = ap.parse_args()
    cfg = C.load_cfg(); O = pd.read_pickle(OOS); O["date"] = pd.to_datetime(O["date"]); by = [(s, g["date"].values) for s, g in O.groupby("sym")]
    with ProcessPoolExecutor(a.workers) as ex:
        D = pd.concat([d for d in ex.map(_one, by, chunksize=8) if d is not None], ignore_index=True).merge(O[["sym", "date", "p"]], on=["sym", "date"])
    u = json.load(open(L.TERM / "universe.json"))["stocks"]; allv = [(s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7 for s in u if s.get("board") == "Main" and not s.get("etf")]
    adv_now = {s["s"]: (s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7 for s in u}; cost = {k: C.round_trip_bps("long", "delivery", k, cfg) / 1e4 for k in range(10)}
    D["dec"] = D["sym"].map({s: C.adv_decile(adv_now.get(s, 0.5), allv) for s in D["sym"].unique()}); D["cost"] = D["dec"].map(cost)
    D["mkt"] = D.groupby("date")["ret"].transform("mean"); D["ex"] = D["ret"] - D["mkt"]; D["exn"] = D["ret"] - D["cost"] - D["mkt"]
    D = D[D.groupby("date")["sym"].transform("size") >= 50].reset_index(drop=True); D["month"] = D["date"].dt.to_period("M").astype(str); D["year"] = D["date"].dt.year
    rk = lambda col: D.groupby("date")[col].rank(pct=True)
    D["s"] = rk("p"); D["s_mom"] = rk("z60"); D["vol_rank"] = rk("vol20"); D["breadth"] = D.groupby("date")["d_sma200"].transform(lambda x: (x > 0).mean())
    sel, held = D[D["date"] < SPLIT], D[D["date"] >= SPLIT]; n_sel_years = sel["year"].nunique()
    out = {"protocol": __doc__.strip(), "rows": int(len(D)), "selection_years": f"{sel['year'].min()}-{sel['year'].max()}", "held_out_years": f"{held['year'].min()}-{held['year'].max()}",
           "base_rates_held_out": {"closed_up": round(float((held["ret"] > 0).mean()), 4), "beat_market_gross": round(float((held["ex"] > 0).mean()), 4)}, "buy": {}, "sell": {}}
    for side, rules in (("buy", BUY_RULES), ("sell", SELL_RULES)):
        for name, f in rules.items():
            out[side][name] = {"selection": summarise(sel[f(sel)], side), "held_out": summarise(held[f(held)], side)}
        eligible = {k: v["selection"] for k, v in out[side].items() if v["selection"]["trades"] >= MIN_PER_YEAR * n_sel_years}
        if side == "buy":
            pick = max(eligible, key=lambda k: eligible[k]["net_excess_ci95_bps"][0])
        else:
            pick = min(eligible, key=lambda k: eligible[k]["gross_excess_ci95_bps"][1])
        out[f"{side}_pick"] = {"rule": pick, "chosen_on": "selection years only", "held_out": out[side][pick]["held_out"], "current_rule_held_out": out[side][next(iter(rules))]["held_out"]}
    json.dump(out, open(a.out, "w"), indent=1)
    for side in ("buy", "sell"):
        print(f"\n== {side.upper()} ==   (selection 2013-2020  ->  held out 2021-2026)")
        for k, v in out[side].items():
            s_, h_ = v["selection"], v["held_out"]; key = "net_excess_bps" if side == "buy" else "gross_excess_bps"
            print(f"{k:55s} sel n={s_.get('trades',0):6d} right={s_.get('right_rate',0):.3f} {key}={s_.get(key)} | held n={h_.get('trades',0):6d} right={h_.get('right_rate',0):.3f} {key}={h_.get(key)} ci={h_.get(key.replace('_bps','_ci95_bps'))}")
        print("PICK:", out[f"{side}_pick"]["rule"])


if __name__ == "__main__":
    main()
