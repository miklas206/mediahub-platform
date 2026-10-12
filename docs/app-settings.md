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

## Managed MediaSeed and MediaVPN removal

For an explicitly registered installation, click the red **Uninstall** button
on its home card, next to the settings icon. Removal is not inside app settings.
The button uses the server's `removable` capability; a connected URL alone never
enables it. The existing identity check and confirmation dialog still apply.
The hub must have `MEDIAHUB_MANAGED_APPS_POLICY_FILE` pointing to a read-only
operator policy and `MEDIAHUB_MANAGED_APPS_DOCKER_SOCKET` to its Docker socket.
This reuses the beta's existing Docker authority; it does not require a new
network listener. Socket access gives Docker control even with a read-only bind.

Example policy (replace identities and project names with verified installation
values; never commit the deployed policy or integration credentials):

```json
{
  "org.mediahub.mediaseed": {
    "installationId": "unique-mediaseed-installation-id",
    "project": "mediaseed-project",
    "runtimeLabels": {"org.mediahub.mediavpn.seedbox": "mediaseed"},
    "integrationUrl": "http://192.168.1.20:18802",
    "integrationTokenFile": "/managed-auth/mediaseed.token"
  },
  "org.mediahub.mediavpn": {
    "installationId": "unique-mediavpn-installation-id",
    "project": "mediavpn-project",
    "runtimeLabels": {"org.mediahub.mediavpn.owner": "mediavpn"}
  }
}
```

Mount the policy and token read-only. The hub user needs read permission on the
token, without exposing it to other users. Runtime labels refer to the single
local MediaVPN controller; this policy does not support multiple controllers
sharing those ownership labels on one Docker daemon.

Removal requires an administrator, CSRF and confirmation tied to the current
container IDs. MediaSeed disconnects its torrent client through MediaVPN's
authenticated integration before stopping and removing its app/client
containers. MediaVPN removal is blocked while that client exists; disconnect
MediaVPN inside MediaSeed's VPN page first. This releases the client container
without removing MediaSeed, its torrents or downloads. A disconnected MediaSeed
can also be uninstalled when MediaVPN is absent. Foreign containers sharing a target's network namespace also
block removal. No real app is removed merely by opening the dialog.

Only selected containers are stopped and removed, with `force=false&v=false`.
No volume, image, network, source, bind-mounted file or VPN profile is deleted.
Active transfers stop. Named volumes are checked after removal. A private,
durable journal contains container identities and mount metadata, never Docker
environment variables. Interrupted removal resumes after a hub restart; failed
removal retains registration and offers retry. New replacement containers stop
the retry rather than being silently included.

After verified removal the saved operator URLs and SSO configuration remain for
rollback, but the app is excluded from connected status and SSO login. Restore
the original Compose project and client settings to roll back; assign a new
installation ID when explicitly registering a fresh installation. Automatic
reinstallation and fresh-install SSO provisioning remain separate work.
