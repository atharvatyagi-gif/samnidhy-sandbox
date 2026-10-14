"""
NEXUS predicted links: for every listed company (not only the NIFTY 500), the other listed companies most likely to have a
revenue relationship with it (customer, supplier or group trade) that the filings read so far do NOT confirm.
A prediction is a model estimate, never a fact: the page labels it "Predicted, not confirmed", shows the evidence behind
it, and shows the model's measured hit rate. Confirmed links (data/supply_graph.json) are never repeated as predictions.

Evidence (all real data; anything missing is recorded as missing, never filled in):
  price      weekly returns over up to 3 years, market move removed, then the company's industry move removed:
             correlation of what is left ("move together beyond their industries") and the one-week lead/lag
  filings    one company's own filings name the other (scripts/filing_mentions.py), counting names in supply sentences
  business   descriptions: words in A's business description typical of B's industry, and the reverse (TF-IDF);
             business group (data/config/business_houses.json)
  size       traded value of both (large companies are more often named; kept so the other weights are not biased)

Model: logistic regression (few positive examples, so a simple model). Positives = confirmed links between two listed
companies; negatives = random pairs that involve a company whose filings were read (the same sampling as the positives).
Test: 5-fold. The confirmed links of one fold are hidden, the model is trained on the rest, and for each hidden link
(A, B) all ~3,000 companies are ranked for A: hit@10 = how often B is in A's top 10. Also run without the filings
evidence, because the confirmed links were found in those same filings (the full-model number flatters it).

  python scripts/nexus_predict.py      -> data/nexus_predict/predicted.json (summary + test) and data/nexus_predict/links/<A-Z0>.json
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TERM = ROOT / "data" / "terminal"
GRAPH = ROOT / "data" / "supply_graph.json"
PROFILES = ROOT / "data" / "nexus_predict" / "profiles.json"
MENTIONS = ROOT / "data" / "nexus_predict" / "mentions.json"
HOUSES = ROOT / "data" / "config" / "business_houses.json"
OUTDIR = ROOT / "data" / "nexus_predict"
WEEKS, MIN_WEEKS, TOP_K, FOLDS, NEG_PER = 156, 52, 10, 5, 60
MIN_CORR, MIN_LEAD = 0.15, 0.2           # price evidence is shown only from these values up
FEATURES = ["corr", "lead", "ment", "ment_sup", "txt", "txt_cross", "group", "size"]
# chosen by the 5-fold test (2026-10-14, 39 confirmed links): an industry-pair rate learned from the confirmed links and
# same-industry/same-sector flags made the test WORSE (too few links to learn 140 x 140 industry pairs), so they are not used.
# not features: whether we have read a company's filings, or whether Yahoo has its profile. Those describe our own data
# collection (NIFTY 500 first), not the businesses, and the model would learn "prefer companies we already read".
FILING_FEATURES = {"ment", "ment_sup"}
SEED = 7
# words of a company description that say where or since when, not what it does
DESC_STOP = set("""india indian limited ltd company companies formerly known changed name incorporated founded headquartered based
located operates operations subsidiary subsidiaries engaged business businesses segment segments include includes including
products services provides offers various range offers private public group new delhi mumbai bengaluru bangalore chennai kolkata
hyderabad pune ahmedabad gurugram gurgaon noida jaipur kochi surat vadodara lucknow chandigarh indore coimbatore nagpur thane
gujarat maharashtra karnataka tamil nadu kerala telangana andhra pradesh uttar rajasthan haryana punjab bengal odisha bihar
madhya goa assam jharkhand uttarakhand himachal internationally international globally worldwide countries abroad also well
pte inc llc corp usa america europe africa asia middle east""".split())


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


# ------------------------------------------------------------------ inputs

def companies(universe):
    rows = [s for s in universe.get("stocks", []) if not s.get("etf")]
    rows.sort(key=lambda s: s["s"])
    return rows


def price_rows(sym, hist_shards):
    d = load(TERM / "daily" / f"{sym}.json", None)
    if d and d.get("d"):
        return d["d"]
    sh = hist_shards.get(sym[0].upper() if sym[0].isalpha() else "0")
    return (sh or {}).get(sym) or []


def weekly_returns(syms, rows_of):
    """-> (W x N) weekly log returns (NaN where missing), last WEEKS weeks ending on a Friday."""
    import pandas as pd
    cols = {}
    for s in syms:
        rows = rows_of(s)
        if len(rows) < 30:
            continue
        ser = pd.Series([r[4] for r in rows], index=pd.to_datetime([r[0] for r in rows]))
        ser = ser[~ser.index.duplicated()].sort_index()
        wk = ser.resample("W-FRI").last()
        cols[s] = np.log(wk).diff()
    if not cols:
        return np.full((0, len(syms)), np.nan)
    df = pd.DataFrame(cols).reindex(columns=syms)
    df = df.iloc[-WEEKS:]
    a = df.to_numpy(dtype=np.float64)
    a[np.abs(a) > 1.0] = np.nan                         # > 170% in a week: a data break (split not adjusted), not a move
    return a


def residuals(R, ind):
    """Market move removed (beta to the cross-sectional median), then the industry's mean residual (others in it) removed."""
    W, N = R.shape
    mkt = np.nanmedian(R, axis=1)
    E = np.full_like(R, np.nan)
    for j in range(N):
        m = ~np.isnan(R[:, j]) & ~np.isnan(mkt)
        if m.sum() < MIN_WEEKS:
            continue
        x, y = mkt[m], R[m, j]
        b = np.dot(x - x.mean(), y - y.mean()) / max(np.dot(x - x.mean(), x - x.mean()), 1e-12)
        E[m, j] = y - y.mean() - b * (x - x.mean())
    groups = {}
    for j, g in enumerate(ind):
        if g:
            groups.setdefault(g, []).append(j)
    out = E.copy()
    for g, js in groups.items():
        if len(js) < 3:
            continue
        sub = E[:, js]
        tot, cnt = np.nansum(sub, axis=1), (~np.isnan(sub)).sum(axis=1)
        for k, j in enumerate(js):
            own = np.nan_to_num(sub[:, k])
            n_oth = cnt - (~np.isnan(sub[:, k])).astype(int)
            mean_oth = np.where(n_oth > 0, (tot - own) / np.maximum(n_oth, 1), 0.0)
            out[:, j] = E[:, j] - mean_oth
    return out


