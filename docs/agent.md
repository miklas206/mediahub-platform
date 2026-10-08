# Agent trust and privileges

Core calls a versioned Agent API with a generated Bearer token. `mediahub agent-init` creates
the token locally using exclusive creation; it does not print it or replace an existing token.
Core reads the same token file. On Linux state is 0700 and the token is 0600. On Windows keep
the development checkout under a private user ACL: POSIX modes do not replace Windows ACLs.

Default Agent bind is 127.0.0.1:18767. Core accepts loopback or the fixed private Compose service
hostname `agent`, not arbitrary user-supplied remote URLs. Agent endpoints require authentication,
including health/version. Access logging is disabled. HTTP is suitable only for this local/private
trust boundary, not for untrusted networks. Future multi-host operation requires TLS/mTLS, pairing
and rotation design. Phase 3 adds a separate HTTPS-only remote host registry and pairing flow;
see [Hosts](hosts.md). The local transport restriction remains unchanged.

Endpoints: `/v1/health`, `/v1/version`, `/v1/status`, `/v1/discovery`, `/v1/directories`,
`/v1/directories/inspect`, `/v1/directories/create`. Last two use POST; only create changes the
filesystem and requires an allowed root, explicit enablement and exact path confirmation.
No container lifecycle, file-content reading, shell execution or log retrieval endpoint exists.

Filesystem access is the intersection of configured roots and Agent OS permissions. Prefer a
dedicated non-root UID with access only to new app directories. Core has no Docker socket.
Development Compose Agent has no Docker socket either. Production read-only inspection sets
`MEDIAHUB_AGENT_DOCKER_SOCKET` to an explicitly mounted engine socket in Agent only. **A socket
bind marked read-only is not a read-only Docker API and remains effectively root-equivalent**;
the current adapter allowlists GET calls but compromise of Agent would bypass that code boundary.
The current deployment explicitly accepts this risk inside a dedicated unprivileged LXC.
No lifecycle API is exposed yet; a restricted socket gateway remains a future hardening option.

Runtime health is not VPN health. No claims are made about production VPN routing, kill-switches
or tracker connectivity. Missing Docker and Compose are reported rather than simulated as healthy.
