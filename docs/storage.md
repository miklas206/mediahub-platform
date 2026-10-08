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

## Browser uploads

In Storage, select the media location and destination, then choose **Upload**, followed by
**Files** or **Folder**. Folder upload includes the selected folder and its subfolders; empty
folders are not provided by the browser. Existing directories are reused, while existing
files are never overwritten. Folder creation requires the local Agent's creation policy
to be enabled. Technical App Data, Backups and Temporary locations cannot receive uploads.

Uploads use tus-js-client, a sequential queue and 5 MiB requests, so large files do not require a single
large proxy request or buffering the entire file in memory. The file limit is 512 GiB,
subject to available space; a selection may contain up to 10,000 files and 32 folder levels.
Keep the page open. This is not a persistent transfer manager: reopening the page does
not automatically resume a previous selection.

**Stop** beside a file's progress cancels that file; **Stop all** cancels the active file
and the remaining queue. Completed files remain. Unfinished data is written to hidden
temporary files and published without replacement only after all bytes are acknowledged.
The Agent serializes writes and cancellation. A lost chunk response is reconciled against
the stored offset before retrying, preventing duplicated data. Cancel removes the temporary
file; if the browser loses connectivity before cancellation reaches the Agent, abandoned
sessions are cleaned after 24 hours of inactivity, checked every 30 minutes. Empty directories
created for an interrupted folder upload may remain. Core and its local Agent must both
be upgraded to 0.4.15 or newer for the tus upload controls. The authenticated creation API
allocates a session; tus-js-client transfers via its upload URL using HEAD/PATCH. The
existing finish API publishes the completed file and the cancel API removes unfinished data.

Capacity is per filesystem, not the sum of logical folders on the same disk. MediaHub does not
format disks or attach raw filesystems. Container paths and host mounts must be mapped explicitly;
appdata and VPN appdata slots are separate to avoid configuration collisions.

## Seedbox isolation

The Seedbox receives only its explicitly delegated Downloads mapping. It does
not need Movies, TV or App Data access. Missing mount observations, an unexpected
source or marker, and failed app-UID permissions block startup. The local backing
mountpoint must not become a writable fallback, even for root. Restore storage
first, verify its identity and permissions, then let the Agent restart VPN and
qBittorrent through the normal fail-closed sequence.
