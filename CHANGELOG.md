# Changelog

## Unreleased

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
