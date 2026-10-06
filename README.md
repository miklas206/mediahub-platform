# MediaHub

**A local-first home for your media apps.** MediaHub 0.4.5 brings Plex,
protected downloads, storage, health and everyday controls into one interface.
Dark mode, responsive layouts and simple controls come first; technical host and
runtime details stay in Advanced mode.

MediaHub is an early self-hosted release, not a promise of perfect anonymity or
an audited appliance. Review the security and operational limits before use.

## What works

- Guided administrator setup, password login, TOTP QR enrollment, single-use
  recovery codes, session management, CSRF protection and login throttling.
- Direct HTTPS and independently authenticated, certificate-validated Agents.
- Dashboard, real CPU/RAM/storage/app health, logs and activity.
- Logical storage mappings: apps can use the same files through different host
  paths. Media is not silently moved, copied, formatted or deleted.
- Managed Plex installation, read-only libraries, streams, resources,
  start/stop/restart and image update with configuration rollback.
- Optional isolated Seedbox: Proton WireGuard, country/server selection,
  fail-closed networking, NAT-PMP renewal and automatic qBittorrent port updates.
- Add magnet/file, view progress/speeds/ratio/seeds/peers, pause, resume, recheck
  and remove a torrent **without deleting downloaded files**.
- Encrypted Core, Plex and Seedbox configuration exports with offline verification
  and non-overwriting restore staging. Media backup remains separate.
- Scheduled release checks, an update badge and a rollback-protected Core/Agent
  updater that accepts only complete digest-verified GitHub Release bundles.
- Optional assisted Cloudflare Tunnel monitoring with clear tunnel, connector
  session and published-route counts, private metrics, public-route probes and
  official cloudflared release checks without granting account or tunnel control.
- Optional read-only FjordHub Access Token adapter. No dependency on FjordHub,
  Cloudflare, a public address, or an exposed torrent-client WebUI.

Sonarr, Radarr, Jellyfin and other catalog entries are extension candidates, not
claims of working installers. The first supported app workflows are Plex and Seedbox.

## Install

**Start here: [Guided installation, step by step](docs/install.md).**

The guide explains where to run commands, what each installer question means,
how to open MediaHub securely, and what to do when something goes wrong.
You do not need to write code.

**Choose your platform in the guide:** Windows with Docker Desktop, or Proxmox.
The Windows script builds and starts Core and Agent using new Docker volumes.
The Proxmox script creates one new MediaHub LXC and installs Docker inside it.
Both configure HTTPS and provide the browser address and setup-token command.
Neither connects, formats or migrates an existing media drive.

The guided bootstrap currently installs MediaHub Core and its local Agent;
app policies and host-driven updating are not configured yet. The intended
layout runs apps as Docker services on the same MediaHub host, not separate
Proxmox guests; Cloudflare may remain separate. Local Seedbox support is still
being prepared, not a completed migration feature. The advanced Linux installer
retains its existing separate-Seedbox-host requirement.

**Already using MediaHub?** Use its Updates page instead. The new-install guide
does not upgrade, migrate or replace an existing installation. It does not
format media drives or change existing media-folder permissions, but it does
create installation files and new data folders. Back up irreplaceable media.

## Phone home-screen app

Open MediaHub's HTTPS address in Safari on iPhone or Chrome on Android, then use
**Add to Home Screen** (or **Install app**, when offered). The shortcut uses the
MediaHub logo and opens in a standalone window. An internet/LAN connection to
Core is still required; this does not add offline support.

If an existing shortcut shows a letter instead of the logo, remove that shortcut
and add it again after updating MediaHub. Phones can cache the old icon.

The PNG home-screen icons are generated from `frontend/public/favicon.svg` with
`node frontend/scripts/generate-webapp-icons.mjs` (requires the frontend's existing
Playwright dependency and Chrome). Regenerate them when changing the logo.

## Architecture

```text
Browser ── HTTPS ── MediaHub Core (UI, accounts, mappings, events)
                         │
                         ├─ private HTTPS ─ Local Agent ─ Plex
                         │                     └─ approved media, read only
                         └─ private HTTPS ─ Seedbox Agent ─ VPN + qBittorrent
                                               └─ shared Downloads, read/write
```

Only policy-scoped Agents control runtime resources. Core does not receive the
Docker socket. Agent access to Docker is privileged in effect: protect the host,
Agent token, CA and pairing authority accordingly. Keep Core single-worker;
its request throttling and event bus are process-local.

## Daily use

Open **Apps → Plex** for libraries, playback status and updates. Open
**Apps → Seedbox** for VPN and torrent controls. Downloads and media are separate
logical mappings of the real filesystem, not duplicate libraries. Advanced
qBittorrent access stays authenticated and private, optionally through a
localhost-only SSH tunnel.

