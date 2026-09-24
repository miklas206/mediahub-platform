# Install MediaHub

## Supported baseline

A fresh Debian/Ubuntu Docker host, Python 3, OpenSSL, Docker Engine with Compose
v2, systemd and cgroup v2. Use a VM or a prepared unprivileged LXC with Docker
nesting. **Never run the installer on a Proxmox hypervisor or an existing app's
container.** Do not share a writable raw disk between guests.

Mount an existing data filesystem first. It must have a stable UUID and be
separate from the OS/root disk. MediaHub does not format or repartition disks.
For LXC bind-mounted storage, the host must provide the read-only device snapshot
described in `docs/deployment/devices.md`; the container must see matching mount identity.
Existing media permissions are not changed by the installer.

From a reviewed source checkout:

```sh
sudo sh install.sh
```

The installer asks for the LAN address, mounted storage and media/app-data
folders. It builds Core and Agent, generates per-installation TLS identities,
creates only new folders, configures strict resource/swap limits, and starts
MediaHub. Docker, the OS and the storage mount must already be prepared; the
script does not silently install host packages or change firewall rules.

Import the generated **public CA certificate only** into your client trust
store, then open the printed HTTPS URL. Never disable certificate verification.
Retrieve the one-time setup token using the printed local command. The browser
wizard creates your administrator, offers TOTP, registers storage and lets you
install Plex. A Plex claim token links the new server to your account.

Seedbox is optional. Prepare a separate host with the scoped Agent/NFS policy,
pair it over verified HTTPS and register its Downloads mapping. Then choose
**Apps → Seedbox → Install**, select that host, and follow the guided Proton
WireGuard/P2P/NAT-PMP and client-credential steps. Other providers are not offered
as supported provisioning workflows until their adapters pass equivalent tests.

## Persistence and recovery

The generated `compose.json` pins the exact built image IDs. Keep the
installation root and data filesystem persistent. Missing media storage blocks
Plex; missing Downloads storage blocks Seedbox. Before restarting a Docker host,
ensure its data mount is configured to start before Docker and guard against a
local-directory fallback. See the storage and Seedbox operations documents.

Read [Backups](backups.md), [Certificates](certificates.md) and
[Security](../SECURITY.md) before using the installation for irreplaceable data.
Host setup and remote Seedbox enrollment remain administrator tasks; the browser
does not provision a Proxmox VM or guess which disk is safe to mount.

## Updates

Plex update/check/rollback is available in MediaHub. MediaHub Core and Seedbox
deployment images are deliberately pinned. Before updating them, export verified
configuration backups, record the current image IDs, build the reviewed release,
and replace only the relevant deployment image. Verify HTTPS, storage and app
health; roll back to the recorded image/config if checks fail. Do not use
unattended `latest` image replacement for the VPN namespace or app databases.
An upstream MediaHub release repository has not been assigned to this checkout;
the UI explicitly reports that rather than inventing an available version.
