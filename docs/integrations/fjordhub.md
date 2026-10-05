# FjordHub external integration — verified correction (2026-09-16)

## CURRENT implementation: resources and optional FjordFlix appdata

Contract verified against [FjordHub appdata documentation](https://github.com/qlerup/fjordhub/blob/main/docs/app-data-integration.md), October 2026. Update FjordHub and FjordFlix (installed through FjordHub); select **FjordFlix** in **Settings → Access Tokens → Edit appdata access**. Docker resources remain included. Core must reach the normal private-IP origin over LAN, not a public/Cloudflare route.

Configure via Integrations or set backend-only `FJORDHUB_BASE_URL` and `FJORDHUB_ACCESS_TOKEN` (also supports `MEDIAHUB_` aliases). Both are required for environment-based setup. Explicit HTTP configuration consents to plaintext LAN token transport; prefer certificate-verified HTTPS. Startup imports the credential into the existing encrypted integration store for enabled integrations. An explicit disconnect remains authoritative across restarts. Keep environment files private; never put tokens in URLs, browser settings or logs.

`GET /api/integrations/v1/resources` retains Docker metrics and reads optional `app_data.fjordflix`, checking its own `ok` independently from top-level Docker `ok`. Old responses without appdata remain valid, without speculative calls to the separate appdata endpoint. App failures never hide resource measurements. Both retain their latest good values with separate visible stale markers; successful empty arrays clear prior data. App statuses 401/403/404/503 become fixed sanitized messages, never upstream error bodies.

Apps and Integrations show a responsive gallery of the **last 10 recently added titles**, preserving API `items` order, plus current streams (including pause/buffering). Optional metadata may be absent; seconds/pixels/Mbit/s are displayed correctly. Viewer names are private appdata available only to local authenticated users. Resource polling is sequential/nonoverlapping with a 10-second healthy interval and existing backoff/deadlines.

Posters use only authenticated local `/api/v1/integrations/{id}/fjordflix/posters/{movie_id}` requests; the browser never sees the upstream poster URL or bearer token. Only the configured origin and `/api/integrations/v1/app-data/fjordflix/posters/` path are accepted. Encoded/traversal paths, credentials, queries and fragments are rejected. No redirects/proxy inheritance; 8-second total timeout, 5 MiB limit, signature-checked JPEG/PNG/WebP, no-store/nosniff/same-origin responses and missing-image placeholders. No media playback controls, files or administrator APIs are exposed.

Local fixtures cover legacy/empty/Unicode/metadata, independent stale/recovery, image authentication/SSRF/redirect/type/size and responsive browser rendering. No live token or deployment is claimed.

## Removing an unused integration (local only)

**Disconnect** stops polling, deletes MediaHub's encrypted token and cached snapshot, but keeps the integration entry for manual reconnection. To clean up an unused entry, disconnect it first and choose **Permanently remove integration** (**Fjern integration permanent** in Danish). The confirmation names the selected integration and URL; Cancel makes no changes.

Permanent removal uses administrator/session/CSRF-protected `DELETE /api/v1/integrations/{id}`. Only that local integration record and any remaining owned token/snapshot (resources, appdata and gallery) are deleted. Posters are not stored in a separate cache. No request uninstalls FjordHub, revokes its remote token, deletes remote files, or changes apps, hosts or deployment jobs. A durable local discovery opt-out prevents this address returning automatically, including late detection/refresh results and restarts. Explicit detection/reconnection or saving that address again clears the opt-out.

Active entries return `409 integration_active` until disconnected. Entries provisioned by `FJORDHUB_BASE_URL` plus `FJORDHUB_ACCESS_TOKEN` cannot be permanently removed while those variables remain configured (`409 integration_environment_managed`). An operator must remove both variables and any `MEDIAHUB_` aliases from server configuration and restart MediaHub first; the disabled action explains this. Disconnect remains effective across restarts even with those variables present.

## HISTORICAL September 2026 catalog-only correction

The historical proposal below is **superseded**. The adapter now calls only
`GET <normal FjordHub LAN URL>/api/integrations/v1/apps` with
`Authorization: Bearer <Access Token>`. No separate API URL is needed.
The response is `{"items":[{"id":"…","name":"…","description":"…"}]}`.
This is the installable catalog, including apps NOT installed, not running apps.
All entries are rendered dynamically; no app names/count are hardcoded.

Verified sources: installed `/opt/fjordhub/app.py:759–779`, README.md:37–64,
services/auth.py:222 onward and Settings → Access Tokens. Host source and running
container `/app/app.py` have matching SHA256
`e0624ecd68ecf36cfa736de9c836acb0e73fb9f5adb12aba964c9838c4b43f8e`.
FjordHub revision: `458931c35f3ae3d5e11545ae670b354429fa7bea`.

The token does NOT offer storage, CPU, RAM, uptime, host/app health, software
version, events, SSE or WebSocket. No scope/capability-discovery or OpenAPI was
found for this token route. API version1 is in the path. `app_catalog.read` is
MediaHub's inferred capability after schema verification, not an upstream scope.
Unsupported provider methods return None without speculative requests. Other
browser/managed-app APIs are not accessed using this token.

The normal LAN URL is enough; an optional `MEDIAHUB_FJORDHUB_URL` setting pre-fills
it without installation-specific addresses in Core/UI source. Current origin
guard requires a private IP literal; DNS hostnames remain unsupported. Public
Cloudflare URLs cannot reach this LAN-only token endpoint. No forwarded client
address is forged and no LAN guard is bypassed.

HTTPS validates certificates. HTTP requires explicit consent and **does not
encrypt the token on Core→FjordHub LAN transport**. Consent is not preselected.
Browser→Core submission remains HTTPS and saved tokens remain encrypted.

Create tokens in FjordHub Settings → Access Tokens (active administrator;
30/90/365day validity). Source generates `fh_at_` plus random material and stores
a hash/metadata, not the full token. Missing/invalid/expired/revoked tokens get401
with WWW-Authenticate:Bearer; non-LAN gets403; responses are no-store. Owners must
remain active admins. No configurable scopes, installation, SSO or user-management
permission is granted. There were no tokens at discovery; none was created by us.

Live tests from Core: missing token401 and deliberately invalid non-secret token
correctly classified Authentication Failed. Actual successful catalog retrieval
awaits user token input. No fixture pass is claimed as live success.
Poll/cache/backoff, encrypted store, CSRF, admin controls, no token echo/storage
in browser and disconnect protections below remain applicable. New Test Connection
validates catalog schema and includes catalog count; unrelated200 JSON is rejected.
Display capped at200 entries with truncation warning;1MiB response limit.

## HISTORICAL PROPOSAL ONLY — not the deployed upstream contract

FjordHub is an optional, read-only external integration, never a MediaHub Agent.
It grants no filesystem, Docker or host access. Multiple independently configured
instances are stored in `external_integrations` (migration0004).

## User flow

Settings → Integrations → FjordHub, or the Integrations navigation entry:

1. Enter a display name, API origin and **Access Token**.
2. Test Connection. Authentication, missing scope, timeout, incompatible endpoint,
   invalid response and offline states are distinguished. The failed fixed API
   path is displayed without secrets or raw upstream response bodies.
3. Save. The token is encrypted using the same generic record store used by the
   Seedbox adapter. The database contains only its opaque reference. The browser
   clears the token field and only receives `tokenConfigured` after saving.
4. Refresh reads actual API data. Provider rate limits/backoff are respected.
5. Disconnect stops polling, deletes the active encrypted token and clears the
   cached snapshot, while preserving the integration entry for manual reconnection.
6. Permanently remove a disconnected entry using the confirmed local-only flow above.

Credential submission requires HTTPS outside development mode. Mutations require
an administrator, a valid session and CSRF token. No browser local/session storage
is used. Access Tokens must not be supplied in URLs or display names.

## Transport and current adapter boundary

The initial adapter accepts an explicit **private LAN IP origin**; localhost,
link-local, embedded credentials, paths, queries, fragments and public hostnames
are rejected. HTTPS performs normal certificate verification. There is no bypass.
If the actual LAN API only provides HTTP, the administrator must explicitly opt
in: its token is then plaintext on the Core-to-FjordHub LAN segment. Browser-to-Core
submission remains HTTPS. This limitation is visible in the UI, not silently hidden.

The upstream contract remains **proposed, not live verified**. No real Access Token
has been imported by this implementation. The user enters it in the deployed UI.
Incompatible real endpoints produce an explicit failure, never fixture success.
Public-hostname support and any final upstream differences belong in the adapter,
not Core/dashboard business logic.

`FjordHubIntegrationProvider` exposes test_connection, get_health, get_info,
get_capabilities, get_apps, get_storage, get_metrics and get_events. The registry
uses its batched `sync` call to avoid repeated summary requests.

Expected read-only contract, authenticated with `Authorization: Bearer <Access Token>`:

| GET endpoint | Expected data |
| --- | --- |
| `/api/v1/info` | `api_version: "1"`, `version` |
| `/api/v1/health` | `status: "healthy"` or `"degraded"` |
| `/api/v1/capabilities` | `capabilities` and `scopes` string arrays |
| `/api/v1/apps` | `items` containing dynamic app metadata |
| `/api/v1/storage` | `items` with total/used/free bytes |
| `/api/v1/metrics` | CPU, RAM and uptime numeric fields |
| `/api/v1/events` | `items`, optional `next_cursor`; accepts `cursor` |

Optional endpoints are requested only when both their capability (`apps.read`,
etc.) and scope (`apps:read`, etc.) are present. Only bounded allowlisted fields
are exposed. Token reflections are redacted; no raw error bodies or authorization
headers are logged. Redirects and environment-proxy inheritance are disabled.

Healthy polling is at most once per minute. Failure backoff doubles up to one hour;
Retry-After is bounded to one day. A batch has a20-second deadline, individual
requests5seconds and1MiB response limit. Failed optional integrations cannot make
Core unhealthy. Last-success timestamp and stale cached data are shown honestly.

Apps are rendered dynamically, storage is informational, and external events are
labelled `FjordHub` in Activity. Test fixtures are injected by tests only and are
not activated by the production service.
