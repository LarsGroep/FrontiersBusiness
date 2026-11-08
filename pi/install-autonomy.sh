#!/usr/bin/env bash
# One-time setup for running unattended: safety guard, hardware watchdog, auto-import, persistent collector.
#   sudo bash ~/FrontiersBusiness/pi/install-autonomy.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR=/opt/herevidence
# Stop the temporary collector run first; a persistent service with the same name replaces it below.
systemctl stop herevidence-cardio 2>/dev/null || true
systemctl reset-failed herevidence-cardio 2>/dev/null || true
install -o herevidence -g herevidence -m 755 "$REPO"/pi/guard.sh "$REPO"/pi/auto-import.sh "$REPO"/pi/import-analysis.sh "$APP_DIR/pi/"
install -o herevidence -g herevidence -m 644 "$REPO"/pi/scrape.py "$REPO"/pi/symptoms.py "$REPO"/pi/analysis_stats.sql "$APP_DIR/pi/"
install -m 644 "$REPO"/pi/systemd/herevidence-{guard,autoimport}.{service,timer} "$REPO"/pi/systemd/herevidence-cardio.service /etc/systemd/system/
# Hardware watchdog: if the system hangs (as on 7 Nov), the Pi reboots itself; services start again on boot.
mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=30s\nRebootWatchdogSec=2min\n' > /etc/systemd/system.conf.d/herevidence-watchdog.conf
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable --now herevidence-guard.timer herevidence-autoimport.timer
systemctl enable herevidence-cardio.service
systemctl start herevidence-cardio.service
bash "$APP_DIR/pi/guard.sh"
echo "== Autonomy installed"
systemctl is-active herevidence-guard.timer herevidence-autoimport.timer herevidence-cardio herevidence-sync.timer herevidence-backup.timer herevidence-api | paste -sd' '
systemctl show -p RuntimeWatchdogUSec | cat
tail -3 "$APP_DIR/models/guard.log" 2>/dev/null || true
