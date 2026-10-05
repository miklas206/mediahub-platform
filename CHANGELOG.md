# Changelog

## Unreleased

- Publish each dashboard runtime observation independently so a slow Seedbox cannot delay Plex or Cloudflare. Retain last-good runtime data and Plex covers across navigation within the current signed-in session; label aged/failed observations stale rather than healthy. Share non-overlapping 10-second runtime and 60-second cover polling, pause hidden-page requests, abort abandoned work and clear private cached data on authentication transitions and app deletion. Existing settings, dashboard layout and FjordFlix polling remain unchanged.

- Expand the existing FjordHub integration with keyed app-info/permissions, validated installed LAN ports, revision-refreshed protected icon proxying and explicit administrator/CSRF update controls for FjordHub and child apps. Poll statuses sequentially every 45 seconds (5 while running), retain stale in-progress state through restart/timeouts, treat HTTP 202 only as acceptance, and never add remote updates to the automatic global queue. Preserve older resource responses and local launch overrides; use safe icon fallbacks for non-origin artwork.

- Add a configurable Active uploads dashboard card for torrents currently sending data to peers, with count, combined upload speed and the five busiest torrents. Reuse the shared dashboard snapshot, exclude stopped/paused and zero-speed seeds, distinguish unavailable data from zero activity, and retain existing saved layout preferences. Available in Choose cards and Settings; new dashboard defaults place it next to ongoing torrents.

- Keep dashboard card geometry identical when entering and leaving layout editing: original and saved layouts now use the same engine in both modes. Draw both ends of the actual CSS tracks (including gaps) in the edit grid, and keep Choose cards registration/order stable while visibility or asynchronous content changes.

- Add authenticated per-integration FjordHub home pages with internal sidebar navigation, an explicit external Open FjordHub action, Docker/app/FjordFlix overview and administrator-only local app launch URL settings. Persist same-host, explicit-port overrides with session/CSRF checks and consistent sidebar/card/dashboard links; clearing restores API/management fallback, and removal cleans up scoped settings. Bundle verified MIT Fjord3D artwork with its copyright/license; use clearly documented ordinary interface-icon fallbacks where official artwork has no verified redistribution license, rather than copying screenshots or inventing replacement logos.

- Reduce Cloudflare Tunnel release-check requests with shared, restart-persistent validated metadata, ETag revalidation and existing encrypted GitHub access. Persist GitHub cooldowns even for manual/forced checks; show deferred checks and explicitly stale versions without marking a working tunnel unhealthy or hiding genuine source failures. Tunnel updates remain manual.

- Add a dedicated configurable Plex-style FjordFlix dashboard card under Your apps, including ordered last-10 protected poster carousel, library/active-stream counts and independent stale/empty/error states. Share one child-app link resolver between navigation, app cards and dashboard: preserve validated explicit app addresses/nondefault ports, reject unsafe or untrusted destinations, and explicitly label FjordHub management links when the resource API omits app addresses (never guess ports).

- Add confirmed, administrator-only permanent removal for disconnected FjordHub integration entries. Remove only the selected local record, token and cached snapshots/gallery; never uninstall or modify FjordHub. Fence late refresh/discovery, persist discovery opt-outs across restarts, and explain environment-managed entries that require operator configuration changes first. Existing disconnect still preserves the row.

- Show qBittorrent's reported popularity as a sortable torrent-list column on desktop and mobile. Preserve saved sort preferences, display real zero values with two localized decimals, and show unavailable/invalid values as unknown without calculating a replacement.

- Extend the read-only FjordHub resources integration with optional FjordFlix appdata: the last 10 recently added titles in API order, current streams and playback metadata, independently stale app/resource snapshots, and authenticated bounded same-origin poster proxying. Add backend-only `FJORDHUB_BASE_URL` / `FJORDHUB_ACCESS_TOKEN` configuration and sequential 10-second polling; old responses without appdata remain compatible.

- Verify identical qBittorrent username/password reapplication with a fresh login instead of rejecting it; allow username-only changes while still proving the previous login is rejected. Report sanitized rotation preflight errors and correlate status with the current operation, so an older healthy VPN journal cannot mask a failed client change. Interrupted/partial rotations still require operator recovery; no live rotation or deployment performed.

- Report asynchronous Seedbox credential rotation separately from installation health, including a sanitized failed step and interrupted-operation recovery state. Poll the result in **Use my MediaHub login** so an accepted request cannot hide a later failure; keep encrypted recovery references private. No live password changes or deployment are performed.

