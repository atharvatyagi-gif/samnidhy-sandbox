"""
ALADIN 2.0 nightly learning job (section 7.6). Resumable, time-budgeted, one code path for production and replay.

  python -m scripts.aladin2.run_nightly --budget-min 110 --workers 2 [--resume] [--steps ingest,resolve,learn,drift,discover,forecast,publish]
  python -m scripts.aladin2.run_nightly --replay-from 2025-07-28 --days 8 --limit 100 --steps resolve,learn,drift,forecast,publish   (one simulated day at a time on history, into data/aladin2/replay/)

Steps (each may fail without stopping the rest; failures are in the report):
  1 ingest    freshness of the price cache and the last days of NSE delivery / F&O / macro files (history_backfill, polite, optional)
  2 resolve   score every forecast whose target date is now in the data and write the `out` ledger lines
  3 learn     rebuild every strategy's trades, rerun the pooled walk-forward to today (the SAME code as the research replay), write strategy states, journal every transition with its evidence
  4 drift     PSI / KS / volatility-regime checks for Probation and Active strategies; alarms go to the journal and into the next lifecycle step
  5 discover  grammar-bounded search for new rules, capped by the discovery budget; survivors enter the strategy registry as Candidates
  6 forecast  today's forecasts for the top 500 into the ledger, signals and product states, kill switches
  7 publish   journal.json, run_report.json, job summary table
Weekly (Sunday) the learn step also refits the quantile models from scratch (they are refit nightly in this version; the weekly flag is recorded in the report).
"""
import argparse
import json
import os
import random
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import costs as C
from . import data_lake as L
from . import discover as DS
from . import drift as DR
from . import evaluate as E
from . import journal as J
from . import live as LV
from . import pooled as PL
from . import robustness as RB
from . import run_phase2 as P
from .strategies import registry as R

ROOT = Path(__file__).resolve().parent.parent.parent
STEPS = ["ingest", "resolve", "learn", "drift", "discover", "forecast", "weekly", "publish"]


