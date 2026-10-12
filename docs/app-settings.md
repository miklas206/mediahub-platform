# Per-app settings

Installed or explicitly connected apps have an administrator-only settings
page at `/app-settings/<package-id>` and an icon on their home card. Available
catalog apps do not become installed merely because settings exist.

The external HTTPS origin is persisted independently of the app's private
operator address. Opening the app uses the external address when one is saved;
clearing it restores the existing local/runtime opening behavior. Private
health checks continue using the configured private origin. App-specific
configuration links reuse the existing installation/configuration surfaces.

This matches the inspected FjordHub `api_app_settings` operation: saving an
external URL is distinct from provisioning DNS, reverse-proxy routes or TLS.
MediaHub does not silently create DNS records, obtain certificates, modify
Cloudflare tunnels or open firewall ports. Configure those before saving a
domain address. No network request is made to an arbitrary submitted URL.

For MediaSeed managed SSO, a different external origin is rejected until the
app's configured origin and MediaHub's registered SSO origin are changed
together. Changing only the opening link must never redirect login codes to
an unregistered domain or break host/origin/state-cookie protections.

Settings endpoints require a current hub administrator and CSRF for writes.
Addresses must be HTTPS origins without credentials, paths, queries or
fragments. Errors and success feedback use the existing notification popup.

Automatic domain provisioning and generic in-place runtime reconfiguration
are not implemented by this settings page. Each app requires its own verified
configuration adapter; existing Plex, Jellyfin, Seedbox and Cloudflare
configuration pages remain separate.