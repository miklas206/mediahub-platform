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
Other Media. Only these media roots are selectable; existing content folders
are excluded. The browser uses an
opaque Agent-issued ID and cannot submit a filesystem path. See
[daily-use controls](../operations/seedbox-daily-use.md).

Runtime-only removal retains downloads, encrypted credentials and qBittorrent state.
Image versions are pinned; a newer version must not be invented from an image tag.

## Copying your MediaHub login (opt-in)

During the wizard's **Credentials** step, or for an existing installation under
**Seedbox → Settings → qBittorrent WebUI**, expand **Use my MediaHub login**.
The username comes from your authenticated administrator account. Enter your
current MediaHub password and, if enabled, an authenticator/recovery code; submit
**Copy login for installation** or **Copy login & rotate qBittorrent credentials**.
Existing installations must be idle. Rotation is accepted asynchronously: check
installation status for verification or recovery before using the new WebUI login.

This copies credentials once, not continuous password synchronization. Later
MediaHub password changes do not change qBittorrent. MediaHub cannot recover your
plaintext password: no existing/live credentials are changed just by updating the
platform or viewing this page. You must perform this opt-in action after updating.
Separate credentials remain safer and are still supported.

The existing Seedbox policy is preserved: passwords need 16–256 characters without
control characters and usernames need 1–64 letters, digits, dots, underscores or
hyphens. MediaHub accepts some shorter passwords or usernames that are incompatible;
these are explicitly rejected, not silently changed. A rotation also requires a
password different from the existing qBittorrent password.

Core verifies the password, administrator session, CSRF and enabled MFA before
forwarding over verified HTTPS to the existing encrypted import/rotation path. It
never returns or persists the submitted plaintext or retrieves a password hash for
the browser. Client rotation retains the VPN configuration and existing network,
storage and authentication guards. Existing rotation failures remain fail-closed
and may require operator reconciliation; this feature does not add live deployment,
change WebUI exposure, or bypass qBittorrent protections.

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
