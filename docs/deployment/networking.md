# Browser access and internal service TLS

Cloudflare is optional. No Cloudflare SDK, public IP, DNS record or tunnel is required
by Core. Nothing in these settings creates public access.

## Browser origins

`MEDIAHUB_BASE_URL` remains the local/LAN origin. Optional `MEDIAHUB_PUBLIC_URL`
is a separate HTTPS origin. `MEDIAHUB_ALLOWED_ORIGINS` enumerates additional exact
browser origins; wildcard origins are not supported. Frontend API and SSE URLs
remain relative, so LAN does not depend on public DNS or tunnel availability.

Session cookies are host-only and HttpOnly. Secure is selected from the validated
request origin, so public HTTPS cookies are Secure while explicitly configured LAN
HTTP access still works. LAN HTTP remains unencrypted; use HTTPS for stronger LAN
security. Separate hostnames have separate browser sessions, not cross-domain SSO.
`MEDIAHUB_COOKIE_SAMESITE` accepts strict (default), lax or none. None requires all
configured browser origins to be HTTPS. Existing CSRF and origin checks stay active.

Only `MEDIAHUB_TRUSTED_PROXIES` peers may supply X-Forwarded-For/Proto. Configure
individual IPs or narrowly scoped CIDRs; wildcard and /0 trust are rejected. Core
does not accept X-Forwarded-Host: the proxy must preserve the configured Host.
The absolute URL helper selects an explicit public origin for public links and the
validated current origin for local navigation. Never build URLs from arbitrary headers.

Proxy handling is in ASGI middleware. Launch through `mediahub serve`, which disables
duplicate Uvicorn proxy processing. Alternate launchers must also disable their own
proxy processing; otherwise Core cannot validate the original peer address reliably.

## Later reverse-proxy deployment (not installed by Phase 4)

Configure the domain/public origin, allowed browser origins and actual trusted proxy
peer. Preserve Host, set X-Forwarded-Proto from the real external transport, and
sanitize forwarded client-IP headers. Do not trust arbitrary Internet-provided headers.
Restrict origin reachability as part of that future deployment; never trust every
Cloudflare client automatically or bypass MediaHub authentication.

SSE uses same-origin authenticated EventSource, periodic heartbeat, reconnect and
`Cache-Control: no-cache, no-transform` / `X-Accel-Buffering: no`. Disable buffering
and caching on API/stream routes and use timeouts longer than the heartbeat interval.
There is no WebSocket application endpoint yet. If one is introduced, the ASGI proxy
middleware supports WebSocket schemes; the deployment must pass Upgrade/Connection
headers and enforce equivalent session/origin checks on that endpoint.
Live Cloudflare, WebSocket and proxy-end-to-end operation have not been tested yet.

## Internal service listener

Core supports an additional direct TLS listener using `MEDIAHUB_INTERNAL_TLS_CERT`,
`MEDIAHUB_INTERNAL_TLS_KEY`, `MEDIAHUB_INTERNAL_TLS_HOST` and
`MEDIAHUB_INTERNAL_TLS_PORT` (18766 by default). It shares one Core lifespan and DB
with the browser listener. It exposes only `/api/v1/health` and `/api/v1/hosts/pair`,
not UI or login. No reverse proxy is involved. Pairing still requires the existing
short-lived single-use secret. Enrollment invitations must be created over trusted
HTTPS or locally through the Core service; the HTTP browser pairing guard stays.

Remote Agent uses `MEDIAHUB_AGENT_TLS_CERT` and `MEDIAHUB_AGENT_TLS_KEY` for direct
TLS. `MEDIAHUB_AGENT_CA_FILE` on Core specifies the CA trusted for remote Agents.
Agent enrollment's `--ca` supplies the CA trusted for Core. Server certificates must
include the exact connection IP as an IP SAN. Certificate verification is mandatory.
Only explicitly approved internal peers should be allowed to reach service ports.

## Certificate lifecycle (deployment procedure, not yet executed)
<!-- Instance deployment evidence lives in private .qa/phase4-tls-results.md. -->

1. Generate a dedicated private CA on an administrator-controlled machine. Store its
   private key outside the repository and outside both runtime containers, in a
   root-only directory with an encrypted offline backup. Do not install it globally.
2. Issue separate server keys/certificates for Core and each Agent, with serverAuth
   EKU, exact IP/DNS SANs, and a short lifetime (recommended 90 days).
3. Runtime receives only its own private key (0600, service owner), certificate and
   public CA trust bundle. Mount keys read-only. Never distribute the CA private key.
4. Test trusted CA + correct SAN success, wrong CA/SAN rejection and expired-cert
   rejection. Record issuer, fingerprint and expiry, never private keys.
5. Renew before expiry to new filenames, verify before switching, then restart only
   the affected new service and verify reconnection. No automatic renewal daemon is
   implemented yet; schedule/operator ownership must be established before handoff.
6. For CA rotation, deploy a temporary old+new public trust bundle first, replace leaf
   certificates, verify all peers, then remove the old CA. Never disable verification.
   If a key is compromised, remove its CA trust where necessary and rotate the Agent
   token as well; there is no claim of automatic CRL/OCSP enforcement here.

Reference: [Uvicorn deployment and TLS options](https://www.uvicorn.org/deployment/).

## Verification status and deployment order

Provision and verify minimal direct internal HTTPS before remote enrollment. Only
then consume a single-use invitation. Never enroll over temporary plaintext HTTP.
After pairing, verify persistence/reconnect and complete the certificate lifecycle
acceptance checks on the actual deployed services.

`tests/test_internal_tls.py` performs real loopback TLS handshakes with ephemeral
test certificates: valid trusted IP succeeds; absent trust, wrong CA, IP mismatch,
and expired certificate fail validation. A mismatched private key fails loading.
These isolated tests do not establish that production hosts have been configured.
Production issuance, secure pairing, restart identity, token-replay rejection and
log-secret checks remain required deployment acceptance checks.

Revocation strategy: quarantine/disable the affected host in Core and remove its
stored enrollment credential; rotate compromised Agent token and key, issue a new
leaf and require a fresh short-lived single-use pairing invitation. If a CA key is
compromised, remove that CA from the dedicated runtime trust bundle and reissue
under a new CA before reconnecting. A leaf-only compromise requires explicit
revocation support or trust isolation/CA rotation to invalidate the old certificate;
expiry alone is not immediate revocation. Do not claim CRL/OCSP enforcement unless
it is implemented and tested. Host revocation tooling is not yet fully implemented.
