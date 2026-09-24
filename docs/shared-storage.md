# Shared storage across hosts

## Decision

Prefer **NFSv4 for Linux hosts**, supplied by one explicitly managed storage owner.
Keep SMB for Windows Explorer. Both protocols may expose the same underlying
directories; they are not replication mechanisms. MediaHub's logical registry
does not format disks, move media or infer ownership changes. Host-level exports
and mounts remain explicit, reviewed deployment operations.

| Method | Appropriate use | Trade-offs |
| --- | --- | --- |
| NFSv4 | Primary Linux-to-Linux shared media | Stable Linux permission model; requires explicit export boundaries, UID/GID policy and mount dependencies. AUTH_SYS is not strong client authentication. |
| SMB/CIFS | Windows access; Linux alternative if storage owner only supports SMB | Credentials/ACL and Linux ownership translation need care. Do not assume POSIX hardlinks or atomic moves work without testing the actual server/client. |
| virtiofs | VM on the same PVE host, with directories already owned by that host | Avoids a network-filesystem hop, but adds same-host coupling and requires supported PVE configuration. Not appropriate for simultaneously exposing an ext4 filesystem already mounted inside another VM. Check migration/snapshot/backup limitations before selection. |
| Bind mount | PVE-owned directory into unprivileged LXC | Low overhead, but LXC UID mapping and backup inclusion are explicit responsibilities. A bind mount is not a cross-host protocol. |

NFS is the recommended direction, **not an instruction to replace current exports**.
Moving ownership from a source VM to a NAS or storage host requires its own
approved, backed-up and verified cutover.
Never attach the same ordinary ext4 block filesystem read/write to two guests.

## Logical model

```text
Logical dataset: downloads / dataset reference: storage-owner/media/downloads
  MediaHub Host: /media/downloads      read-only by default
  Seedbox Host:  /data/downloads       read/write

Logical dataset: movies
  MediaHub Host: /media/movies         read-only for Plex
  Seedbox Host:  not mapped

Logical dataset: tv
  MediaHub Host: /media/tv             read-only for Plex
  Seedbox Host:  not mapped
```

These are examples, not deployment defaults. `tv` may map to an existing folder
named `shows`; no renaming is necessary. Backups, appdata, temp and custom storage
use the same model. A mapping is unique per logical dataset/host pair.

`dataset_ref` is an administrator assertion identifying the intended underlying
dataset. It does not prove that two paths contain the same data. Capacity is
reported per filesystem and must not be added across duplicate mappings.

The Core registry resolves app storage slots on the **selected host**, checks
the mapping's maximum access, then requests live inspection from that Agent.
A read-only mapping cannot satisfy a read/write app requirement. Unknown hosts,
missing mappings and inaccessible directories block the plan. Directory inspection
is advisory and does not prove the future app UID can write; app-user checks are
required before any future installation. No file contents are read by inspection.

The Storage media browser reports recursive folder sizes as metadata and can
stream administrator-approved uploads from the browser to the local Agent. Core
does not mount the media filesystem and does not buffer an entire upload in RAM
or on its system disk. The Agent accepts only a single basename inside the
selected registered media root, writes a hidden same-directory partial file,
and publishes it atomically only after the complete body is durable. Existing
files are never overwritten. Technical `appdata`, `backups` and `temp` locations
cannot receive browser uploads.

## Permissions and isolation

- Seedbox gets a downloads-only server-side export/share. Do not export the whole
  media root and rely solely on a Docker mount restriction to isolate a VM.
- Plex media mounts remain read-only. Its configuration and transcoding cache get
  separate writable app-data paths; transcoding does not require writable media.
- Use planned numeric UID/GID and group inheritance; no `chmod 777` or recursive
  ownership rewrite of existing media.
- Unprivileged LXC IDs are translated to host IDs. Inspect actual UID/GID maps;
  UID 1000 in a guest is not automatically UID 1000 on the NFS client/server.
- NFS AUTH_SYS trusts client-supplied IDs. `root_squash` alone does not prevent a
  compromised client from asserting another UID. Use narrow per-client exports,
  dedicated identities/all_squash where appropriate, and network isolation; use
  authenticated/encrypted transport where the threat model requires it.
- NFS/SMB access on a private LAN does not traverse an Internet VPN automatically.
  Encryption in transit requires a separately configured suitable transport.

## qBittorrent, Plex and *arr compatibility

Applications see the same completed/partial files without making duplicate media
copies. Keep incomplete downloads separate from library scanning where practical.
qBittorrent retains its data path while seeding; Plex may read completed torrents.

For Sonarr/Radarr hardlink imports, source and destination must be on the same
filesystem and visible through a suitable common parent mount to that trusted
application. Separate Docker mounts can cause cross-device failures even when
their sources share a disk. Plan a common `/data` view for trusted importers if
needed; this does **not** justify giving the Seedbox VM access to movie/TV roots.
Test hardlink support, device IDs and permissions on the actual NFS/export layout.
USB and main-disk filesystems cannot share hardlinks. Never silently fall back to
copying entire media files when the installation policy forbids copies.

## Mount lifecycle and backup

Later deployment must fail closed if a required mount disappears. Check mount
identity before app start (not just directory existence), order apps after mount
availability, and avoid creating downloads in an empty local mountpoint. Prefer
hard NFS mounts for data integrity, with monitoring for blocked I/O and recovery.
No soft-mount retry policy should be selected merely to hide outages.

Backup the authoritative dataset once, plus Core DB/config/encryption keys and
Agent identity separately. Shared mounts are not automatically included in LXC/VM
backups, and a second mount is not a backup. Coordinate SQLite backups correctly;
copying an active database without its transaction state is not a backup strategy.

## Implementation boundary

Implemented: registry and API/UI for logical metadata, host paths, access ceilings,
Agent validation, host-specific app-plan resolution, bounded media browsing,
streamed no-overwrite uploads and fail-closed mount checks.
Deployment documentation supports narrow NFSv4 sharing between a storage owner
and an isolated Seedbox. MediaHub itself deliberately does not format disks,
invent exports, migrate media, rewrite ownership recursively or attach writable
raw filesystems to multiple guests.

References: [NFS administration](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/configuring_and_using_network_file_services/deploying-an-nfs-server_configuring-and-using-network-file-services),
[Servarr Docker storage guidance](https://github.com/Servarr/Wiki/blob/master/docker-guide.md).
