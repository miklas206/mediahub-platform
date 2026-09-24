# First-install security model

The 13-step wizard and production transaction adapter are deployed on the new
isolated Core/Agent installation. This describes implementation, not a blanket
Phase 4 acceptance claim; the final QA report owns the live-test result.

## Secret drafts

`SeedboxSecretStore` stages encrypted credentials on the Agent, beneath an
operator-delegated absolute private directory. On Linux the directory must be
owned by the Agent UID, mode0700; master.key and sealed records are0600.
References are identifiers, not filesystem paths. First save is exclusive and
will not overwrite an existing record. Callers must hold the installation's
operation lock. Authenticated wizard endpoints require administrator access,
browser HTTPS, CSRF and a separately trusted HTTPS Agent connection. Core forwards
private input without persisting it. Only configured flags return to the browser.

Fernet protects the sealed file from disclosure without the master key. The
master key is on the same host: this does NOT protect against Agent/root or full
host compromise. Public status returns only configured true/false. Loading is a
private provisioning operation returning secret-wrapped values, not an API result.
Ordinary credential model dumps exclude password and VPN profile fields.

VPN runtime configuration is materialized on the destination into protected,
non-swappable tmpfs with restrictive ownership and read-only VPN runtime mounts.
The secret store does not itself start services. Serialized rotation stages an
encrypted candidate, blocks automatic restart until verification, and retains
encrypted recovery information on failure. VPN rotation stops the torrent client
before applying the new profile; tunnel, NAT-PMP, storage and egress are rechecked.
No default qBittorrent password is supplied. WireGuard import accepts a restricted
data-only profile; hooks, extra sections, script directives and non-default
IPv4 routing are rejected. OpenVPN needs a separate approved adapter and is
currently rejected explicitly by the provisioning registry.

## Transaction ledger

The transaction engine persists controlled step IDs and fixed messages, not
request bodies, secrets or exception text. An interrupted process becomes
ManualIntervention on next load. Failure before mutation is PreflightFailed;
later failure calls an owned-runtime cleanup driver, then records RollbackComplete
or ManualIntervention. Disk failure cannot skip the cleanup attempt. Explicit
configuration is required before ReadyForPreflight. Installing transitions to
Verifying before authenticated API/egress/listen-port checks, and only then Healthy.
The step ledger includes obtaining and verifying the forwarded torrent port.
Invalid direct transitions (for example NotInstalled to Healthy) are rejected.

The runtime driver is responsible for verifying exact container ownership,
stopping qBittorrent before VPN, and never deleting volumes or user data. A
production adapter calls the scoped Docker runtime, checks transaction labels,
and deletes neither downloads nor persistent appdata/vault records. Existing
runtime must be explicitly verified and adopted, not silently overwritten.
Fresh qBittorrent configuration is provisioned with a password verifier in an
in-memory archive; no plaintext password is written to its persistent config.
Unit tests do not replace live fail-closed/storage/disconnection tests.

## Backup/restore prerequisites

Preserve installation ledger and reviewed nonsecret spec, logical storage/host
mappings, approved host policy, qBittorrent configuration AND state, required
image digests, nonsecret provider settings, secret references and sealed records.
The vault master key is required to decrypt sealed records and must have a
separately protected recovery backup. A database-only backup is insufficient.
Do not include plaintext VPN profiles or passwords in ordinary exports/events.

Restore must first re-establish authenticated Agent trust, validate the physical
storage source and app UID permissions, reconcile owned runtime and restore
secret availability. Missing secrets require user re-entry. Restored applications
must remain stopped until storage, real tunnel, namespace/API and egress pass.
Credential rotation is available through the private API/UI. An independent
automatic backup destination is not provisioned. See phase4-backup-restore.md
for the recovery set and restore-validation boundaries. No production migration
is authorized by this deployment.
