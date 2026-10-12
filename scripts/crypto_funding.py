"""
Bitcoin perpetual-futures funding rates (Binance USD-M, every 8 hours), the cost of holding a short (or long) futures position.

  python scripts/crypto_funding.py            -> data/crypto/funding_btc.csv  (ts, rate), 2020-01 to now; resumes from the last saved row

History: data.binance.vision monthly files (reachable from GitHub's runners). The current month: the same site's daily files, then
fapi.binance.com for the last hours where it answers (it is geo-blocked from some networks; then the newest rows simply wait for the daily file).
A positive rate means longs pay shorts. Nothing is estimated: a missing period stays missing and the simulator charges 0 there, which it reports.
"""
import io
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "crypto" / "funding_btc.csv"
MONTHLY = "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{m}.zip"
REST = "https://fapi.binance.com/fapi/v1/fundingRate"


def _zip_rows(content):
    z = zipfile.ZipFile(io.BytesIO(content)); df = pd.read_csv(z.open(z.namelist()[0]))
    tcol = [c for c in df.columns if "time" in c.lower()][0]; rcol = [c for c in df.columns if "rate" in c.lower() and "funding" in c.lower()][0]
    return pd.DataFrame({"ts": pd.to_datetime(df[tcol], unit="ms", utc=True).dt.tz_localize(None).dt.floor("min"), "rate": df[rcol].astype(float)})


def load(path=OUT):
    p = Path(path)
    return pd.read_csv(p, parse_dates=["ts"]) if p.exists() else pd.DataFrame(columns=["ts", "rate"])


def update(path=OUT, now=None, session=None):
    s = session or requests.Session(); now = now or datetime.now(timezone.utc); old = load(path); parts = [old]
    start = (old["ts"].max() if len(old) else pd.Timestamp("2020-01-01")).to_period("M")
    for m in pd.period_range(start, pd.Timestamp(now.date()).to_period("M") - 1, freq="M"):
        r = s.get(MONTHLY.format(m=str(m)), timeout=60)
        if r.status_code == 200:
            parts.append(_zip_rows(r.content))
    try:
        since = int((pd.Timestamp(now.date()).replace(day=1)).timestamp() * 1000); rows = []
        while True:
            r = s.get(REST, params={"symbol": "BTCUSDT", "startTime": since, "limit": 1000}, timeout=30); r.raise_for_status(); page = r.json()
            if not page:
                break
            rows += [{"ts": pd.Timestamp(x["fundingTime"], unit="ms").floor("min"), "rate": float(x["fundingRate"])} for x in page]
            if len(page) < 1000:
                break
            since = page[-1]["fundingTime"] + 1
        parts.append(pd.DataFrame(rows))
    except Exception as e:                                                       # noqa: BLE001  geo-blocked or down: the monthly file brings these later
        print("funding: recent rows not available now:", type(e).__name__)
    df = pd.concat([p for p in parts if len(p)]).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True); df.to_csv(path, index=False)
    print(f"funding: {len(df)} rows, {df['ts'].min()} to {df['ts'].max()}"); return df


if __name__ == "__main__":
    update(); sys.exit(0)
