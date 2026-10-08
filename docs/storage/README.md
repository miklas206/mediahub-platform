# Storage foundation

A StorageLocation records a user-selected existing path and logical kind. StorageMapping defines future
app access by app ID, location ID, container target and ro/rw mode. Mapping tables do not mount anything
in this phase. The only storage writes are records in the new Core database.

Validation resolves the path, checks that it is inside administrator-configured roots, then reports:
directory existence, read/traverse access, advisory write/traverse access, free bytes and total bytes.
No mkdir, move, delete, chmod, chown or write probe runs on registered paths.

`os.access` is advisory. ACLs, server-side NFS policy and changes between check and use can affect actual
access. This phase reports permissions, not a guarantee that future writes will succeed. Mount UUID
validation, TOCTOU-safe file operations, NFS/SMB mounting and user/group mapping are later implementation.

Symlinks resolve before allowed-root validation. Actual writable operations must not be added to this
read-only implementation without a new descriptor-based path authorization design.

Do not register `/`, a Windows drive root, your home directory or the old production media root just
to make development convenient. Keep Phase 1 approved roots narrow.
