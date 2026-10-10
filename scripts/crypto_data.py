"""
Bitcoin order-flow bars for research and for the live engine: Binance BTCUSDT 1-minute candles (open, high, low, close, volume, trades, TAKER BUY volume = what aggressive buyers bought) from Binance's public data
archive (data.binance.vision, monthly files), aggregated to 15-minute bars -> data/crypto/bars_15m.csv.gz. Signed flow per bar: delta = taker buy volume - taker sell volume = 2 x taker buy - volume.

  python scripts/crypto_data.py [--from 2020-01] [--to 2026-09]
"""
import argparse
import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "crypto" / "bars_15m.csv.gz"
URL = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{m}.zip"
COLS = ["open_time", "o", "h", "l", "c", "v", "close_time", "qv", "n", "tbv", "tbqv", "x"]


def month_file(m):
    r = requests.get(URL.format(m=m), timeout=120)
    if r.status_code != 200:
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content)); df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=COLS)
    t = df["open_time"]; unit = "us" if t.iloc[0] > 1e14 else "ms"                      # Binance switched the archive to microseconds in 2025
    df["t"] = pd.to_datetime(t, unit=unit); return df[["t", "o", "h", "l", "c", "v", "n", "tbv"]]


def to_bars(m1, rule="15min"):
    g = m1.set_index("t").resample(rule, label="left", closed="left")
    b = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(), "v": g["v"].sum(), "n": g["n"].sum(), "tbv": g["tbv"].sum(), "m": g["o"].count()}).dropna(subset=["o"])
    b = b[b["m"] == int(pd.Timedelta(rule) / pd.Timedelta("1min"))]                       # only complete bars
    return b.drop(columns="m")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--from", dest="a", default="2020-01"); ap.add_argument("--to", dest="b", default="2026-09"); x = ap.parse_args()
    months = [p.strftime("%Y-%m") for p in pd.period_range(x.a, x.b, freq="M")]
    with ThreadPoolExecutor(6) as ex:
        parts = list(ex.map(month_file, months))
    miss = [m for m, p in zip(months, parts) if p is None]; print("missing months:", miss)
    m1 = pd.concat([p for p in parts if p is not None]); bars = pd.concat([to_bars(p) for p in parts if p is not None]).sort_index()
    OUT.parent.mkdir(parents=True, exist_ok=True); bars.to_csv(OUT, compression="gzip", float_format="%.8g")
    print(f"{len(m1):,} one-minute candles -> {len(bars):,} 15-minute bars, {bars.index[0]} to {bars.index[-1]}; {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
