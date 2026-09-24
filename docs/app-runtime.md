# Application runtime and future apps

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
