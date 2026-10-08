# Seedbox daily operations

The Seedbox page provides VPN location selection, magnet/metainfo submission,
live torrent status and pause/resume/force-recheck/remove-job actions. Administrator sessions,
CSRF protection and validated Core-to-Agent HTTPS remain required.

## VPN location provider

`LocationProvider` is the Agent adapter boundary. Proton is implemented; other
providers explicitly report unsupported until an adapter is registered. Core
does not manipulate provider keys or WireGuard peer details.

The Proton adapter reads the public server catalog from the installed, pinned
Gluetun image (`format-servers -protonvpn -format json`). It filters for WireGuard
and port forwarding, excludes Tor/Secure Core, and validates peer public keys and
public IPv4 endpoints. It preserves the existing private key, tunnel address and
NAT-PMP settings, replacing only peer endpoint/public key inside RAM. The new
profile is validated and stored in the encrypted vault before runtime use.

Automatic chooses an eligible P2P server in the selected country; it is NOT a
latency/load benchmark. Catalog freshness is tied to the installed Gluetun image.
Automatic selection can try at most three eligible servers in the requested
country when connection verification fails. An explicitly selected server is
not silently replaced. qBittorrent stays stopped throughout unsuccessful attempts.
The in-process catalog cache lasts ten minutes. If selection is unavailable, the
UI reports failure instead of inventing a location or falling back to WAN.

Switch sequence: persist desired-stopped state; stop qBittorrent; check storage
and devices; stop VPN; replace encrypted profile and materialize protected RAM
files; restart and verify tunnel/external IP; check GeoIP when available; renew
NAT-PMP; update the stopped client's port; check storage/devices again; start
client in the fresh VPN namespace; verify egress/interface/forwarded port;
persist desired-running state. Failures stop the client and retain stopped state.
Independent geolocation is labeled separately from provider-catalog evidence.

References: [Gluetun Proton provider](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md),
[WireGuard configuration precedence](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/wireguard.md).

## Torrents and storage

Only the installation's approved logical downloads storage can be selected.
No user-supplied host path is accepted. The Agent maps it to `/downloads` inside
qBittorrent. The actual host path and logical ID are deployment configuration,
not fixed product paths. Seedbox never implicitly gains access to Movies or TV.

Metainfo is bounded to 2 MiB and parsed/validated in memory. Magnet input is
bounded and restricted to supported identity/name/tracker fields. Credentials and
passkeys are not echoed in validation errors or recorded in MediaHub events.
qBittorrent itself necessarily retains its torrent state; this is not a promise
that tracker metadata disappears from qBittorrent's own persistent state.

Admission is verified by exact infohash in the authenticated qBittorrent API,
not by assuming a particular version's HTTP response text. Duplicate jobs are
reported without changing their settings. Jobs are paused by default. Immediate
start and resume require live safety checks. Category customization is not yet
exposed; the single approved storage mapping is enforced.

The list shows up to 500 jobs, progress, state, transfer rates, ratio, ETA, size,
seeds/peers, seeding time and category where returned by qBittorrent.
Remove job always sends `deleteFiles=false`; there is no file-deletion control.
An explicit browser confirmation states that downloaded files are retained.

## Advanced qBittorrent WebUI access

Seedbox **Settings → qBittorrent WebUI** always shows the access control. It is
disabled until Core has an explicit `MEDIAHUB_OPERATOR_APP_URLS` entry for
`seedbox`. A configured link is **not** evidence of a working connection. There
is no general child-app/browser proxy through Core or the paired Agent; the
Agent's HTTPS port (18767) is not qBittorrent's WebUI port.

The reviewed installer publishes the WebUI **only on the Seedbox host's
127.0.0.1 address**, on `webPort` from the approved installation (default 18080).
Do not assume a LAN port such as 8080 is published. Preserve qBittorrent login,
localhost authentication, CSRF protection and host-header validation, as well
as VPN fail-closed checks.

### Opt-in SSH tunnel (recommended)

1. Check the approved Seedbox installation's `webPort` and the existing runtime
   port mapping on that host. An adopted runtime may differ; a configuration
   default is not proof that its listener exists. If it is not loopback-bound,
   stop and review its setup rather than opening a firewall or disabling checks.
2. On the **client where the browser runs**, use an already authorized SSH
   account on the **Seedbox Docker host**, not the Core host or Agent container.
   Windows OpenSSH example, **only if the reviewed host WebUI port is 18080**:

   ```powershell
   ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18081:127.0.0.1:18080 SSH_USER@SEEDBOX_HOST
   ```

   Replace `SSH_USER` and `SEEDBOX_HOST` with the authorized account and host.
   Replace the final `18080` with the actual reviewed WebUI port. The first
   `18081` is an unused client-only port. Keep SSH running; no new host listener,
   firewall change or VPN egress exception is required. Verify the SSH host key
   normally; do not disable host-key checks.
3. Open `http://127.0.0.1:18081/` on that same client and verify the existing
   qBittorrent login. Authentication remains separate from MediaHub; credentials
   must not be embedded in the URL. If connection/login fails, inspect the
   authorized tunnel and the existing runtime; the button cannot repair either.
4. Configure **Core's environment** (not the Agent's) with:

   ```dotenv
   MEDIAHUB_OPERATOR_APP_URLS={"seedbox":"http://127.0.0.1:18081/"}
   ```

   The repository `compose.production.yaml` forwards this variable from its
   Compose environment. Native Core reads it from its process environment or
   `.env`. For an `install.sh` installation using generated `compose.json`,
   add the entry explicitly to `services.core.environment` in the operator's
   maintained Compose configuration; a project `.env` alone does not pass new
   variables into an existing container. Merge other app entries if present.
   Applying the changed Core environment is a separate, explicit operator
   action; updating source does not enable it or restart services automatically.
5. After the operator applies that configuration, the Settings button opens
   the configured WebUI in a new tab. Its localhost URL refers to the browser
   device, not Core or the remote server. A phone or another PC needs its own
   authorized tunnel; it does not inherit this Windows client's connection.
   Restart the tunnel after a client reboot or SSH disconnect.

An already operator-managed authenticated HTTPS endpoint may be configured
instead; MediaHub does not create or test one, forward WebUI sessions, or relax
its TLS/authentication/CSRF safeguards. Do not publish the WebUI unauthenticated
or expose its port to the Internet. Normal MediaHub torrent management continues
to use the authenticated Agent API and does not depend on the WebUI tunnel.

Reference: [qBittorrent WebUI API v5](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)).