VPN failure blocks torrent traffic. The internet provider can still observe VPN
traffic volume and its endpoint; a VPN does not make a server untraceable.
Neither Plex account entitlements nor remote streaming are bypassed by MediaHub.

## Maintenance and limitations

Plex has a UI update/rollback workflow. Core and local Agent updates use complete
digest-verified release bundles, a root-owned trusted image policy, a configuration
snapshot, health verification and automatic rollback. Release checks can be
scheduled, but installation always requires administrator approval. Seedbox/VPN
updates remain separately coordinated and fail-closed. No upstream MediaHub GitHub
release repository is assumed; version checks report that truthfully. Certificates
require operator-managed renewal before their expiry.

Configuration exports do not back up media, deployment TLS identities or whole
servers. App exports are bounded to 48 MiB; Core to 64 MiB. Restore stages a new
offline directory, not a live overwrite. Keep independent media backups.

Proton is the supported guided VPN provider. Other provider adapters must pass
the same tunnel, port-forwarding, storage-failure and recovery checks before
they are advertised as supported. Hardware transcoding depends on host GPU
delegation, codecs and Plex entitlements; it is not automatically enabled.

## Optional future public access

LAN operation is independent of a public URL. `MEDIAHUB_PUBLIC_URL`, explicit
allowed origins, trusted proxies, forwarded headers and secure cookie handling
support later deployment behind a reviewed reverse proxy or Cloudflare Tunnel.
Cloudflare is optional. No installer opens router ports, creates DNS records or
starts a public tunnel. SSE proxies must allow long-lived unbuffered responses.
Use a dedicated origin; subdirectory deployment is not supported.

## Development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
pytest
```

Use `.env.example` for loopback development; LAN credentials require HTTPS.
Instance configuration, keys, archives and private acceptance reports belong
outside the public source tree (`.qa/` is ignored). Never publish that directory.

## Documentation

- [Install](docs/install.md) · [Storage](docs/storage.md) · [Shared storage](docs/shared-storage.md)
- [Backups](docs/backups.md) · [Certificate lifecycle](docs/certificates.md)
- [Plex operations](docs/operations/plex-runtime.md) · [Seedbox](docs/apps/seedbox.md) · [Seedbox daily use](docs/operations/seedbox-daily-use.md)
- [Platform updates](docs/operations/platform-updates.md)
- [App Store](docs/app-system/app-store.md) · [Cloudflare Tunnel](docs/operations/cloudflared-monitoring.md)
- [FjordHub integration](docs/integrations/fjordhub.md) · [Architecture](docs/architecture/README.md)
- [FjordHub Proxmox storage discovery and existing-install repair](docs/deployment/fjordhub-proxmox.md)
- [Security policy](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Release notes](CHANGELOG.md)

Screenshots: place reviewed, anonymized dashboard/app screenshots in
`docs/screenshots/`. Do not include IPs, usernames, torrent names or private media.

## License

Apache-2.0 for MediaHub's own code. Third-party applications, images and
dependencies retain their own licenses and terms.


### FjordHub installation from MediaHub

The App Store FjordHub guide recommends **4 CPU cores and 10 GiB RAM (10240 MiB)**.
Choose a new unprivileged Debian 13 Proxmox LXC or an existing fresh Debian 12/13 host,
then review storage, bridge, networking and paths. In the Install step enter the target
server's private IPv4 address, SSH port and root SSH password. Use **Check SSH connection**,
compare the displayed SHA256 fingerprint with the server console (for the default Ed25519
host key: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`), trust that identity,
and click **Create LXC and install FjordHub** or **Install FjordHub**. The SSH service must
permit root password login; SSH-key authentication is not offered by this initial flow.

The installer uses the same reviewed template as the manual command preview. It does not
accept executable scripts from API callers. Passwords are used in memory for that job and
are not persisted. This administrator-only action creates the chosen container/disks or
installs on the chosen Debian host; the commands can still be copied/downloaded instead.

The console shows the latest 300 redacted output lines. You can leave the page and return;
the job continues in Core. Keep Core running during installation. If Core restarts, SSH
fails or the one-hour limit is reached, status requires inspection: remote work may still
be running. Nothing is retried or deleted automatically. Check the target and any created
LXC before explicitly acknowledging a fresh attempt. On success, open FjordHub on its guest
IP and chosen port to create its administrator and connect its read-only Access Token.


### Agent write access on mergerfs

The Agent image uses UID `10001` and primary GID `1000` from v0.4.26.
This preserves access to its existing private state while making the shared media group
available to mergerfs as the primary group, rather than relying only on Docker supplementary
group resolution. The generated production Compose configuration inherits this image default;
a normal Agent image update applies it without changing ownership or permissions of existing
media. Custom Compose configurations with an explicit `user:` override must be reviewed by
the operator because that override takes precedence over the image's default user.
