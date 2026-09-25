# Changelog

## Unreleased

## 0.4.4 - 2026-09-25

- Added an assisted, least-privilege Cloudflare Tunnel monitoring setup that
  distinguishes one tunnel from its published routes and redundant connector
  sessions. It supports route-only checks or private Prometheus metrics without
  receiving an account API token or tunnel token.
- Made app submenu selection fill the sidebar row and aligned update cards with
  consistent rows, actions, messages and expandable advanced settings.
- Successful update checks with no available releases now automatically resolve
  stale update notifications while preserving their activity audit entries.

## 0.4.3 - 2026-09-25

- Fixed the Plex remote-reachability status check when the Agent correctly runs
  on an internal-only control network. The check now uses a short-lived,
  secretless, read-only bridge helper with no mounts or capabilities, while the
  Agent itself remains isolated.

## 0.4.2 - 2026-09-25

- Fixed Plex remote access through Proton NAT-PMP. Proton translates the
  allocated public port to the private port requested by MediaHub; the
  fail-closed `tun0` redirect now matches that translated private port before
  forwarding traffic to Plex. Added a regression test for the exact rule.

## 0.4.1 - 2026-09-25

- Fixed offline Core/Agent image activation after discovering that Docker
  correctly verifies and loads a digest-exported bundle but does not preserve
  the registry digest as a locally addressable image reference. The
  networkless host updater now binds the single loaded image ID to a local tag
  derived from the release version and verified bundle hash, enforces
  `pull_policy: never`, and still rejects untrusted release repositories.

## 0.4.0 - 2026-09-25

- Added compact update cards whose progress stays inside the app being checked
  or updated, preventing layout jumps and hidden status at the top of the page.
- Added configurable scheduled update checks, deduplicated notifications, live
  SSE refresh and an available-update badge in the sidebar.
- Added a complete, rollback-protected MediaHub Core and local Agent updater for
  digest-verified private GitHub Release bundles. The networkless root helper
  enforces trusted image repositories, stable forward-only versions, bounded
  configuration snapshots, health verification and automatic rollback; media is
  outside the transaction.
- Cloudflare Tunnel is now always visible as an optional app. Without a local
  helper it explains that monitoring is not configured; with one it reports
  connections, route health and official cloudflared release information.

## 0.3.0 - 2026-09-25

- Added reusable operation progress with stages, completion percentage and
  redacted technical details for Maintenance and update actions.
- Added a safe Maintenance workspace under Settings with live Core, Agent,
  storage and app checks, explicit movie/TV protection and direct links to
  storage, updates and backups.
- Storage browser folder-size totals and streamed, administrator-only uploads that
  stay inside approved media roots and never overwrite existing files.
- Added encrypted, repository-scoped GitHub access for private release discovery.

- Stable app-card loading with reserved layout space and direct app shortcuts in the sidebar.
- Simple-first dashboard with media storage first and collapsed Core/app diagnostics.
- Main-volume storage summary with technical mappings and read-only archives behind disclosures.
- Configurable public GitHub release discovery requiring a SHA-256 identified release manifest.
- GHCR release workflow with immutable image digests and build attestations; host installation
  remains gated until the transactional updater and rollback path are deployed.
- Added dedicated fail-closed Proton WireGuard networking for Plex remote access,
  renewable NAT-PMP port forwarding and actual public-port reachability checks.
- Added Cloudflare Tunnel health and official release monitoring plus a guided,
  provider-safe App Store setup foundation for a future installer.

## 0.2.0

- Real Plex installation, read-only media libraries, streams/resources and image update/rollback.
- Optional isolated Proton Seedbox with verified VPN, fail-closed recovery and NAT-PMP.
- Daily torrent management, force recheck and remove-job-without-data-deletion.
- TOTP enrollment/recovery, secure direct HTTPS, protected runtime secrets and memory limits.
- Encrypted Core/Plex/Seedbox configuration backups and offline non-overwriting restore.
- Logical shared storage, disk identity checks, missing-storage guards and live resource health.
- Refreshed simple-first navigation, version/maintenance page and guided app selection.
- New-install Linux bootstrap and public documentation without private deployment reports.
- FjordHub Access Token adapter using the actual read-only integration API.
- Limitations: Core/Seedbox updates and certificate renewal remain operator-managed;
  remote Seedbox host preparation is not an automatic Proxmox provisioning service.

## 0.1.0-dev

- Separate Phase 1 Core foundation: API, local auth, SQLite migrations and live dashboard.
- Generic manifests and a database-only mock adapter.
- Read-only storage validation, activity and settings.
- Proxy-free local HTTP serving and an isolated development Compose definition.
- Unit, integration and real-browser tests. Not a production release.
