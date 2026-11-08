#!/usr/bin/env bash
# Safety guard for running unattended (every minute, as root, via herevidence-guard.timer).
#  - temperature >= 80 C: pause the heavy jobs (collector, symptom run); resume below 70 C
#  - temperature >= 85 C for 3 checks in a row (~3 min) even with jobs paused: clean shutdown
#  - low memory (< 80 MB available): pause the heavy jobs (Saturday's freeze was memory)
#  - data disk missing or > 95% full: pause the heavy jobs
#  - under-voltage / throttling flags: logged
# Log (persistent, on the data disk): /opt/herevidence/models/guard.log
set -u
LOG=/opt/herevidence/models/guard.log
STATE=/run/herevidence-guard
mkdir -p "$STATE"
HEAVY="herevidence-cardio herevidence-symptoms herevidence-analyse"   # never the import: it replaces tables
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
[ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 1048576 ] && mv "$LOG" "$LOG.1"

pause() {
  for u in $HEAVY; do
    if systemctl is-active -q "$u"; then systemctl stop "$u" && echo "$u" >> "$STATE/paused" && log "paused $u ($1)"; fi
  done
}
resume() {
  [ -f "$STATE/paused" ] || return 0
  if grep -q herevidence-cardio "$STATE/paused"; then systemctl start herevidence-cardio && log "resumed herevidence-cardio ($1)"; fi
  rm -f "$STATE/paused"
}

temp=$(( $(cat /sys/class/thermal/thermal_zone0/temp) / 1000 ))
memavail=$(( $(awk '/MemAvailable/ {print $2}' /proc/meminfo) / 1024 ))
thr=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)

# Heat
if [ "$temp" -ge 85 ]; then
  n=$(( $(cat "$STATE/hot" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE/hot"
  pause "temp ${temp}C"
  log "HOT ${temp}C (check $n of 3)"
  if [ "$n" -ge 3 ]; then log "SHUTDOWN: ${temp}C for 3 minutes"; sync; systemctl poweroff; exit 0; fi
elif [ "$temp" -ge 80 ]; then
  echo 0 > "$STATE/hot"; pause "temp ${temp}C"
else
  echo 0 > "$STATE/hot"
  [ "$temp" -lt 70 ] && [ "$memavail" -ge 150 ] && resume "temp ${temp}C, ${memavail} MB free"
fi

# Memory
[ "$memavail" -lt 80 ] && pause "only ${memavail} MB memory available"

# Data disk
if ! mountpoint -q /mnt/evidence; then
  pause "data disk not mounted"; log "WARNING: /mnt/evidence not mounted"
else
  use=$(df --output=pcent /mnt/evidence | tail -1 | tr -dc 0-9)
  [ "$use" -gt 95 ] && pause "data disk ${use}% full"
fi

# Power / throttling (0x0 = fine)
if [ -n "$thr" ] && [ "$thr" != "0x0" ] && [ "$(cat "$STATE/thr" 2>/dev/null)" != "$thr" ]; then
  log "throttle flags $thr (0x50000/0x50005 = under-voltage or throttling happened)"; echo "$thr" > "$STATE/thr"
fi

# Heartbeat every 30 minutes, so the log shows the guard was alive
[ "$(date +%M)" = "00" ] || [ "$(date +%M)" = "30" ] && log "ok ${temp}C, ${memavail} MB free, throttled=${thr:-?}"
exit 0
