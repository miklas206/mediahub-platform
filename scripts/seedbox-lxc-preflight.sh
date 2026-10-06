#!/usr/bin/env bash
set +x
set -Eeuo pipefail

SOURCE_VMID=${1:?Supply the existing Seedbox VM ID}
MEDIA_ROOT=${2:?Supply the existing media mount point}
[[ "$SOURCE_VMID" =~ ^[1-9][0-9]{2,8}$ ]] || { echo 'Invalid source VM ID.' >&2; exit 1; }
[[ "$MEDIA_ROOT" =~ ^/mnt/[a-zA-Z0-9_-]+$ ]] || { echo 'Use an explicit mount point directly under /mnt.' >&2; exit 1; }
[ "$(id -u)" -eq 0 ] && [ -d /etc/pve ] || { echo 'Run on the Proxmox host as root.' >&2; exit 1; }
for required in qm pct findmnt mountpoint df awk; do
    command -v "$required" >/dev/null || { echo "Missing command: $required" >&2; exit 1; }
done
SOURCE_CONFIG="/etc/pve/qemu-server/$SOURCE_VMID.conf"
[ -f "$SOURCE_CONFIG" ] || { echo 'Source VM configuration is missing.' >&2; exit 1; }
mountpoint -q -- "$MEDIA_ROOT" || { echo 'Media root is not mounted; refusing directory fallback.' >&2; exit 1; }

awk '
    /^(scsi|sata|virtio|ide)[0-9]+:/ && $0 !~ /media=cdrom/ {
        disks++
        if ($1 != "scsi0:" || $2 !~ /^local-lvm:vm-[0-9]+-disk-[0-9]+,/) unexpected=1
    }
    END {
        if (disks != 1 || unexpected) {
            print "Unexpected source disks: inspect manually before planning a migration." > "/dev/stderr"
            exit 1
        }
    }
' "$SOURCE_CONFIG"

printf '%s\n' 'READ-ONLY PREFLIGHT: no guests, mounts, permissions or media are changed.'
qm status "$SOURCE_VMID"
awk '/^(name|cores|memory|scsi0):/' "$SOURCE_CONFIG"
findmnt -rn --mountpoint "$MEDIA_ROOT" -o TARGET,SOURCE,FSTYPE,OPTIONS
df -h -- "$MEDIA_ROOT"
printf '%s\n' 'Existing containers:'
pct list
printf '%s\n' 'Source VM network interfaces:'
qm guest cmd "$SOURCE_VMID" network-get-interfaces
printf '%s\n' 'Preflight completed. This does NOT verify backup, VPN isolation, file integrity or migration readiness.'
printf '%s\n' 'Keep the source VM running. Any test guest must have no writable production media mounts.'