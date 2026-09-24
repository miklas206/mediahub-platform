# MediaHub

**A local-first home for your media apps.** MediaHub 0.3.0 brings Plex,
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
- Optional read-only FjordHub Access Token adapter. No dependency on FjordHub,
  Cloudflare, a public address, or an exposed torrent-client WebUI.

Sonarr, Radarr, Jellyfin and other catalog entries are extension candidates, not
claims of working installers. The first supported app workflows are Plex and Seedbox.

## Install

Use a **new** Debian/Ubuntu Docker host with Compose v2, Python 3, OpenSSL,
systemd/cgroup v2 and a separately mounted data filesystem. On Proxmox, use a
guest; never install this stack directly on the hypervisor.

```sh
sudo sh install.sh
```

The interactive installer creates a new deployment, builds pinned source images,
creates private HTTPS identities and prints the browser URL and local setup-token
command. It never formats disks or changes existing media permissions. Import
only the generated public CA on your client; never bypass certificate validation.
Complete the browser wizard and optionally install Plex. Seedbox requires a
separate prepared and securely paired host with approved Downloads storage.

See [installation prerequisites and procedure](docs/install.md). The installer
does not provision a Proxmox VM, install Docker, or automatically migrate an old
server. Those host-level steps require deliberate administration.

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

Plex has a UI update/rollback workflow. Core and Seedbox deployment images remain
pinned and use reviewed deployment updates. No upstream MediaHub GitHub release
repository is assumed; version checks report that truthfully. Automatic patching
is disabled. Certificates require operator-managed renewal before their expiry.

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
- [Plex operations](docs/operations/plex-runtime.md) · [Seedbox](docs/apps/seedbox.md)
- [Platform updates](docs/operations/platform-updates.md)
- [FjordHub integration](docs/integrations/fjordhub.md) · [Architecture](docs/architecture/README.md)
- [Security policy](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Release notes](CHANGELOG.md)

Screenshots: place reviewed, anonymized dashboard/app screenshots in
`docs/screenshots/`. Do not include IPs, usernames, torrent names or private media.

## License

Apache-2.0 for MediaHub's own code. Third-party applications, images and
dependencies retain their own licenses and terms.
