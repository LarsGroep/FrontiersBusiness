#!/usr/bin/env bash
# Load the analysis tables (embeddings, MeSH areas, themes) made by the GitHub "Analyse" workflow into the Pi database.
#   bash /opt/herevidence/pi/import-analysis.sh
# Light on memory: it downloads one file and lets pg_restore stream it in. Safe to re-run (replaces the tables).
set -euo pipefail
APP_DIR=/opt/herevidence
URL="${ANALYSIS_URL:-https://github.com/LarsGroep/FrontiersBusiness/releases/download/analysis-latest/analysis.dump}"
FILE="$APP_DIR/models/analysis.dump"
sudo -u herevidence mkdir -p "$APP_DIR/models"
echo "== Downloading $URL"
sudo -u herevidence curl -fsSL -o "$FILE" "$URL"
ls -lh "$FILE"
echo "== Tables"
sudo -u postgres psql -d herdb -qc "create extension if not exists vector"
sudo -u herevidence psql -d herdb -q -f "$APP_DIR/pi/schema_analysis.sql"
echo "== Replacing analysis data"
sudo -u herevidence psql -d herdb -qc "truncate paper_cluster, clusters, paper_symptom, paper_area, paper_vec, mesh"
# Papers the runner had but the Pi doesn't (should not happen; same catalogue) would break the foreign keys,
# so restore into the tables and report counts afterwards.
sudo -u herevidence pg_restore -d herdb --data-only --no-owner "$FILE"
# Fresh tables have no planner statistics; without them area/theme-filtered searches time out.
sudo -u herevidence psql -d herdb -qc "analyze paper_area, paper_cluster, paper_vec, paper_symptom, clusters, mesh"
# Area counts + totals for the theme page, computed once here (joining the big papers table is too slow per request).
sudo -u herevidence psql -d herdb -q -f "$APP_DIR/pi/analysis_stats.sql"
sudo -u herevidence psql -d herdb -Atc "insert into meta (key, value, updated_at)
  select 'cluster_run', max(run_id), now() from clusters
  on conflict (key) do update set value = excluded.value, updated_at = now()"
sudo -u herevidence psql -d herdb -Atc "select 'vectors '||(select count(*) from paper_vec)||', areas '||(select count(*) from paper_area)
  ||', themes '||(select count(*) from clusters where level=1)||', sub-themes '||(select count(*) from clusters where level=2)"
sudo systemctl restart herevidence-api   # drops the cached theme list
echo "== Done"
