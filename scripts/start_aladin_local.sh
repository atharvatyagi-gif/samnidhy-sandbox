#!/usr/bin/env sh
# Starts the ALADIN tick daemon on this machine (loopback only). Then open the desk and type TICKS ON.
cd "$(dirname "$0")/.." || exit 1
python3 -m pip install -q -r requirements-aladin.txt
exec python3 scripts/aladin_ticker_daemon.py
