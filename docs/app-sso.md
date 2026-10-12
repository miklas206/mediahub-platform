# Managed app login

MediaHub separates hub roles (`administrator`, `user`) from app roles
(`administrator`, `user`, `viewer`, `denied`). New users default to ordinary
users with no app access. Existing hub administrators keep their default app
access unless an explicit app assignment denies or reduces it. The last hub
administrator cannot be demoted or deleted.

The managed SSO adapters support MediaSeed and MediaVPN. Other apps need an adapter
that enforces their roles; adding a URL does not provide generic SSO support.

## Configuration

Both browser-facing origins must use trusted HTTPS. Set
`MEDIAHUB_SSO_APP_URLS` to a JSON mapping from `org.mediahub.mediaseed` and
`org.mediahub.mediavpn` to their respective HTTPS origins. This is an explicit operator registration, not an
automatic app installation. Keep `MEDIAHUB_OPERATOR_APP_URLS` configured for
the separate health probe. Registered SSO apps appear in Users and in an
ordinary user's app list only when that user has access.

On MediaSeed set `MEDIASEED_HUB_URL` to the HTTPS hub origin and
`MEDIASEED_BASE_URL` to the HTTPS app origin. For a private hub CA, mount only
its public certificate read-only and set `MEDIASEED_HUB_CA_FILE` to that path.
Never mount the CA private key or disable certificate verification.

The app reverse proxy must preserve the app origin's Host header. MediaSeed
does not trust forwarded headers for authentication. Restrict the direct
backend port to the trusted proxy network. Retain existing VPN Compose
overrides, volumes, and protected MediaVPN token mounts.

MediaSeed includes `compose.hub.yaml` for direct HTTPS with its own app
certificate/key and a read-only public hub CA. Use it in addition to both
`compose.yaml` and `compose.vpn.yaml`. Set `MEDIASEED_TLS_PATH` to the app's
protected certificate directory and `MEDIASEED_HUB_CA_PATH` to the public CA.
The app certificate must cover the configured app hostname and chain to the
same trusted CA used by the health check. Never reuse the hub private key.

MediaVPN uses `MEDIAVPN_HUB_URL`, `MEDIAVPN_BASE_URL`, and
`MEDIAVPN_HUB_CA_FILE` with the same HTTPS requirements. Its `compose.hub.yaml`
adds a TLS proxy using `hub-proxy.yaml`, a separate app certificate/key from
`MEDIAVPN_TLS_PATH`, and the public CA from `MEDIAVPN_HUB_CA_PATH`.
The default HTTPS port is 18803 (`MEDIAVPN_TLS_PORT`). Retain
`compose.runtime.yaml` where Docker runtime is explicitly enabled. The existing
HTTP port 18802 can remain available for the restricted machine integration;
browser login uses the registered HTTPS origin. Keep machine API access confined
to the trusted network. The proxy does not receive Docker access or the CA key.

## Behavior

Opening either managed app starts a browser-bound login attempt using state and PKCE.
Its root page automatically starts hub login when the app session is missing (401).
Denied access (403) and hub unavailability (503) display an error instead of
repeatedly redirecting. An active session at the configured hub origin avoids
another password prompt; a different hub hostname has a separate browser cookie.
Where the hub has a public browser hostname and a private HTTPS service origin,
set `MEDIASEED_HUB_BROWSER_URL` / `MEDIAVPN_HUB_BROWSER_URL` to that public
HTTPS origin. Browser authorization then reuses the existing public hub session,
while code exchange and permission checks continue over the verified private
`*_HUB_URL`. This avoids routing machine requests through browser access policies.
Saving an HTTPS app domain in app settings updates the canonical SSO callback
and opening link together. Apps obtain this registration from `/sso/origin`
over verified TLS. Login redirects to that app origin before setting state;
only the local host and the current registered app host are accepted. Domain
DNS, TLS, and proxy routing must already reach the app. Reset restores the
operator-configured HTTPS app origin without changing private health addresses.
The hub issues a 60-second single-use code for the registered callback.
MediaSeed exchanges that code over verified TLS and creates a local session
bound to the stable hub user ID. No hub passwords or password hashes are
copied to the app.

Every authenticated app request checks the current hub session and app grant.
Hub logout, password reset, user deletion, permission removal, and hub-session
expiry invalidate app access. Hub unavailability denies access rather than
using stale permissions. App logout removes only that app session.

Managed mode disables local setup and local password login. Existing local
accounts and data remain stored for rollback to standalone mode. Standalone
mode remains available when `MEDIASEED_HUB_URL` is not set.
MediaVPN follows the same rule with `MEDIAVPN_HUB_URL`.

Viewers can read downloads but cannot change them. Users can manage torrents,
including tracker imports, but cannot manage tracker accounts, RSS feeds,
or VPN settings. App administrators can use all existing app operations.
In MediaVPN, users and viewers have read-only access to profiles and status;
only app administrators can change profiles, forwarding, or runtime state.
SSO registration does not attach MediaSeed to MediaVPN: that remains an explicit
provider/profile choice inside MediaSeed.

## Remaining Delivery Gates

- Automatic MediaSeed installation and SSO registration in the hub installer.
- Desktop/mobile visual browser testing of the automatic login transition.
- Adapters and role enforcement for additional apps.