- Add opt-in **Use my MediaHub login** to Seedbox installation and existing Seedbox Settings. Reauthenticate the administrator's entered password and enabled MFA with session/CSRF checks; copy the server-side account username through existing encrypted credential import/client rotation without changing VPN or WebUI protections. Clearly reject logins incompatible with Seedbox's existing policy and explain one-time copying, not continuous password synchronization. Existing users must opt in after updating; no live rotation or deployment is automatic.

- Add regression checks confirming fast/full MediaHub platform updates target only Core/Agent, use dependency-isolated starts, and leave managed Plex/VPN running during Agent shutdown. Document the difference between platform updates and Plex/VPN updates or safety failures.

- Add a dedicated qBittorrent WebUI control under Seedbox Settings, including an explicit unconfigured state and Danish access guidance. Document opt-in authorized client SSH tunneling to the reviewed loopback WebUI port and Core operator-link configuration; preserve qBittorrent login, CSRF/host validation and VPN fail-closed behavior. No endpoint is exposed or live deployment performed.

- Make every automatic RSS feed use newly discovered entry IDs regardless of publication date, including older torrents exposed by rotating feeds and undated/future-dated entries. Preserve creation/activation baselines, durable retries and the 20-item per-poll limit. Previously seen IDs, including entries skipped by the former date rule, are not automatically replayed; manual selection remains available.

- Add an explicit `--refresh-helper` migration for the privileged host updater while preserving existing source trust or image-only update policy. Explain that updating Core alone does not enable host cleanup, and publish capabilities only after replacing the real helper.
- Keep maintenance app-health counts consistent with the badge: unknown reports are not counted as healthy, and an empty installation list is explicitly unknown. Disable cleanup submission while its status is unavailable or still loading.

- Show qBittorrent's accumulated seeding time directly below each torrent name on desktop and mobile, including zero and unavailable values; keep the existing seeding-time sort and expanded details.

- Load App Store installation badges and setup selections from lightweight installed-app metadata (`GET /apps?include_health=false`) without waiting for remote health checks. The default app listing still includes health, and store controls still wait for installation and integration metadata.

- Reuse app and integration snapshots across authenticated pages instead of repeating page-mount requests and integration polls. Cancel obsolete reads/retries, pause integration polling in hidden tabs, and batch app health event bursts into a bounded refresh.
- Load optional pages and the upload client on demand, and fetch authentication/setup state in parallel. Reduce initial JavaScript from 948.42 kB to 767.32 kB (gzip 284.11 kB to 235.75 kB) in the local production build.
- Check independent app health reports concurrently (up to eight at a time) for the app list and initial live stream, retaining response order, authentication, bounded remote timeouts and status validation. Fetch installed app rows with one database query instead of one additional query per app.

- Use the MediaHub logo for iPhone and Android home-screen webapps with an Apple touch icon, maskable PNG icons and a standalone web app manifest.

- Follow the configured GitHub repository's main branch by commit instead of requiring a new release or version number. Pin source downloads to the selected commit and retain bounded archive validation, builds, snapshots and rollback.
- Display installed and available commit IDs, and add a one-time host-helper migration for same-version source updates.

- Serialize release publishing by target tag so overlapping runs cannot collide while uploading the same release assets.

## 0.4.29 - 2026-09-30

- Release merged PR #1: cancel superseded folder requests so delayed responses cannot replace the current folder; retain loaded data on failed refreshes of the same path.
- Report aggregate update-check errors as incomplete checks while keeping successfully discovered updates visible. Clear old notices before checking again.
- Add browser regression coverage for folder navigation and incomplete update checks, and correct the disconnected-progress accessibility assertion.

## 0.4.28 - 2026-09-30

- Preserve the Agent's supplementary private-state group 10001 alongside primary media group 1000. An explicit Docker USER group in v0.4.26 discarded membership needed to read host storage evidence and blocked Plex recovery.
- Explicitly retain Plex VPN's outbound bridge when attaching the internal control network. Reconnect a missing bridge on an owned, stopped VPN before its normal verified start; do not change a running VPN's networks.
- Extend image CI checks to require both primary media and supplementary private-state groups.

## 0.4.27 - 2026-09-30

- Label update progress and steps as last received while Core is unreachable, and show a separate reconnecting indicator instead of animating a stale build step.
- Explain the possible service-restart pause without claiming the unseen server state; restore live progress when status polling succeeds.

## 0.4.26 - 2026-09-30

