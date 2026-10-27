#!/usr/bin/env bash
# Prepare a USB drive as the data disk for the evidence server (run once, on the Pi, BEFORE install.sh).
#   bash pi/prepare-usb.sh
# It ERASES the chosen drive, formats it as ext4 (the Linux format PostgreSQL needs; Windows' NTFS/exFAT
# are not safe for databases), mounts it at /mnt/evidence and adds it to /etc/fstab so it mounts at every boot.
set -euo pipefail
MOUNT=/mnt/evidence
LABEL=evidence

if findmnt -rno TARGET "$MOUNT" >/dev/null 2>&1; then
  echo "$MOUNT is already mounted from $(findmnt -no SOURCE "$MOUNT"). Nothing to do."
  exit 0
fi

ROOT_DISK=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || true)
echo "Disks on this Pi (the system disk is ${ROOT_DISK:-unknown} and is never offered):"
echo
lsblk -d -o NAME,SIZE,MODEL,TRAN,TYPE | awk -v root="$ROOT_DISK" 'NR==1 || ($5=="disk" && $1!=root)'
echo
read -r -p "Type the NAME of the USB drive to ERASE and use (e.g. sda): " DEV
DEV=${DEV#/dev/}
[ -b "/dev/$DEV" ] || { echo "No such disk: /dev/$DEV"; exit 1; }
[ "$DEV" != "$ROOT_DISK" ] || { echo "That is the system disk. Refusing."; exit 1; }
[ "$(lsblk -dno TYPE "/dev/$DEV")" = "disk" ] || { echo "Choose a whole disk (like sda), not a partition."; exit 1; }

echo
echo "ALL DATA ON /dev/$DEV ($(lsblk -dno SIZE,MODEL "/dev/$DEV" | xargs)) WILL BE ERASED."
read -r -p "Type the disk name again to confirm ($DEV): " CONFIRM
[ "$CONFIRM" = "$DEV" ] || { echo "Not confirmed. Nothing changed."; exit 1; }

echo "== Unmounting anything on /dev/$DEV"
for p in $(lsblk -nro NAME "/dev/$DEV" | tail -n +2); do sudo umount "/dev/$p" 2>/dev/null || true; done

echo "== Creating one ext4 partition"
sudo wipefs -a "/dev/$DEV" >/dev/null
echo 'type=83' | sudo sfdisk -q "/dev/$DEV"
sleep 2
PART=$(lsblk -nro NAME "/dev/$DEV" | sed -n 2p)
sudo mkfs.ext4 -q -F -L "$LABEL" -m 1 "/dev/$PART"

echo "== Mounting at $MOUNT and adding it to /etc/fstab"
UUID=$(sudo blkid -s UUID -o value "/dev/$PART")
sudo mkdir -p "$MOUNT"
grep -q "$UUID" /etc/fstab || echo "UUID=$UUID $MOUNT ext4 defaults,noatime,nofail,x-systemd.device-timeout=15s 0 2" | sudo tee -a /etc/fstab >/dev/null
sudo systemctl daemon-reload
sudo mount "$MOUNT"
df -h "$MOUNT"
echo
echo "USB drive ready at $MOUNT. Now run:  bash pi/install.sh"
