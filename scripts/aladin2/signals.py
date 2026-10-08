"""
ALADIN 2.0 signals, trade plan, position sizing and portfolio limits (section 9 of the brief).

Design notes (deviations from the brief are marked):
  * A signal is bullish only when ALL hold: the stock is `Validated`; at least one ACTIVE strategy of the pooled lifecycle is on for it today; its shrunk expected net return exceeds the round-trip
    cost buffer; no known event is inside the holding window. [DEVIATION: the brief also asks for p >= 0.58 at the primary horizon. Phase 3 showed P(up) carries no directional skill, so it is not a gate.]
  * Long-only: cash-equity delivery cannot be shorted. BEARISH means "exit / avoid" for a stock that has an open paper position or an Active strategy turning off; it is never a short trade.
  * Everything else reads NO EDGE: stand aside, and shows the forecast range only.
  * All wording goes through label(); all risk numbers come from data/config/aladin2.json.
"""
import math

import numpy as np

from . import costs as C
from . import forecast as FC
from . import lifecycle as LC

DIS = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results."


def label(cfg, key):
    """The ONLY place UI wording is looked up. key in bull, bear, none, range, level, plan_level."""
    return cfg["labels"][cfg["signal_labels"]][key]


# ------------------------------------------------------------------ product state (7.4)

def product_state(ev, cfg):
    """ev: dict(oos_trades, live_days, ece, net_expectancy_bps, fdr_clean, strategies = list of lifecycle states of the strategies behind the stock, suspended = bool, suspended_reason).
    -> (state, reasons). Learning (insufficient evidence) -> Provisional (some evidence) -> Validated; Suspended overrides."""
    v = cfg["states"]["validated"]; why = []
    if ev.get("suspended"):
        return "Suspended", [ev.get("suspended_reason") or "calibration or live performance broke its limits"]
    live = [s for s in ev.get("strategies", []) if s in ("Probation", "Active")]
    if not live:
        return "Learning", ["no strategy has passed the evaluation protocol for this stock yet"]
    ok = {"oos_trades": ev.get("oos_trades", 0) >= v["min_oos_trades"], "live_days": ev.get("live_days", 0) >= v["min_live_days"], "ece": ev.get("ece") is not None and ev["ece"] <= v["ece_max"],
          "net_expectancy": (ev.get("net_expectancy_bps") or 0) >= v["net_expectancy_bps_min"], "fdr_clean": bool(ev.get("fdr_clean")), "active": "Active" in live}
    if all(ok.values()):
        return "Validated", ["meets every Validated threshold"]
    miss = {"oos_trades": f"needs >= {v['min_oos_trades']} out-of-sample trades (has {ev.get('oos_trades', 0)})", "live_days": f"needs >= {v['min_live_days']} live days (has {ev.get('live_days', 0)})",
            "ece": f"calibration error must be <= {v['ece_max']}", "net_expectancy": f"net expectancy must be >= {v['net_expectancy_bps_min']} bps", "fdr_clean": "must pass the false-discovery filter", "active": "no strategy is Active yet (Probation only)"}
    return "Provisional", [miss[k] for k, g in ok.items() if not g]


# ------------------------------------------------------------------ the signal (9.1, 9.4)

def decide_signal(state, direction, mu_bps, cost_bps, event_imminent=False):
    """direction: +1 an Active strategy is on, -1 an Active strategy turned off while a paper position is open, 0 nothing. -> (key, reason). key in bull / bear / none."""
    if state != "Validated":
        return "none", f"state is {state}"
    if event_imminent:
        return "none", "a known event falls inside the holding window"
    if direction > 0:
        if mu_bps is None or mu_bps <= cost_bps:
            return "none", "expected net return is inside the cost buffer"
        return "bull", "Validated, an Active strategy is on, edge above the cost buffer"
    if direction < 0:
        return "bear", "an Active strategy turned off for a held position (exit / avoid; never a short)"
    return "none", "no Active strategy is on"


def strength_bucket(reliability, p_bucket_hit=None):
    """Low / Medium / High from the strategy's historical reliability (hit rate in its confidence bucket and sample), never from a probability alone. Without history: Low."""
    if not reliability or reliability.get("n", 0) < 100:
        return "Low"
    h = reliability.get("hit_rate", 0)
    return "High" if h >= 0.6 else "Medium" if h >= 0.5 else "Low"


# ------------------------------------------------------------------ trade plan (9.2)

