#!/usr/bin/env bash
# B-LAB real-time relay: one-time install on a fresh Ubuntu server (Oracle Cloud / Google Cloud free VM).
#   curl -fsSLO https://raw.githubusercontent.com/atharvatyagi-gif/samnidhy-sandbox/main/relay/setup.sh
#   sudo bash setup.sh
# It asks for your Angel One details once and stores them only on this server (/opt/blab-relay/.env, readable
# by root and the relay only). Run it again any time to update the relay code; your details are kept.
set -euo pipefail
REPO=https://raw.githubusercontent.com/atharvatyagi-gif/samnidhy-sandbox/main/relay
DIR=/opt/blab-relay

echo "== 1/6 system packages"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip curl debian-keyring debian-archive-keyring apt-transport-https gnupg iptables-persistent >/dev/null

echo "== 2/6 Caddy (automatic HTTPS)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

echo "== 3/6 relay code"
id blab >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin blab
mkdir -p "$DIR"
curl -fsSL "$REPO/relay.py" -o "$DIR/relay.py"
curl -fsSL "$REPO/requirements.txt" -o "$DIR/requirements.txt"
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"

echo "== 4/6 your Angel One details (stored only on this server)"
if [ ! -f "$DIR/.env" ]; then
  read -rp "Angel One SmartAPI API key: " K
  read -rp "Angel One client code (login ID): " C
  read -rsp "Angel One MPIN (hidden): " P; echo
  read -rsp "TOTP secret (the text code shown when you enabled TOTP; hidden): " T; echo
  umask 077
  cat > "$DIR/.env" <<EOF
ANGEL_API_KEY=$K
ANGEL_CLIENT_CODE=$C
ANGEL_MPIN=$P
ANGEL_TOTP_SECRET=$T
FIREBASE_PROJECT_ID=terminal-b-863a0
ALLOWED_ORIGINS=https://atharvatyagi-gif.github.io
PORT=8765
EOF
fi
chown -R blab:blab "$DIR"; chmod 600 "$DIR/.env"

echo "== 5/6 background service (starts on boot, restarts on failure)"
cat > /etc/systemd/system/blab-relay.service <<EOF
[Unit]
Description=B-LAB real-time relay (Angel One -> B-Lab terminal)
After=network-online.target
Wants=network-online.target
[Service]
User=blab
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/venv/bin/python $DIR/relay.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now blab-relay
systemctl restart blab-relay

echo "== 6/6 HTTPS address"
IP=$(curl -fsS https://api.ipify.org)
HOST="${IP//./-}.sslip.io"
cat > /etc/caddy/Caddyfile <<EOF
$HOST {
  reverse_proxy /ws* 127.0.0.1:8765
  reverse_proxy /health 127.0.0.1:8765
}
EOF
# Oracle's Ubuntu images block web ports in iptables; open 80 (certificate check) and 443 (HTTPS)
iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT
iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT
netfilter-persistent save >/dev/null 2>&1 || true
systemctl restart caddy

sleep 8
echo
echo "Relay status:"; curl -s http://127.0.0.1:8765/health || echo "(not answering yet: run  sudo journalctl -u blab-relay -n 50)"
echo
echo "DONE. Send this address to Claude:   wss://$HOST/ws"
echo "Health check in a browser:           https://$HOST/health"
