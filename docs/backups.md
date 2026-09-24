# Configuration backups

Open **Backups** and choose MediaHub, Plex or Seedbox. Re-enter your current
administrator password and, when enabled, an authenticator/recovery code. Choose
a separate backup password of at least 16 characters. Keep it separately from
the downloaded archive: there is no password recovery.

Archives use AES-256-GCM with a fresh salt/nonce and a scrypt-derived key. They
are created and verified in memory. The server does not retain the archive or
its password. Browser download and Core–Agent transport require verified HTTPS.

| Archive | Includes | Excludes |
| --- | --- | --- |
| MediaHub | SQLite database, settings, accounts, storage mappings, encrypted Core records and the keys needed to recover them | Browser sessions, pairing invitations, media, app databases, TLS authority |
| Plex | Library databases, encrypted account preferences, installation/storage policy | Movies, episodes, thumbnails/artwork/cache, logs and TLS keys |
| Seedbox | Client state and job metadata, categories, watched folders, encrypted runtime credentials, installation/lifecycle configuration | Downloads, GeoIP cache, plaintext RAM configuration, Docker layers and TLS keys |

The selected app stops briefly to obtain a consistent configuration, then
restarts only if it was running. Seedbox restart repeats all storage, VPN,
egress and port-forwarding gates. A failed safety check leaves it blocked.
Core remains available. Exports are bounded: 64 MiB Core, 48 MiB app configuration.
Larger installations need a separate offline backup procedure.

## Verify or restore

Use a trusted offline machine with the same MediaHub version:

```sh
mediahub backup-verify --backup-file /secure/backup.mhbackup
mediahub backup-restore --backup-file /secure/backup.mhbackup --restore-directory /secure/new-restored-config
```

The password is requested privately, never as a command argument. Restore only
creates a **new** directory and refuses to replace existing files. It does not
install an app, activate credentials, mount a disk or overwrite a live database.
Review logical storage mappings, actual mount identities, ownership and host
policy before applying restored configuration. Restore deployment trust/TLS
separately. Old sessions and pairing tokens are never revived by Core restore.

For Plex, keep the app stopped while restoring its databases and encrypted
preferences vault to the corresponding new installation paths. For Seedbox,
restore into a prepared stopped installation; imported torrent jobs must be
rechecked against the real Downloads storage before they can resume. Do not
overwrite media as part of either restore.

**This is not a media backup.** A second physical copy of irreplaceable files
remains necessary. Disk health and checksums do not replace that copy.
