#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077
[ "$(id -u)" -eq 0 ] && [ -d /etc/pve ] && command -v pct >/dev/null || { echo 'Open the Proxmox node Shell as root.' >&2; exit 1; }
[ "$(dpkg --print-architecture)" = amd64 ] || { echo 'This installer currently supports amd64 Proxmox hosts.' >&2; exit 1; }
read -r -p 'New container ID (press Enter for the next free ID): ' CTID
CTID=${CTID:-$(pvesh get /cluster/nextid)}
[[ "$CTID" =~ ^[1-9][0-9]{2,8}$ ]] || { echo 'Invalid container ID.' >&2; exit 1; }
pvesh get /cluster/nextid --vmid "$CTID" >/dev/null
read -r -p 'Container storage [local-lvm]: ' STORAGE
STORAGE=${STORAGE:-local-lvm}
read -r -p 'Template storage [local]: ' TEMPLATE_STORAGE
TEMPLATE_STORAGE=${TEMPLATE_STORAGE:-local}
read -r -p 'Network bridge [vmbr0]: ' BRIDGE
BRIDGE=${BRIDGE:-vmbr0}
for value in "$STORAGE" "$TEMPLATE_STORAGE" "$BRIDGE"; do
    [[ "$value" =~ ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$ ]] || { echo 'Invalid storage or bridge name.' >&2; exit 1; }
done
ip link show "$BRIDGE" >/dev/null
pvesm status --storage "$STORAGE" --content rootdir
pvesm status --storage "$TEMPLATE_STORAGE" --content vztmpl
printf '%s\n' "New LXC $CTID: 6 cores, 16384 MiB RAM, 64 GiB NEW system disk, DHCP."
printf '%s\n' 'Docker data will live on the NEW system disk. No existing disks or media folders are attached.'
printf '%s\n' 'This installs Core and Agent, not an existing Seedbox migration. Check storage capacity above before accepting.'
read -r -p 'Type INSTALL to create this new container: ' CONFIRM
[ "$CONFIRM" = INSTALL ] || exit 0
trap 'echo "If a step failed, inspect the new container before retrying. Existing guests/media are not cleaned up." >&2' ERR
pveam update
TEMPLATE=$(pveam available --section system | awk '$2 ~ /^debian-13-standard_.*_amd64.tar.zst$/ {print $2}' | sort -V | tail -n 1)
[ -n "$TEMPLATE" ] || { echo 'No Debian 13 template found.' >&2; exit 1; }
pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
pvesh get /cluster/nextid --vmid "$CTID" >/dev/null
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" --hostname mediahub-guided \
    --unprivileged 1 --features nesting=1,keyctl=1 --cores 6 --memory 16384 --swap 0 \
    --rootfs "$STORAGE:64" --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp,ip6=manual,firewall=1" --onboot 1
pct start "$CTID"
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
git clone --depth 1 https://github.com/miklas206/mediahub-platform.git /opt/mediahub-source
ADDRESS=$(ip -4 -o addr show dev eth0 scope global | awk '{split($4, address, "/"); print address[1]; exit}')
[ -n "$ADDRESS" ] || { echo 'DHCP did not provide an IPv4 address.' >&2; exit 1; }
bash /opt/mediahub-source/scripts/install-docker.sh /opt/mediahub-guided "$ADDRESS"
MEDIAHUB_GUEST
printf 'New MediaHub LXC: %s. Public CA: pct pull %s /opt/mediahub-guided/ca.pem /root/mediahub-public-ca.pem\n' "$CTID" "$CTID"
printf 'Private setup token: pct exec %s -- docker compose -f /opt/mediahub-guided/compose.json exec -T core mediahub bootstrap-token\n' "$CTID"