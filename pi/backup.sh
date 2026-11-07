#!/usr/bin/env bash
# Nightly database backup (run by herevidence-backup.timer). Keeps the last 7.
# Backups live in $BACKUP_DIR (on the Pi: the data disk, /mnt/evidence/backups). They share the drive with the
# database, so copy them off the Pi now and then (e.g. `rclone copy "$BACKUP_DIR" remote:herevidence`).
set -euo pipefail
DIR=${BACKUP_DIR:-/var/backups/herevidence}
mkdir -p "$DIR"
pg_dump -Fc -Z 6 herdb > "$DIR/herdb-$(date +%Y%m%d).dump.tmp"
mv "$DIR/herdb-$(date +%Y%m%d).dump.tmp" "$DIR/herdb-$(date +%Y%m%d).dump"
ls -1t "$DIR"/herdb-*.dump | tail -n +8 | xargs -r rm --
ls -lh "$DIR"
