#!/usr/bin/env bash
# Make the search API reachable over HTTPS on a server with a public IP (VPS), using Caddy.
# Caddy gets a free Let's Encrypt certificate automatically.
#   bash /opt/herevidence/pi/expose-https.sh                 # address <ip>.sslip.io (no domain needed)
#   DOMAIN=api.example.com bash /opt/herevidence/pi/expose-https.sh   # your own domain (point its A record at the server first)
# (On a Raspberry Pi at home use expose.sh, Tailscale Funnel, instead.)
set -euo pipefail
IP=$(curl -4 -fsS https://api.ipify.org)
DOMAIN=${DOMAIN:-$(echo "$IP" | tr . -).sslip.io}

echo "== Installing Caddy"
sudo apt-get update -qq
sudo apt-get install -y -qq caddy >/dev/null

echo "== Firewall: allow SSH, HTTP, HTTPS only"
sudo apt-get install -y -qq ufw >/dev/null
sudo ufw allow OpenSSH >/dev/null
sudo ufw allow 80/tcp >/dev/null
sudo ufw allow 443/tcp >/dev/null
sudo ufw --force enable >/dev/null

echo "== Publishing https://$DOMAIN -> API on 127.0.0.1:8000"
sudo tee /etc/caddy/Caddyfile >/dev/null <<CFG
$DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:8000
	header -Server
}
CFG
sudo systemctl enable caddy >/dev/null 2>&1
sudo systemctl restart caddy
sleep 8
echo
curl -fsS "https://$DOMAIN/health" && echo || echo "(the certificate can take a minute; try: curl https://$DOMAIN/health)"
echo
echo "Your API address: https://$DOMAIN"
echo "Put this address in Vercel as PI_API_URL (no trailing slash), and PI_API_TOKEN from /etc/herevidence.env."
