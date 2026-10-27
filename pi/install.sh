#!/usr/bin/env bash
# One-time setup of the full-text evidence server on a Raspberry Pi 5 (Raspberry Pi OS 64-bit, Bookworm).
# Run from the repo folder on the Pi:   bash pi/install.sh
# Safe to re-run: it updates the code and keeps the database, token and settings.
set -euo pipefail

APP_USER=herevidence
APP_DIR=/opt/herevidence
ENV_FILE=/etc/herevidence.env
SITE_ORIGIN="${SITE_ORIGIN:-https://larsfrontiers2.vercel.app}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }

# ---------- checks ----------
[ "$(uname -m)" = "aarch64" ] || warn "Expected a 64-bit Raspberry Pi OS (aarch64); found $(uname -m)."
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
ROOT_DEV=$(findmnt -no SOURCE /)
say "Pi has ${RAM_MB} MB RAM; system disk is ${ROOT_DEV}"
if [[ "$ROOT_DEV" != /dev/nvme* ]]; then
  warn "The system is not running from the NVMe SSD. A database on the SD card is slow and wears it out."
  warn "Recommended: write Raspberry Pi OS to the SSD with Raspberry Pi Imager and boot from it, then run this again."
  read -r -p "Continue anyway? [y/N] " ans; [[ "$ans" =~ ^[Yy]$ ]] || exit 1
fi

# ---------- packages ----------
say "Installing PostgreSQL, Python and tools"
sudo apt-get update -qq
sudo apt-get install -y -qq postgresql python3-venv python3-dev git curl rsync openssl >/dev/null

# ---------- PostgreSQL tuning for the Pi + SSD ----------
PGVER=$(ls /etc/postgresql | sort -V | tail -1)
SHARED=$(( RAM_MB / 4 )); [ "$SHARED" -gt 2048 ] && SHARED=2048
say "Tuning PostgreSQL $PGVER (shared_buffers ${SHARED}MB)"
sudo tee "/etc/postgresql/$PGVER/main/conf.d/herevidence.conf" >/dev/null <<EOF
# herevidence: tuned for Raspberry Pi 5 with NVMe SSD
shared_buffers = ${SHARED}MB
effective_cache_size = $(( RAM_MB * 3 / 4 ))MB
work_mem = 16MB
maintenance_work_mem = 256MB
random_page_cost = 1.1
effective_io_concurrency = 200
max_connections = 40
EOF
sudo systemctl restart postgresql

# ---------- user, role, database ----------
say "Creating service user and database"
id "$APP_USER" >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /var/lib/$APP_USER --shell /usr/sbin/nologin "$APP_USER"
sudo -u postgres psql -tAc "select 1 from pg_roles where rolname='$APP_USER'" | grep -q 1 || sudo -u postgres createuser "$APP_USER"
sudo -u postgres psql -tAc "select 1 from pg_database where datname='herdb'" | grep -q 1 || sudo -u postgres createdb -O "$APP_USER" herdb

# ---------- code + Python environment ----------
say "Installing the app in $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo rsync -a --delete --exclude .git --exclude data --exclude reports --exclude .venv "$REPO_DIR"/ "$APP_DIR"/
sudo chown -R "$APP_USER": "$APP_DIR"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/pi/requirements.txt"

# ---------- settings (kept on re-run) ----------
if [ ! -f "$ENV_FILE" ]; then
  say "Creating $ENV_FILE with a new API token"
  sudo tee "$ENV_FILE" >/dev/null <<EOF
PI_DB_URL=postgresql:///herdb
PI_API_TOKEN=$(openssl rand -hex 24)
PI_CORS=$SITE_ORIGIN
SUPABASE_URL=https://jvlrbsusjvuxsgijgxpb.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_aA-czPmRvwj2QODVXOUS3A_-AHkUK7F
# Optional: Claude checks labels + writes evidence records for papers the Pi scrapes
#ANTHROPIC_API_KEY=
# Papers the Pi scraper adds per hourly run
PI_SCRAPE_PER_RUN=300
EOF
  sudo chown root:"$APP_USER" "$ENV_FILE"
  sudo chmod 640 "$ENV_FILE"
fi

say "Creating the database tables"
sudo -u "$APP_USER" bash -c "set -a; . $ENV_FILE; set +a; cd $APP_DIR && .venv/bin/python -c 'from pi import store; c=store.connect(); store.apply_schema(c); print(\"schema ok\")'"

# ---------- services ----------
say "Installing services (API, hourly sync, nightly backup)"
sudo mkdir -p /var/backups/herevidence && sudo chown "$APP_USER": /var/backups/herevidence
sudo cp "$APP_DIR"/pi/systemd/*.service "$APP_DIR"/pi/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now herevidence-api.service herevidence-sync.timer herevidence-backup.timer
sleep 3
curl -fsS http://127.0.0.1:8000/health && echo

TOKEN=$(sudo grep PI_API_TOKEN "$ENV_FILE" | cut -d= -f2)
cat <<EOF

Done. Next steps:
  1. First fill (copies 28k+ papers, then downloads full text; ~2-4 hours, safe to stop/restart):
       bash $APP_DIR/pi/first-fill.sh
  2. Make the API reachable for the website:
       bash $APP_DIR/pi/expose.sh
  3. In Vercel (project larsfrontiers2 → Settings → Environment Variables) add:
       PI_API_URL   = the https address printed by expose.sh
       PI_API_TOKEN = $TOKEN
     then redeploy.
EOF
