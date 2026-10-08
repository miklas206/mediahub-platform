# Core configuration backups

Open **Backups** and select **Download encrypted backup**. Confirm your current
password and, if enabled, an authenticator or recovery code. Choose a separate
backup password with at least 16 characters. Keep the downloaded `.mhbackup` file
and password separately. The password is not retained by MediaHub.

The export includes a consistent SQLite online snapshot, settings, logical
storage mappings, encrypted Core secrets, their protected local encryption keys,
and the catalog encryption key. Browser sessions and unused pairing requests
are excluded from the restored database.

It does **not** include media, Plex databases/metadata, Seedbox state, host
certificates, the private certificate authority, Compose files, or host mounts.
Those require separate protected backups. This feature is not a complete server
or disaster-recovery backup.

## Encryption and verification

Archives use AES-256-GCM with a unique random salt and nonce. Scrypt derives the
key from the backup password (`N=32768`, `r=8`, `p=1`). The format identifier is
authenticated. Plaintext ZIP/SQLite snapshots remain in process memory; only
the encrypted export is sent to the browser. Export requires administrator
authentication, CSRF, reauthentication and HTTPS outside development mode.

Every export is decrypted in memory and checked for ZIP corruption and SQLite
integrity before download. The uncompressed Core configuration limit is 64 MiB.
Only one export can run at a time. No media folders are traversed.

To verify a saved archive without writing its contents:

```sh
mediahub backup-verify --backup-file /secure-backups/mediahub-core.mhbackup
```

The password is requested privately, never as a command argument.

## Offline restore to a new directory

```sh
mediahub backup-restore --backup-file /secure-backups/mediahub-core.mhbackup \
  --restore-directory /srv/mediahub-restored
```

The parent must exist. The destination must **not** exist; restoring over an
existing installation is rejected. MediaHub validates the authenticated archive,
allowed paths, size limits and database before creating the new directory.
Files are created with mode 0600 and directories with 0700 on Unix.

Restore into an isolated deployment first. Restore the matching deployment
certificates/trust and Agent credentials separately; paths and logical mappings
must still point to the intended data. Stop the old Core before switching the
deployment to the new Core data directory. Never run two active Cores against
the same SQLite database. Sign in again after restore; old browser sessions do
not survive. Do not change or format any media filesystem during Core restore.

Test recovery periodically. A successful configuration export is not evidence
that media or app databases have a backup.
