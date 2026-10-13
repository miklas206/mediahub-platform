# Beta workspace promotion, 0.5.8

Main through `68b679c` was merged into beta `69d2130` before promotion. Conflicts preserve the reference workspace layout while retaining main localization and the unconfigured MediaVPN catalog entry. Backend changes relative to main are additive appearance fields only. Existing appearance payloads remain valid; navigation defaults to sidebar and existing account colors are preserved.

All five navigation layouts remain selectable in Appearance. Preview is temporary until Save; Discard returns to the saved preference. No beta account, database, app configuration, storage identity, credential or VPN profile is copied to release.

Deployment builds a new image from each target's current runtime base with reviewed backend/agent/app sources and the same frontend bundle. Dependency lockfiles are unchanged. It updates only the Core image in each target's existing Compose configuration, retaining environment, command, user, volumes and networks. The release updater source marker points to this repository's commit, while beta keeps its own source repository.

Before restart, preserve a private database backup, existing image, Compose configuration, source marker and runtime state. Capture metadata for regular files beneath the external downloads and media directories and compare it afterwards. This is a path/size/mtime/inode/mode check, not a full content hash. Existing media files and appdata are never deployment inputs or deletion targets.

Rollback uses the recorded previous image and Compose configuration. Keep the database snapshot for recovery; do not automatically overwrite newer user activity. Older releases do not expose the new appearance fields, so restore account preferences from the backup only if an old UI cannot read them. No database schema migration is required by the appearance fields.
