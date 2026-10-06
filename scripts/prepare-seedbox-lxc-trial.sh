#!/usr/bin/env bash
set +x
set -Eeuo pipefail

TRIAL_CTID=${1:?Supply a new, unused trial CT ID}
SOURCE_VMID=${2:?Supply the existing Seedbox VM ID}
TEMPLATE=${3:?Supply an existing cached local Debian template}
MEDIA_ROOT=${4:?Supply the existing media mount point}
[[ "$TRIAL_CTID" =~ ^[1-9][0-9]{2,8}$ && "$SOURCE_VMID" =~ ^[1-9][0-9]{2,8}$ && "$TRIAL_CTID" != "$SOURCE_VMID" ]] || { echo 'Invalid or overlapping guest IDs.' >&2; exit 1; }
[[ "$TEMPLATE" =~ ^local:vztmpl/debian-13-standard_[a-zA-Z0-9._-]+\.tar\.zst$ ]] || { echo 'Use a reviewed cached Debian 13 template.' >&2; exit 1; }
[[ "$MEDIA_ROOT" =~ ^/mnt/[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid media mount point.' >&2; exit 1; }
[ "$(id -u)" -eq 0 ] && [ -d /etc/pve ] || { echo 'Run on the Proxmox host as root.' >&2; exit 1; }
[ -f "/etc/pve/qemu-server/$SOURCE_VMID.conf" ] || { echo 'Source VM does not exist.' >&2; exit 1; }
[ ! -e "/etc/pve/lxc/$TRIAL_CTID.conf" ] && [ ! -e "/etc/pve/qemu-server/$TRIAL_CTID.conf" ] || { echo 'Trial ID is already in use; nothing changed.' >&2; exit 1; }
mountpoint -q -- "$MEDIA_ROOT" || { echo 'Media filesystem is not mounted.' >&2; exit 1; }
MOVIES_ROOT="$MEDIA_ROOT/media/movies"
[ -d "$MOVIES_ROOT" ] && [ "$(readlink -f -- "$MOVIES_ROOT")" = "$MOVIES_ROOT" ] || { echo 'Movie folder is missing or traverses symlinks.' >&2; exit 1; }
[ -c /dev/net/tun ] || { echo 'Host TUN device is missing.' >&2; exit 1; }
[ -f "$(pvesm path "$TEMPLATE")" ] || { echo 'Cached template is missing.' >&2; exit 1; }

CREATED=0
finish() {
    result=$?
    trap - EXIT
    if [ "$CREATED" = 1 ]; then
        pct stop "$TRIAL_CTID" || { echo 'Could not stop the trial; inspect it manually.' >&2; exit 1; }
    fi
    exit "$result"
}
trap finish EXIT

pct create "$TRIAL_CTID" "$TEMPLATE" \
    --hostname mediahub-seedbox-trial \
    --description 'Preparation only. No production pairing, torrent state or writable media.' \
    --rootfs local-lvm:16 --cores 2 --memory 4096 --swap 0 \
    --unprivileged 1 --features nesting=1,keyctl=1 --onboot 0 \
    --net0 name=eth0,bridge=vmbr0,firewall=1,ip=dhcp,ip6=manual \
    --dev0 path=/dev/net/tun,uid=0,gid=0,mode=0600 \
    --mp0 "$MOVIES_ROOT,mp=/data/movies,ro=1,backup=0"
CREATED=1
pct start "$TRIAL_CTID"
printf '%s\n' 'Checking the effective guest mount is read-only:'
pct exec "$TRIAL_CTID" -- findmnt -rn --mountpoint /data/movies -o VFS-OPTIONS | grep -Eq '(^|,)ro(,|$)'
pct exec "$TRIAL_CTID" -- test -r /data/movies
pct exec "$TRIAL_CTID" -- test -x /data/movies
pct exec "$TRIAL_CTID" -- test -c /dev/net/tun
pct exec "$TRIAL_CTID" -- test -r /dev/net/tun
pct exec "$TRIAL_CTID" -- test -w /dev/net/tun
printf '%s\n' 'Read-only movie access and TUN device access passed. No media write was attempted.'
printf '%s\n' 'Source VM status (unchanged by this script):'
qm status "$SOURCE_VMID"
printf '%s\n' 'The trial will be stopped and retained, with automatic start disabled.'
printf '%s\n' 'Docker, Agent pairing, VPN fail-closed networking and torrent state are NOT tested yet.'