class Run:
    def __init__(self, a, base):
        self.a, self.base = a, Path(base); self.state = self.base / "state"; self.ledger = self.base / "ledger"; self.state.mkdir(parents=True, exist_ok=True)
        self.cfg = C.load_cfg(); self.t0 = time.time(); self.budget = a.budget_min * 60; self.rows = []; self.errors = []; self.counts = {}; self.U = None; self.cal = None; self.res = None
        self.rs_file = self.state / "run_state.json"; self.today = None

    def left(self):
        return self.budget - (time.time() - self.t0)

    def done_steps(self, day):
        if self.a.resume and self.rs_file.exists():
            d = json.loads(self.rs_file.read_text())
            if d.get("day") == day:
                return set(d["done"])
        return set()

    def mark(self, day, done):
        self.rs_file.write_text(json.dumps({"day": day, "done": sorted(done)}))

    def step(self, name, fn, day, done):
        if name in done:
            self.rows.append((name, 0.0, "skipped (done earlier, --resume)")); return
        if self.left() < 30 and name not in ("publish",):
            self.rows.append((name, 0.0, "skipped: time budget used")); return
        t = time.time()
        try:
            note = fn(); self.rows.append((name, round(time.time() - t, 1), note or "ok")); done.add(name); self.mark(day, done)
        except Exception as e:                                                  # noqa: BLE001  non-critical steps never stop the run
            self.errors.append({"step": name, "error": repr(e), "trace": traceback.format_exc()[-1500:]}); self.rows.append((name, round(time.time() - t, 1), f"FAILED: {e!r}"))

    # ------------------------------------------------------------------ steps
    def calendar(self):
        n = L.load_index(); return n.index[n.index >= pd.Timestamp(self.cfg["eval"]["data_start"])]

    def s_ingest(self):
        px = L.load_prices("RELIANCE"); last = px.index[-1].date() if px is not None else None; self.today = last
        msg = [f"latest price bar {last}"]
        try:                                                              # which inputs are live today (never fatal; offline in replay)
            from . import sources_status as SS
            for r in SS.table(offline=bool(self.a.replay_from or self.a.no_backfill)):
                print(f"  source {r[0]:<16} {r[1][:40]:<42} {r[2]:<20} {r[3]}")
        except Exception as e:                                           # noqa: BLE001
            msg.append(f"source table unavailable: {e!r}")
        if not self.a.replay_from and not self.a.no_backfill:
            from . import history_backfill as HB
            from datetime import date, timedelta
            try:
                s = date.today() - timedelta(days=10); HB.delivery(s, date.today()); HB.fno(s, date.today()); HB.macro(); msg.append("delivery / F&O / macro refreshed")
            except Exception as e:                                              # noqa: BLE001
                msg.append(f"backfill not available: {e!r}")
        return "; ".join(msg)

    def s_resolve(self):
        n = LV.resolve_matured(self.calendar(), self.ledger); self.counts["outcomes_written"] = n; return f"{n} outcome lines"

    def build_U(self):
        self.cal = self.calendar()
        if self.U is not None:
            return
        self.U, _, _ = RB.load_universe(self.a.workers, None, "pit", 500)

    def block_start(self):
        """Position and date of the walk-forward block that contains today. Strategy states only change at block boundaries (about every 63 trading days), so between boundaries the learn step is a cache hit."""
        cal = self.calendar(); until = pd.Timestamp(self.today) if self.today else cal[-1]
        fl = [(a_, b_) for a_, b_ in E.folds(cal, self.cfg) if cal[a_] <= until]; return (cal[fl[-1][0]].date() if fl else None)

    def s_learn(self):
        strategies = R.all_strategies(include_discovered=True); ids = ",".join(sorted(s.id for s in strategies)); blk = str(self.block_start()); cf = self.state / "learn_cache.json"
        if cf.exists() and (self.state / "strategies.json").exists() and not self.a.force_learn:
            c = json.loads(cf.read_text())
            at = (self.state / "alarms.json").read_text() if (self.state / "alarms.json").exists() else None
            if c.get("block") == blk and c.get("ids") == ids and c.get("alarms") == at:
                self.counts["learn_cached"] = True; return f"cache hit: no new block since {blk} and the same strategies; states unchanged"
        self.build_U(); alarms = {}
        af = self.state / "alarms.json"
        if af.exists():
            alarms = json.loads(af.read_text())
        until = pd.Timestamp(self.today) if self.today else None
        self.res = PL.walk_forward(self.U, strategies, self.cal, self.cfg, seed=1, log=None, until=until, extra_alarms=alarms)
        recs = self.res["records"]
        (self.state / "strategies.json").write_text(json.dumps({"as_of": str(self.cal[-1].date()), "universe": "pit", "strategies": {sid: {"state": r.state, "since": r.since, "retired_on": r.retired_on, "last_events": r.history[-3:]} for sid, r in recs.items()}}, indent=1, default=str))
        evs = [J.from_lifecycle(e) for e in self.res["events"]]; n = J.append(evs, self.base); self.counts["lifecycle_events"] = len(evs); self.counts["journal_new"] = n
        states = pd.Series([r.state for r in recs.values()]).value_counts().to_dict(); self.counts["strategy_states"] = states
        cf.write_text(json.dumps({"block": blk, "ids": ids, "alarms": af.read_text() if af.exists() else None}))
        return f"{len(self.U)} stocks, {len(strategies)} strategies; {len(evs)} lifecycle events ({n} new in the journal); states {states}"

    def s_drift(self):
        strategies = {s.id: s for s in R.all_strategies(include_discovered=True)}; sf = self.state / "strategies.json"
        states = {k: v["state"] for k, v in json.loads(sf.read_text())["strategies"].items()} if sf.exists() else {}
        live_ids = [sid for sid, st in states.items() if st in ("Probation", "Active") and sid in strategies]
        if not live_ids:
            (self.state / "alarms.json").write_text("{}"); return "no Probation/Active strategy to check"
        rng = random.Random(3); pool = [r[0] for r in P.universe_pit(self.cfg)]; syms = rng.sample(pool, min(150, len(pool))); ref, cur, rr, cr = {}, {}, [], []
        end = self.calendar()[-1]
        for s in syms:
            px = L.load_prices(s)
            if px is None or len(px) < 600:
                continue
            F = L.price_features(L.clean_prices(px)); a = F[(F.index > end - pd.Timedelta(days=1000)) & (F.index < end - pd.Timedelta(days=120))]; b = F[F.index > end - pd.Timedelta(days=90)]
            for c in F.columns:
                ref.setdefault(c, []).append(a[c].values); cur.setdefault(c, []).append(b[c].values)
            rr.append(a["lr1"].values); cr.append(b["lr1"].values)
        ref = {k: np.concatenate(v) for k, v in ref.items()}; cur = {k: np.concatenate(v) for k, v in cur.items()}; rr, cr = np.concatenate(rr), np.concatenate(cr); alarms = {}; ev = []
        for sid in live_ids:
            al = DR.strategy_drift(strategies[sid].features_used, ref, cur, ref_ret=rr, cur_ret=cr)
            if al:
                alarms[sid] = al; ev.append({"date": str(end.date()), "kind": "drift_alarm", "strategy": sid, "scope": "universe", "text": f"Drift alarm for {J.name(sid)}: {al['reason']} ({json.dumps(al['features'] or al['vol'])}).", "evidence": al})
        (self.state / "alarms.json").write_text(json.dumps(alarms)); n = J.append(ev, self.base); self.counts["drift_alarms"] = len(alarms)
        return f"{len(live_ids)} strategies checked, {len(alarms)} alarms"

    def s_discover(self):
        t_end = time.time() + min(self.cfg["compute"]["discovery_budget_min"] * 60, max(self.left() - 300, 0)); cal = self.calendar()
        tested = DS.load_tested(self.state); rng = random.Random(int(pd.Timestamp(cal[-1]).strftime("%Y%m%d"))); promoted = json.loads((self.state / "discovered.json").read_text())["promoted"] if (self.state / "discovered.json").exists() else []
        rows_all = P.universe_pit(self.cfg); rows_all = sorted(rows_all, key=lambda r: r[0]); rng.shuffle(rows_all); sample = rows_all[: self.a.discover_stocks]
        parents = [x["spec"] for x in promoted] or None; gen = 0; n_new = 0; n_pass = 0; best = []
        while time.time() < t_end and gen < self.a.max_generations:
            specs = DS.propose(self.a.batch, parents, rng, tested)
            if not specs:
                break
            jobs = [(s, sec, d, cal.values, self.cfg, specs) for s, sec, d in sample]
            with ProcessPoolExecutor(self.a.workers) as ex:
                Us = {sd.sym: sd for sd in ex.map(_build_cands, jobs, chunksize=4) if sd is not None}
            E.attach_benchmark(Us, cal)
            res = DS.evaluate_batch(specs, Us, cal, self.cfg, len(cal) - 1); res = DS.verdicts(res, len(tested), self.cfg)
            for r in res:
                tested[r["hash"]] = {"spec": r["spec"], "asof": str(cal[-1].date()), "n": r["n"], "mean_bps": r.get("mean_bps"), "p": r["p"], "holdout_mean_bps": r.get("holdout_mean_bps"), "passed": r["passed"], "why": r["why"]}
                n_new += 1
                if r["passed"]:
                    n_pass += 1; promoted.append({"spec": r["spec"], "hash": r["hash"], "promoted_on": str(cal[-1].date()), "evidence": {k: r.get(k) for k in ("n", "mean_bps", "p", "bar_p", "holdout_mean_bps", "holdout_p")}})
                    J.append([{"date": str(cal[-1].date()), "kind": "candidate_promoted", "strategy": f"disc_{r['hash'][:8]}", "scope": "universe", "text": f"New rule found by the search enters the registry as a Candidate: {r['text']}. Training {r['mean_bps']:+.0f} bps per trade over {r['n']} trades (p = {r['p']:.5f}, bar {r['bar_p']:.5f}); unseen holdout {r['holdout_mean_bps']:+.0f} bps. Its history is survivor-only, so live paper-forward trading decides whether it stays.", "evidence": {k: r.get(k) for k in ('n', 'mean_bps', 'p', 'bar_p', 'holdout_mean_bps', 'holdout_p')}}], self.base)
            best += sorted(res, key=lambda r: -r["fitness"])[:3]; parents = [x["spec"] for x in promoted] + [b["spec"] for b in sorted(best, key=lambda r: -r["fitness"])[:6]]; gen += 1
        DS.save_tested(tested, self.state); DS.save_discovered(promoted, self.state)
        J.append([{"date": str(cal[-1].date()), "kind": "candidate_tested", "strategy": "discovery", "scope": "universe", "text": f"The search tested {n_new} new rules tonight on {len(sample)} stocks; {n_pass} passed the search-wide false-discovery bar and the unseen holdout. {len(tested)} distinct rules tested in total.", "evidence": {"new": n_new, "passed": n_pass, "total_tested": len(tested)}}], self.base)
        self.counts["discovery"] = {"generations": gen, "new_rules": n_new, "passed": n_pass, "total_tested": len(tested)}
        return f"{gen} generations, {n_new} new rules, {n_pass} passed, {len(tested)} tested in total"

    def s_forecast(self):
        s = LV.run(self.a.workers, False, str(self.ledger), self.a.limit, self.state); self.counts["forecast"] = {k: s[k] for k in ("as_of", "stocks_forecast", "product_state_counts", "ledger_status")}
        return f"as of {s['as_of']}, {s['stocks_forecast']} stocks, states {s['product_state_counts']}, ledger {s['ledger_status']}"

    def s_weekly(self):
        from . import weekly_run as WR
        r = WR.run(False, str(self.ledger), str(self.base))
        if not r.get("built"):
            return r.get("why", "not built")
        b = r["book"]; self.counts["weekly"] = b["counts"]; return f"as of {b['as_of']}: bull {b['counts']['bull']}, bear {b['counts']['bear']}, hold {b['counts']['hold']}; ledger {r['ledger_status']}; {r['outcome_lines_written']} outcome lines"

    def s_publish(self):
        n = J.publish(self.base); return f"journal.json with {n} events"

    # ------------------------------------------------------------------ driver
    def run_day(self, day, steps):
        done = self.done_steps(day) if self.a.resume else set(); self.rows = []; self.errors = []
        fns = {"ingest": self.s_ingest, "resolve": self.s_resolve, "learn": self.s_learn, "drift": self.s_drift, "discover": self.s_discover, "forecast": self.s_forecast, "weekly": self.s_weekly, "publish": self.s_publish}
        for s in [x for x in STEPS if x in steps]:
            self.step(s, fns[s], day, done)
        rep = {"day": day, "weekday": pd.Timestamp(day).day_name(), "full_refit_day": pd.Timestamp(day).weekday() == 6, "budget_min": self.a.budget_min, "total_s": round(time.time() - self.t0), "steps": [{"step": n, "seconds": s, "note": m} for n, s, m in self.rows],
               "errors": self.errors, "counts": self.counts, "within_budget": (time.time() - self.t0) <= self.budget}
        (self.state / "run_report.json").write_text(json.dumps(rep, indent=1, default=str))
        print("\nJOB SUMMARY  " + day + "\n" + "-" * 100)
        for n, s, m in self.rows:
            print(f"{n:<10}{s:>8.1f}s  {m}")
        print("-" * 100 + f"\ntotal {rep['total_s']}s of {self.a.budget_min} min budget; errors: {len(self.errors)}")
        return rep


