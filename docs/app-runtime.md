# Application runtime and future apps

## Browser observations

Dashboard runtime results are published per app as soon as they arrive, independently
of slower services. Runtime pages share those observations instead of starting a second
poller. Runtime snapshots poll every 10 seconds; Plex recently-added covers poll every
60 seconds. Each endpoint allows one in-flight request; hidden pages do not start new
requests and visibility return refreshes expired observations immediately.

Last-good data is retained in browser memory across navigation in the same signed-in
session. Fresh data is shown immediately without a duplicate navigation fetch. Expired
or failed observations remain visible with a stale notice, and their overall health is
unknown until a successful refresh. These observations are not persisted in browser
storage. Authentication transitions clear data and abort outstanding requests; app
removal prunes its observations. Inactive retained snapshots are limited to 64 entries;
currently mounted consumers keep their own observations until they unmount.


Docker is the primary manifest runtime; metadata does not assume a VM or LXC.
The Core app manager selects a registered host, checks Docker/capability readiness
and resolves storage slots through that host's logical mappings. Plans are preview
only; no real installation or import executor is enabled in Phase 3.

Trusted apps can later share the MediaHub host. Seedbox declares dedicated-host
recommendation and VPN/network-control capabilities. Installation policy can forbid
using the local host for Seedbox. Merely registering a host does not prove its VPN
is healthy or grant it network-control capabilities.

Future Plex adapter responsibilities: install/start/stop/restart/update, health,
sanitized logs, version and stream status. Media slots are RO; appdata/transcode
are separate RW slots. Preserve the existing server identity/configuration during
an approved migration. No Plex migration is executed now.

Before lifecycle execution exists, Agent must translate approved inspection paths
to Docker-host bind sources, enforce app UID/GID access, verify actual mounts and
reject unavailable storage. Do not treat a successful Agent directory inspection
as permission to create arbitrary Docker mounts.


## Independent first-party updates (Core 0.6.30+)

From Core 0.6.32, version discovery uses read-only Git over HTTPS instead of GitHub REST metadata, retaining the existing encrypted token for private access. MediaSeed and MediaVPN check their own main branch in `miklas206/mediaseed` and `miklas206/mediavpn`. Updates shows the actual installed container version and the independently checked latest version. Use **Check** and **Install update** on the selected app card. Update all explicitly includes every available selected component and keeps Core last.

Existing installations first need Core 0.6.30 to obtain this update mechanism. A Core update does not install newer app code. It preserves the app image, source context, credentials, storage and running/stopped intent while backfilling required configuration. Configuration repairs can recreate an affected container using its existing image. A fresh installation builds the reviewed bundled versions as initial bootstrap.

The selected app update downloads a commit-pinned source archive, verifies the app name/version and safe build inputs, then uses the owned host helper to build only that app's Compose project. A stopped app remains stopped. Existing configuration and data are retained; a build or startup failure restores the preceding Compose configuration. The operation journal survives Core restarts and reconnects to the same helper without repeating an uncertain installation. Recovery verifies helper completion and the installed source/version labels.

Private app repositories require the encrypted GitHub token configured in MediaHub to have read access to each app repository (`Contents: read` for a fine-grained token). The Core repository's scoped deploy key does not grant access to app repositories. Missing access produces a failed version check; it never falls back to a bundled version presented as a verified upstream release.


## Plex shared VPN status (0.6.63)

The Plex runtime adapter enriches the paired Agent report with the selected
shared VPN and the separately approved public Plex port. A shared VPN must have
a running Plex container, verified relay/namespace, a ready assigned provider and
no pending profile change. The inbound gateway can intentionally use a different
profile from Plex's outbound VPN. Its saved gateway profile, public address/port
and fresh Plex identity probe must match before remote access is shown as ready.
The remote access card shows the inbound public address when it differs from the
outbound VPN. Countries without current evidence remain unverified.

Port probes now save their own verifiedAt timestamp. A later gateway sync attempt
cannot make an old probe appear fresh. Existing saved ports are rechecked by the
regular reconciler after upgrade; no manual reset, replacement credentials or
media migration is needed. The existing dedicated VPN path remains supported.
Public status is filtered and cached for five seconds, with bounded calls and
unavailable remote status on errors/timeouts.

Both shared VPN Agent routes enter the HTTPS/app-storage dependency through
FastAPI Depends. The earlier manual await failed once that dependency acquired a
yielding storage lock; status/configuration and port reconciliation could fail.
Fresh installations and restored existing Core databases register the enriched
Plex adapter after gateway services are ready.

Live read-only verification confirmed the current Plex identity through its
public TCP port. Reviewed Agent/status code also passed against the real saved
profiles in an isolated process; a fresh identity probe was applied in memory
only. Production files, running services, media and saved preferences were not
changed. Installing the released Core activates the UI/API fixes and automatic
port re-verification.

Release verification: 162 focused Python tests and 28 frontend tests passed,
along with the production frontend build and Ruff checks. Chromium at 390 and
1280 pixels verified shared VPN/port status, hidden completed installation cards,
visible active/error cards, and no horizontal overflow or JavaScript errors.
A physical fresh installation and full host reboot were not performed.

## Stable polling observations and notifications

Runtime freshness, in-flight refresh and failed health checks are separate states.
When a previously healthy observation expires, the runtime view retains its health
as `observationHealth`, marks the current report unknown/cached, and labels the
badge as the last observation. Expiration alone does not manufacture a failed
storage/runtime check or a Cloudflare warning. Actual degraded/critical checks
remain visible through refresh; transport failures keep their own error and
stale/unavailable status. Action authorization and fresh validation remain on the
server; no readiness TTL or action bypass is introduced by this display change.

The common `useData` loader retains an unresolved error during a background
refresh. Repeated failures with the same text keep the same notification mounted
instead of clearing/remounting it on every poll. A successful response clears the
error. Requests to another path do not inherit the old data/error, and repeated
automatic polls of the same pending path share that read rather than continuously
aborting a slow response. Explicit reloads after user actions still cancel an
older read and start a new one, so pre-mutation data cannot replace the new state. Existing cancellation and two bounded read retries are
preserved; mutations are not retried by this loader.

This common path covers app settings/resources/storage, shared VPN and Plex
account/domain setup, including corresponding Jellyfin and container app views.
The other polling paths were checked: service/page snapshots and `useLoad`
already retain errors; Cloudflare and port checks clear errors only on successful
responses; MediaSeed/MediaVPN automatic status loops do not emit operation-error
popups on each refresh. No unrelated app data, media, credentials, polling
intervals or installations change. Fresh installations and upgrades use the same
frontend bundle without a schema/configuration migration.

Regression coverage includes a held Plex status response over repeated polling
cycles, genuine storage failures after recovery, persistent API errors across
multiple read attempts, clearing after real recovery, and repeated clicks during
a slow read. These browser fixtures are synthetic and do not operate live apps.
