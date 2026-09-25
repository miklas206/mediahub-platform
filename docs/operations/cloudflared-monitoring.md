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

## App Store setup and configuration

On a fresh installation, Cloudflare Tunnel appears in **App Store**, not in the
installed Apps list. The guided flow makes every external choice explicit:

1. The user selects an existing Tunnel or follows Cloudflare's official flow to
   create and deploy a connector.
2. The user supplies the Tunnel name, published hostnames and MediaHub's private
   HTTPS origin.
3. If MediaHub uses its internal CA, the user copies only the public CA
   certificate to the connector host, configures the CA Pool path and sets the
   Origin Server Name to the certificate SAN. TLS verification remains enabled.
4. The user may provide a private cloudflared Prometheus URL for connector
   health. This endpoint must never be exposed publicly.
5. MediaHub stores the non-secret monitoring profile and verifies the public
   routes. It then appears under installed Apps, where the same data can be
   edited without repeating first-time setup.

The guided flow does not receive a Cloudflare account token, create DNS records,
install a connector process or change a remote Tunnel automatically. Connector
deployment remains an explicit Cloudflare step because it requires credentials
and host-level choices that MediaHub cannot safely infer. Multiple routes are
stored under their real Tunnel profile rather than being presented as separate
Tunnels.

The supplied `docker/mediahub-cloudflared-status.service` runs as `nobody` with
a read-only filesystem and no elevated capabilities. Put only the listen IP,
allowed Core source IP and loopback metrics URL in
`/etc/default/mediahub-cloudflared-status`; the file contains no Cloudflare token.
