# Shared application VPN

MediaVPN can share one selected full-tunnel WireGuard profile with MediaSeed,
owned Plex and Jellyfin installations. Enabling sharing stops other MediaVPN
profiles and prevents starting another provider profile until sharing is off.
Existing dedicated Plex VPN must be disabled before selecting the shared gateway.

MediaSeed's download motor stays in the provider namespace and follows its
NAT-PMP port. Plex and Jellyfin use separate private WireGuard relays, so their
web ports remain stable. These relay keys are generated on each Agent host;
the provider private key never leaves MediaVPN. Only MediaHub's separate
management key can register relays. The MediaSeed integration key cannot.

## Installation and updates

Reviewed first-party build sources are included under `docker/bundled/` with a source
manifest. No private repository token is needed on the server. Refresh this
snapshot with `scripts/sync_bundled_apps.py` when publishing first-party changes.

Keep the checkout bundle at `docker/bundled/`: older installed Core updaters retain
the `docker/` source root but discard new top-level directories. The Core image
copies this reviewed bundle to `/app/bundled` and the two host preparation helpers
from `docker/runtime-scripts/` to `/app/scripts/`. These helper copies must match
their reviewed `scripts/` originals; regression tests enforce parity and verify
every Core Docker COPY input survives the legacy archive normalizer. Do not fix
this by disabling archive path filtering or by downloading mutable app source
during an update.
Runtime databases, keys, profiles and downloads must never be copied there.

The Linux installer prepares local HTTPS app origins, certificates issued by the
host CA, integration identities, immutable install recipes and app images.
Existing registered origins and app configuration are preserved on upgrades.
The updated Core backfills app prerequisites using its own immutable image and
an owned, temporary host helper. This also supports older host updater scripts.
Preparation is serialized with the host updater and app lifecycle operations.
It rebuilds changed app sources, resumes only services that were running, and
leaves uninstalled/stopped applications stopped. Failed builds restore the
previous Compose configuration; persistent volumes are never deleted.

Selecting an app's VPN installs its relay image automatically. Reinstallation
and Plex updates retain the selection and provision the relay before starting
the app. Agent updates rebuild changed relay helpers. Interrupted migrations
remain blocked and can be retried; they never restore direct internet access.

## Managed remote hosts

Plex/Jellyfin may run on another paired Linux Docker Agent. The Agent must have
verified HTTPS, its private state bind mount, Docker access and a TUN device.
The helper includes WireGuard tools and a userspace fallback for hosts where the
kernel driver cannot be loaded from an existing LXC. It must reach the MediaVPN
host's private UDP port (default 18804).
The internal relay subnet is 10.250.87.0/24 and must not overlap the provider's
interface network. Proxmox fresh installation loads and maps the TUN driver.
Existing hypervisor firewall rules are not silently widened by an app update.

An independently installed FjordHub or an unmanaged LXC is not granted container
control by its read-only integration. Those installations need a supported
Agent/installer adapter before they can be attached through this flow.

## Cloudflare and DNS

The [MediaVPN guide](vpn-gateway-guide.md) combines Proton, Cloudflare and selected
installed app domains. A Traefik instance in the provider namespace handles
inbound HTTPS, DNS-01 certificates and trusted private origins. Owned proxied
A-records and Origin Rules follow the verified Proton IP/port. Torrents use a
separate renewable NAT-PMP mapping. The Hub's existing Traefik remains independent.
No Caddy dependency or new cloudflared connector is needed. Existing legacy
tunnels and unrelated records are preserved until explicitly migrated.

## Verification and recovery

Provider readiness, relay handshake readiness and application health are separate.
Gateway failure blocks outbound traffic. IPv6 outbound traffic is disabled in
relays. Only marked replies to incoming LAN web requests and encrypted relay
transport may use the physical interface; established VPN flows may not fall
back to it after WireGuard disappears.

Synthetic tests cover lifecycle ordering, interrupted migration retry, namespace
generation, routing/firewall contracts, key separation and data retention. They
are not a physical cross-host egress/leak test. Local Docker engine was unavailable
during development; no real provider configuration or existing tunnel was started.
Confirm each selected app's public egress and loss-of-tunnel behavior on the
target installation before treating the network protection as live verified.

To restore ordinary networking for an app, explicitly turn its shared VPN choice
off. This recreates only the app container using its current image and original
network/ports, preserving mounts. Stopping shared VPN instead keeps app selections
and blocks their internet access. Compose backups and old source directories are
kept under the host's private `local-apps` directory for operator recovery.
