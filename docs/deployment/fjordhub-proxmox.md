# FjordHub Proxmox storage discovery

MediaHub's LXC installer configures FjordHub with the actual Proxmox node,
node address and allocated CTID. Previously it only configured the application's
port and data directory, leaving the Proxmox credentials missing and the CTID
at FjordHub's default of 1000.

The installer creates a unique `mediahub-fjordhub-<CTID>-<suffix>@pve` account,
with a privilege-separated `inventory` API token. Both receive the built-in
**PVEAuditor** role at `/`, propagated across the cluster. This is read-only
cluster inventory access; it does not authorize disk, mount or guest changes.
The token is generated on Proxmox, transferred through stdin, and stored in
FjordHub's mode-0600 `.env`. It is not returned to MediaHub or printed in job logs.
An unused account is removed if setup fails before saving the credentials.

The connection uses FjordHub's existing `PROXMOX_VERIFY_SSL=false` default for
self-signed Proxmox certificates. Use a trusted private network. For verified
TLS, configure a certificate trusted by the FjordHub container, set the matching
hostname in `PROXMOX_API_URL`, and set `PROXMOX_VERIFY_SSL=true` in `.env`.

After recreating the FjordHub service, setup checks all five inventory endpoints
from inside the application container. An authentication, routing or permissions
failure makes deployment fail instead of reporting a healthy application as a
working Proxmox integration. It preserves the LXC and application data.

## Repair an existing MediaHub installation

If the installer stopped with `Missing node IP` after the guest became healthy,
the application is already installed. The current helper uses Proxmox's native
node-address resolver, including hostname resolution when membership metadata
does not contain an IP. Update MediaHub and run the helper below for the existing
CTID; do not rerun the LXC creation installer. An unresolvable hostname still
stops setup before credentials are created; check the node's `/etc/hosts`/DNS.

The connection form uses the latest guest's health-checked URL even when the
subsequent Proxmox configuration fails. If that deployment has no valid URL,
the form stays empty instead of linking to an older guest or configured default.

Update FjordHub and FjordFlix first: old FjordHub versions do not have the
`/api/hub/apps/fjordflix/library` endpoint. Missing/old endpoints may appear as a
login/SSO error in FjordFlix, separately from missing Proxmox credentials.

From a checkout of this version of MediaHub on the **Proxmox host**, run as root:

```bash
bash scripts/configure-fjordhub-proxmox.sh 210 /opt/fjordhub
```

Replace `210` and `/opt/fjordhub` with the existing container ID and source path
inside it. The container must be running. The helper does not reinstall FjordHub
or recreate disks. It refuses to overwrite existing nonempty Proxmox credentials.
If credentials were saved but verification failed, fix routing/firewall/permissions
or service startup and inspect the existing configuration; do not reinstall the LXC.
The account name is recorded in the output and in `.env`'s `PROXMOX_TOKEN_ID`.
On decommissioning, remove that dedicated account with `pveum user delete USERID`.
MediaHub's runtime-only removal intentionally does not delete it or application data.

## Discovery and media access

The new app-data disk is an empty managed volume. Selecting its storage pool
does not expose that pool's existing files. A block storage such as `local-lvm`
is not itself a browsable media folder.

Share the chosen existing host folders into the LXC using explicit read-only
bind mounts, then expose those mount paths to FjordFlix and add each folder in
its library settings. Indexing and streaming read the original files; this
installer does not copy, format or automatically share existing media storage.

Automated tests cover template parity, script syntax, environment preservation,
the actual CTID/node, credential handling and failed inventory checks. A live
Proxmox host is still required for end-to-end validation of `pct`, ACL creation,
container networking and the resulting FjordFlix library UI.
