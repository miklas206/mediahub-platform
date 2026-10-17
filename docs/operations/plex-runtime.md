# Managed Plex runtime

Plex is optional. It uses the local trusted Agent, independently of Seedbox.
The guided installer selects operator-approved logical media and app-data
mappings; browser requests cannot supply filesystem paths or container names.

## Storage and account protection

* Media is mounted read-only, without moving or duplicating existing files.
* App data is separate from media and must be covered by a filesystem UUID guard.
* A fresh application-specific directory is created. An existing directory is
  not silently adopted, recursively changed, or removed.
* Plex's `Preferences.xml`, including account tokens, resides in a private tmpfs
  volume. The Agent saves an encrypted checkpoint when preferences change and
  before a controlled stop. It restores that checkpoint before starting Plex.
* Database, artwork and codec directories have explicit durable mounts. Logs and
  crash-report directories stay in RAM. Docker process logging is disabled for
  this runtime, so tokens emitted by a third-party startup script are not saved.
* Core dumps and container swap are disabled. The preparation container verifies
  cgroup v2 `memory.swap.max=0` before accepting any account material.
* Where kernel/user-namespace support permits, tmpfs additionally uses `noswap`.
  On hosts that reject that mount flag, an explicit operator policy can disable
  the flag; the cgroup no-swap check remains mandatory. Never disable both.
* A transient, labelled preparation container keeps the RAM volume mounted until
  Plex starts. It has no network and receives no broad media mount.

The vault protects disk contents against casual disclosure, not a compromised
host administrator. Its encryption key and encrypted records must be included in
the operator's protected configuration backup. Media backups are separate.

## Lifecycle

Before start/recovery the Agent checks fresh host mount evidence, the expected
filesystem UUIDs and marker files. It also checks the exact container image,
ownership labels and mounts. A missing disk does not become a writable directory
on the system disk. A failed preference checkpoint must never prevent stopping
an unsafe runtime.

Plex has no Docker automatic-start policy: the Agent starts it after storage
validation and restores encrypted preferences first. Changing that restart policy
would bypass this ordering and is unsupported.

## Temporary transcoding storage

The installer selects approved movie, TV and other library mappings independently
of temporary storage. Each approved app-data mapping automatically offers a
`Temp` choice; operators can also provide explicit policy mappings with kind
`temp`. Browser input selects approved IDs, never arbitrary host paths. Libraries
remain read-only and temporary paths cannot overlap any approved media library.

