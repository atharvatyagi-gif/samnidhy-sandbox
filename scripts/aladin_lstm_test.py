"""
Does a small LSTM add anything to ALADIN's Technical model?   python scripts/aladin_lstm_test.py [--budget-min 15]   ->  data/aladin/lstm_test.json

The brief makes the LSTM optional and sets the rule for keeping it, which is fixed HERE, before any result is seen:
  * model: 1 LSTM layer of 32 units on the last 60 trading days x 4 inputs (daily log return, high-low range, volume against its 20-day average, where the close sat in the
    day's range), dropout 0.2, at most 8 epochs, CPU, 15 minutes in total for all the years;
  * test: walk-forward, one fold per calendar year from 2018. Each fold trains ONLY on earlier stock-days (a 20-calendar-day gap before the test year, because a 10-day outcome
    reaches that far) and is scored on the test year, on exactly the stock-days the LightGBM model was scored on (its saved out-of-sample probabilities, oos_10.pkl);
  * adopt it only if averaging it with LightGBM (equal rank average, no tuning) raises the pooled out-of-sample AUC by at least 0.003 ON AVERAGE over the folds AND the blend
    beats LightGBM alone in at least two thirds of them. Otherwise the result is reported as "tested, no out-of-sample gain, not used".
Nothing here changes the model that produces P(up); it only writes the verdict, which aladin_model.py copies into aladin.json and the page shows.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OOS = ROOT / "data" / "aladin_cache" / "oos_10.pkl"
OUT = ROOT / "data" / "aladin" / "lstm_test.json"
L, F, UNITS, DROPOUT, MAX_EPOCHS = 60, 4, 32, 0.2, 8
FIRST_TEST_YEAR, GAP_DAYS, TRAIN_CAP, MIN_GAIN = 2018, 20, 120_000, 0.003


def make_features(df):
    """df: daily bars with c, h, l, v indexed by date -> float32 (T, 4). Only today's and earlier bars are used for each row (no look-ahead)."""
    c, h, l, v = df["c"].astype(float), df["h"].astype(float), df["l"].astype(float), df["v"].astype(float)
    ret = np.log(c / c.shift(1))
    rng = (h - l) / c
    base = v.shift(1).rolling(20, min_periods=10).mean()
    vr = np.log((v + 1) / (base + 1))
    pos = ((c - l) / (h - l).replace(0, np.nan)).fillna(0.5)
    X = np.column_stack([ret / 0.02, rng / 0.03, vr.clip(-3, 3), pos - 0.5]).astype(np.float32)
    return np.clip(np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), -8, 8)


def build_sequences(rows, feats, index_of):
    """rows: DataFrame (date, sym, y, ...) -> (X (n, L, F), kept row positions). A row needs L days of history ending on its own date."""
    xs, keep = [], []
    for k, (d, s) in enumerate(zip(rows["date"].dt.strftime("%Y-%m-%d"), rows["sym"])):
        X, ix = feats.get(s), index_of.get(s)
        i = ix.get(d) if ix is not None else None
        if i is None or i < L - 1:
            continue
        xs.append(X[i - L + 1:i + 1])
        keep.append(k)
    return (np.stack(xs) if xs else np.zeros((0, L, F), np.float32)), np.array(keep, dtype=int)


def train_lstm(X, y, seconds, seed=7, max_epochs=MAX_EPOCHS, batch=512):
    import torch
    from torch import nn
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, torch.get_num_threads()))

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm, self.drop, self.out = nn.LSTM(F, UNITS, batch_first=True), nn.Dropout(DROPOUT), nn.Linear(UNITS, 1)

        def forward(self, x):
            h, _ = self.lstm(x)
            return self.out(self.drop(h[:, -1])).squeeze(-1)
    net, opt, loss_fn = Net(), None, nn.BCEWithLogitsLoss()
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    Xt, yt = torch.from_numpy(X), torch.from_numpy(y.astype(np.float32))
    t0, g, epochs = time.time(), np.random.default_rng(seed), 0
    for ep in range(max_epochs):
        net.train()
        order = g.permutation(len(Xt))
        for i in range(0, len(order), batch):
            b = order[i:i + batch]
            opt.zero_grad()
            loss_fn(net(Xt[b]), yt[b]).backward()
            opt.step()
            if time.time() - t0 > seconds:
                return net, epochs + (i / len(order))
        epochs += 1
    return net, float(epochs)


def predict(net, X, batch=4096):
    import torch
    net.eval()
    out = []
    with torch.inference_mode():
        for i in range(0, len(X), batch):
            out.append(torch.sigmoid(net(torch.from_numpy(X[i:i + batch]))).numpy())
    return np.concatenate(out) if out else np.zeros(0)


def auc(y, s):
    from sklearn.metrics import roc_auc_score
    y = np.asarray(y)
    return float(roc_auc_score(y, s)) if len(np.unique(y)) == 2 else None


