#!/usr/bin/env bash
# Hourly: if GitHub published a newer analysis release than the one loaded here, load it and rerun the
# cardiovascular symptom pilot. Runs as root via herevidence-autoimport.timer.
set -euo pipefail
APP_DIR=/opt/herevidence
STAMP=$APP_DIR/models/.analysis_imported_at
LOG=$APP_DIR/models/guard.log
api=https://api.github.com/repos/LarsGroep/FrontiersBusiness/releases/tags/analysis-latest
latest=$(curl -fsS -H "User-Agent: herevidence-pi" "$api" | python3 -c "import json,sys; a=[x for x in json.load(sys.stdin)['assets'] if x['name']=='analysis.dump']; print(a[0]['updated_at'] if a else '')")
[ -n "$latest" ] || exit 0
[ "$latest" = "$(cat "$STAMP" 2>/dev/null)" ] && exit 0
echo "$(date '+%F %T') auto-import: new analysis $latest" >> "$LOG"
bash $APP_DIR/pi/import-analysis.sh
echo "$latest" > "$STAMP"
sudo -u herevidence bash -c "set -a; . /etc/herevidence.env; set +a; cd $APP_DIR && .venv/bin/python -m pi.symptoms run --area 'C14 Cardiovascular Diseases' --out $APP_DIR/models/symptoms-cardio.json" >/dev/null
echo "$(date '+%F %T') auto-import: done" >> "$LOG"
