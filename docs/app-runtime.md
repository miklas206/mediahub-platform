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

MediaSeed and MediaVPN check their own main branch in `miklas206/mediaseed` and `miklas206/mediavpn`. Updates shows the actual installed container version and the independently checked latest version. Use **Check** and **Install update** on the selected app card. Update all explicitly includes every available selected component and keeps Core last.

Existing installations first need Core 0.6.30 to obtain this update mechanism. A Core update does not install newer app code. It preserves the app image, source context, credentials, storage and running/stopped intent while backfilling required configuration. Configuration repairs can recreate an affected container using its existing image. A fresh installation builds the reviewed bundled versions as initial bootstrap.

The selected app update downloads a commit-pinned source archive, verifies the app name/version and safe build inputs, then uses the owned host helper to build only that app's Compose project. A stopped app remains stopped. Existing configuration and data are retained; a build or startup failure restores the preceding Compose configuration. The operation journal survives Core restarts and reconnects to the same helper without repeating an uncertain installation. Recovery verifies helper completion and the installed source/version labels.

Private app repositories require the encrypted GitHub token configured in MediaHub to have read access to each app repository (`Contents: read` for a fine-grained token). The Core repository's scoped deploy key does not grant access to app repositories. Missing access produces a failed version check; it never falls back to a bundled version presented as a verified upstream release.