By default the Agent creates `<appdata>/Temp/<installation>/work`, mounts it at
`/transcode`, sets `TMPDIR=/transcode` and configures Plex's transcoder directory.
The bounded initialization helper uses the Plex UID/GID, verified storage,
no network and a read-only container root. It checks actual file allocation and
at least 1 GiB of free space. This is a minimum preflight, not a promise that a
large 4K conversion will fit: Plex recommends roughly the source file size plus
100 MB ([Plex documentation](https://support.plex.tv/articles/transcoder/)).
Pooled storage may report aggregate free space while the branch containing an
existing directory is full; allocation failure is reported explicitly. The Agent
does not change pool policies or relocate existing metadata/media automatically.

An ownership marker lives outside the work directory exposed to Plex. Plex cleans
finished sessions with persistent session directories disabled. Before starting a
stopped server, MediaHub also removes only recognized `plex-transcode-*` session
directories inside its marked work tree. It never runs orphan deletion while
Plex is running, follows symlinks or removes unrelated files.

Existing managed installations receive the missing bind mapping automatically
after the updated Agent starts and playback is idle. A second session check runs
after storage preparation, before the container is stopped. Migration retains
the installed image, existing mappings and settings and records a recovery
receipt before replacing the container. Failure or interrupted migration restores
the original container without deleting volumes. A failed migration remains
blocked for inspection rather than restarting repeatedly. An intentionally
stopped installation remains stopped and is reconciled after its next start.
An existing custom Plex transcoding path is preserved and is not cleaned by
MediaHub. Repeated reconciliation leaves an already migrated plan unchanged.

From 0.6.47 readiness requires the actual inspected container to have the approved
writable `/transcode` bind and `TMPDIR=/transcode`. A saved plan or completed
receipt alone is insufficient. This repairs the 0.6.46 shared-VPN regression where
an old pre-VPN specification could discard the newly added mount. Reapplying VPN
networking now preserves the current non-network application configuration.
On an unprivileged LXC the Docker daemon's mapped root also needs directory
traversal to stat a private bind source. The app-UID helper adds execute-only ACL
entries for namespace root on the approved parent and its marked temporary
directories. It preserves private files, other ACL entries and masks; native
root needs no extra ACL. Unsupported ACLs or a restrictive existing extended mask
produce an explicit storage/permissions prerequisite rather than world-readable
temporary data.

## Updates

The Updates card checks the same fixed `lscr.io/linuxserver/plex:latest`
container-image publisher used by the managed update transaction. It reads Docker's
`GET /distribution/{image}/json` metadata and verifies the installed pinned
repository digest against the local image's `RepoDigests`. The publisher must list
the installed OS/architecture/variant; different digests must refer to matching
manifest types, so a platform manifest is not mistaken for a newer multi-platform
index. This check neither pulls
an image nor stops Plex. Unsupported images or unverifiable metadata do not enable
Update Plex; failed checks clear the previous approval. A successful fresh check
must explicitly confirm a different publisher digest before the button is enabled.
The installed Plex server version and latest publisher-image digest are separate:
an image release can change packaging without changing the Plex server version.

Plex's `/updater/check?download=0` and `/updater/status` describe the **server's**
updater, not the managed container release. They cannot authorize an image update;
the legacy server-only check reports managed updating as unsupported. Recovery and
explicit lifecycle controls remain available independently on the app page.

On an approved update the Agent pulls the publisher image and rechecks its image
ID under the lifecycle lock. If it is already installed, it returns "already up
to date" before stopping Plex, changing intent, or creating a rollback snapshot.
Concurrent requests cannot admit multiple background update transactions.

## Network

For the shared VPN relay, 0.6.47 prepares a source-NAT rule restricted to the
verified host LAN subnet, the owned relay's current Docker address, TCP 32400 and
the original published private destination/port. The host's actual interface
prefix and Docker gateway are checked by a bounded helper using the reviewed
relay image. The helper has host networking and NET_ADMIN to manage this rule,
a read-only root, no data/key mounts, no other added capabilities and no daemon.
Only recognized rules carrying this installation's exact ownership comment can
be replaced or removed. Reconciliation restores a missing rule after a reboot;
VPN disconnect/removal cleans the owned rule without flushing any firewall chain.

This makes genuine LAN clients appear on Plex's local Docker subnet. Those
clients consequently share the Docker gateway address in Plex's server-side
client-IP reports; Plex login remains required. External public/VPN traffic does
not match the source subnet and published private destination. Established
connections retain their old NAT state: reconnect clients to refresh their
classification. Verify a new session with `local=1`, `location=lan`, `relayed=0`,
and independently verify remote access. Unsupported host addressing or firewall
permissions produce a concrete local-access error rather than silently disabling
Plex authentication, its VPN assignment, or remote access.

From 0.6.48 the dedicated public TCP proxy targets the ready app's private
WireGuard address rather than the published LAN listener. This distinction is
required because a TCP proxy connecting back through the host LAN would otherwise
be mistaken for a local client. Verify public requests as WAN independently of
successful public HTTPS/identity checks; reachability alone does not prove the
classification. Older Agents must provide the verified relay address before this
route can be reconfigured.

Only the configured private LAN address publishes TCP 32400. No router rule,
Cloudflare Tunnel or public service is created. A Plex claim token is optional,
short-lived, submitted over HTTPS and never persisted in container configuration.
See [the image maintainer's documentation](https://docs.linuxserver.io/images/docker-plex/)
for claim-token lifetime and `FILE__` secret-file support.

The isolated installation lab uses a loopback-only port and no production media.
Its mount snapshot is a fixture; actual media acceptance also requires a real
filesystem identity check and playback test.
