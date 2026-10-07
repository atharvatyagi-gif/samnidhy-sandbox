"""
ALADIN 2.0 transaction-cost model for Indian equities. Every number comes from data/config/aladin2.json; nothing is hard-coded here.

A trade has two legs (buy, sell). Each leg is costed on its own traded value V (price x quantity), in rupees, rounded to the paisa:

  brokerage    V x brokerage_bps
  STT          delivery: V x stt_delivery_bps on BOTH legs;  intraday: V x stt_intraday_bps on the SELL leg only;  futures: V x stt_sell_bps on the SELL leg only
  exchange     V x exchange_bps
  SEBI fee     V x sebi_bps
  GST          gst_on_fees x (brokerage + exchange + SEBI)     (GST is charged on fees, never on STT or stamp)
  stamp duty   BUY leg only: delivery stamp_bps, intraday stamp_intraday_bps, futures stamp_buy_bps
  slippage     V x slippage_bps_by_adv_decile[decile]           (adverse fill vs the quoted open; the decile is the stock's liquidity rank, 0 = most liquid)

Kinds: "delivery" (cash equity held overnight), "intraday" (cash equity squared off the same day), "futures" (single-stock futures).
Shorting: cash-equity DELIVERY cannot be shorted in India. A short is only costed as "intraday" (same-day) or "futures" (a futures-eligible stock);
cost_trade() refuses {"delivery", side "short"} so that a backtest can never count a trade that cannot be placed.
"""
from decimal import ROUND_HALF_UP, Decimal
import json
from pathlib import Path

CFG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "config" / "aladin2.json"
KINDS = ("delivery", "intraday", "futures")


def load_cfg(path=CFG_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rs(x):
    """Round a rupee amount to the paisa, half up (how contract notes round)."""
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def adv_decile(adv_cr, universe_adv_cr):
    """Liquidity decile 0 (most liquid) .. 9 (least) of `adv_cr` within the universe's list of 20-day average traded values (Rs crore)."""
    xs = sorted(universe_adv_cr)
    if not xs:
        return 9
    below = sum(1 for v in xs if v > adv_cr)                  # how many stocks are MORE liquid than this one
    return min(9, int(10 * below / len(xs)))


def leg_cost(leg, value, kind="delivery", decile=5, cfg=None):
    """Itemised cost of ONE leg. leg: "buy" | "sell". value: traded value in rupees. -> dict of Decimal rupee amounts plus "total"."""
    cfg = cfg or load_cfg(); c = cfg["costs"]; V = Decimal(str(value)); bp = Decimal("0.0001")
    if kind not in KINDS or leg not in ("buy", "sell"):
        raise ValueError(f"bad kind/leg: {kind}/{leg}")
    f = c["futures"] if kind == "futures" else c
    brokerage = V * Decimal(str(f["brokerage_bps"])) * bp
    exchange = V * Decimal(str(f["exchange_bps"])) * bp
    sebi = V * Decimal(str(c["sebi_bps"])) * bp
    if kind == "delivery":
        stt = V * Decimal(str(c["stt_delivery_bps"])) * bp
        stamp = V * Decimal(str(c["stamp_bps"])) * bp if leg == "buy" else Decimal(0)
    elif kind == "intraday":
        stt = V * Decimal(str(c["stt_intraday_bps"])) * bp if leg == "sell" else Decimal(0)
        stamp = V * Decimal(str(c["stamp_intraday_bps"])) * bp if leg == "buy" else Decimal(0)
    else:
        stt = V * Decimal(str(f["stt_sell_bps"])) * bp if leg == "sell" else Decimal(0)
        stamp = V * Decimal(str(f["stamp_buy_bps"])) * bp if leg == "buy" else Decimal(0)
    gst = Decimal(str(c["gst_on_fees"])) * (_rs(brokerage) + _rs(exchange) + _rs(sebi))
    slip = V * Decimal(str(c["slippage_bps_by_adv_decile"][int(decile)])) * bp
    parts = {"brokerage": _rs(brokerage), "stt": _rs(stt), "exchange": _rs(exchange), "sebi": _rs(sebi), "gst": _rs(gst), "stamp": _rs(stamp), "slippage": _rs(slip)}
    parts["total"] = sum(parts.values(), Decimal(0))
    return parts


def cost_trade(side, kind, entry_value, exit_value, decile=5, cfg=None):
    """Both legs of a round trip. side: "long" (buy then sell) | "short" (sell then buy). -> {"entry": legcosts, "exit": legcosts, "total": Decimal}."""
    if side not in ("long", "short"):
        raise ValueError(side)
    if side == "short" and kind == "delivery":
        raise ValueError("cash-equity delivery cannot be shorted: use kind='intraday' or 'futures'")
    e, x = ("buy", "sell") if side == "long" else ("sell", "buy")
    a, b = leg_cost(e, entry_value, kind, decile, cfg), leg_cost(x, exit_value, kind, decile, cfg)
    return {"entry": a, "exit": b, "total": a["total"] + b["total"]}


def round_trip_bps(side, kind, decile=5, cfg=None, value=100000):
    """Round-trip cost as basis points of the entry value (price move assumed zero), the figure the backtest charges as a fraction."""
    t = cost_trade(side, kind, value, value, decile, cfg)
    return float(t["total"] / Decimal(str(value)) * 10000)


def leg_bps(leg, kind, decile=5, cfg=None, value=100000):
    return float(leg_cost(leg, value, kind, decile, cfg)["total"] / Decimal(str(value)) * 10000)


def worked_example(cfg=None):
    """A printable line-by-line example: 500 shares at Rs 800 bought for delivery, sold at Rs 830 ten days later, liquidity decile 3."""
    cfg = cfg or load_cfg(); q, pin, pout, dec = 500, Decimal("800"), Decimal("830"), 3
    t = cost_trade("long", "delivery", pin * q, pout * q, dec, cfg); gross = (pout - pin) * q
    L = [f"Long {q} x Rs {pin} -> Rs {pout} (delivery, liquidity decile {dec})", f"  buy value Rs {pin * q}, sell value Rs {pout * q}, gross P&L Rs {gross}"]
    for leg in ("entry", "exit"):
        L.append(f"  {leg} leg:   " + "   ".join(f"{k} {v}" for k, v in t[leg].items() if k != "total") + f"   = Rs {t[leg]['total']}")
    L.append(f"  total cost Rs {t['total']}  ->  net P&L Rs {gross - t['total']}  ({float(t['total'] / (pin * q) * 10000):.2f} bps of the entry value)")
    return "\n".join(L)


if __name__ == "__main__":
    print(worked_example())
    cfg = load_cfg()
    for k, s in (("delivery", "long"), ("intraday", "long"), ("intraday", "short"), ("futures", "long"), ("futures", "short")):
        print(f"round trip {k:9s} {s:5s} decile 0/5/9: " + " / ".join(f"{round_trip_bps(s, k, d, cfg):6.2f}" for d in (0, 5, 9)) + " bps")
