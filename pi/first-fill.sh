#!/usr/bin/env bash
# First fill of the Pi database: copy the catalogue from Supabase, then download + index all full text.
# Takes roughly 2-4 hours for ~28k papers. Safe to stop (Ctrl+C) and re-run: it continues where it stopped.
set -euo pipefail
APP_DIR=/opt/herevidence
run() { sudo -u herevidence bash -c "set -a; . /etc/herevidence.env; set +a; cd $APP_DIR && .venv/bin/python -m $*"; }

echo "== 1/2 Copying the catalogue from Supabase"
run pi.sync catalogue
echo "== 2/2 Downloading and indexing full text (progress every 100 papers)"
run pi.sync fulltext --limit 0 --workers 4
echo "== Done"
run pi.sync status
