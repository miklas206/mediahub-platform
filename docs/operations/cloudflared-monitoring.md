# Cloudflared monitoring

MediaHub can display read-only Cloudflare Tunnel health without receiving the
tunnel token or administrative access to the Cloudflare host.

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

The supplied `docker/mediahub-cloudflared-status.service` runs as `nobody` with
a read-only filesystem and no elevated capabilities. Put only the listen IP,
allowed Core source IP and loopback metrics URL in
`/etc/default/mediahub-cloudflared-status`; the file contains no Cloudflare token.
