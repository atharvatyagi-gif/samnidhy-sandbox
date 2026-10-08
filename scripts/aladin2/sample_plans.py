"""
ALADIN 2.0 ILLUSTRATIVE trade plans for ten real stocks (Phase 4 review item). Not signals: today no stock is Validated, so none of these would be shown to a user as a plan.
They show what the plan machinery produces from the live forecast engine: entry zone, invalidation level, profit levels with touch probabilities and typical days, probability of
being stopped out, expected R, and the position size for Rs 10 lakh with 1% risk, using a HYPOTHETICAL per-trade edge of +1% (sd 8%) so the Kelly cap is not zero.
  python -m scripts.aladin2.sample_plans --workers 8   -> data/aladin2/sample_plans.json
"""
import argparse
import json

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import forecast as FC
from . import run_phase3 as R3
from . import signals as SG

PICK = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC", "TATASTEEL", "MARUTI", "SUNPHARMA", "LT", "BAJFINANCE"]
CAPITAL, H = 1_000_000, 20


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=8); ap.add_argument("--out", default="data/aladin2/sample_plans.json"); a = ap.parse_args()
    cfg = C.load_cfg(); D, resid, _ = R3.build_panel(a.workers); as_of = D["date"].max(); live = D[(D["date"] == as_of) & D["sym"].isin(PICK)].dropna(subset=R3.BASE_COLS)
    ys = as_of + pd.Timedelta(days=1); B = {h: R3.fit_bundle(D, ys, h, cfg) for h in (1, H, 60)}
    s1, _, _, _, _ = R3.predict_bundle(B[1], live); sH, _, AH, _, _ = R3.predict_bundle(B[H], live); s60, _, _, _, _ = R3.predict_bundle(B[60], live)
    res = FC.standardise(resid[np.isfinite(resid)]); rng = np.random.default_rng(7); out = []
    for i, (_, r) in enumerate(live.iterrows()):
        close = float(r["close"]); atr = float(r["atr14"]); px = L.load_prices(r["sym"]); swing = float(px["l"].iloc[-cfg["signals"]["swing_low_days"]:].min()); adv_sh = float(px["v"].iloc[-20:].mean())
        raw = FC.simulate_paths(s1[i] / 1.0, s60[i] / np.sqrt(60), H, 2000, res, rng); lo80, hi80 = AH[i, 1] * sH[i], AH[i, 5] * sH[i]; paths = FC.fit_to_band(raw, lo80, hi80)
        entry = close; zone = SG.entry_zone(close, atr, cfg); stop = SG.choose_stop(close, atr, None, swing, cfg)
        band = [float(close * np.exp(AH[i, k] * sH[i])) for k in (2, 4, 1, 5, 0, 6)]; levels = SG.profit_levels(paths, close, cfg, band); ev = SG.evaluate_plan(paths, close, entry, stop, levels)
        size = SG.position_size(CAPITAL, entry, stop, adv_sh, 0.01, 0.08, cfg)
        out.append({"sym": r["sym"], "close": round(close, 2), "atr14": round(atr, 2), "entry_zone": [round(x, 2) for x in zone], "invalidation_level": round(stop, 2), "stop_distance_pct": round((entry - stop) / entry * 100, 2),
                    "range_20d_80pct": [round(band[2], 2), round(band[3], 2)], "range_20d_50pct": [round(band[0], 2), round(band[1], 2)],
                    "levels": [{"level": round(v["level"], 2), "p_touch": round(v["p_touch"], 3), "typical_day": v["day_median"], "day_iqr": v["day_iqr"]} for v in ev["levels"]],
                    "p_stopped_out_within_20d": round(ev["p_stop"], 3), "expected_R": round(ev["expected_R"], 3), "loss_if_invalidated_inr": round(size["capital_at_risk"], 0), "loss_if_invalidated_pct_of_capital": round(size["capital_at_risk"] / CAPITAL * 100, 3),
                    "hypothetical_size": {"qty": size["qty"], "binding_limit": size["binding"], "position_value_inr": round(size["position_value"], 0)}})
    rep = {"as_of": str(as_of.date()), "capital_inr": CAPITAL, "label": "ILLUSTRATION ONLY: no stock is Validated; the edge used for sizing (+1% per trade, sd 8%) is hypothetical", "horizon_d": H, "plans": out}
    json.dump(rep, open(a.out, "w"), indent=1); print(json.dumps(rep["plans"][0], indent=1)); print([(p["sym"], p["p_stopped_out_within_20d"], p["expected_R"], p["hypothetical_size"]["qty"]) for p in out])


if __name__ == "__main__":
    main()
