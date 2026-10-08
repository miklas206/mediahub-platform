#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077

INSTALL_ROOT=${1:-/opt/mediahub-guided}
ADDRESS=${2:-127.0.0.1}
[[ "$INSTALL_ROOT" =~ ^/(opt|srv)/[a-zA-Z0-9_-]+$ ]] || { echo 'Use a new folder directly under /opt or /srv.' >&2; exit 1; }
[ "$(realpath -m "$INSTALL_ROOT")" = "$INSTALL_ROOT" ] && [ ! -e "$INSTALL_ROOT" ] && [ ! -L "$INSTALL_ROOT" ] || { echo 'Installation path exists or traverses symlinks; stopping.' >&2; exit 1; }
[ "$(id -u)" -eq 0 ] && [ ! -d /etc/pve ] || { echo 'Run inside a Linux Docker host, never directly on Proxmox.' >&2; exit 1; }
[ "$(docker info --format '{{.OSType}}')" = linux ] || { echo 'A running Linux Docker engine is required.' >&2; exit 1; }
docker compose version
python3 -c 'import ipaddress,sys; address=ipaddress.IPv4Address(sys.argv[1]); sys.exit(0 if (address.is_private or address.is_loopback) and not address.is_unspecified and not address.is_link_local else "Use a local IPv4 address")' "$ADDRESS"
[ -z "$(docker volume ls --format '{{.Name}}' | grep '^mediahub-guided-' || true)" ] || { echo 'Existing guided volumes found; stopping.' >&2; exit 1; }
[ -z "$(docker ps -a --filter label=com.docker.compose.project=mediahub-guided --format '{{.ID}}')" ] || { echo 'Existing guided containers found; stopping.' >&2; exit 1; }
[ -z "$(ss -H -ltn 'sport = :18765')" ] || { echo 'Port 18765 is already in use.' >&2; exit 1; }
mkdir "$INSTALL_ROOT"
SOURCE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [ ! -f "$SOURCE_ROOT/docker/Dockerfile" ]; then
    git clone --depth 1 https://github.com/miklas206/mediahub-platform.git "$INSTALL_ROOT/source"
    SOURCE_ROOT="$INSTALL_ROOT/source"
fi
docker build -f "$SOURCE_ROOT/docker/Agent.Dockerfile" -t mediahub-guided-agent:local "$SOURCE_ROOT"
docker build -f "$SOURCE_ROOT/docker/Dockerfile" -t mediahub-guided-core:local "$SOURCE_ROOT"
MOUNTS=()
for volume in data state storage credentials core-tls agent-tls trust authority; do
    docker volume create --label mediahub.guided=true "mediahub-guided-$volume"
    MOUNTS+=(--mount "type=volume,src=mediahub-guided-$volume,dst=/bootstrap/$volume")
done
docker run --rm --network none --user 0 --entrypoint python "${MOUNTS[@]}" \
    --mount "type=bind,src=$SOURCE_ROOT/scripts/docker_bootstrap.py,dst=/bootstrap.py,readonly" \
    --mount "type=bind,src=$INSTALL_ROOT,dst=/output" mediahub-guided-agent:local /bootstrap.py --address "$ADDRESS"
docker compose -f "$INSTALL_ROOT/compose.json" config --quiet
docker compose -f "$INSTALL_ROOT/compose.json" up -d --wait --wait-timeout 180
printf 'MediaHub and Agent passed HTTPS health checks. Open https://%s:18765 after importing the public CA.\n' "$ADDRESS"
printf 'Public CA only: %s/ca.pem (verify the printed SHA-256 fingerprint).\n' "$INSTALL_ROOT"
printf 'Create your administrator in the setup wizard. Keep the server private until setup is claimed.\n'
printf '%s\n' 'Certificates expire in 90 days. Keep all volumes; never use down -v or volume prune.'
printf '%s\n' 'Core and Agent are installed. Media apps, host updates and production media mappings need separate preparation.'