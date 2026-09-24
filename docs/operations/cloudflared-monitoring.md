# Cloudflared monitoring

MediaHub can display read-only Cloudflare Tunnel health without receiving the
tunnel token or administrative access to the Cloudflare host.

When the status endpoint is configured, MediaHub registers **Cloudflare
Tunnel** as an optional infrastructure app. It appears in Apps, in the app
shortcut menu and on the Updates page. Its app view shows the current tunnel
connections, observed cloudflared version, sanitized request counters and the
result of every configured public route probe.

`scripts/cloudflared_status_proxy.py` runs beside cloudflared. It accepts one
explicit source IP, reads cloudflared's loopback-only Prometheus endpoint and
returns only version, HA connection count and request/error counters. It has no
restart, configuration or token endpoint and emits no request log.

Core uses `MEDIAHUB_CLOUDFLARED_STATUS_URL` for that private status endpoint.
`MEDIAHUB_CLOUDFLARED_PROBE_URLS` is an optional JSON list of HTTPS URLs. These
probes distinguish an established Cloudflare tunnel from a public hostname whose
origin is unavailable. HTTP 5xx and connection failures are unhealthy; redirects,
authentication challenges and ordinary application responses prove the route is
reachable.

The status helper should be bound to the Cloudflared container's LAN address and
restricted to the MediaHub Core address. Never expose it to WAN. A tunnel token,
Cloudflare API token or account credential is neither required nor accepted.

## Release checks

The app can compare the observed cloudflared version with the latest stable
release from the fixed official
`cloudflare/cloudflared` GitHub repository. Release metadata is size-bounded,
semantic versions are validated and the release link is generated for that
allowlisted repository rather than trusted from the response.

MediaHub does not install the update or restart cloudflared. Cloudflare's
supported update procedure depends on whether the installation uses a package
manager, Docker or a standalone binary, and an update can briefly interrupt
tunnel traffic. The app therefore reports the result and links to the official
release while keeping the service read-only.

Cloudflare Tunnel remains optional. Adding this app does not create a tunnel,
publish a hostname, modify DNS, open a router port or make Cloudflare a runtime
dependency for MediaHub.

## Planned App Store installation

The catalog entry is marked **coming soon** until a rollback-safe installer is
implemented. Its guided setup metadata already describes the intended flow:

1. The user selects a new or existing remotely managed Tunnel.
2. The user supplies a public hostname and MediaHub's private HTTPS origin.
3. The user pastes only the Tunnel connector token. MediaHub does not request a
   Cloudflare account API token.
4. The connector token is encrypted at rest and materialized only for the
   cloudflared runtime when the installer is implemented.
5. MediaHub verifies local connector health, Cloudflare links, the public route,
   HTTPS origin validation and realtime WebSocket/SSE behavior.

The future installer must require explicit confirmation before creating a
container or publishing a hostname. Until that lifecycle exists, the catalog
can save encrypted draft configuration and preview requirements, but it cannot
execute an installation.

The supplied `docker/mediahub-cloudflared-status.service` runs as `nobody` with
a read-only filesystem and no elevated capabilities. Put only the listen IP,
allowed Core source IP and loopback metrics URL in
`/etc/default/mediahub-cloudflared-status`; the file contains no Cloudflare token.
