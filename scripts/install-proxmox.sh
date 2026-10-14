#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077
[ "$(id -u)" -eq 0 ] && [ -d /etc/pve ] && command -v pct >/dev/null || { echo 'Open the Proxmox node Shell as root.' >&2; exit 1; }
MEDIAHUB_ARCH=$(dpkg --print-architecture)
case "$MEDIAHUB_ARCH" in
    amd64|arm64) ;;
    *) echo 'MediaHub needs a supported 64-bit amd64 or arm64 Docker host.' >&2; exit 1 ;;
esac
printf '\nMediaHub guided installation (%s). Existing guests and media are preserved.\n' "$MEDIAHUB_ARCH"
read -r -p 'New container ID (press Enter for the next free ID): ' CTID
CTID=${CTID:-$(pvesh get /cluster/nextid)}
[[ "$CTID" =~ ^[1-9][0-9]{2,8}$ ]] || { echo 'Invalid container ID.' >&2; exit 1; }
pvesh get /cluster/nextid --vmid "$CTID" >/dev/null
pvesm status --content rootdir
DEFAULT_STORAGE=$(pvesm status --content rootdir | awk 'NR>1 && $3=="active" {print $1; exit}')
[ -n "$DEFAULT_STORAGE" ] || { echo 'No active storage supports container disks. Enable rootdir storage in Proxmox first.' >&2; exit 1; }
read -r -p "Container storage [$DEFAULT_STORAGE]: " STORAGE
STORAGE=${STORAGE:-$DEFAULT_STORAGE}
pvesm status --content vztmpl
DEFAULT_TEMPLATE_STORAGE=$(pvesm status --content vztmpl | awk 'NR>1 && $3=="active" {print $1; exit}')
[ -n "$DEFAULT_TEMPLATE_STORAGE" ] || { echo 'Enable a storage location for container templates in Proxmox first.' >&2; exit 1; }
read -r -p "Template storage [$DEFAULT_TEMPLATE_STORAGE]: " TEMPLATE_STORAGE
TEMPLATE_STORAGE=${TEMPLATE_STORAGE:-$DEFAULT_TEMPLATE_STORAGE}
ip -o link show type bridge
DEFAULT_BRIDGE=$(ip -o link show type bridge | awk -F': ' 'NR==1 {split($2,a,"@"); print a[1]}')
[ -n "$DEFAULT_BRIDGE" ] || { echo 'Create a network bridge in Proxmox before continuing.' >&2; exit 1; }
read -r -p "Network bridge [$DEFAULT_BRIDGE]: " BRIDGE
BRIDGE=${BRIDGE:-$DEFAULT_BRIDGE}
HOST_CPUS=$(nproc)
HOST_AVAILABLE_MIB=$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
[ "$HOST_AVAILABLE_MIB" -ge 3072 ] || { echo 'At least 3 GiB of available host memory is needed for the guided installation. Free memory or use another node.' >&2; exit 1; }
DEFAULT_CORES=$(( HOST_CPUS < 4 ? HOST_CPUS : 4 ))
DEFAULT_MEMORY=$(( HOST_AVAILABLE_MIB / 2 ))
[ "$DEFAULT_MEMORY" -ge 2048 ] || DEFAULT_MEMORY=2048
[ "$DEFAULT_MEMORY" -le 8192 ] || DEFAULT_MEMORY=8192
read -r -p "Container CPU cores [$DEFAULT_CORES]: " CT_CORES
CT_CORES=${CT_CORES:-$DEFAULT_CORES}
read -r -p "Container RAM in MiB [$DEFAULT_MEMORY]: " CT_MEMORY
CT_MEMORY=${CT_MEMORY:-$DEFAULT_MEMORY}
[[ "$CT_CORES" =~ ^[1-9][0-9]*$ && "$CT_MEMORY" =~ ^[1-9][0-9]*$ ]] || { echo 'CPU and RAM values must be positive whole numbers.' >&2; exit 1; }
(( CT_CORES <= HOST_CPUS && CT_MEMORY >= 2048 && CT_MEMORY <= HOST_AVAILABLE_MIB - 512 )) || { echo 'Choose available CPU cores and at least 2048 MiB RAM, leaving 512 MiB free on the host.' >&2; exit 1; }
read -r -p 'Container hostname [mediahub]: ' HOSTNAME
HOSTNAME=${HOSTNAME:-mediahub}
[[ "$HOSTNAME" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || { echo 'Invalid hostname.' >&2; exit 1; }
for value in "$STORAGE" "$TEMPLATE_STORAGE" "$BRIDGE"; do
    [[ "$value" =~ ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$ ]] || { echo 'Invalid storage or bridge name.' >&2; exit 1; }
done
ip link show "$BRIDGE" >/dev/null
pvesm status --storage "$STORAGE" --content rootdir
pvesm status --storage "$TEMPLATE_STORAGE" --content vztmpl
GPU_WORK=$(mktemp -d /var/tmp/mediahub-gpu.XXXXXXXX)
GPU_HELPER="$GPU_WORK/proxmox_gpu.py"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ -f "$SCRIPT_DIR/proxmox_gpu.py" ]; then
    cp -- "$SCRIPT_DIR/proxmox_gpu.py" "$GPU_HELPER"
else
    curl -fsSL https://raw.githubusercontent.com/miklas206/mediahub-platform/main/scripts/proxmox_gpu.py -o "$GPU_HELPER"
fi
read -r -p 'Check/install missing GPU host drivers and firmware? [y/N]: ' GPU_DRIVERS
if [[ "$GPU_DRIVERS" =~ ^[yY]$ ]]; then
    python3 "$GPU_HELPER" --prepare-drivers
fi
printf '\nAvailable GPUs (optional; shared with this LXC, not reassigned from the host):\n'
python3 "$GPU_HELPER" --list
GPU_ID=${MEDIAHUB_GPU:-}
if [ -z "$GPU_ID" ]; then
    read -r -p 'GPU ID to share with MediaHub [Enter = CPU only]: ' GPU_ID
fi
if [ -n "$GPU_ID" ]; then
    python3 "$GPU_HELPER" --check --gpu "$GPU_ID"
fi
printf '%s\n' "New LXC $CTID ($HOSTNAME): $MEDIAHUB_ARCH, $CT_CORES cores, $CT_MEMORY MiB RAM, 32 GiB NEW system disk and 32 GiB NEW data disk, DHCP."
printf 'GPU: %s\n' "${GPU_ID:-None (CPU only)}"
printf '%s\n' 'App storage is prepared on the NEW data disk. No existing disks or media folders are attached.'
printf '%s\n' 'This installs Core and Agent, not an existing Seedbox migration. Check storage capacity above before accepting.'
read -r -p 'Type INSTALL to create this new container: ' CONFIRM
[ "$CONFIRM" = INSTALL ] || exit 0
trap 'echo "If a step failed, inspect the new container before retrying. Existing guests/media are not cleaned up." >&2' ERR
if [ ! -c /dev/net/tun ]; then
    modprobe tun || { echo 'Cannot load the host TUN driver. MediaHub VPN apps require /dev/net/tun.' >&2; exit 1; }
fi
[ -c /dev/net/tun ] || { echo 'Host TUN device is unavailable. No container was created.' >&2; exit 1; }
install -d -m 0755 /etc/modules-load.d
printf 'tun\n' > /etc/modules-load.d/mediahub-tun.conf
pveam update
TEMPLATE=$(pveam available --section system | awk -v arch="$MEDIAHUB_ARCH" '$2 ~ ("^debian-13-standard_.*_" arch "[.]tar[.](zst|xz|gz)$") {print $2}' | sort -V | tail -n 1)
[ -n "$TEMPLATE" ] || { echo "No Debian 13 $MEDIAHUB_ARCH container template is available on this Proxmox version. Update its template catalog or use a supported Debian 13 VM with the Linux installer." >&2; exit 1; }
pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
pvesh get /cluster/nextid --vmid "$CTID" >/dev/null
TUN_ARGS=()
PCT_CREATE_HELP=$(pct help create 2>&1 || true)
if [[ "$PCT_CREATE_HELP" == *'--dev'* ]]; then
    TUN_ARGS=(--dev0 path=/dev/net/tun,uid=0,gid=0,mode=0600)
fi
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" --hostname "$HOSTNAME" \
    --arch "$MEDIAHUB_ARCH" --unprivileged 1 --features nesting=1,keyctl=1 --cores "$CT_CORES" --memory "$CT_MEMORY" --swap 0 \
    --rootfs "$STORAGE:32" --mp0 "$STORAGE:32,mp=/storage,backup=1" \
    "${TUN_ARGS[@]}" \
    --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp,ip6=manual,firewall=1" --onboot 1
if [ "${#TUN_ARGS[@]}" -eq 0 ]; then
    # Older PVE device syntax: only this just-created container is amended.
    CT_CONFIG="/etc/pve/lxc/$CTID.conf"
    [ -f "$CT_CONFIG" ] && [ ! -L "$CT_CONFIG" ] || { echo 'New container configuration cannot be verified.' >&2; exit 1; }
    CGROUP_DEVICES=lxc.cgroup2.devices.allow
    [ "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs ] || CGROUP_DEVICES=lxc.cgroup.devices.allow
    printf '%s: c 10:200 rwm\nlxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file\n' "$CGROUP_DEVICES" >> "$CT_CONFIG"
fi
if [ -n "$GPU_ID" ]; then
    python3 "$GPU_HELPER" --gpu "$GPU_ID" --ctid "$CTID" --inventory "$GPU_WORK/inventory.json"
fi
pct start "$CTID"
if [ -n "$GPU_ID" ]; then
    pct push "$CTID" "$GPU_WORK/inventory.json" /etc/mediahub-gpus.json --perms 0600
fi
pct exec "$CTID" -- sh -c 'test -c /dev/net/tun && test -r /dev/net/tun && test -w /dev/net/tun' || {
    echo 'The new MediaHub LXC cannot access TUN. Installation stopped before installing apps; inspect its device configuration.' >&2
    exit 1
}
pct exec "$CTID" -- sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y python3 iproute2'
pct exec "$CTID" -- python3 -c 'import os; fd=os.open("/dev/net/tun",os.O_RDWR); os.close(fd)' || {
    echo 'TUN is mounted but cannot be opened by the new LXC. Check the host device policy before continuing.' >&2
    exit 1
}
DATA_VOLUME=$(pct config "$CTID" | awk '/^mp0:/ {split($2, parts, ","); print parts[1]}')
DATA_DEVICE=$(pvesm path "$DATA_VOLUME")
DATA_UUID=$(blkid -s UUID -o value "$DATA_DEVICE" 2>/dev/null || true)
if [ -z "$DATA_UUID" ] && [ -d "$DATA_DEVICE" ] && command -v zfs >/dev/null; then
    DATA_FSTYPE=$(findmnt -n -o FSTYPE --target "$DATA_DEVICE")
    DATA_DATASET=$(findmnt -n -o SOURCE --target "$DATA_DEVICE")
    if [ "$DATA_FSTYPE" = zfs ]; then
        DATA_GUID=$(zfs get -H -o value guid "$DATA_DATASET")
        [[ "$DATA_GUID" =~ ^[0-9]+$ ]] && DATA_UUID="zfs:$DATA_GUID"
    fi
fi
[ -n "$DATA_UUID" ] || { echo 'The new data volume has no verifiable filesystem UUID or ZFS dataset GUID. Use a supported block-volume or ZFS dataset storage; the new guest was kept for inspection.' >&2; exit 1; }
pct exec "$CTID" -- python3 -c 'import json,os,sys; from pathlib import Path; p=Path("/etc/mediahub-storage-identities.json"); source=json.loads(os.popen("findmnt --json --target /storage --output SOURCE,TARGET").read())["filesystems"][0]; assert source["target"]=="/storage"; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,json.dumps([{"path":"/storage","source":source["source"],"uuid":sys.argv[1]}]).encode()); os.close(fd)' "$DATA_UUID"
pct exec "$CTID" -- bash -s <<'MEDIAHUB_GUEST'
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git python3 openssl iproute2
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
printf 'deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian trixie stable\n' > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
INSTALL_SOURCE=$(mktemp -d /var/tmp/mediahub-install.XXXXXXXX)
git clone --depth 1 https://github.com/miklas206/mediahub-platform.git "$INSTALL_SOURCE/source"
ADDRESS=$(ip -4 -o addr show dev eth0 scope global | awk '{split($4, address, "/"); print address[1]; exit}')
[ -n "$ADDRESS" ] || { echo 'DHCP did not provide an IPv4 address.' >&2; exit 1; }
GPU_ARGS=()
if [ -f /etc/mediahub-gpus.json ]; then
    python3 "$INSTALL_SOURCE/source/scripts/gpu_setup.py" --inventory /etc/mediahub-gpus.json
    GPU_ARGS=(--gpu-policy /etc/mediahub-gpus.json)
fi
python3 "$INSTALL_SOURCE/source/scripts/install_linux.py" --root /opt/mediahub --lan-ip "$ADDRESS" \
    --storage /storage --storage-identities /etc/mediahub-storage-identities.json --yes "${GPU_ARGS[@]}"
python3 - "$INSTALL_SOURCE" <<'MEDIAHUB_INSTALL_CLEANUP'
import re, shutil, sys
from pathlib import Path
root = Path(sys.argv[1])
if (root.parent != Path('/var/tmp') or not re.fullmatch(r'mediahub-install\.[A-Za-z0-9]{8}', root.name)
        or root.is_symlink() or root.resolve() != root):
    raise SystemExit('Unsafe installation workspace; cleanup stopped.')
shutil.rmtree(root)
MEDIAHUB_INSTALL_CLEANUP
MEDIAHUB_GUEST
printf 'New MediaHub LXC: %s. Public CA: pct pull %s /opt/mediahub/trust/ca.pem /root/mediahub-public-ca.pem\n' "$CTID" "$CTID"
printf 'Create your administrator in the setup wizard. Keep the server private until setup is claimed.\n'
