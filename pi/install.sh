#!/usr/bin/env bash
# One-time setup of the full-text evidence server on a Raspberry Pi 5 (Raspberry Pi OS 64-bit, Bookworm).
# Run from the repo folder on the Pi:   bash pi/install.sh
# Safe to re-run: it updates the code and keeps the database, token and settings.
set -euo pipefail

APP_USER=herevidence
APP_DIR=/opt/herevidence
ENV_FILE=/etc/herevidence.env
DATA_MOUNT=/mnt/evidence          # USB/SSD data disk prepared by pi/prepare-usb.sh
SITE_ORIGIN="${SITE_ORIGIN:-https://larsfrontiers2.vercel.app}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }

# ---------- checks ----------
[ "$(uname -m)" = "aarch64" ] || warn "Expected a 64-bit Raspberry Pi OS (aarch64); found $(uname -m)."
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
ROOT_DEV=$(findmnt -no SOURCE /)
say "Pi has ${RAM_MB} MB RAM; system disk is ${ROOT_DEV}"
USE_DATA_DISK=0
if findmnt -rno TARGET "$DATA_MOUNT" >/dev/null 2>&1; then
  USE_DATA_DISK=1
  say "Data disk found at $DATA_MOUNT ($(findmnt -no SOURCE "$DATA_MOUNT"), $(df -h --output=avail "$DATA_MOUNT" | tail -1 | xargs) free): database and backups go there"
elif [[ "$ROOT_DEV" != /dev/nvme* ]]; then
  warn "No data disk at $DATA_MOUNT and the system runs from ${ROOT_DEV} (SD card?). A database on an SD card is slow and wears it out."
  warn "Recommended: plug in the USB drive and run  bash pi/prepare-usb.sh  first, then this script again."
  read -r -p "Continue with the database on the system disk anyway? [y/N] " ans; [[ "$ans" =~ ^[Yy]$ ]] || exit 1
fi
# Backups go on the system disk: with the database on the USB drive, a dead drive can be restored from them.
BACKUP_DIR=/var/backups/herevidence

# ---------- packages ----------
say "Installing PostgreSQL, Python and tools"
sudo apt-get update -qq
sudo apt-get install -y -qq postgresql python3-venv python3-dev git curl rsync openssl >/dev/null

# ---------- PostgreSQL tuning for the Pi + SSD ----------
PGVER=$(ls /etc/postgresql | sort -V | tail -1)
SHARED=$(( RAM_MB / 4 )); [ "$SHARED" -gt 2048 ] && SHARED=2048
say "Tuning PostgreSQL $PGVER (shared_buffers ${SHARED}MB)"
sudo tee "/etc/postgresql/$PGVER/main/conf.d/herevidence.conf" >/dev/null <<EOF
# herevidence: tuned for Raspberry Pi 5 with an SSD / USB data disk
shared_buffers = ${SHARED}MB
effective_cache_size = $(( RAM_MB * 3 / 4 ))MB
work_mem = 16MB
maintenance_work_mem = 256MB
random_page_cost = 1.1
effective_io_concurrency = 200
max_connections = 40
EOF
# ---------- move the PostgreSQL data folder onto the USB/SSD data disk ----------
if [ "$USE_DATA_DISK" = 1 ]; then
  NEW_DATA="$DATA_MOUNT/postgresql/$PGVER/main"
  CUR_DATA=$(sudo -u postgres psql -tAc "show data_directory" 2>/dev/null || echo "/var/lib/postgresql/$PGVER/main")
  # The database must never start without the data disk (it would silently start empty on the SD card).
  sudo mkdir -p "/etc/systemd/system/postgresql@$PGVER-main.service.d"
  printf '[Unit]\nRequiresMountsFor=%s\n' "$DATA_MOUNT" | sudo tee "/etc/systemd/system/postgresql@$PGVER-main.service.d/data-disk.conf" >/dev/null
  sudo systemctl daemon-reload
  if [ "$CUR_DATA" != "$NEW_DATA" ]; then
    say "Moving the database folder to $NEW_DATA"
    sudo systemctl stop postgresql
    sudo mkdir -p "$NEW_DATA"
    sudo rsync -a "$CUR_DATA"/ "$NEW_DATA"/
    sudo chown -R postgres:postgres "$DATA_MOUNT/postgresql"
    sudo chmod 700 "$NEW_DATA"
    echo "data_directory = '$NEW_DATA'" | sudo tee "/etc/postgresql/$PGVER/main/conf.d/herevidence-data.conf" >/dev/null
    sudo mv "$CUR_DATA" "$CUR_DATA.moved-to-usb"   # kept as a fallback copy; delete once everything works
  fi
fi
sudo systemctl restart postgresql
[ "$USE_DATA_DISK" = 1 ] && say "Database folder: $(sudo -u postgres psql -tAc 'show data_directory')"

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
# Nightly backups go here
BACKUP_DIR=$BACKUP_DIR
EOF
  sudo chown root:"$APP_USER" "$ENV_FILE"
  sudo chmod 640 "$ENV_FILE"
fi
# Settings files from older installs: point backups at the data disk
sudo grep -q '^BACKUP_DIR=' "$ENV_FILE" || echo "BACKUP_DIR=$BACKUP_DIR" | sudo tee -a "$ENV_FILE" >/dev/null
sudo sed -i "s#^BACKUP_DIR=.*#BACKUP_DIR=$BACKUP_DIR#" "$ENV_FILE"

say "Creating the database tables"
sudo -u "$APP_USER" bash -c "set -a; . $ENV_FILE; set +a; cd $APP_DIR && .venv/bin/python -c 'from pi import store; c=store.connect(); store.apply_schema(c); print(\"schema ok\")'"

# ---------- services ----------
say "Installing services (API, hourly sync, nightly backup)"
sudo mkdir -p "$BACKUP_DIR" && sudo chown "$APP_USER": "$BACKUP_DIR"
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
