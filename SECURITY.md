# Security policy

v0.3.0 targets authenticated private/LAN deployments over HTTPS. Public Internet
exposure has not been enabled or independently security-audited.
Before a public GitHub release, maintainers must enable private vulnerability reporting and publish
a monitored security contact. Do not post secrets or exploitable production details in public issues.

## Current protections

- Argon2id password hashing; no default account or password.
- Random session cookies, SHA-256 token hashes in SQLite, expiry and logout revocation.
- HttpOnly + SameSite=Strict cookies; Secure automatically when base URL uses HTTPS.
- CSRF tokens for authenticated mutations, exact origin checks and Host validation.
- Explicit trusted proxy addresses only. Forwarded headers are ignored by default.
- One-process login rate limiting; no reliance on a client-supplied forwarded IP.
- SQLAlchemy parameterized queries, strict request models and non-secret API errors.
- Scoped logical storage, read-only Plex media and fail-closed Seedbox mount checks.
- Verified TOTP enrollment, hashed one-use recovery codes and session management.
- Encrypted durable application secrets and restricted RAM-backed runtime files.
- Application-authored structured logs only; no passwords, headers or request bodies.

Local development HTTP is unencrypted. Production browser HTTPS terminates in Core;
internal Core–Agent HTTPS validates CA trust and hostname/IP. DNS and remote access
remain the operator's responsibility and are not enabled by installation.
Never treat an external proxy as permission to bypass application authentication.

## Runtime boundary warning

A Docker socket mounted read-only is NOT a read-only API. It can confer effective control of the Docker
host (the LXC in the target architecture). Only the trusted Agent receives this socket,
not Core. Agent enforces ownership, capabilities, storage scope and safe command types.
The socket is still an administrator trust boundary; do not treat it as a sandbox.

The database contains password hashes and active-session CSRF values; protect its directory. Unix
startup uses owner-only permissions for the Core data directory. Windows inherits the current user's
directory ACL; review it for a shared PC. Encryption protects a database-only leak,
not a compromised host with both keys and encrypted data. OIDC and an independent
security audit remain future work. Protect encrypted backups and their passwords.

Secret-bearing services have swap/core dumps disabled. Application credentials
must not be committed, logged or returned by status APIs. Server TLS and vault
master keys remain on the server with restricted ownership; public CA material
alone belongs on clients. See [certificate lifecycle](docs/certificates.md).

VPN protection hides torrent peers/content from the ISP, not the VPN endpoint or
traffic volume, and is not a promise of anonymity. Missing tunnel/forwarding/storage
checks block qBittorrent. Configuration backups do not back up the media collection.
