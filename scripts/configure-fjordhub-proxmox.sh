#!/usr/bin/env bash
# Run on the Proxmox host: bash configure-fjordhub-proxmox.sh CTID /opt/fjordhub
set +x
set -Eeuo pipefail
umask 077
CTID=${1:?Supply the existing FjordHub CTID}
INSTALL_DIR=${2:-/opt/fjordhub}
[[ "$CTID" =~ ^[0-9]+$ ]] && [[ "$INSTALL_DIR" =~ ^/(opt|srv|mnt)/[a-zA-Z0-9_./-]+$ ]] || exit 1
[ "$(id -u)" -eq 0 ] && [ -d /etc/pve ] || { echo 'Run on the Proxmox host as root.' >&2; exit 1; }
NODE=$(basename "$(readlink -f /etc/pve/local)")
API_IP=$(perl -MJSON::PP -0777 -e 'my $node=shift; my $m=decode_json(<>); print $m->{nodelist}{$node}{ip} // die "Missing node IP\n"' "$NODE" /etc/pve/.members)
[[ "$API_IP" == *:* ]] && API_IP="[$API_IP]"
API_URL="https://$API_IP:8006"
# Refuse accidental replacement of an administrator's existing credentials.
pct exec "$CTID" -- python3 -c '
import pathlib, sys
p = pathlib.Path(sys.argv[1]) / ".env"
if not p.is_file() or p.is_symlink():
    sys.exit("Expected an existing regular FjordHub .env file")
for line in p.read_text().splitlines():
    key, _, value = line.partition("=")
    if key in ("PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET") and value.strip().strip(chr(34)).strip(chr(39)):
        sys.exit("Proxmox credentials already configured; inspect them instead of replacing them")
' "$INSTALL_DIR"
ACCOUNT="mediahub-fjordhub-${CTID}-$(cut -c1-8 /proc/sys/kernel/random/uuid)@pve"
TOKEN_FILE=$(mktemp)
CREATED=0
INSTALLED=0
cleanup() {
    result=$?
    rm -f -- "$TOKEN_FILE"
    if [ "$CREATED" = 1 ] && [ "$INSTALLED" = 0 ]; then
        pveum user delete "$ACCOUNT" >/dev/null || echo "Remove unused Proxmox account manually: $ACCOUNT" >&2
    fi
    if [ "$result" != 0 ] && [ "$INSTALLED" = 1 ]; then
        echo "Credentials saved for $ACCOUNT; check FjordHub Compose startup. Do not reinstall the LXC." >&2
    fi
    exit "$result"
}
trap cleanup EXIT
pveum user add "$ACCOUNT" --comment "FjordHub inventory for LXC $CTID (MediaHub)"
CREATED=1
# Both the user and privilege-separated token must have read-only permissions.
# Root propagation is needed to discover storage and the disks/directory endpoint.
pveum acl modify / --users "$ACCOUNT" --roles PVEAuditor --propagate 1
pveum user token add "$ACCOUNT" inventory --privsep 1 --output-format json >"$TOKEN_FILE"
pveum acl modify / --tokens "$ACCOUNT!inventory" --roles PVEAuditor --propagate 1
pct exec "$CTID" -- python3 -c '
import json, os, pathlib, re, sys
token = json.load(sys.stdin)
values = {
    "PROXMOX_API_URL": sys.argv[2], "PROXMOX_NODE": sys.argv[3],
    "PROXMOX_VMID": sys.argv[4], "PROXMOX_TOKEN_ID": token["full-tokenid"],
    "PROXMOX_TOKEN_SECRET": token["value"], "PROXMOX_VERIFY_SSL": "false",
}
if not all(re.fullmatch(r"[a-zA-Z0-9_@!.:/\[\]-]+", v) for v in values.values()):
    sys.exit("Unexpected Proxmox connection value")
p = pathlib.Path(sys.argv[1]) / ".env"
lines = [s for s in p.read_text().splitlines() if s.partition("=")[0] not in values]
tmp = p.with_name(".env.mediahub-proxmox")
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines + [k + "=" + v for k, v in values.items()]) + "\n")
    tmp.replace(p)
finally:
    tmp.unlink(missing_ok=True)
' "$INSTALL_DIR" "$API_URL" "$NODE" "$CTID" <"$TOKEN_FILE"
INSTALLED=1
rm -f -- "$TOKEN_FILE"
pct exec "$CTID" -- bash -c 'cd -- "$1"; docker compose config --quiet && docker compose up -d --wait --wait-timeout 180 fjordhub' bash "$INSTALL_DIR"
# Verify from the application container, including credentials, routing and ACLs.
pct exec "$CTID" -- bash -c 'cd -- "$1"; docker compose exec -T fjordhub python -' bash "$INSTALL_DIR" <<'MEDIAHUB_CHECK'
import os, sys
import requests
from urllib.parse import quote
requests.packages.urllib3.disable_warnings()
node = quote(os.environ['PROXMOX_NODE'], safe='')
ctid = os.environ['PROXMOX_VMID']
headers = {'Authorization': 'PVEAPIToken=' + os.environ['PROXMOX_TOKEN_ID'] + '=' + os.environ['PROXMOX_TOKEN_SECRET']}
for path in ('/storage', f'/nodes/{node}/storage', f'/nodes/{node}/lxc/{ctid}/config',
             f'/nodes/{node}/disks/list', f'/nodes/{node}/disks/directory'):
    try:
        response = requests.get(os.environ['PROXMOX_API_URL'] + '/api2/json' + path,
                                headers=headers, verify=False, timeout=20)
        response.raise_for_status()
        if 'data' not in response.json():
            raise ValueError('Missing API data')
    except Exception:
        sys.exit('Proxmox inventory check failed at ' + path + '; check routing, firewall and API permissions.')
print('Proxmox storage, disks and LXC mount discovery verified.')
MEDIAHUB_CHECK
echo "Read-only Proxmox account: $ACCOUNT"
echo 'Existing media folders still require explicit read-only mounts into the LXC and FjordFlix.'
