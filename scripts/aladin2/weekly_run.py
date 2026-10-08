"""
ALADIN 2.0 weekly signal run (the nightly "weekly" step): today's BUY / SELL book into the ledger, scoring of past books, the published file.

  python -m scripts.aladin2.weekly_run [--dry]      writes data/aladin2/ledger (wk, wkout lines) and data/aladin2/weekly.json (the page's data)
Reads: data/aladin/latest.json (ALADIN 1), data/terminal/universe.json, data/predict/latest.json (Outlook), data/aladin/sentiment.json, the newest F&O file (which stocks have futures),
the newest forecast batch in the ledger (5-day ranges). Nothing is invented: a missing input is None in the output and "not measured" on the page.
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from . import costs as C
from . import data_lake as L
from . import ledger as LG
from . import weekly as W

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else None


def fno_set(term=None):
    d = Path(term or L.TERM) / "aladin2" / "fno"; fs = sorted(d.glob("2*.json")) if d.exists() else []
    if not fs:
        return set()
    doc = json.loads(fs[-1].read_text(encoding="utf-8")); return {s for s, v in doc["d"].items() if v and v[0] > 0}          # a symbol with futures open interest


def forecast_bands(ledger_dir=None):
    fcs = [r for r in LG.read_all(ledger_dir) if r["t"] == "fc"]
    if not fcs:
        return {}
    f = fcs[-1]; j5 = f["H"].index(5); j20 = f["H"].index(20)
    return {s: {"bands5": f["bands"][i][j5], "bands20": f["bands"][i][j20]} for i, s in enumerate(f["syms"])}


def run(dry=False, ledger_dir=None, out_dir=None, capital=1_000_000):
    cfg = C.load_cfg(); aladin = _load(DATA / "aladin" / "latest.json"); uni = _load(L.TERM / "universe.json")
    if not aladin or not uni:
        return {"built": False, "why": "ALADIN 1 or the universe file is missing"}
    as_of = aladin["as_of"]; stocks = uni["stocks"]; liq = W.liquid(stocks)
    # which stocks will have a signal: rank first, then load only those prices
    R = W.rank_universe(aladin, liq); W_ = cfg["weekly"]; picked = [r.sym for r in R.itertuples() if W.decide(r.pct, W_) != "none"]
    prices = {s: L.load_prices(s) for s in picked}
    book = W.build(as_of, aladin, stocks, cfg, _load(DATA / "predict" / "latest.json"), _load(DATA / "aladin" / "sentiment.json"), fno_set(), forecast_bands(ledger_dir), prices, None, capital)
    created = pd.Timestamp.utcnow().isoformat(); status = "dry run"
    if not dry:
        rec = W.ledger_record(book, created)
        status = "already in the ledger" if LG.has("wk", as_of, ledger_dir, H=5) else LG.append(rec, ledger_dir)
        n_out = score_matured(ledger_dir, cfg, liq)
    else:
        n_out = 0
    live = W.live_record(ledger_dir) if not dry else {}
    out = {"built": True, "book": book, "live_record": live, "ledger_status": status, "outcome_lines_written": n_out, "disclaimer": cfg["disclaimer"], "labels": cfg["labels"][cfg["signal_labels"]], "mode": cfg["signal_labels"]}
    if not dry:
        od = Path(out_dir or DATA / "aladin2"); od.mkdir(parents=True, exist_ok=True); (od / "weekly.json").write_text(json.dumps(out, separators=(",", ":"), default=str), encoding="utf-8")
    return out


def score_matured(ledger_dir, cfg, liq):
    """Write a `wkout` line for every signal week whose exit open is now in the data. The market for a week = the equal-weight mean return of the liquid universe over the same five days."""
    lines = LG.read_all(ledger_dir); done = {r["d"] for r in lines if r["t"] == "wkout"}; todo = [r for r in lines if r["t"] == "wk" and r["d"] not in done]; n = 0
    if not todo:
        return 0
    cache = {}
    def prices(s):
        if s not in cache:
            cache[s] = L.load_prices(s)
        return cache[s]
    pool = [v["adv_cr"] for v in liq.values()]; dec = lambda s: C.adv_decile((liq.get(s) or {"adv_cr": 0.5})["adv_cr"], pool)
    for wk in todo:
        i = [None]
        def market(d=wk["d"]):
            rets = []
            for s in liq:
                px = prices(s)
                if px is None:
                    continue
                k = px.index.searchsorted(pd.Timestamp(d))
                if k < len(px) and px.index[k] == pd.Timestamp(d) and k + 1 + W.H < len(px):
                    rets.append(px["o"].iloc[k + 1 + W.H] / px["o"].iloc[k + 1] - 1)
            return float(pd.Series(rets).clip(-0.6, 0.6).mean()) if len(rets) > 50 else None
        # only worth the market computation if the exit open exists for at least one signal
        probe = next((s for s, _, _ in wk["buy"] + wk["sell"]), None)
        if probe is None or prices(probe) is None:
            continue
        m = market()
        if m is None:
            continue
        res = W.resolve(wk, prices, cfg, dec, m)
        if res is not None:
            LG.append(res, ledger_dir); n += 1
    return n


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); a = ap.parse_args(); r = run(a.dry)
    if not r["built"]:
        print(r["why"]); return
    b = r["book"]; print(f"as of {b['as_of']}: {b['universe']} liquid stocks ranked; bull {b['counts']['bull']}, bear {b['counts']['bear']}, HOLD {b['counts']['hold']}; ledger {r['ledger_status']}; outcome lines {r['outcome_lines_written']}")
    for side in ("bull", "bear"):
        print(side.upper(), [(x["sym"], x["rank_pct"]) for x in b[side]][:12])


if __name__ == "__main__":
    main()
