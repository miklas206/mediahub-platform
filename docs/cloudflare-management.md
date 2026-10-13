# Cloudflare tunnel management

The App Store Cloudflare page has optional API management alongside the existing
read-only monitor. Connect a scoped Cloudflare API token and account ID, create
a remotely managed tunnel, then bind a DNS hostname and zone ID to MediaHub,
MediaSeed or MediaVPN. The token is encrypted with the existing private SecretStore.
It is never returned by configuration/status endpoints or written into logs.
Management endpoints require HTTPS, administrator access and CSRF for mutations.

Permissions: account Cloudflare Tunnel Edit (Cloudflare Tunnel Write in the API),
and Zone Read plus DNS Edit on the selected DNS zones. A connector token is not an
account API token. Only tunnels created and recorded by this MediaHub can be managed.

## Connector

Creating a tunnel creates its Cloudflare resource; it does not deploy cloudflared.
Download its connector token using the administrator-only download button and
place the token file on the connector host with restrictive permissions. For example:

```sh
cloudflared tunnel --no-autoupdate run --token-file /path/to/cloudflared-token.txt
```

Use a recent cloudflared supporting --token-file. The connector must reach the
apps' local addresses. For local HTTPS, provide MediaHub's public CA certificate
on the connector at the configured CA path (default
/etc/cloudflared/mediahub-ca.pem). This is a public CA certificate, never the CA
private key. Certificate verification is enabled; each origin certificate must
cover the currently published local IP. Existing monitor metrics remain optional.

## App-bound routes

The background reconciler runs once per minute. It resolves the hub's configured
local origin, or reads the owned MediaSeed/MediaVPN web container's live Docker
published IP/port. It never targets the app's external address (which would create
a tunnel loop). Stopped, removed or unreachable apps keep their last route and
show an error. Plain HTTP is only supported when that is the explicitly configured
local hub/app endpoint; managed app web endpoints remain HTTPS.

A binding creates a proxied CNAME to <tunnel-id>.cfargotunnel.com and an ingress rule.
DNS remains pointed at that tunnel when app IP/port changes. Unchanged endpoints
cause no Cloudflare calls in the background. Manual Synchronize now rechecks all
linked routes. Per-route Follow app IP and port disables/enables the background
updates. Credentials and route journals survive Core restarts.

Existing DNS records with different destinations, duplicate/path-matched ingress
rules, externally changed origin services, and configurations changed during the
read/update sequence are treated as conflicts. Other ingress rules and origin
options are preserved. Cloudflare does not provide a transactional lock spanning
DNS and configuration writes; partial publishing is saved and retried without
recreating an already matching CNAME. A timeout during tunnel creation may require
checking the Cloudflare dashboard before attempting another creation.

Publishing an app explicitly fills its optional external address only if no
external address was already saved. Publishing MediaHub adds that exact hostname
to its trusted browser origins and restores it from the route journal at startup;
unknown hosts remain rejected. No wildcard browser host is accepted.

Disconnect account removes local API credentials and stops reconciliation. It does
not delete tunnels, DNS records or existing connectors. Existing monitor profiles
remain independent. There is no automatic import, deletion or replacement of
existing manually administered tunnels in this release.

API contract:
- GET /api/v1/cloudflare/manage: redacted account, tunnel and route status.
- PUT/DELETE /api/v1/cloudflare/manage/credentials: connect/rotate/disconnect.
- POST /api/v1/cloudflare/manage/tunnels: create a remote tunnel.
- POST /api/v1/cloudflare/manage/tunnels/<uuid>/token: no-store token download.
- POST /api/v1/cloudflare/manage/routes: publish an app binding.
- PUT /api/v1/cloudflare/manage/routes/<id>: toggle automatic sync.
- POST /api/v1/cloudflare/manage/sync: explicitly reconcile linked routes.

Cloudflare references:
https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/
https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/

Validation uses a simulated Cloudflare API and Docker metadata. No live account,
DNS, connector, production service or beta runtime is changed by these tests.
