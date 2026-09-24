# Phase 4 backup and restore boundaries

Back up Core and Seedbox separately. A VM snapshot or a second mount of the same
storage is not an independent backup. No production data migration is performed by
these checks, and no remote/offsite backup destination has been provisioned.

## Recovery set

| Component | Required recovery material |
| --- | --- |
| Core | Consistent SQLite backup, encryption key, deployment environment and Compose overlays, exact image digest |
| App and host mappings | SQLite settings, installed_apps, app_configurations, logical_storage, host_storage and hosts |
| Paired Agents | Agent state/identity and token, matching encrypted Core host token, CA trust and valid server certificates |
| Seedbox | installation.json, wizard.json, install-transaction.json, install-ownership.json, lifecycle.json, credential-rotation.json if present |
| Private inputs | Encrypted vault records **and** separately protected master key; losing the master key prevents decryption |
| qBittorrent | Entire persistent appdata directory, including configuration and BT_backup torrent/resume state; stop the client for a consistent application backup |
| VPN | Non-secret provider/protocol/region metadata, exact image, encrypted private profile; do not back up decrypted RAM files |
| Host | Agent policy, logical mount mapping, device requirements, NFS mount/guard configuration, protected tmpfs service and its dependency on Docker |
| Actual media | Separate storage-aware backup plan; not copied by Phase 4 |

Never export plaintext profiles, passwords, HTTP cookies or decrypted Agent tokens.
Keep master keys and private TLS/identity material in a separately access-controlled,
encrypted recovery system. Do not place them into a public repository or browser.
The original private key must never be copied to a Windows client for deployment.

## Restore rehearsal without starting services

1. Restore a consistent SQLite copy to a separate file. Check integrity, foreign
   keys, migration revision and the presence of settings, mappings and identities.
2. With the matching original encryption key available only in process memory,
   verify encrypted records can be decrypted. Never print decrypted data.
3. Validate each recovered encrypted Seedbox record against its matching master
   key in memory. Verify private directory 0700 and files 0600 with the Agent UID.
4. Validate qBittorrent backup inventory, file ownership and consistency while
   stopped. Do not start a second client with the same torrent state/passkey.
5. Restore mount and device policies before runtime. Missing NFS must continue to
   block startup, and the underlying mountpoint must not become a writable fallback.
6. Recreate protected non-swappable tmpfs, disable core dumps and materialize
   runtime secrets from the encrypted vault. Never restore plaintext RAM files.
7. Revalidate TLS chain, SAN and expiry. An invalid certificate must block pairing
   and remote control. Re-pair explicitly if identity cannot be recovered safely.
8. Reconcile interrupted transaction ownership before starting containers. Run
   storage, VPN, forwarded-port and qBittorrent gates before enabling recovery.
9. Only after an isolated restore passes may a separate migration plan be approved.

The QA restore validation does not prove recovery after total host loss without an
external recovery copy. It proves database consistency and encrypted-record/key
compatibility. The final acceptance report records which checks ran live.
