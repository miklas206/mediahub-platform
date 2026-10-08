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
read -r -p 'Container hostname [mediahub]: ' HOSTNAME
HOSTNAME=${HOSTNAME:-mediahub}
[[ "$HOSTNAME" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || { echo 'Invalid hostname.' >&2; exit 1; }
for value in "$STORAGE" "$TEMPLATE_STORAGE" "$BRIDGE"; do
    [[ "$value" =~ ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$ ]] || { echo 'Invalid storage or bridge name.' >&2; exit 1; }
done
ip link show "$BRIDGE" >/dev/null
pvesm status --storage "$STORAGE" --content rootdir
pvesm status --storage "$TEMPLATE_STORAGE" --content vztmpl
printf '%s\n' "New LXC $CTID ($HOSTNAME): 6 cores, 16384 MiB RAM, 32 GiB NEW system disk and 32 GiB NEW data disk, DHCP."
printf '%s\n' 'App storage is prepared on the NEW data disk. No existing disks or media folders are attached.'
printf '%s\n' 'This installs Core and Agent, not an existing Seedbox migration. Check storage capacity above before accepting.'
read -r -p 'Type INSTALL to create this new container: ' CONFIRM
[ "$CONFIRM" = INSTALL ] || exit 0
trap 'echo "If a step failed, inspect the new container before retrying. Existing guests/media are not cleaned up." >&2' ERR
pveam update
TEMPLATE=$(pveam available --section system | awk '$2 ~ /^debian-13-standard_.*_amd64.tar.zst$/ {print $2}' | sort -V | tail -n 1)
[ -n "$TEMPLATE" ] || { echo 'No Debian 13 template found.' >&2; exit 1; }
pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
pvesh get /cluster/nextid --vmid "$CTID" >/dev/null
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" --hostname "$HOSTNAME" \
    --unprivileged 1 --features nesting=1,keyctl=1 --cores 6 --memory 16384 --swap 0 \
    --rootfs "$STORAGE:32" --mp0 "$STORAGE:32,mp=/storage,backup=1" \
    --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp,ip6=manual,firewall=1" --onboot 1
pct start "$CTID"
DATA_VOLUME=$(pct config "$CTID" | awk '/^mp0:/ {split($2, parts, ","); print parts[1]}')
DATA_DEVICE=$(pvesm path "$DATA_VOLUME")
DATA_UUID=$(blkid -s UUID -o value "$DATA_DEVICE")
[ -n "$DATA_UUID" ] || { echo 'New data disk UUID unavailable.' >&2; exit 1; }
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
git clone --depth 1 https://github.com/miklas206/mediahub-platform.git /opt/mediahub-source
ADDRESS=$(ip -4 -o addr show dev eth0 scope global | awk '{split($4, address, "/"); print address[1]; exit}')
[ -n "$ADDRESS" ] || { echo 'DHCP did not provide an IPv4 address.' >&2; exit 1; }
python3 /opt/mediahub-source/scripts/install_linux.py --root /opt/mediahub --lan-ip "$ADDRESS" \
    --storage /storage --storage-identities /etc/mediahub-storage-identities.json --yes
MEDIAHUB_GUEST
printf 'New MediaHub LXC: %s. Public CA: pct pull %s /opt/mediahub/trust/ca.pem /root/mediahub-public-ca.pem\n' "$CTID" "$CTID"
printf 'Create your administrator in the setup wizard. Keep the server private until setup is claimed.\n'