def corr_matrices(E):
    """-> (corr, lead) N x N float32; lead[a, b] = corr(a this week, b last week) (b moves first). NaN with < MIN_WEEKS overlap."""
    M = (~np.isnan(E)).astype(np.float32)

    def pair_corr(X, Y, MX, MY):
        Xz, Yz = np.nan_to_num(X), np.nan_to_num(Y)
        n = MX.T @ MY
        sx, sy = Xz.T @ MY, MX.T @ Yz
        sxx, syy = (Xz * Xz).T @ MY, MX.T @ (Yz * Yz)
        sxy = Xz.T @ Yz
        with np.errstate(invalid="ignore", divide="ignore"):
            cov = sxy - sx * sy / n
            vx, vy = sxx - sx * sx / n, syy - sy * sy / n
            c = cov / np.sqrt(vx * vy)
        c[n < MIN_WEEKS] = np.nan
        return c.astype(np.float32)

    E32 = E.astype(np.float32)
    corr = pair_corr(E32, E32, M, M)
    lead = pair_corr(E32[1:], E32[:-1], M[1:], M[:-1])
    np.fill_diagonal(corr, np.nan)
    np.fill_diagonal(lead, np.nan)
    return corr, lead


def text_matrices(descs, ind):
    """-> (txt, cross, vectorizer, X, centroids) ; txt = cosine of the two descriptions; cross[a, b] = cosine of a's
    description with the centroid of b's industry (a talks about b's kind of business)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize
    N = len(descs)
    has = np.array([bool(d) for d in descs])
    if has.sum() < 10:
        z = np.zeros((N, N), np.float32)
        return z, z.copy(), None, None, {}
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    vec = TfidfVectorizer(stop_words=sorted(ENGLISH_STOP_WORDS | DESC_STOP), min_df=3, max_df=0.1, sublinear_tf=True,
                          token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]{2,}\b")
    vec.fit([d for d in descs if d])
    X = vec.transform([d or "" for d in descs])
    txt = (X @ X.T).toarray().astype(np.float32)
    inds = sorted({g for g in ind if g})
    cent = {}
    for g in inds:
        js = [j for j, x in enumerate(ind) if x == g and has[j]]
        if js:
            cent[g] = normalize(np.asarray(X[js].mean(axis=0)))[0]
    if cent:
        C = np.vstack([cent[g] for g in inds])
        AxI = np.asarray(X @ C.T, dtype=np.float32)             # N x K
        col = np.array([inds.index(g) if g in cent else -1 for g in ind])
        cross = np.where(col[None, :] >= 0, AxI[:, np.maximum(col, 0)], 0.0).astype(np.float32)
    else:
        cross = np.zeros((N, N), np.float32)
    np.fill_diagonal(txt, 0)
    np.fill_diagonal(cross, 0)
    return txt, cross, vec, X, cent


def mention_matrices(mentions, idx):
    N = len(idx)
    n = np.zeros((N, N), np.float32)
    sup = np.zeros((N, N), np.float32)
    for own, rows in (mentions.get("m") or {}).items():
        a = idx.get(own)
        if a is None:
            continue
        for sym, r in rows.items():
            b = idx.get(sym)
            if b is None or b == a:
                continue
            n[a, b] += r.get("n", 0)
            sup[a, b] += r.get("sup", 0)
    read = np.zeros(N, bool)
    for s in mentions.get("read") or []:
        if s in idx:
            read[idx[s]] = True
    return n, sup, read


def confirmed_pairs(graph, idx):
    """Undirected confirmed links between two listed companies -> {(a, b): {"rel", "s", "d"}} with a < b."""
    nodes = {x["id"]: x for x in graph.get("nodes", [])}
    out = {}
    for e in graph.get("edges", []):
        s, d = (nodes.get(e["s"]) or {}).get("sym"), (nodes.get(e["d"]) or {}).get("sym")
        if not s or not d or s == d or s not in idx or d not in idx:
            continue
        a, b = sorted((idx[s], idx[d]))
        out.setdefault((a, b), {"rel": e.get("rel"), "s": s, "d": d})
    return out


def read_set(graph, mentions, idx):
    r = np.zeros(len(idx), bool)
    for s in list((graph.get("cos") or {}).keys()) + list(mentions.get("read") or []):
        if s in idx:
            r[idx[s]] = True
    return r


# ------------------------------------------------------------------ features

class Features:
    """Pair features computed on demand from the N x N matrices (symmetric where the evidence is undirected)."""

    def __init__(self, corr, lead, mn, msup, txt, cross, ind, sec, group, size):
        self.corr, self.lead, self.mn, self.msup = corr, lead, mn, msup
        self.txt, self.cross, self.ind, self.sec, self.group, self.size = txt, cross, ind, sec, group, size

    def pairs(self, A, B):
        A, B = np.asarray(A), np.asarray(B)
        c = self.corr[A, B]
        ld = np.fmax(self.lead[A, B], self.lead[B, A])
        f = {
            "corr": np.nan_to_num(c),
            "lead": np.nan_to_num(ld),
            "ment": np.log1p(self.mn[A, B] + self.mn[B, A]),
            "ment_sup": np.log1p(self.msup[A, B] + self.msup[B, A]),
            "txt": self.txt[A, B],
            "txt_cross": np.fmax(self.cross[A, B], self.cross[B, A]),
            "group": ((self.group[A] == self.group[B]) & (self.group[A] >= 0)).astype(np.float32),
            "size": self.size[A] + self.size[B],
        }
        return np.column_stack([f[k] for k in FEATURES]).astype(np.float32)


def fit(Xp, Xn, keep):
    from sklearn.linear_model import LogisticRegression
    X = np.vstack([Xp, Xn])[:, keep]
    y = np.r_[np.ones(len(Xp)), np.zeros(len(Xn))]
    mu, sd = X.mean(0), X.std(0) + 1e-6
    m = LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000)
    m.fit((X - mu) / sd, y)
    w = m.coef_[0] / sd
    b = m.intercept_[0] - (m.coef_[0] * mu / sd).sum()
    return w, b, mu


def row_scores(F, a, N, w, b, keep):
    B = np.arange(N)
    X = F.pairs(np.full(N, a), B)[:, keep]
    s = X @ w + b
    s[a] = -np.inf
    return s


def sample_negatives(rng, readv, N, exclude, per):
    A = np.flatnonzero(readv)
    out = []
    for a in A:
        for b in rng.choice(N, size=per, replace=False):
            if b != a and (min(a, b), max(a, b)) not in exclude:
                out.append((a, b))
    return out


def evaluate(F, pos, readv, N, ind, n_ind, keep, rng):
    """5-fold test; -> metrics dict and the out-of-fold scores of the positives."""
    pos = list(pos)
    order = rng.permutation(len(pos))
    folds = [order[i::FOLDS] for i in range(FOLDS)]
    allpos = set(pos)
    ranks, oof = [], []
    for k in range(FOLDS):
        test = [pos[i] for i in folds[k]]
        train = [pos[i] for i in range(len(pos)) if i not in set(folds[k])]
        neg = sample_negatives(rng, readv, N, allpos, NEG_PER)
        Xp = F.pairs(*zip(*train)) if train else np.zeros((0, len(FEATURES)), np.float32)
        Xn = F.pairs(*zip(*neg))
        w, b, _ = fit(Xp, Xn, keep)
        train_set = set(train)
        for a, bb in test:
            for x, y in ((a, bb), (bb, a)):
                if not readv[x]:
                    continue                                  # rank only from a company whose filings were read
                s = row_scores(F, x, N, w, b, keep)
                for p, q in train_set:                        # links already confirmed are not candidates
                    if p == x:
                        s[q] = -np.inf
                    elif q == x:
                        s[p] = -np.inf
                ranks.append(int((s > s[y]).sum()) + 1)
                oof.append(float(s[y]))
    r = np.array(ranks)
    n_cand = N - 1
    res = {
        "tests": int(len(r)),
        "hit10": round(float((r <= 10).mean()), 3) if len(r) else None,
        "hit50": round(float((r <= 50).mean()), 3) if len(r) else None,
        "median_rank": int(np.median(r)) if len(r) else None,
        "candidates": int(n_cand),
        "random_hit10": round(10 / n_cand, 4),
        "random_hit50": round(50 / n_cand, 4),
    }
    return res, oof


# ------------------------------------------------------------------ explanation

def top_terms(vec, X, cent, a, g, k=4):
    """Words of company a's description that are most typical of industry g (shown as the reason)."""
    if vec is None or g not in cent:
        return []
    row = X[a].toarray()[0] * cent[g]
    idx = np.argsort(row)[::-1][:k]
    names = vec.get_feature_names_out()
    return [names[i] for i in idx if row[i] > 0]


