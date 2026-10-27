# Raspberry Pi 5 full-text evidence server

The Pi keeps the **full text of every paper** with a word index, so the website finds every study that mentions a term anywhere in the text. It shows exact totals, lets you page through all results and download them as a CSV. It also keeps scraping new papers without Supabase's 500 MB limit.

```
Europe PMC ──► Pi: scraper + sync ──► PostgreSQL on the USB/SSD drive ──► search API (port 8000)
Supabase catalogue ──┘                                                   │  Tailscale Funnel (HTTPS)
                                                                         ▼
                                   Vercel site /api/fulltext (keeps the token secret) ──► browser
```
If the Pi is offline, the website automatically falls back to the Supabase search.

## What you need
- **Raspberry Pi 5:** 8 GB recommended (4 GB works), with the official power supply (27 W) and a case with a fan.
- **Data drive (USB or NVMe):** holds the database (backups stay on the SD card); 16 GB is enough for ~100k papers, 256 GB+ for much more.
  - A **USB SSD** (or NVMe in a USB enclosure) in a **blue USB 3 port** works well.
  - A plain USB flash stick also works, but it is slower and wears out sooner, so keep off-site backups.
  - The Pi's system can stay on its SD card; only the operating system lives there.
- **Internet** via an Ethernet cable (better than Wi-Fi for a server).
- **A free Tailscale account** (tailscale.com) to reach the Pi over HTTPS.

## 1. Put Raspberry Pi OS on the SD card
1. On your computer, open **Raspberry Pi Imager** and choose **Raspberry Pi 5 → Raspberry Pi OS Lite (64-bit)**. Write it to the SD card.
2. In the Imager settings, set a hostname (e.g. `evidence`), your user + password, and enable SSH.
3. Start the Pi, plug the USB drive into a **blue USB 3 port**, and log in: `ssh <user>@evidence.local`.

## 2. Install
```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/LarsGroep/FrontiersBusiness.git
cd FrontiersBusiness
bash pi/prepare-usb.sh    # ERASES the USB drive: formats it (ext4), mounts it at /mnt/evidence, auto-mounts at boot
bash pi/install.sh
```
- `prepare-usb.sh` lists the drives and only formats the one you name. You type its name twice, and it never offers the system disk.
- Windows formats (NTFS/exFAT) aren't safe for a database, so the drive must be reformatted. Copy off anything you want to keep first.
- `install.sh` puts the database on the USB drive and the nightly backups on the SD card, so either one can fail without losing everything. The database is set to only start when the drive is mounted.
The script does the following, and prints the token you'll need in step 4:
- installs PostgreSQL (tuned for the Pi + SSD) and Python;
- creates the database and a service user;
- creates `/etc/herevidence.env` with a fresh API token;
- starts three services: the search API, an hourly sync, and a nightly backup.

## 3. First fill (2–4 hours, can run overnight)
```bash
bash /opt/herevidence/pi/first-fill.sh
```
This copies all ~28.5k papers from Supabase, then downloads and indexes their full text from Europe PMC. You can stop it with Ctrl+C and start it again; it continues where it stopped. After that, the hourly service:
- picks up new Supabase papers;
- fills in missing full text;
- scrapes 300 new papers per hour itself (`PI_SCRAPE_PER_RUN` in `/etc/herevidence.env`).

## 4. Connect it to the website
```bash
bash /opt/herevidence/pi/expose.sh
```
1. Sign in to Tailscale when asked. The first time, open the link it prints to allow HTTPS/Funnel, then run the script again.
2. It prints an address like `https://evidence.tail1234.ts.net`.
3. In **Vercel → larsfrontiers2 → Settings → Environment Variables**, add:
   - `PI_API_URL` = that address (no trailing slash)
   - `PI_API_TOKEN` = the token printed by `install.sh` (also in `/etc/herevidence.env`)
4. Redeploy. The site then shows *"Whole-text search is on"* under the study count.

## Everyday use
| What | Command |
|---|---|
| Is the USB drive mounted? | `df -h /mnt/evidence` |
| Is everything running? | `systemctl status herevidence-api herevidence-sync.timer herevidence-backup.timer` |
| How full is the database? | `sudo -u herevidence bash -c 'set -a; . /etc/herevidence.env; cd /opt/herevidence && .venv/bin/python -m pi.sync status'` |
| Watch the sync / scraper | `journalctl -u herevidence-sync -f` |
| API errors | `journalctl -u herevidence-api -n 100` |
| Run a sync now | `sudo systemctl start herevidence-sync` |
| Pause scraping | `sudo systemctl stop herevidence-sync.timer` (start again with `start`) |
| Update after code changes | `cd ~/FrontiersBusiness && git pull && bash pi/install.sh` |
| Try the API on the Pi | `curl -H "x-api-key: $(sudo grep TOKEN /etc/herevidence.env \| cut -d= -f2)" "http://127.0.0.1:8000/search?q=night%20sweats"` |
| API documentation | `http://127.0.0.1:8000/docs` on the Pi |

## Backups
- **Nightly:** a copy goes to `/var/backups/herevidence` (on the SD card, separate from the database drive) at 03:30, keeping the last 7.
- **Off-site:** the Pi can still be lost or stolen, so also copy them off the Pi weekly, e.g. with `rclone` to Google Drive / OneDrive:
  ```bash
  sudo apt-get install -y rclone && rclone config    # add a remote called "cloud"
  rclone copy /var/backups/herevidence cloud:herevidence
  ```
- **Restore:** `sudo -u herevidence pg_restore -d herdb --clean /var/backups/herevidence/herdb-YYYYMMDD.dump`
- **If the USB drive is unplugged:** the database and API stop (by design) and the website falls back to Supabase. Plug it back in and run `sudo systemctl restart postgresql herevidence-api`.

## Expected size and speed
- **Size:** about 35–50 KB per paper (full text + indexes), so ~1–1.5 GB for 28.5k papers and ~4–6 GB for the ~110k women-only pool. A 256 GB SSD has room for many times that.
- **Speed:** searches take ~20–200 ms on a Pi 5. Very broad queries (thousands of matches) rank on title + abstract to stay fast; every match is still counted and exportable.

## Licences
- **Open licences (CC-BY/CC0):** full text is stored and can be read via `/paper/{id}`.
- **Restricted licences (NC/ND/unknown):** only the word index is stored, so they show up in search results and counts, but the API returns just the abstract and a link.
