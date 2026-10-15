"""GAP analysis: for every undefined or hard-coded parameter swept in the simulation, the tested range, the most robust value and how sensitive results are.

Method (one parameter at a time, the others at the terminal's own values):
  per value: median Sharpe over seeds in each scenario -> its median across the 12 scenarios ("typical") and its worst scenario.
  robust value: the value with the best typical Sharpe; it is called ROBUST if it is at least as good as the terminal's value in 8+ of 12 scenarios,
                MIXED if 4-7, FRAGILE if it only wins in 3 or fewer (good in one kind of market only); TERMINAL VALUE OK when no tested value beats the
                terminal's own by at least 0.02 typical Sharpe.
  sensitivity:  the change in typical Sharpe when the parameter moves to its nearest tested neighbours (the closest the grid gets to +-20%).
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd


def _num(v):
    try:
        x = json.loads(v)
        return x if isinstance(x, (int, float)) and not isinstance(x, bool) else x
    except (TypeError, ValueError):
        return v


def analyse(sweeps: pd.DataFrame, cfg: dict, metric: str = "sharpe") -> pd.DataFrame:
    rows = []
    med = sweeps.groupby(["strategy", "param", "value", "scenario"])[metric].median().reset_index()
    for strat, g in med.groupby("strategy"):
        base = cfg["strategies"][strat]["defaults"]; d = g[g["param"] == "default"].set_index("scenario")[metric]
        for prm in [p for p in g["param"].unique() if p != "default"]:
            h = g[g["param"] == prm]; vals = {}
            for v, hv in h.groupby("value"):
                vals[_num(v)] = hv.set_index("scenario")[metric]
            vals[base.get(prm)] = d
            table = []
            for v, ser in vals.items():
                s = ser.reindex(d.index)
                table.append({"value": v, "typical": float(np.nanmedian(s)), "worst": float(np.nanmin(s)), "wins": int(np.sum(s.values >= d.values - 1e-9))})
            table.sort(key=lambda r: (str(type(r["value"])), r["value"] if not isinstance(r["value"], str) else 0))
            best = max(table, key=lambda r: r["typical"]); dflt = next(r for r in table if r["value"] == base.get(prm))
            n = len(d); verdict = "ROBUST" if best["wins"] >= 8 * n / 12 else "MIXED" if best["wins"] >= 4 * n / 12 else "FRAGILE"
            if best["value"] == base.get(prm) or best["typical"] - dflt["typical"] < 0.02:
                best = dflt; verdict = "TERMINAL VALUE OK"                                  # no tested value does meaningfully better
            nums = sorted(r["value"] for r in table if isinstance(r["value"], (int, float)) and not isinstance(r["value"], bool))
            sens = np.nan; note_move = ""
            if isinstance(base.get(prm), (int, float)) and not isinstance(base.get(prm), bool) and base.get(prm) in nums and len(nums) > 1:
                k = nums.index(base.get(prm)); nb = [nums[j] for j in (k - 1, k + 1) if 0 <= j < len(nums)]
                deltas = [next(r["typical"] for r in table if r["value"] == x) - dflt["typical"] for x in nb]
                sens = float(max(deltas, key=abs)); note_move = " / ".join(f"{x:g}" for x in nb)
            frag = (not math.isnan(sens)) and abs(sens) > 0.3 and abs(sens) > 0.5 * max(0.3, abs(dflt["typical"]))
            note = (f"Terminal value {base.get(prm)}: typical Sharpe {dflt['typical']:+.2f}. Best tested {best['value']}: {best['typical']:+.2f} "
                    f"({best['wins']} of {n} scenarios at least as good; {verdict.lower()}). ")
            if not math.isnan(sens):
                note += f"Moving to the neighbours ({note_move}) changes the typical Sharpe by up to {sens:+.2f}: {'SENSITIVE' if frag else 'not very sensitive'}."
            rows.append({"strategy": strat, "param": prm, "default": json.dumps(base.get(prm)), "tested": json.dumps([r["value"] for r in table]),
                         "best_value": json.dumps(best["value"]), "best_typical_sharpe": best["typical"], "default_typical_sharpe": dflt["typical"],
                         "best_worst_sharpe": best["worst"], "wins": best["wins"], "scenarios": n, "verdict": verdict, "sensitivity": sens, "sensitive": bool(frag),
                         "table": json.dumps(table), "note": note})
    return pd.DataFrame(rows)