def choose_stop(close, atr, strategy_stop, swing_low, cfg):
    """The more conservative (higher, i.e. smaller loss) of the strategy's own exit, a volatility stop and a structure stop, kept inside [stop_atr_min, stop_atr_max] ATRs below the close."""
    s = cfg["signals"]; vol_stop = close - s["stop_atr_default"] * atr
    cands = [x for x in (strategy_stop, vol_stop, swing_low) if x is not None and x < close]
    stop = max(cands) if cands else vol_stop
    return float(min(max(stop, close - s["stop_atr_max"] * atr), close - s["stop_atr_min"] * atr))


def evaluate_plan(paths, close, entry, stop, levels):
    """Monte-Carlo facts about a plan from simulated cumulative log-return paths (n, H) from today's close.
    The stop is monitored at closes and, once breached, the exit is the breach-day close (not the stop price): stops are not guaranteed fills, price can gap through them. The quoted loss at the
    invalidation level (capital_at_risk) is the loss IF the stop fills exactly at the stop; expected_R includes the slippage through it. Per level: plain probability of touching, and the typical day."""
    px = close * np.exp(paths); risk = entry - stop; n, H = px.shape
    hit = (px <= stop).any(1); first_stop = np.where(hit, (px <= stop).argmax(1), H)
    breach_px = px[np.arange(n), np.minimum(first_stop, H - 1)]                      # the first close below the stop: a stop is not a guaranteed fill, price can gap through it
    exit_px = np.where(hit, breach_px, px[:, -1]); R = (exit_px - entry) / risk
    out = {"p_stop": float(hit.mean()), "expected_R": float(R.mean()), "p_end_above_entry": float((px[:, -1] > entry).mean()), "levels": []}
    for lv in levels:
        t = (px >= lv); touched = t.any(1); day = t.argmax(1)[touched] + 1
        out["levels"].append({"level": float(lv), "p_touch": float(touched.mean()), "day_median": float(np.median(day)) if len(day) else None, "day_iqr": [float(np.percentile(day, 25)), float(np.percentile(day, 75))] if len(day) else None})
    return out


def profit_levels(paths, close, cfg, bands):
    """Candidate profit levels: the upper 50% and 80% band levels and every level on a 0.25-sigma grid whose touch probability is >= touch_min_prob (the highest such). bands = [lo50, hi50, lo80, hi80, ...] price levels."""
    lv = {bands[1], bands[3]}; sig = float(paths[:, -1].std()); best = None
    for k in range(1, 40):
        L = close * math.exp(0.25 * sig * k)
        if (paths.max(1) >= math.log(L / close)).mean() >= cfg["signals"]["touch_min_prob"]:
            best = L
        else:
            break
    if best:
        lv.add(best)
    return sorted(lv)


def entry_zone(close, atr, cfg):
    m = cfg["signals"]["entry_atr_mult"]; return [float(close - m * atr), float(close + m * atr)]


def capital_at_risk(entry, stop, qty):
    """The ONE definition the UI must show: rupees lost if the stop fills exactly at the stop."""
    return float(qty * (entry - stop))


# ------------------------------------------------------------------ sizing (9.3)

def position_size(capital, entry, stop, adv_shares, mu, sd, cfg, risk_pct=None, max_pos_pct=None, brake=False, corr_mult=1.0):
    """qty = floor(risk amount / (entry - stop)); then capped by max position %, by liquidity (adv_participation_max x average daily shares) and by a fractional-Kelly cap built from the
    SHRUNK, calibrated per-trade edge (mu, sd): max value = capital x kelly_fraction_cap x mu / sd^2. A non-positive edge gives zero. brake halves the size; corr_mult scales it. -> dict with qty and the binding limit."""
    r = cfg["risk"]; risk_pct = r["risk_per_trade_pct"] if risk_pct is None else risk_pct; max_pos_pct = r["max_position_pct"] if max_pos_pct is None else max_pos_pct
    per_share = entry - stop
    if per_share <= 0 or entry <= 0 or capital <= 0:
        return {"qty": 0, "binding": "invalid inputs", "capital_at_risk": 0.0}
    q_risk = math.floor(capital * risk_pct / 100 / per_share)
    q_pos = math.floor(capital * max_pos_pct / 100 / entry)
    q_liq = math.floor(r["adv_participation_max"] * (adv_shares or 0))
    kelly = (mu / (sd * sd)) if (mu and sd and mu > 0) else 0.0
    q_kel = math.floor(capital * min(1.0, kelly * r["kelly_fraction_cap"]) / entry + 1e-9)       # +1e-9: binary floating point must not turn 200.0 into 199
    caps = {"risk per trade": q_risk, "max position size": q_pos, "liquidity": q_liq, "fractional Kelly (edge too small)": q_kel}
    binding = min(caps, key=caps.get); qty = caps[binding]
    mult = (0.5 if brake else 1.0) * corr_mult; qty = math.floor(qty * mult)
    return {"qty": int(qty), "binding": binding + (" + drawdown brake" if brake else "") + (" + correlation" if corr_mult < 1 else ""), "caps": caps, "capital_at_risk": capital_at_risk(entry, stop, qty), "position_value": float(qty * entry)}


