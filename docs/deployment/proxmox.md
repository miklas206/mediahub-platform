# Proxmox architecture

The platform is generic: one trusted Docker host or multiple Agent hosts are both
supported by the registry. The selected installation uses an unprivileged MediaHub
LXC for Core/Agent and future trusted apps, with a separate isolated Seedbox VM.
Core does not assume all apps run locally.

See [LXC deployment](lxc.md), [Hosts](../hosts.md) and [Shared storage](../shared-storage.md).
Private guest IDs, IPs and discovered paths are stored in ignored instance reports,
not defaults or sample manifests.

Before creating a guest verify ID, capacity and current topology. Existing VM disks
must not be mounted concurrently read/write to obtain a convenient media path.
Record current NFS/SMB ownership and client bindings. A media-owning source guest
cannot be retired until a separate storage cutover is explicitly planned and tested.

Phase 4 tests do not stop old Plex/qBittorrent/VPN, change production mounts or
install a reverse proxy. Fault injection/reboot targets only the new Seedbox VM
and its isolated test storage. The media disk stays on the old guest until a
separately approved migration. Stable raw SCSI by-id mapping remains preferred.

Core updates preserve browser HTTPS, internal Agent HTTPS, trust roots, ports,
mounts and environmental settings. Retain every active Compose override when
redeploying: omitting a later TLS or RAM-secret overlay is not a valid rollback.
Take a consistent SQLite backup before Core replacement and keep the old image
and complete deployment configuration. Scope guest SSH setup access narrowly,
remove only the exact added public-key line and test fresh authentication rejection.
