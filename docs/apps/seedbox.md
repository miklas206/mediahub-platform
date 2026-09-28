# Seedbox

Dedicated paired Agent host, pinned VPN/qBittorrent images, logical downloads
storage and gated lifecycle operations. The current runtime supports authenticated
start/stop/restart, VPN/client restart, verification and metadata-only diagnostics.
Core mutations require an administrator session and CSRF protection.

The live panel displays verified tunnel egress, qBittorrent API/binding/namespace,
NFS source, app permissions, disk capacity, host resources and the real
forwarded-port lease state. Low-level block-device inventory is kept under the
collapsed Maintenance diagnostics instead of the daily app view. WebUI access
remains a local authenticated SSH tunnel; CSRF and Host validation are not
disabled.

MediaHub can add a magnet or uploaded `.torrent` to Downloads or to another
explicitly approved writable logical destination such as Movies, TV Shows or
Other. Existing direct child folders are also selectable. The browser uses an
opaque Agent-issued ID and cannot submit a filesystem path. See
[daily-use controls](../operations/seedbox-daily-use.md).

Runtime-only removal retains downloads, encrypted credentials and qBittorrent state.
Image versions are pinned; a newer version must not be invented from an image tag.

## Installation and acceptance

The 13-step wizard connects encrypted credential import, live preflight and the
production transaction driver. It supports existing-runtime adoption, controlled
VPN/client credential rotation and runtime-only rollback/removal. Progress is
stored on the Agent and the server owns state transitions.

Deployment readiness is determined by the installation's acceptance report,
including browser E2E, failure matrix, rotation and final post-install reboot
tests. Passing tests does not authorize migration of production data.

See [first-install foundation](../deployment/seedbox-first-install-security.md),
[recovery](../recovery.md), [VPN](../vpn.md) and [secret custody](../security/secrets.md).