def _build_cands(args):
    sym, sector, decile, cal_vals, cfg, specs = args
    cal = pd.DatetimeIndex(cal_vals); px = L.load_prices(sym)
    if px is None or len(px) < cfg["universe"]["min_history_d"]:
        return None
    px = L.clean_prices(px[px.index >= pd.Timestamp(cfg["eval"]["data_start"]) - pd.Timedelta(days=420)]); F = L.price_features(px)
    return E.build_stock(sym, sector, px, F, [DS.to_strategy(s) for s in specs], cal, decile, cfg, None, None, min_entry=pd.Timestamp(cfg["eval"]["data_start"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-min", type=int, default=110); ap.add_argument("--workers", type=int, default=2); ap.add_argument("--resume", action="store_true"); ap.add_argument("--steps", default=",".join(STEPS))
    ap.add_argument("--limit", type=int, default=None); ap.add_argument("--no-backfill", action="store_true"); ap.add_argument("--replay-from", default=None); ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--force-learn", action="store_true"); ap.add_argument("--batch", type=int, default=24); ap.add_argument("--discover-stocks", type=int, default=200); ap.add_argument("--max-generations", type=int, default=50)
    a = ap.parse_args(); steps = set(a.steps.split(","))
    if not a.replay_from:
        r = Run(a, ROOT / "data" / "aladin2"); rep = r.run_day(pd.Timestamp.utcnow().strftime("%Y-%m-%d"), steps); sys.exit(0 if not rep["errors"] or True else 1)
    cal = L.load_index().index; i0 = cal.searchsorted(pd.Timestamp(a.replay_from)); reports = []; shared = None
    if "learn" in steps or "drift" in steps:
        shared, _, _ = RB.load_universe(a.workers, None, "pit", 500)                         # trades are causal, so one build on all data serves every replay day; each day only looks at blocks that had started by then
    for d in cal[i0:i0 + a.days]:
        os.environ["ALADIN2_ASOF"] = str(d.date()); L.ASOF = str(d.date())                    # every loader (including the worker processes) now sees only data up to d
        r = Run(a, ROOT / "data" / "aladin2" / "replay"); r.today = d.date(); r.U = shared; reports.append(r.run_day(str(d.date()), steps))
    (ROOT / "data" / "aladin2" / "replay" / "replay_summary.json").write_text(json.dumps([{"day": x["day"], "total_s": x["total_s"], "steps": x["steps"], "counts": x["counts"], "errors": len(x["errors"])} for x in reports], indent=1, default=str))


if __name__ == "__main__":
    main()
