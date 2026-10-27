#!/usr/bin/env bash
# Nightly database backup (run by herevidence-backup.timer). Keeps the last 7.
# Backups on the same SSD protect against mistakes, not against a dead SSD: copy them elsewhere weekly
# (e.g. `rclone copy "$BACKUP_DIR" remote:herevidence`), see pi/README.md.
set -euo pipefail
DIR=${BACKUP_DIR:-/var/backups/herevidence}
mkdir -p "$DIR"
pg_dump -Fc -Z 6 herdb > "$DIR/herdb-$(date +%Y%m%d).dump.tmp"
mv "$DIR/herdb-$(date +%Y%m%d).dump.tmp" "$DIR/herdb-$(date +%Y%m%d).dump"
ls -1t "$DIR"/herdb-*.dump | tail -n +8 | xargs -r rm --
ls -lh "$DIR"
