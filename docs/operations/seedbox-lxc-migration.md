# Seedbox LXC migration preparation

## Current boundary

Read-only inspection on 2026-10-06 found Seedbox in Proxmox VM 104
(`mediahub-seedbox`, LAN address `192.168.1.148`) and MediaHub in LXC 102.
VM 104 has one 24 GiB virtual system disk. The Seedbox mounts `/data/downloads`,
`/data/movies`, `/data/tv` and `/data/other` from Proxmox NFS exports.
The host media filesystem is mounted at `/mnt/mediahub-storage` using mergerfs.
These are observations, not permanent identifiers; verify them before acting.

The user authorized preparation and testing only, not a production switch.
There is no separate media backup. Do not stop VM 104, change MediaHub pairing,
create writable production mounts, change ownership recursively, move media,
format disks, remove guests or prune Docker volumes during this phase.

## Read-only preflight

From a reviewed checkout on the Proxmox host:

```sh
bash scripts/seedbox-lxc-preflight.sh 104 /mnt/mediahub-storage
```

The script reads current configuration, rejects an unmounted media directory and
unexpected VM disks, and reports the mount and VM network interfaces. It does not
provision an LXC or establish migration readiness. Output excludes cloud-init
passwords, SSH keys and application credentials. Keep network reports private.

## Isolated trial requirements

1. Choose a new, unused CT ID and LAN address. Keep VM 104 and LXC 102 unchanged.
2. Prepare a dedicated unprivileged Debian/Ubuntu LXC with Docker nesting, the
   required Agent resources and explicit VPN TUN access. Review compatibility
   with the existing fail-closed VPN setup before installing the application.
3. Use only new system and application-data storage. Do not clone live torrent
   state or credentials into a running torrent service. Use a disposable test
   downloads directory, never production downloads, for write tests.
4. If inspecting existing media, expose only explicitly approved read-only
   folders. Do not expose the storage root: it may include private app data.
   Confirm the effective mount is read-only and the app cannot modify files.
   Preserve current file ownership; map guest users rather than changing media.
5. Do not mount a physical disk directly or create another mergerfs pool inside
   the guest. Review host FUSE/bind-mount and Proxmox backup behavior separately.
6. Test the scoped Agent, VPN connectivity and traffic blocking on VPN failure,
   torrent controls against disposable data, logs and version/update reporting.
   Do not repoint the production Seedbox integration to run these checks.

## Trial result on 2026-10-06

LXC 103 (`mediahub-seedbox-trial`) was provisioned from the cached Debian 13.6
template with a new 16 GiB system disk, 2 cores, 4 GiB RAM, no swap and automatic
start disabled. It has no production downloads mount, credentials or pairing.
Its only media mount is `/mnt/mediahub-storage/media/movies` at `/data/movies`,
configured read-only. Runtime checks confirmed the effective VFS mount is
read-only, the directory is readable/traversable and `/dev/net/tun` is accessible.
No write to media was attempted. The trial was stopped after the checks.

The preparation script is `scripts/prepare-seedbox-lxc-trial.sh`. It refuses an
occupied CT ID, missing source VM, missing media mount or symlinked movie path.
It must not be rerun against LXC 103: the existing-ID guard will reject it.

Proxmox warned that thin volumes are overprovisioned and automatic thin-pool
extension protection is not enabled. Actual pool data usage was 63.53% after
provisioning. Do not expand the trial or copy application data before reviewing
capacity and monitoring. No storage settings were changed to suppress warnings.

Docker, Agent pairing, actual VPN operation/failure blocking, torrent state and
MediaHub lifecycle/update integration remain untested in the trial. This is only
a storage/device feasibility check, not a completed migration.

## Later switch: separate approval required

Before switching, identify the real Docker mounts and persist all configuration,
Agent trust/enrollment data, VPN settings, qBittorrent configuration and
`BT_backup` torrent/resume state. Store a protected, verified configuration backup
outside both guests. Configuration backup does not back up media.

Require explicit approval for a download pause. Stop the old torrent writer
before taking the final consistent state copy or granting the new writer access.
Keep the same in-container download paths, verify UID/GID access without changing
existing permissions, and enroll the new Agent through MediaHub's supported
verified HTTPS flow. Do not reuse the old IP while it is still assigned.

Check torrent paths and retained state, VPN failure blocking, MediaHub controls,
logs and updates before accepting the switch. Keep VM 104 and its system disk as
rollback; do not delete them as part of migration. Rollback requires stopping the
new writer first and reviewing any torrent state changed since the switch.

Until a separate media backup exists, no procedure can guarantee recovery from
disk failure or all operational errors. Do not present this plan as a guarantee
that the only copy cannot be lost.