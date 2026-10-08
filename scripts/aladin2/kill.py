"""
ALADIN 2.0 kill switches (section 10.3): a stock, a sector or the whole engine becomes `Suspended` automatically when LIVE evidence breaks pre-registered limits. Suspension hides
signals and plans (the forecast range stays visible with the banner) and lasts until the limits are met again on a fresh window.

Inputs are LIVE statistics recomputed from the ledger (ledger.stats), per scope: ece, n (resolved calibrated forecasts), coverage dict {"50","80","95"}, n_cov, cusum_alarm (bool).
"""
from . import forecast as FC


def check(scope_stats, cfg):
    """-> (suspended: bool, reasons: list[str]). Limits from cfg['kill']."""
    k = cfg["kill"]; why = []
    if scope_stats.get("ece") is not None and scope_stats.get("n", 0) >= k["min_n"] and scope_stats["ece"] > k["ece_max"]:
        why.append(f"live calibration error {scope_stats['ece']:.3f} is above {k['ece_max']} (n = {scope_stats['n']})")
    cov = scope_stats.get("coverage")
    if cov and scope_stats.get("n_cov", 0) >= k["min_coverage_n"]:
        for b, v in cov.items():
            if abs(v - FC.NOMINAL[b]) > k["coverage_tol"]:
                why.append(f"live {b}% band covered {v:.1%}, more than {k['coverage_tol']:.0%} from nominal (n = {scope_stats['n_cov']})")
    if scope_stats.get("cusum_alarm"):
        why.append("live-return CUSUM alarm")
    return bool(why), why


def apply(stocks, per_stock, per_sector, engine, cfg):
    """stocks: {sym: {sector, state}}; per_stock / per_sector / engine: live stats dicts (may be empty). Returns {sym: (state_or_None, reasons)} for suspended scopes and the banner list.
    Engine suspension suspends everything; a sector is suspended when it breaks its own limits or when >= sector_share of its stocks are suspended."""
    banners = []; out = {}
    eng_s, eng_w = check(engine or {}, cfg)
    if eng_s:
        banners.append({"scope": "engine", "why": eng_w})
    st_s = {s: check(per_stock.get(s, {}), cfg) for s in stocks}
    by_sec = {}
    for s, v in stocks.items():
        by_sec.setdefault(v.get("sector"), []).append(s)
    sec_s = {}
    for sec, syms in by_sec.items():
        own, w = check(per_sector.get(sec, {}), cfg)
        share = sum(st_s[s][0] for s in syms) / max(len(syms), 1)
        if own or (share >= cfg["kill"]["sector_share"] and len(syms) >= 5):
            sec_s[sec] = w or [f"{share:.0%} of its stocks are suspended"]; banners.append({"scope": f"sector {sec}", "why": sec_s[sec]})
    for s, v in stocks.items():
        if eng_s:
            out[s] = ("Suspended", eng_w)
        elif v.get("sector") in sec_s:
            out[s] = ("Suspended", sec_s[v["sector"]])
        elif st_s[s][0]:
            out[s] = ("Suspended", st_s[s][1])
    return out, banners