def portfolio_apply(candidates, positions, capital, cfg, paper_drawdown_pct=0.0, corr=None):
    """Apply the portfolio layer to a list of sized candidates (best first). candidate: dict(sym, sector, entry, stop, qty). positions: open ones with the same keys.
    Rules: max_open_signals; sector exposure <= max_sector_pct of capital; size x corr_size_mult when correlated (> corr_threshold) with one already taken; halve sizes while the paper
    drawdown exceeds drawdown_brake_pct. -> (accepted list with final qty, rejected list with reasons, summary with worst-case loss)."""
    r = cfg["risk"]; brake = paper_drawdown_pct > r["drawdown_brake_pct"]; taken = list(positions); acc, rej = [], []
    for c in candidates:
        if len(taken) >= r["max_open_signals"]:
            rej.append({**c, "reason": f"already {r['max_open_signals']} open signals"}); continue
        qty = c["qty"] * (0.5 if brake else 1.0)
        if corr and any((corr(c["sym"], t["sym"]) or 0) > r["corr_threshold"] for t in taken):
            qty *= r["corr_size_mult"]; c = {**c, "note": "size reduced: highly correlated with an open signal"}
        used = sum(t["qty"] * t["entry"] for t in taken if t.get("sector") == c.get("sector")); room = capital * r["max_sector_pct"] / 100 - used
        cap_q = math.floor(room / c["entry"]) if room > 0 else 0
        if cap_q < qty:
            c = {**c, "note": (c.get("note", "") + " sector limit").strip()}
        qty = int(max(0, min(math.floor(qty), cap_q)))
        if qty <= 0:
            rej.append({**c, "reason": "sector limit or zero size"}); continue
        d = {**c, "qty": qty}; acc.append(d); taken.append(d)
    worst = sum(capital_at_risk(a["entry"], a["stop"], a["qty"]) for a in acc + list(positions))
    return acc, rej, {"worst_case_loss_if_every_stop_hits": float(worst), "worst_case_pct_of_capital": float(worst / capital * 100) if capital else None, "drawdown_brake_on": brake}


# ------------------------------------------------------------------ paper portfolio

class PaperBook:
    """Paper portfolio for VALIDATED signals only: cash, open positions, equity curve, drawdown. Costs from costs.py (delivery, long). No orders are ever placed anywhere."""
    def __init__(self, capital, cfg):
        self.cfg, self.cash, self.start, self.pos, self.closed, self.curve = cfg, float(capital), float(capital), {}, [], []

    def open(self, sym, qty, price, stop, date, decile=5):
        cost = float(C.leg_cost("buy", qty * price, "delivery", decile, self.cfg)["total"]); self.cash -= qty * price + cost
        self.pos[sym] = {"qty": qty, "entry": price, "stop": stop, "date": str(date), "decile": decile, "cost_in": cost}

    def close(self, sym, price, date):
        p = self.pos.pop(sym); cost = float(C.leg_cost("sell", p["qty"] * price, "delivery", p["decile"], self.cfg)["total"]); self.cash += p["qty"] * price - cost
        pnl = p["qty"] * (price - p["entry"]) - p["cost_in"] - cost; self.closed.append({**p, "exit": price, "exit_date": str(date), "net_pnl": pnl}); return pnl

    def equity(self, prices):
        return self.cash + sum(p["qty"] * prices.get(s, p["entry"]) for s, p in self.pos.items())

    def mark(self, date, prices):
        e = self.equity(prices); self.curve.append((str(date), e)); return e

    def drawdown_pct(self):
        if not self.curve:
            return 0.0
        e = np.array([v for _, v in self.curve]); return float((1 - e[-1] / e.max()) * 100)
