# Historical prototype security boundary

> This is the historical Phase 2/3 record. It does not describe v0.2.0.
> Current release: browser HTTPS is built in, Core–Agent TLS is validated,
> TOTP/recovery codes are implemented, and runtime app secrets use protected RAM.
> Read [current security guidance](../SECURITY.md), [certificate lifecycle](certificates.md),
> [secrets](security/secrets.md) and [installation](install.md) instead.

Core uses Argon2id administrator passwords, authenticated sessions, HttpOnly cookies, CSRF checks
and explicit allowed origins. Loopback HTTP is the development default; TLS is required for exposed
deployments and is provided by the operator's proxy. No reverse proxy, DNS, router or firewall is
automatically configured. 2FA/SSO is not implemented in the new Core in this phase.

Unclaimed installations do not require an installation token. Do not publish an unconfigured
instance: the first visitor can create its administrator. Admin creation is rate-limited. Installation progress is separate from
account existence. Authenticated setup revisions prevent silent concurrent draft overwrites.

Manifest secret fields are encrypted with a locally generated Fernet key. Read APIs return only
configured flags; discovery returns sanitized metadata. Encryption protects a database-only leak,
not a compromised host with both key and database. Back up the key securely with the new database;
losing it makes saved secrets unrecoverable. Never commit `.data`, `.agent`, `.qa`, `.env`, credentials
or production configurations. These directories are ignored by Git.

Agent token authentication does not make a public plain-HTTP Agent safe. Keep it private. Core has
no Docker socket. See [Agent](agent.md) for the optional socket's root-equivalent risk and
[Storage](storage.md) for filesystem limits. No execution endpoint accepts user-provided shell code.

Phase 2 is a tested development foundation, not an audited production security product. It does not
hide ISP metadata, modify VPN routing or prove any existing service secure. Existing services remain
outside this development trust boundary.

Phase 3 retains these limits. LAN HTTP is explicitly limited to the trusted LAN and is
not encrypted; do not reuse valuable passwords or expose it publicly. Remote pairing
refuses HTTP. Hosts and logical-storage mutations require existing authentication and
CSRF protections. Registered remote Agents are powerful trusted peers, not untrusted plugins.
Only Agent receives the Docker socket; the read-only bind flag does not remove its
root-equivalent power inside the enclosing LXC. No Proxmox management credentials or
existing media mounts belong in either Core or Agent containers.