- Run the Agent image with UID 10001 and primary media GID 1000 so mergerfs writes do not depend on resolving Docker supplementary groups.
- Preserve Agent state ownership and existing media permissions. The normal image update applies the new identity to installations without a Compose user override.
- Verify the built production Agent image's effective UID and GID in CI.

## 0.4.25 - 2026-09-29

- Preserve Agent filesystem and path-policy errors through Core, including HTTP 403 responses for denied writes, read-only storage and disabled directory creation.
- Distinguish authentication failures from storage failures for folder preparation and streamed upload chunks; handle malformed rejection responses without exposing proxy pages.

## 0.4.24 - 2026-09-29

- Recommend and prefill 4 CPU cores and 10240 MiB RAM for new FjordHub LXCs.
- Run the reviewed FjordHub installer from the guide over fingerprint-pinned root SSH, with a live console and durable installation status.
- Share the command template between browser preview and backend execution; accept validated configuration only, never browser-supplied shell commands.
- Keep SSH passwords in job memory only, redact bounded logs, prevent duplicate/racing jobs and require target inspection after failed or interrupted attempts.

## 0.4.23 - 2026-09-29

- Align FjordHub guide inputs at the top of each form row so Timezone does not stretch or shift downward when adjacent fields have helper text.

## 0.4.22 - 2026-09-29

- Fix Linux folder creation and resumable uploads through search-only ancestor directories by using O_PATH with O_DIRECTORY/O_NOFOLLOW instead of requiring read permission on every ancestor.
- Report the actual filesystem error, affected path and Agent identity for permission failures; distinguish read-only mounts, full disks, quotas and path limits.
- Show folder preparation errors above the upload queue and avoid repeating the same failed folder-creation request for every file.

## 0.4.21 - 2026-09-29

- Generate copyable/downloadable FjordHub setup commands for a new unprivileged Debian 13 Proxmox LXC or an existing Debian host.
- Configure container ID, storage, separate data disk, CPU/RAM, bridge, DHCP/static IPv4, application paths, port and timezone from the guide.
- Generate a private session secret on the target and write the selected `.env` values automatically. Refuse occupied IDs and existing installations; never run provisioning from MediaHub.

## 0.4.20 - 2026-09-29

- Preserve actual update steps, progress and console history across temporary connection failures instead of replacing them with a fixed 82% fallback that omits Build.
- Add an expandable Console to platform update progress, with bounded live history and automatic scrolling that pauses when reading older lines. Keep the result visible after completion.
- Stream bounded, redacted Docker build output from the host helper. Existing helpers retain status-message history; detailed build output requires a one-time helper refresh from this checkout.

## 0.4.19 - 2026-09-29

- Accept files and whole folders dropped directly onto the existing Media files panel, preserving nested paths and mixed selections.
- Keep the Upload menu's Files and Folder choices, existing 5 MiB tus transfers and Stop controls.
- Highlight the drop target, block overlapping uploads and prevent accidental file navigation. Read all directory batches and report unreadable or oversized selections before uploading.

## 0.4.18 - 2026-09-29

- Reuse the frontend build across backend-only releases: read the displayed version from Core and exclude package release metadata from Docker build inputs.
- Run Python application source directly with locked dependencies, eliminating repeated package/build-tool installation for source edits.
- Skip building, stopping, snapshotting and recreating an unchanged local Agent. Bind reuse to a root-owned source fingerprint and the installed immutable image; rebuild if evidence is missing or invalid.
- Preserve Core backup and rollback while an unchanged Agent continues running. The first update establishes the Agent fingerprint.
- Existing hosts must refresh the root-owned updater once using `scripts/enable_source_updates.py` from this version's checkout to enable Agent reuse. Normal Core updates do not replace that helper. Dockerfile improvements work with the existing source updater.

## 0.4.17 - 2026-09-29

- Replace the two storage upload buttons with one Upload button offering Files or Folder.
- Preserve tus transfers, folder structure and Stop controls.

## 0.4.16 - 2026-09-29

- Cache Python dependencies before copying application source, reusing the same dependency layer between Core and Agent builds.
- Fetch frontend packages from the lockfile before copying the versioned package manifest; install offline so version-only releases do not repeat package downloads.
- Preserve the existing verified-source, backup, preflight and rollback update workflow. The first build warms the new cache; later builds benefit while dependencies and the base image remain unchanged.

## 0.4.15 - 2026-09-29

- Use tus-js-client for browser uploads with 5 MiB chunks and automatic offset recovery.
- Add authenticated tus HEAD/PATCH endpoints while preserving folder uploads, Stop controls and no-overwrite publication.

