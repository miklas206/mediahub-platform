# Cloudflare tunnel management

The App Store Cloudflare page has optional API management alongside the existing
read-only monitor. Connect a scoped Cloudflare API token and account ID, create
a remotely managed tunnel, then bind a DNS hostname and zone ID to MediaHub,
MediaSeed or MediaVPN. The token is encrypted with the existing private SecretStore.
It is never returned by configuration/status endpoints or written into logs.
Management endpoints require HTTPS, administrator access and CSRF for mutations.

Permissions: account Cloudflare Tunnel Edit (Cloudflare Tunnel Write in the API),
and Zone Read plus DNS Edit on the selected DNS zones. A connector token is not an
account API token. Tunnels must be created through MediaHub or explicitly selected
from the discovered remotely managed tunnels before MediaHub can manage them.

## API discovery

Connecting an API token automatically fetches the account's accessible zones,
existing DNS records and Cloudflare tunnels. Lists are paginated; exceeding the
bounded fetch limit is reported rather than silently hiding records. TXT and other
non-address record contents are not copied into MediaHub. Partial failures retain
the previous inventory with an incomplete/access warning and disable publishing
in the connected UI. The inventory is cached for five minutes, including failures;
explicit refresh bypasses this cache at most once every 30 seconds. Normal UI
status polling therefore does not repeatedly query Cloudflare.

The connected UI replaces manual zone IDs, target IP/port and CA paths with domain,
record, tunnel and app choices. It hides the legacy monitoring editor while API
access is connected. New hostnames are generated from the chosen app/domain.
Existing proxied CNAME records may be selected when they already target the chosen
tunnel. Records pointing elsewhere are listed but never automatically converted
or overwritten. Origin resolution remains server-side, using current managed app
ports or the paired Agent; missing app setup is shown next to the selection.

Zone Read is required to list domains; DNS Read or Edit is required to list records.
DNS Edit and Cloudflare Tunnel Edit are required for the corresponding write actions.
Tunnel Read is sufficient for discovery. The UI distinguishes successful read
checks from unverified write permissions and reports the account/zone scope and
permission needed when Cloudflare rejects a request. VPN integration does not
require granting Cloudflare access to Proton credentials or WireGuard private keys.
Cloudflare routes continue to use local web origins, never VPN public IPs or torrent
forwarding ports. The existing DNS-only API remains available for compatibility;
manual IP entry is not exposed in the connected app UI.

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
remain independent. Discovery alone does not grant ownership or change remote
resources. Explicit tunnel selection only records that tunnel locally; unrelated
ingress rules and existing DNS records remain protected from replacement.

API contract:
- GET /api/v1/cloudflare/manage: redacted account, tunnel and route status.
- POST /api/v1/cloudflare/manage/discover: refresh cached API inventory.
- POST /api/v1/cloudflare/manage/tunnels/<uuid>/adopt: select an existing remotely managed tunnel.
- POST /api/v1/cloudflare/manage/routes/discovered: publish using selected IDs or a generated hostname.
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
