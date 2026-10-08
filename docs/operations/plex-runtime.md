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

Only the configured private LAN address publishes TCP 32400. No router rule,
Cloudflare Tunnel or public service is created. A Plex claim token is optional,
short-lived, submitted over HTTPS and never persisted in container configuration.
See [the image maintainer's documentation](https://docs.linuxserver.io/images/docker-plex/)
for claim-token lifetime and `FILE__` secret-file support.

The isolated installation lab uses a loopback-only port and no production media.
Its mount snapshot is a fixture; actual media acceptance also requires a real
filesystem identity check and playback test.
