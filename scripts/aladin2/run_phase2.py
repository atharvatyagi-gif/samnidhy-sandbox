"""
ALADIN 2.0 Phase 2 real-data run: nested walk-forward policy on the NIFTY 500 versus the baselines, net of costs.

  python -m scripts.aladin2.run_phase2 --workers 12            -> data/aladin2/phase2_report.json (+ phase2_events.jsonl.gz)
Universe: NIFTY 500 members with >= min_history_d daily bars and 20-day average traded value >= min_adv_inr_cr (today's liquidity; survivor-only list: see the caveat in the report).
Costs: real model (costs.py), liquidity decile from today's average traded value. Strategies: every selectable one in the registry; baselines are not selectable.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
import time

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import evaluate as E
from .strategies import registry as R

_DELIV = None


def _deliv(sym):
    global _DELIV
    if _DELIV is None:
        _DELIV = L.load_delivery_panel()
    return _DELIV.get(sym)


def _build(args):
    sym, sector, decile, cal_vals, cfg = args
    cal = pd.DatetimeIndex(cal_vals)
    px = L.load_prices(sym)
    if px is None or len(px) < cfg["universe"]["min_history_d"]:
        return None
    px = L.clean_prices(px[px.index >= pd.Timestamp(cfg["eval"]["data_start"]) - pd.Timedelta(days=420)]); F = L.price_features(px)
    nifty = L.load_index(); d = _deliv(sym)
    return E.build_stock(sym, sector, px, F, R.all_strategies(include_discovered=True), cal, decile, cfg, nifty, d, min_entry=pd.Timestamp(cfg["eval"]["data_start"]))


def universe(cfg):
    u = json.load(open(L.TERM / "universe.json"))["stocks"]; allv = [(s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7 for s in u if s.get("board") == "Main" and not s.get("etf")]
    rows = []
    for s in u:
        if not s.get("n500") or s.get("etf"):
            continue
        adv = (s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7
        if adv >= cfg["universe"]["min_adv_inr_cr"]:
            rows.append((s["s"], s.get("ind") or "Unknown", C.adv_decile(adv, allv)))
    return rows


def universe_pit(cfg, min_adv_cr=0.25):
    """Every Main-board non-ETF stock with a price file and today's 20-day average traded value >= min_adv_cr. The point-in-time top-N filter is applied later (evaluate.attach_benchmark)."""
    u = json.load(open(L.TERM / "universe.json"))["stocks"]; allv = [(s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7 for s in u if s.get("board") == "Main" and not s.get("etf")]
    rows = []
    for s in u:
        if s.get("board") != "Main" or s.get("etf") or not (L.TERM / "daily" / f"{s['s']}.json").exists():
            continue
        adv = (s.get("avgv20") or 0) * (s.get("c") or 0) / 1e7
        if adv >= min_adv_cr:
            rows.append((s["s"], s.get("ind") or "Unknown", C.adv_decile(adv, allv)))
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default="data/aladin2/phase2_report.json")
    ap.add_argument("--events", default="data/aladin2/phase2_events.jsonl.gz"); a = ap.parse_args()
    cfg = C.load_cfg(); t0 = time.time()
    nifty = L.load_index(); cal = nifty.index[nifty.index >= pd.Timestamp(cfg["eval"]["data_start"])]
    rows = universe(cfg)[: a.limit or None]; print(f"universe {len(rows)} stocks (NIFTY 500, ADV >= {cfg['universe']['min_adv_inr_cr']} cr); calendar {cal[0].date()}..{cal[-1].date()} ({len(cal)} days)", flush=True)
    jobs = [(s, sec, d, cal.values, cfg) for s, sec, d in rows]
    with ProcessPoolExecutor(a.workers) as ex:
        U = {sd.sym: sd for sd in ex.map(_build, jobs, chunksize=2) if sd is not None}
    print(f"built {len(U)} stocks in {time.time() - t0:.0f}s", flush=True)
    E.attach_benchmark(U, cal)
    strategies = R.all_strategies(); selectable = [s for s in strategies if not s.baseline]
    t1 = time.time(); res = E.walk_forward(U, strategies, cal, cfg, seed=1); print(f"walk-forward {time.time() - t1:.0f}s", flush=True)
    rows_ = res["rows"]; rows_ = rows_[rows_["entry_date"] >= pd.Timestamp(cfg["eval"]["first_test"])]
    recs = res["records"]; fold = res["folds"]
    # ---- policies and baselines on the same unseen blocks
    A = rows_; Bn = rows_[rows_["state"] == "Active"]
    naive = E.baseline_rows(U, cal, cfg, "naive_momentum_12_1")
    pool = pd.concat([E.baseline_rows(U, cal, cfg, s.id) for s in selectable], ignore_index=True)
    keyA = set(zip(A["sym"], A["fold"]))
    same = lambda df: df[[(s, f) in keyA for s, f in zip(df["sym"], df["fold"])]]
    out = {"universe": {"stocks": len(U), "adv_filter_cr": cfg["universe"]["min_adv_inr_cr"], "list": "NIFTY 500 members today (survivor-only)"},
           "protocol": {"folds": len(fold), "first_test": cfg["eval"]["first_test"], "test_d": cfg["eval"]["test_d"], "purge_d": cfg["eval"]["purge_d"], "embargo_d": cfg["eval"]["embargo_d"], "fdr_q": cfg["eval"]["fdr_q"],
                        "select_lookback_d": cfg["eval"]["select_lookback_d"], "selectable_strategies": len(selectable), "distinct_hashes": len({s.hash for s in selectable}), "costs": "costs.py real model, liquidity decile 0-9"},
           "policy_A_probation_and_active_paper_traded": E.describe(A, "ALADIN policy (Probation+Active)"),
           "policy_B_active_only": E.describe(Bn, "ALADIN policy (Active only)"),
           "baseline_naive_momentum_all_stocks": E.describe(naive, "naive 12-1 momentum, every stock"),
           "baseline_naive_momentum_same_stock_blocks": E.describe(same(naive), "naive 12-1 momentum, same stock-blocks as policy A"),
           "baseline_no_selection_pool_all_stocks": E.describe(pool, "all selectable strategies, every stock, no selection"),
           "baseline_no_selection_pool_same_stock_blocks": E.describe(same(pool), "all selectable strategies, same stock-blocks as policy A"),
           "buy_and_hold": "excess vs stock drift is zero by definition; absolute equal-weight 10-day figures are in phase0_report.json",
           "outlook_model": "its per-row out-of-sample predictions were not persisted; only its published yearly metrics exist (AUC 0.534): not re-scorable as a trading policy", }
    # ---- who has evidence
    last = {}
    for (sym, sid), r in recs.items():
        if r.state in ("Probation", "Active"):
            last.setdefault(sym, []).append((sid, r.state))
    fam = pd.Series([R.by_id()[sid].family for lst in last.values() for sid, _ in lst]).value_counts().to_dict()
    out["evidence_at_end"] = {"stocks_with_any_probation_or_active": len(last), "share_of_universe": round(len(last) / max(len(U), 1), 3),
                              "active_strategies": int(sum(s == "Active" for lst in last.values() for _, s in lst)), "probation_strategies": int(sum(s == "Probation" for lst in last.values() for _, s in lst)),
                              "by_family": fam, "ever_eligible_pairs": int(sum(any(h["to"] == "Probation" for h in r.history) for r in recs.values())), "pairs_tested_per_block_max": int(fold["pairs"].max())}
    out["by_year_policy_A"] = {int(y): E.describe(g, str(y)).get("excess_vs_stock_drift") for y, g in A.groupby(A["entry_date"].dt.year)}
    out["fold_summary"] = fold[["fold", "start", "pairs", "fdr_pass", "eligible", "paper_trades", "active_trades", "n_Probation", "n_Active", "n_Demoted", "n_Retired"]].iloc[::6].to_dict("records")
    out["transitions"] = pd.Series([f"{e['from']}->{e['to']}" for e in res["events"]]).value_counts().to_dict()
    # ---- pooled evidence per strategy (no selection, no per-stock claim): 29 hypotheses, month-clustered bootstrap, BH at q
    P_ = []
    for sid, g in pool.groupby("sid"):
        mb = E.month_bootstrap(g, "excess"); P_.append({"strategy": sid, "family": R.by_id()[sid].family, "trades": mb["n_trades"], "excess_bps": mb["mean_bps"], "ci95_bps": mb["ci95_bps"], "p": E.month_p(g)})
    ps = np.array([r["p"] for r in P_]); rej = E.bh_reject(ps, cfg["eval"]["fdr_q"])
    for r, k in zip(P_, rej):
        r["bh_pass"] = bool(k)
    out["pooled_by_strategy_oos"] = sorted(P_, key=lambda r: r["p"])
    out["runtime_s"] = round(time.time() - t0)
    json.dump(out, open(a.out, "w"), indent=1, default=str)
    with gzip.open(a.events, "wt") as f:
        for e in res["events"]:
            f.write(json.dumps(e, default=str) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("fold_summary", "by_year_policy_A")}, indent=1, default=str))


if __name__ == "__main__":
    main()
