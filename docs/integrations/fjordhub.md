# FjordHub external integration — verified correction (2026-09-16)

## CURRENT implementation: resources and optional FjordFlix appdata

Contract verified against [FjordHub appdata documentation](https://github.com/qlerup/fjordhub/blob/main/docs/app-data-integration.md), October 2026. Update FjordHub and FjordFlix (installed through FjordHub); select **FjordFlix** in **Settings → Access Tokens → Edit appdata access**. Docker resources remain included. Core must reach the normal private-IP origin over LAN, not a public/Cloudflare route.

Configure via Integrations or set backend-only `FJORDHUB_BASE_URL` and `FJORDHUB_ACCESS_TOKEN` (also supports `MEDIAHUB_` aliases). Both are required for environment-based setup. Explicit HTTP configuration consents to plaintext LAN token transport; prefer certificate-verified HTTPS. Startup imports the credential into the existing encrypted integration store for enabled integrations. An explicit disconnect remains authoritative across restarts. Keep environment files private; never put tokens in URLs, browser settings or logs.

`GET /api/integrations/v1/resources` retains Docker metrics and reads optional `app_data.fjordflix`, checking its own `ok` independently from top-level Docker `ok`. Old responses without appdata remain valid, without speculative calls to the separate appdata endpoint. App failures never hide resource measurements. Both retain their latest good values with separate visible stale markers; successful empty arrays clear prior data. App statuses 401/403/404/503 become fixed sanitized messages, never upstream error bodies.

Dashboard **Your apps** includes a dedicated, individually configurable Plex-style FjordFlix card, with library count, active-stream count and a keyboard-accessible horizontal carousel of the last 10 titles in API order. The card uses appdata's own availability/stale state, independent of Docker metrics, and is absent for disabled entries or responses without optional appdata. Apps and Integrations retain their responsive gallery of the **last 10 recently added titles**, preserving API `items` order, plus current streams (including pause/buffering). Optional metadata may be absent; seconds/pixels/Mbit/s are displayed correctly. Viewer names are private appdata available only to local authenticated users. Resource polling is sequential/nonoverlapping with a 10-second healthy interval and existing backoff/deadlines.

Posters use only authenticated local `/api/v1/integrations/{id}/fjordflix/posters/{movie_id}` requests; the browser never sees the upstream poster URL or bearer token. Only the configured origin and `/api/integrations/v1/app-data/fjordflix/posters/` path are accepted. Encoded/traversal paths, credentials, queries and fragments are rejected. No redirects/proxy inheritance; 8-second total timeout, 5 MiB limit, signature-checked JPEG/PNG/WebP, no-store/nosniff/same-origin responses and missing-image placeholders. No media playback controls, files or administrator APIs are exposed.

### App information and explicit updates (2026-10-06)

Contract verified against [public app-data-integration documentation](https://github.com/qlerup/fjordhub/blob/b4a0d958369023b1d7579120c7d1bc30080fbe92/docs/app-data-integration.md) and [app.py](https://github.com/qlerup/fjordhub/blob/b4a0d958369023b1d7579120c7d1bc30080fbe92/app.py#L833-L928). `GET /api/integrations/v1/app-info` returns `app_info` keyed by app ID, with `id`, `name`, `installed`, integer `port`, `icon_url` and independent `permissions.app_data` / `permissions.updates`. The same optional map occurs in resources. Resource refreshes continue every 10 seconds; missing metadata uses the app-info fallback. Old servers preserve prior metadata marked stale rather than clearing resources/appdata. No second integration/token is created.

Only installed apps with integer ports 1–65535 get a composed configured-LAN-host URL, preserving its scheme. User launch overrides remain authoritative, followed by verified app-info ports, then legacy explicit addresses and finally labelled management links. Unknown/uninstalled ports are never guessed.

Authenticated readers use local `GET /api/v1/integrations/{id}/updates`. Explicit administrator/CSRF actions use `POST /api/v1/integrations/{id}/updates/{app_id}/check` and `/start`; no request body can supply commands, repositories, URLs or arbitrary upstream paths. A fresh app-info and updates read under the shared integration lock validates known installed app IDs, token update permission, availability and non-running status before start. The FjordHub updater uses ID `fjordhub`. Updates are never registered with the global automatic update queue. Status polls are sequential/nonoverlapping, normally 45 seconds and 5 seconds while running. Metadata refresh and actions share the lock, and late writes are fenced against token/disconnect/removal changes.

Upstream updates are keyed by app ID. Individual check/start responses are flat public status objects with `app_id`, `ok`, `state`, `running`, `update_available` and optional revisions/timestamps. Only documented status fields are retained; upstream error bodies/logs/configuration are not forwarded. HTTP 202 is reflected as acceptance, never completion. An uncertain start is persisted as stale/in-progress before the POST; restart/timeouts and sanitized 401/403/404/409 errors retain status and cannot enable another start. Polling alone resumes and only a confirmed upstream status ends the in-progress display. An action is never automatically retried.

The icon proxy is authenticated local `/api/v1/integrations/{id}/apps/{app_id}/icon`; the browser never receives a Bearer token or upstream icon URL. The configured exact scheme/authority and published `/static/logos/(icons/)<filename>.png|jpg|jpeg|webp` paths from returned metadata are fetchable, including safe relative paths (optional bounded `v=` brand revision). Exact, app-specific `raw.githubusercontent.com/qlerup/...` PNG paths published by the registry are also accepted. Public GitHub images NEVER receive the FjordHub Bearer token. Unknown repositories, paths and cross-app artwork are rejected. No redirects, URL credentials, traversal/encoding, arbitrary queries or inherited environment proxies. Responses remain limited to 2 MiB with PNG/JPEG/WebP signature/content-type checks and no-store/nosniff/same-origin headers. Changed metadata/successful resource refreshes revise browser icon URLs, allowing recovery after failed image loads. The FjordFlix dashboard shares this same proxy.

The current upstream app-info contract includes the independent **Appikoner og porte** token selection under **Rediger appadgang**. Existing appdata/update grants also include that app's metadata. Enable the relevant apps on the existing token; no replacement token or update permission is needed for icons. The images themselves are public, while metadata access remains token-controlled. A fresh metadata poll is required before new selections appear. Missing permissions, unknown artwork or fetch failures retain the interface placeholder.

Home renders Danish update labels, revisions, timestamps, acceptance/running/error/stale states and permission-gated actions; viewers see status only. Fixture tests verify exact keyed/flat contracts, old responses, invalid ports/icons, auth/CSRF, permission/availability gates, acceptance/progression, restart/timeout failures, locking and redaction. Desktop/mobile mocks also retain authoritative override save/reset behavior. No live token or remote mutation/deployment is used.

### Legacy installed-app links: previously verified upstream limitation

At upstream revision `566a4ccbb69e32ec913d7dea2244a716c60c8540`, [resource_integration.py](https://github.com/qlerup/fjordhub/blob/566a4ccbb69e32ec913d7dea2244a716c60c8540/services/resource_integration.py) allowlists app IDs, names and counters, **not app URLs or published ports**. `hub_url` identifies FjordHub itself, not a child app. FjordHub's session-authenticated dashboard builds `local_url` from installed `APP_PORT` and the host LAN IP, but those fields are not exposed in the Access Token resource response. MediaHub therefore cannot determine the real installed port from this contract, and never uses catalog `default_port` or guesses a port. No administrative/session-only endpoint is probed.

Navigation, installed-app cards and the FjordFlix dashboard share one resolver. Explicit `url`, `local_url` or `external_url` metadata, when supplied by a compatible upstream version, is retained only for the configured LAN host and scheme; a different explicit nonzero port and application path are allowed. Other hosts/schemes, credentials, query strings, fragments, encoded/unsafe addresses and token reflection are rejected. Explicit URLs do not grant backend network-fetch access. Missing/rejected addresses get an explicitly named **Manage in FjordHub (app address unavailable)** link to the existing management card, never an **Open app** button pretending the main FjordHub URL is an app URL. With no installed row, the dashboard instead links to the local integration details.

Local fixtures cover legacy/empty/Unicode/metadata, independent stale/recovery, image authentication/SSRF/redirect/type/size and desktop/mobile dashboard carousel rendering. No live token, private-page content or deployment is claimed.

## FjordHub home and branding

The sidebar's FjordHub parent opens authenticated local `/integrations/{id}`. Each configured integration has its own status, apps, Docker resource measurements, optional FjordFlix library/streams and local launch settings. **Open FjordHub** remains a separately labelled external action. Child sidebar labels stay concise; tooltips distinguish direct app opening from the explicit management fallback. All app surfaces use the same override-aware link resolver. Settings show the signed-in MediaHub username, not remote credentials.

Official artwork was checked against `qlerup/fjordhub`'s public `app_registry/*.json` / `registry.json` and each listed source repository on 2026-10-05. The new FjordHub/FjordFlix export provenance is documented in their `branding/README.md`; no additional FjordHub-family marks are bundled. Token-granted metadata now enables the official public images through the bounded proxy described above. Existing Lucide interface icons (house, film, shield, map pin, camera, graph, planet/package as applicable) remain placeholders when metadata or approved images are unavailable, not claimed official logos. The old gradient FjordHub PNG remains untouched but is no longer rendered.

The Fjord3D icon is the official `static/logos/icons/fjord3D-mark-transparent-512.png` named by its `fjordhub.json`, bundled unchanged as `frontend/public/assets/services/fjord3d.png`. Its verified [MIT license](https://github.com/qlerup/fjord3d/blob/main/LICENSE), copyright © 2026 Glerup, is retained in adjacent `fjord3d-LICENSE.txt`. No remote image loads are needed for the fallback. Verified Fjord3D source revision: `cb445bcbe72e8a6b0d3b86bc23a9657a6e4a5403`; bundled PNG SHA-256: `eacceb4093bcf511b4bc70a5f39e04e3d4a0774a5719e9708c5dc9ab50af3ce0`. Other official marks are displayed through the protected proxy from token-granted metadata without bundling them; interface fallbacks remain when metadata or images are unavailable. App defaults/ports from the registry are never used as launch URLs.

## Local app launch overrides

Authenticated integration responses include `appLaunchOverrides`, a map keyed by installed app ID. Administrators can set or clear an entry with session/CSRF-protected `PUT /api/v1/integrations/{id}/apps/{app_id}/launch-url`, body `{"url":"https://<configured-LAN-IP>:<actual-port>/path"}` or `{"url":null}`. The app must occur in that integration's snapshot and have a safe identifier; an existing override can still be cleared after the app disappears.

These are browser-only links, not remote FjordHub configuration or a server fetch capability. The configured host is required; explicit ports and application paths are permitted without port guessing. HTTP requires the integration's explicit LAN consent. Credentials, control characters (including encoded controls), query strings, fragments and the integration's Access Token are rejected with sanitized errors. URLs are persisted in local settings scoped to the integration, survive restarts and are removed on permanent integration deletion. Clearing restores explicit API-address/management fallback behavior. No other integration, deployment or installed-app configuration is changed.

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
