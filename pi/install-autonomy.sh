#!/usr/bin/env bash
# One-time setup for running unattended: safety guard, hardware watchdog, auto-import, persistent collector.
#   sudo bash ~/FrontiersBusiness/pi/install-autonomy.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR=/opt/herevidence
# The finished cardio-only collector is replaced by the continuous multi-topic collector (pi/collect.py).
systemctl disable --now herevidence-cardio 2>/dev/null || true
systemctl reset-failed herevidence-cardio 2>/dev/null || true
install -o herevidence -g herevidence -m 755 "$REPO"/pi/guard.sh "$REPO"/pi/auto-import.sh "$REPO"/pi/import-analysis.sh "$APP_DIR/pi/"
install -o herevidence -g herevidence -m 644 "$REPO"/pi/scrape.py "$REPO"/pi/collect.py "$REPO"/pi/symptoms.py "$REPO"/pi/analysis_stats.sql "$APP_DIR/pi/"
install -o herevidence -g herevidence -m 644 "$REPO"/scraper/europepmc.py "$APP_DIR/scraper/"
install -m 644 "$REPO"/pi/systemd/herevidence-{guard,autoimport}.{service,timer} "$REPO"/pi/systemd/herevidence-collect.service /etc/systemd/system/
# Hardware watchdog: if the system hangs (as on 7 Nov), the Pi reboots itself; services start again on boot.
mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=30s\nRebootWatchdogSec=2min\n' > /etc/systemd/system.conf.d/herevidence-watchdog.conf
# daemon-reexec drops transient systemd-run jobs (8 Nov), so only re-exec when the watchdog setting is new.
if [ "$(systemctl show -p RuntimeWatchdogUSec --value)" != "30s" ]; then systemctl daemon-reexec; fi
systemctl daemon-reload
systemctl enable --now herevidence-guard.timer herevidence-autoimport.timer
systemctl enable --now herevidence-collect.service
bash "$APP_DIR/pi/guard.sh"
echo "== Autonomy installed"
systemctl is-active herevidence-guard.timer herevidence-autoimport.timer herevidence-collect herevidence-sync.timer herevidence-backup.timer herevidence-api | paste -sd' '
systemctl show -p RuntimeWatchdogUSec | cat
tail -3 "$APP_DIR/models/guard.log" 2>/dev/null || true
