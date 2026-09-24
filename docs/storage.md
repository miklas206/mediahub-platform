# Storage v2

Logical types: App Data, Downloads, Incomplete Downloads, Completed Downloads, Movies, TV Shows,
Backups, Temporary and Custom. Each has its own user-selected Agent-visible path. Paths shown in
the UI refer to the **Agent filesystem**, not the browser's PC or necessarily the Docker host.

The directory browser lists approved roots and subdirectories only. It cannot read file contents.
Inspection reports exists/directory, read/write checks, owner UID/GID where meaningful, permissions,
filesystem and disk capacity. `os.access` is advisory; ACLs, network filesystems and changes between
inspection and use may still cause an operation to fail. Windows reports ACL-based ownership rather
than fabricated POSIX IDs. Missing directories use the closest existing parent for capacity.

The central path policy rejects filesystem roots, protected system paths, traversal, symlinks and
Windows reparse points/junctions. There is no override in Phase 2. Configure only narrow dedicated
roots. Linux creation walks directory descriptors with O_NOFOLLOW. Windows creation is development-only
and assumes other processes cannot maliciously change the private approved root during validation;
it does not claim a race-proof Windows security boundary against a hostile local user.

Selecting a new folder merely proposes a path. Creation requires the exact canonical path checkbox,
Agent creation enabled, and Apply. Existing folders are reused without deleting or changing contents.
Interrupted Apply may leave a newly created empty directory: retries inspect/reuse it, never delete
it as rollback. Registering or editing a mapping does not move any media or change filesystem owners.

Capacity is per filesystem, not the sum of logical folders on the same disk. No SMB/NFS mounts,
formatting, USB passthrough or production mounts are created. Future container paths must be mapped
explicitly; appdata and VPN appdata slots are separate to avoid config collisions.
# Phase 4 test boundary

The new Seedbox uses only an explicitly delegated NFS test mapping. It does not
gain access to existing downloads, movies or TV. Missing host mount observations,
wrong source/marker or failed app-UID permissions block startup. The backing
local mountpoint must not become a writable fallback, even for a root process.
Tests withdraw only the new VM's test mount; they do not modify source exports.
Shared media migration remains a separate, explicitly approved operation.
