@echo off
rem Starts the ALADIN tick daemon on this PC (loopback only). Then open the desk and type TICKS ON.
cd /d "%~dp0.."
python -m pip install -q -r requirements-aladin.txt
python scripts\aladin_ticker_daemon.py
pause
