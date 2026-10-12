# Managed app login

MediaHub separates hub roles (`administrator`, `user`) from app roles
(`administrator`, `user`, `viewer`, `denied`). New users default to ordinary
users with no app access. Existing hub administrators keep their default app
access unless an explicit app assignment denies or reduces it. The last hub
administrator cannot be demoted or deleted.

The initial SSO adapter supports MediaSeed only. Other apps need an adapter
that enforces their roles; adding a URL does not provide generic SSO support.

## Configuration

Both browser-facing origins must use trusted HTTPS. Set
`MEDIAHUB_SSO_APP_URLS` to a JSON mapping from `org.mediahub.mediaseed` to the
MediaSeed HTTPS origin. This is an explicit operator registration, not an
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

## Behavior

Opening MediaSeed starts a browser-bound login attempt using state and PKCE.
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

Viewers can read downloads but cannot change them. Users can manage torrents,
including tracker imports, but cannot manage tracker accounts, RSS feeds,
or VPN settings. App administrators can use all existing app operations.

## Remaining Delivery Gates

- Automatic MediaSeed installation and SSO registration in the hub installer.
- Trusted HTTPS app routing and hub CA distribution on the beta deployment.
- Desktop/mobile browser testing and live beta verification.
- Adapters and role enforcement for additional apps.