## 0.4.14 - 2026-09-29

- Upload a whole folder from Storage, preserving its name and nested files.
- Add Stop beside each file's progress and Stop all for the upload queue.
- Transfer large files in bounded 8 MiB chunks with persisted offsets and recovery from lost acknowledgements.
- Serialize cancellation with in-flight writes, remove unfinished temporary files, and preserve completed media and existing files.
- Clean abandoned sessions after 24 hours and warn before leaving an active upload page.
- Cover nested folder uploads, chunk retries, active/queued cancellation and responsive controls in browser tests.

## 0.4.13 - 2026-09-29

- Show only approved media roots in the torrent destination selector; existing movie-title folders no longer appear.
- Display the configured media names without the MediaHub or Top folder decoration.
- Reject obsolete child-folder destination IDs when adding torrents, while preserving actions on existing jobs.
- Keep media content, mount paths, VPN settings and torrent state unchanged.

## 0.4.12 - 2026-09-28

- Preserve readable source permissions inside non-root Docker images, including builds run under a private systemd umask.
- Add POSIX permission regression coverage and run source-built images as their non-root runtime user in CI.
- Run isolated non-root image smoke checks on the host before stopping any existing service.
- Preserve uid/gid in configuration backups and restoration for non-root Core/Agent runtimes.
- Supersede 0.4.11; its first live deployment failed startup checks and required ownership repair during rollback.

## 0.4.11 - 2026-09-28

- Build platform updates from verified GitHub source on the server, before stopping Core.
- Preserve configuration backup and rollback; never include media in the update transaction.
- Add source-build progress and explicit host capability/trusted repository checks.
- Provide a one-time migration helper for existing installations; keep image bundles optional for older clients.

## 0.4.10 - 2026-09-28

- Supersede the v0.4.9 storage-destination release with the repository's
  canonical Python formatting so the full GitHub CI gate passes unchanged.

## 0.4.9 - 2026-09-28

- Allow Seedbox administrators to choose among explicitly approved writable
  logical destinations such as Downloads, Movies, TV Shows and Other when
  adding a torrent.
- Keep destination selection fail-closed: the browser receives opaque IDs,
  read-only or merely mounted storage is excluded, and the Agent revalidates
  the selected root or direct child folder before contacting qBittorrent.
- Keep torrent actions available for jobs stored in any approved writable
  destination while preserving compatibility with the original Downloads root.

## 0.4.8 - 2026-09-28

- Keep sidebar app-health indicators synchronized with the same remote status
  used by app detail pages through SSE-triggered, focus-triggered and bounded
  visible-page refreshes.
- Move Seedbox block-device and mount inventory out of the daily app view into
  a collapsed troubleshooting section under Settings → Maintenance.
- Let administrators select the Downloads top folder or an existing direct
  child folder when adding a torrent. Destination identifiers are opaque and
  are revalidated by the Agent; arbitrary paths, hidden folders and symlinks
  remain unavailable.

## 0.4.7 - 2026-09-25

- Add a dedicated App Store navigation entry with stable, equal-height catalog
  cards and loading placeholders that prevent content from moving while data
  arrives.
- Keep a fresh installation's Apps page limited to actually installed apps;
  Cloudflare Tunnel moves from the installed list into its guided App Store
  flow until the administrator saves a configuration.
- Add a complete Cloudflare setup and edit flow for multiple tunnels, public
  routes, private HTTPS origins, internal CA validation and optional connector
  metrics without requesting an account-wide Cloudflare token.
- Add FjordHub to the App Store with a guided deployment from its official
  GitHub source and a separate least-privilege, read-only Access Token
  integration step.
- Add a one-time navigation migration so existing installations receive the
  App Store entry without overriding later user customisation.

## 0.4.6 - 2026-09-25

- Turn the completed update check into a clear green "Everything is up to date" state.
- Keep multiple Cloudflare tunnel monitoring profiles and show edit, remove, and add controls after installation.
- Reserve the assisted Cloudflare wizard for first-time setup and explicit configuration changes.
- Add a direct Plex server settings button and clear stale app-specific update results when switching apps.
- Extend Cloudflare monitoring to aggregate routes from saved tunnel profiles without storing Cloudflare account tokens.

## 0.4.5 - 2026-09-25

- Fixed platform updates failing before download when the private staging
  directory had been created by root. Fresh installs now create the directory
  for the unprivileged Core user, the host updater verifies that ownership, and
  Core reports a clear storage-permission error instead of a generic failure.

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