def main(argv=None):
    uni = load(TERM / "universe.json", {})
    rows = companies(uni)
    if len(rows) < 100:
        print("predict: no universe; nothing done")
        return 0
    syms = [r["s"] for r in rows]
    idx = {s: i for i, s in enumerate(syms)}
    N = len(syms)
    names = {r["s"]: r.get("n") or r["s"] for r in rows}
    prof = load(PROFILES, {}).get("cos", {})
    graph, mentions = load(GRAPH, {}), load(MENTIONS, {})

    ind_name = [(prof.get(s) or {}).get("ind") or None for s in syms]
    sec_name = [(prof.get(s) or {}).get("sec") or None for s in syms]
    inds, secs = sorted({x for x in ind_name if x}), sorted({x for x in sec_name if x})
    ind = np.array([inds.index(x) if x else -1 for x in ind_name])
    sec = np.array([secs.index(x) if x else -1 for x in sec_name])
    has_prof = np.array([bool((prof.get(s) or {}).get("ind") or (prof.get(s) or {}).get("desc")) for s in syms])
    houses = load(HOUSES, {}).get("houses", [])
    group = np.full(N, -1)
    house_name = {}
    for k, h in enumerate(houses):
        for s in h.get("symbols", []):
            if s in idx:
                group[idx[s]] = k
                house_name[s] = h.get("name")
    size = np.array([np.log1p(max((r.get("avgv20") or 0) * (r.get("c") or 0), 0) / 1e5) for r in rows], np.float32)

    print(f"predict: {N} companies; {int(has_prof.sum())} with an industry or description")
    hist = {p.stem: load(p, {}) for p in (TERM / "hist").glob("*.json")}
    R = weekly_returns(syms, lambda s: price_rows(s, hist))
    E = residuals(R, ind_name)
    corr, lead = corr_matrices(E)
    priced = int((np.sum(~np.isnan(E), axis=0) >= MIN_WEEKS).sum())
    print(f"  price history: {R.shape[0]} weeks, {priced} companies with at least {MIN_WEEKS} weeks")
    txt, cross, vec, X, cent = text_matrices([(prof.get(s) or {}).get("desc") for s in syms], ind_name)
    mn, msup, _ = mention_matrices(mentions, idx)
    readv = read_set(graph, mentions, idx)
    F = Features(corr, lead, mn, msup, txt, cross, ind, sec, group, size)

    conf = confirmed_pairs(graph, idx)
    pos = list(conf)
    print(f"  confirmed links between two listed companies: {len(pos)}; companies whose filings were read: {int(readv.sum())}")
    rng = np.random.default_rng(SEED)
    keep_all = np.arange(len(FEATURES))
    keep_nofil = np.array([i for i, f in enumerate(FEATURES) if f not in FILING_FEATURES])
    keep_price = np.array([FEATURES.index("corr"), FEATURES.index("lead"), FEATURES.index("size")])
    test_full, _ = evaluate(F, pos, readv, N, ind, len(inds), keep_all, np.random.default_rng(SEED))
    test_nofil, _ = evaluate(F, pos, readv, N, ind, len(inds), keep_nofil, np.random.default_rng(SEED))
    test_price, _ = evaluate(F, pos, readv, N, ind, len(inds), keep_price, np.random.default_rng(SEED))
    print(f"  test (all evidence): {test_full}")
    print(f"  test (without filings): {test_nofil}")
    print(f"  test (price only): {test_price}")

    # final model on every confirmed link
    neg = sample_negatives(rng, readv, N, set(pos), NEG_PER)
    w, b, mu = fit(F.pairs(*zip(*pos)), F.pairs(*zip(*neg)), keep_all)
    all_pairs = F.pairs(*zip(*neg))
    cross_cut = float(np.quantile(all_pairs[:, FEATURES.index("txt_cross")], 0.95))      # top 5% of random pairs
    txt_cut = float(np.quantile(all_pairs[:, FEATURES.index("txt")], 0.95))
    confirmed_of = {}
    for (a, bb) in pos:
        confirmed_of.setdefault(a, set()).add(bb)
        confirmed_of.setdefault(bb, set()).add(a)

    links = {}
    for a in range(N):
        s = row_scores(F, a, N, w, b, keep_all)
        for x in confirmed_of.get(a, ()):
            s[x] = -np.inf
        top = np.argsort(-s)[:TOP_K]
        Xa = F.pairs(np.full(len(top), a), top)
        out = []
        for j, bb in enumerate(top):
            if not np.isfinite(s[bb]):
                continue
            ev, kinds = {}, []
            c = float(np.nan_to_num(corr[a, bb]))
            la, lb = float(np.nan_to_num(lead[a, bb])), float(np.nan_to_num(lead[bb, a]))
            if c >= MIN_CORR or max(la, lb) >= MIN_LEAD:
                kinds.append("price")
                ev["corr"] = round(c, 3)
                if max(la, lb) >= MIN_LEAD:
                    ev["lead"] = {"v": round(max(la, lb), 3), "first": syms[bb] if la >= lb else syms[a]}
            for own, oth in ((a, bb), (bb, a)):
                r = ((mentions.get("m") or {}).get(syms[own]) or {}).get(syms[oth])
                if r:
                    ev.setdefault("named", []).append({"by": syms[own], "n": r["n"], "sup": r["sup"], "pg": r.get("pg"),
                                                       "q": r.get("q"), "url": r.get("url"), "kind": r.get("kind"), "per": r.get("per")})
            if ev.get("named"):
                kinds.append("filings")
            fx = Xa[j]
            if fx[FEATURES.index("txt_cross")] >= cross_cut or fx[FEATURES.index("txt")] >= txt_cut:
                wa = top_terms(vec, X, cent, a, ind_name[bb]) if ind_name[bb] else []
                wb = top_terms(vec, X, cent, bb, ind_name[a]) if ind_name[a] else []
                if wa or wb:
                    kinds.append("business")
                    ev["words"] = {syms[a]: wa, syms[bb]: wb}
            if group[a] >= 0 and group[a] == group[bb]:
                kinds.append("group")
                ev["group"] = house_name.get(syms[a])
            if ind_name[a] or ind_name[bb]:
                ev["ind"] = [ind_name[a], ind_name[bb]]
            if ind_name[a] and ind_name[a] == ind_name[bb]:
                ev["same_ind"] = True                         # 6 of the 39 confirmed links are inside one industry, so kept, but the page says "may be a rival"
            if not kinds:
                continue                                      # a score with no evidence we can show is not published
            out.append({"p": syms[bb], "n": names[syms[bb]], "rank": len(out) + 1, "kinds": kinds, "ev": ev})
        links[syms[a]] = out

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (OUTDIR / "links").mkdir(parents=True, exist_ok=True)
    shards = {}
    for s, v in links.items():
        shards.setdefault(s[0].upper() if s[0].isalpha() else "0", {})[s] = v
    for k, v in shards.items():
        (OUTDIR / "links" / f"{k}.json").write_text(json.dumps({"generated_utc": now, "cos": v}, separators=(",", ":"), ensure_ascii=False),
                                                     encoding="utf-8")
    summary = {
        "v": 1, "generated_utc": now,
        "label": "Predicted, not confirmed",
        "method": __doc__.strip().split("\n\n")[0:4],
        "weights": {f: round(float(x), 4) for f, x in zip(FEATURES, w)},
        "test": {"all_evidence": test_full, "without_filings": test_nofil, "price_only": test_price,
                 "note": "Confirmed links were found in the same filings the mention evidence reads, so the all-evidence number flatters the model; the without-filings number is the fair one."},
        "coverage": {"companies": N, "with_profile": int(has_prof.sum()), "with_price": priced, "filings_read": int(readv.sum()),
                     "confirmed_listed_links": len(pos), "industries": len(inds)},
        "top_k": TOP_K,
    }
    (OUTDIR / "predicted.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"predict: wrote {sum(len(v) for v in links.values())} predicted links for {len(links)} companies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