def rank_avg(a, b):
    return pd.Series(a).rank(pct=True).to_numpy() + pd.Series(b).rank(pct=True).to_numpy()


def decide(folds, min_gain=MIN_GAIN):
    """The rule from the module text. folds: [{year, auc_lgb, auc_blend}]. -> {used, auc_gain, years_better, rule}"""
    done = [f for f in folds if f.get("auc_lgb") is not None and f.get("auc_blend") is not None]
    gains = [f["auc_blend"] - f["auc_lgb"] for f in done]
    gain = float(np.mean(gains)) if gains else 0.0
    better = sum(1 for g in gains if g > 0)
    used = bool(done) and gain >= min_gain and better >= (2 * len(done) + 2) // 3
    return {"used": used, "auc_gain": round(gain, 4), "years_better": f"{better} of {len(done)}",
            "rule": f"used only if the blend raises AUC by at least {min_gain} on average and beats LightGBM alone in at least two thirds of the years"}


def run(rows, feats, index_of, budget_s, log=print, first_year=FIRST_TEST_YEAR, max_epochs=MAX_EPOCHS, cap=TRAIN_CAP):
    """rows: the LightGBM out-of-sample rows (date, sym, y, p). -> the result document."""
    years = sorted({d.year for d in rows["date"] if d.year >= first_year})
    folds, per = [], budget_s / max(1, len(years))
    for yr in years:
        cut = pd.Timestamp(f"{yr}-01-01") - pd.Timedelta(days=GAP_DAYS)
        tr, te = rows[rows["date"] < cut], rows[rows["date"].dt.year == yr]
        if len(tr) > cap:
            tr = tr.sample(cap, random_state=1)
        Xtr, ktr = build_sequences(tr, feats, index_of)
        Xte, kte = build_sequences(te, feats, index_of)
        if len(Xtr) < 1000 or len(Xte) < 500:
            folds.append({"year": yr, "n_train": int(len(Xtr)), "n_test": int(len(Xte)), "auc_lgb": None, "auc_lstm": None, "auc_blend": None})
            continue
        t0 = time.time()
        net, ep = train_lstm(Xtr, tr["y"].to_numpy()[ktr], per, max_epochs=max_epochs)
        p = predict(net, Xte)
        te = te.iloc[kte]
        y, plgb = te["y"].to_numpy(), te["p"].to_numpy()
        f = {"year": yr, "n_train": int(len(Xtr)), "n_test": int(len(Xte)), "epochs": round(ep, 1), "seconds": round(time.time() - t0), "auc_lgb": auc(y, plgb), "auc_lstm": auc(y, p), "auc_blend": auc(y, rank_avg(plgb, p))}
        folds.append({k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()})
        log(f"  {yr}: LightGBM {f['auc_lgb']:.4f}  LSTM {f['auc_lstm']:.4f}  blend {f['auc_blend']:.4f}  ({f['n_train']:,} train rows, {ep:.1f} epochs, {f['seconds']}s)")
    d = decide(folds)
    note = ("tested, no out-of-sample gain, not used" if not d["used"] else "tested, raised out-of-sample AUC, passes the rule; wiring it into the nightly model is a separate step")
    return {"tested": True, "horizon": 10, "units": UNITS, "window": L, "inputs": F, "dropout": DROPOUT, "max_epochs": max_epochs, "folds": folds, **d, "note": note,
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def load_universe(syms, log=print):
    import aladin_model as am
    feats, index_of = {}, {}
    for k, s in enumerate(syms):
        df = am.load_prices(s, 120)
        if df is None:
            continue
        feats[s] = make_features(df)
        index_of[s] = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
        if (k + 1) % 400 == 0:
            log(f"  prices loaded for {k + 1} of {len(syms)} stocks")
    return feats, index_of


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-min", type=float, default=15.0)
    ap.add_argument("--first-year", type=int, default=FIRST_TEST_YEAR)
    a = ap.parse_args(argv)
    if not OOS.exists():
        print("data/aladin_cache/oos_10.pkl is missing: run  python scripts/aladin_model.py --full  first (it saves the out-of-sample record this test compares against).")
        return 0
    rows = pd.read_pickle(OOS)[["date", "sym", "y", "p"]].dropna()
    rows["date"] = pd.to_datetime(rows["date"])
    print(f"LSTM test: {len(rows):,} out-of-sample stock-days, {rows['sym'].nunique():,} stocks, budget {a.budget_min:g} min")
    t0 = time.time()
    feats, index_of = load_universe(sorted(rows["sym"].unique()))
    print(f"  {len(feats):,} stocks with prices ({time.time() - t0:.0f}s)")
    res = run(rows, feats, index_of, a.budget_min * 60, first_year=a.first_year)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    print(f"verdict: {res['note']} | average AUC change {res['auc_gain']:+.4f}, blend better in {res['years_better']} years | {time.time() - t0:.0f}s in all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
