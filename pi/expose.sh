#!/usr/bin/env bash
# Make the Pi's search API reachable over HTTPS with Tailscale Funnel:
# free, a fixed address (https://<pi-name>.<tailnet>.ts.net), no domain and no router changes.
set -euo pipefail

if ! command -v tailscale >/dev/null; then
  echo "== Installing Tailscale"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

echo "== Logging in to Tailscale (open the link it prints, sign in, approve this Pi)"
sudo tailscale up

echo "== Publishing the API (port 8000) with Funnel"
echo "   The first time, Tailscale may print a link to enable HTTPS + Funnel for your account: open it, approve, then re-run this script."
sudo tailscale funnel --bg 8000

echo
sudo tailscale funnel status
URL=$(sudo tailscale funnel status 2>/dev/null | grep -o 'https://[^ ]*' | head -1 || true)
if [ -n "${URL:-}" ]; then
  echo
  echo "Your API address: ${URL%/}"
  echo "Test it:  curl ${URL%/}/health"
  echo "Put this address in Vercel as PI_API_URL (no trailing slash)."
fi
