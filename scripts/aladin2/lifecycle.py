"""
ALADIN 2.0 strategy lifecycle (section 7 of the brief). One Record per (stock, strategy); transitions are pure functions so they can be unit-tested and replayed.

  Candidate  -> Probation   passes the evaluation protocol on past data (evaluate.eligible)
  Probation  -> Active      >= probation_days of paper-forward evidence AND >= min_live_trades trades AND PSR >= promote_psr AND live mean excess >= 0
  Probation  -> Demoted     fails the protocol again on refreshed data
  Active     -> Demoted     CUSUM alarm on live excess returns, or fails the protocol again, or live expectancy significantly negative
  Demoted    -> Active      eligible again before retire_min_days elapse
  Demoted    -> Retired     still not eligible after retire_min_days. Archived, never deleted
  Retired    -> Probation   only with fresh evidence: eligibility computed on data AFTER the retirement date (`fresh` flag)
  any        -> Suspended   input data missing (set by the caller); Suspended -> previous state is not automatic: it re-enters as Candidate
At most max_active_per_stock strategies per stock are Active (best score first); the rest wait in Probation.
Every transition returns an event dict with the evidence, which journal.py writes as text.
"""
from dataclasses import dataclass, field
import math

import numpy as np

STATES = ("Candidate", "Probation", "Active", "Demoted", "Retired", "Suspended")
TRADING = ("Probation", "Active")                      # states whose signals are traded (paper) in the next block


@dataclass
class Record:
    sym: str
    sid: str
    state: str = "Candidate"
    since: str = ""
    retired_on: str = ""
    live_n: int = 0
    live_start: str = ""
    live_returns: list = field(default_factory=list)   # paper-forward excess returns since entering Probation
    history: list = field(default_factory=list)


def psr(sr, n, skew=0.0, kurt=3.0, sr_ref=0.0):
    """Probabilistic Sharpe ratio (Bailey & Lopez de Prado): P(true per-period Sharpe > sr_ref) given n observations, skewness and (non-excess) kurtosis."""
    if n < 3 or sr is None or not np.isfinite(sr):
        return 0.0
    den = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if den <= 0:
        return 0.0
    z = (sr - sr_ref) * math.sqrt(n - 1) / math.sqrt(den)
    return 0.5 * math.erfc(-z / math.sqrt(2))


def psr_of(x, sr_ref=0.0):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return 0.0
    m, s = x.mean(), x.std(ddof=1); z = (x - m) / s
    return psr(m / s, len(x), float((z ** 3).mean()), float((z ** 4).mean()), sr_ref)


def dsr(x, n_trials, var_trial_sr):
    """Deflated Sharpe ratio: PSR against the Sharpe you would expect to see as the maximum of n_trials unskilled strategies (var_trial_sr = variance of the trial Sharpes)."""
    from statistics import NormalDist
    nd = NormalDist(); g = 0.5772156649
    n_trials = max(2, int(n_trials)); sr0 = math.sqrt(max(var_trial_sr, 0.0)) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials) + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    return psr_of(x, sr0)


def cusum_alarm(x, mu0, sd, k=0.5, h=5.0):
    """Lower-side CUSUM of standardised live returns against the expected mean mu0. Returns the index of the first alarm, or None, and the statistic path's maximum."""
    S, peak = 0.0, 0.0
    sd = sd if sd and sd > 0 else 1.0
    for i, v in enumerate(x):
        S = max(0.0, S + (mu0 - v) / sd - k); peak = max(peak, S)
        if S > h:
            return i, peak
    return None, peak


def _log(rec, date, to, why, evidence=None):
    ev = {"date": str(date), "sym": rec.sym, "strategy": rec.sid, "from": rec.state, "to": to, "why": why, "evidence": evidence or {}}
    rec.history.append(ev); rec.state = to; rec.since = str(date)
    return ev


def add_live(rec, excess_returns):
    rec.live_returns.extend(list(excess_returns)); rec.live_n = len(rec.live_returns)


def step(rec, date, eligible, fresh=True, alarm=None, cfg=None, days_since=None, score=0.0, evidence=None, live_test=None):
    """Advance one record at a block boundary. `eligible` = passes the protocol on data up to now; `fresh` = (for Retired) eligibility rests on post-retirement data;
    `alarm` = a live CUSUM / drift alarm raised during the last block (dict) or None; days_since = calendar days since rec.since.
    `live_test` = optional (ok, evidence) replacing the per-trade PSR promotion test (used for POOLED strategy records, whose live evidence is clustered by month). Returns a list of events."""
    lc = cfg["lifecycle"]; ev = []; evidence = evidence or {}
    ds = days_since if days_since is not None else 0
    if rec.state == "Candidate":
        if eligible:
            rec.live_returns, rec.live_n, rec.live_start = [], 0, str(date)
            ev.append(_log(rec, date, "Probation", "passed the evaluation protocol on past data", evidence))
    elif rec.state == "Probation":
        if alarm or not eligible:
            ev.append(_log(rec, date, "Demoted", "live alarm" if alarm else "no longer passes the evaluation protocol", {**evidence, **(alarm or {})}))
        else:
            n = rec.live_n; p = psr_of(rec.live_returns) if n >= 3 else 0.0
            if live_test is not None:
                if ds >= lc["probation_days"] and live_test[0]:
                    ev.append(_log(rec, date, "Active", "paper-forward evidence holds up", {**evidence, **live_test[1]}))
            elif ds >= lc["probation_days"] and n >= lc.get("min_live_trades", 10) and p >= lc["promote_psr"] and float(np.mean(rec.live_returns)) >= 0:
                ev.append(_log(rec, date, "Active", f"{n} live paper trades over {ds} days, PSR {p:.2f}", {**evidence, "live_n": n, "live_psr": round(p, 3), "live_mean_bps": round(float(np.mean(rec.live_returns)) * 1e4, 1)}))
    elif rec.state == "Active":
        if alarm or not eligible:
            ev.append(_log(rec, date, "Demoted", "live alarm" if alarm else "no longer passes the evaluation protocol", {**evidence, **(alarm or {})}))
    elif rec.state == "Demoted":
        if eligible and not alarm:
            ev.append(_log(rec, date, "Active", "recovered: passes the evaluation protocol again", evidence))
        elif ds >= lc["retire_min_days"]:
            rec.retired_on = str(date); ev.append(_log(rec, date, "Retired", f"did not recover within {lc['retire_min_days']} days", evidence))
    elif rec.state == "Retired":
        if eligible and fresh:
            rec.live_returns, rec.live_n, rec.live_start = [], 0, str(date)
            ev.append(_log(rec, date, "Probation", "re-entered with fresh out-of-sample evidence", evidence))
    elif rec.state == "Suspended":
        rec.state = "Candidate"
    return ev


def enforce_cap(recs, scores, date, cfg):
    """No more than max_active_per_stock Active per stock: keep the best-scoring, send the rest back to Probation (reason logged). recs: records of ONE stock."""
    cap = cfg["lifecycle"]["max_active_per_stock"]; act = sorted([r for r in recs if r.state == "Active"], key=lambda r: -scores.get(r.sid, 0.0)); ev = []
    for r in act[cap:]:
        ev.append(_log(r, date, "Probation", f"cap of {cap} active strategies per stock", {"score": round(scores.get(r.sid, 0.0), 4)}))
    return ev
