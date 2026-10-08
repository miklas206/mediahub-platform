# Secret custody and RAM-only runtime

The generic `mediahub.secret_store.SecretStore` stores bounded opaque encrypted
records. Application adapters validate their schemas; public APIs return only
configured metadata, never decrypted values. Exclusive record creation prevents
silent replacement. The local `replace` primitive writes authenticated ciphertext
to an exclusive 0600 temporary file, fsyncs and atomically replaces an existing
record. It rejects unsafe/missing records and removes only its own encrypted
temporary file. The caller must hold the operation lock and block runtime first.
This primitive alone is NOT a completed/deployed VPN or password rotation workflow.

## Threat model

Fernet provides authenticated encryption. The local master key and store directory
are restricted to the service account (0600 files / 0700 directory). The master key
is the protected root of trust for unattended restart: it is not itself encrypted
with another colocated key. This protects database-only exports and accidental
file disclosure, **not** a compromised host root or a full-disk theft containing
both ciphertext and its key. Stronger offline protection requires an external
unlock mechanism, hardware-backed key, or encrypted disk with independent unlock.

Do not include keys or decrypted records in Git, container build contexts, image
layers, environment variables, arguments, frontend storage, URLs, logs or exports.
Back up encrypted records and their key separately with restricted access.

## Seedbox runtime

The deployment-owned `secrets` directory is a dedicated Linux tmpfs with
`noswap,noexec,nosuid,nodev`, mode 0700, bounded size and service UID/GID.
`RuntimeSecrets` checks the actual mount and permissions and refuses ordinary
filesystems. Active swap blocks provisioning. Containers additionally have
`MemorySwap == Memory` and core-dump soft/hard limits of zero.

The Agent reads qBittorrent API credentials from a 0600 RAM file. The VPN receives
only its config via a read-only file bind. qBittorrent receives neither the vault
nor the plaintext API-password file; its own persistent config stores a password
verifier. Host root and Docker administrators remain trusted principals.

At VPN stop, the two RAM files are truncated while preserving their inodes for
Docker binds. Gated start reconstructs them from authenticated ciphertext before
starting the VPN. Downloads still require independent storage/tunnel checks.
The host oneshot service prepares RAM before Docker starts after reboot; failure
blocks that dependency instead of falling back to disk. The host helper disables
core dumps and process dumpability before reading credentials.

Python and VPN software necessarily retain transient secret bytes in process
memory. Reliable language-level zeroization of every immutable copy is not
claimed. No-swap and disabled core dumps prevent normal memory persistence;
privileged debugging, host compromise and hypervisor memory snapshots remain
outside this protection.

## Migration and verification

1. Encrypt existing material and compare a decrypted roundtrip before mutation.
2. Stop only the explicitly scoped new runtime.
3. Preserve the old files temporarily; mount an empty dedicated tmpfs.
4. Restore from ciphertext, recreate scoped file binds, verify gated runtime.
5. Test stop clears RAM and start reconstructs correctly.
6. Compare the legacy files against both ciphertext and RAM, then unlink only
   those exact verified files. Keep the encrypted recovery record.
7. Scan known plaintext values without outputting values, including local Docker
   storage and logs. Report scan exclusions and unavailable credentials honestly.
8. Verify reboot, fail-closed, storage failure and recovery.

Unlinking files is **not** forensic erasure of SSD blocks, journals, hypervisor
snapshots or historical backups. Previously persisted credentials should be
rotated after migration if that historical exposure is in the threat model.

This document describes the new Seedbox credential path. It does not claim that
existing Agent pairing tokens, TLS keys or Core stores have already been migrated
to the same runtime materialization model. Final security review must cover them.
