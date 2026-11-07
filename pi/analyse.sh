#!/usr/bin/env bash
# Embed and cluster the Pi database:  bash /opt/herevidence/pi/analyse.sh [all|mesh|embed|cluster|summary]
# Safe to re-run: embedding only does papers without a vector; clustering replaces the previous run.
# Long run (1 GB Pi: cap memory so the database is never the one that gets squeezed):
#   sudo systemd-run --unit=herevidence-analyse --collect -p MemoryHigh=450M -p MemoryMax=750M bash /opt/herevidence/pi/analyse.sh
set -euo pipefail
APP_DIR=/opt/herevidence
STEP="${1:-all}"
DB=$(sudo -u herevidence bash -c "set -a; . /etc/herevidence.env; set +a; echo \${PI_DB_URL:-postgresql:///herdb}" | sed 's#.*/##')
echo "== pgvector in database $DB"
sudo -u postgres psql -d "$DB" -qc "create extension if not exists vector"
echo "== Python packages (fastembed, scikit-learn)"
sudo -u herevidence env PIP_NO_CACHE_DIR=1 "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/pi/requirements-analysis.txt"
sudo mkdir -p "$APP_DIR/models" && sudo chown herevidence: "$APP_DIR/models"
echo "== analysis: $STEP"
# Caches (model download, Hugging Face metadata) stay on the data disk, not in the service user's home on the SD card.
sudo -u herevidence bash -c "set -a; . /etc/herevidence.env; set +a; export HF_HOME=$APP_DIR/models/hf XDG_CACHE_HOME=$APP_DIR/models/cache TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2; cd $APP_DIR && nice -n 10 .venv/bin/python -m pi.analysis $STEP"
echo "== Done"
