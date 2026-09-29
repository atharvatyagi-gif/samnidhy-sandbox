# B-LAB real-time relay (Angel One SmartAPI)

Streams real-time NSE prices from Angel One to signed-in B-Lab terminal users (registered students and invited
guests). Runs on a small always-on server; the website itself stays on GitHub Pages.

```
Angel One SmartAPI WebSocket  --(ticks, <1 s)-->  relay.py on your server  --(wss, 250 ms batches)-->  terminal
```

- Your Angel One API key, client code, MPIN and TOTP secret are stored **only** on the server
  (`/opt/blab-relay/.env`, readable by root and the relay). Never in git or the website.
- Every browser must prove it is a registered B-Lab user (Firebase ID token + its own `ExpertUsers` record,
  checked with Firestore's rules) before any price is sent. Other websites cannot connect (origin check).
- It logs in again automatically every day at 08:45 IST (TOTP), so it runs without you.
- Licence: Angel One market data is licensed to the account holder. Get Angel One's written OK before showing it
  to other people (the cohort).

## Setup (once)
1. Angel One account → https://smartapi.angelone.in → **Enable TOTP** (save the text secret) → **Create an app**
   (type: Trading APIs) → copy the **API key**.
2. Oracle Cloud Always Free → create an **Ubuntu** VM in **Mumbai** (ap-mumbai-1) → in the VM's subnet
   *Security List* add ingress rules for TCP **80** and **443** from 0.0.0.0/0.
3. SSH into the VM and run:
   ```
   curl -fsSLO https://raw.githubusercontent.com/atharvatyagi-gif/samnidhy-sandbox/main/relay/setup.sh
   sudo bash setup.sh
   ```
   It asks for the four Angel One details, installs everything, and prints `wss://<ip>.sslip.io/ws`.
4. Put that address in `config.js` → `LIVE_RELAY_URL` and publish.

## Day to day
- Health: `https://<ip>.sslip.io/health` (feed status, symbols, connected users)
- Logs: `sudo journalctl -u blab-relay -f`   Restart: `sudo systemctl restart blab-relay`
- Update the relay code: run `sudo bash setup.sh` again (your details are kept).
