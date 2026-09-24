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

Advanced WebUI is a configurable localhost-only SSH-tunnel URL. It works only on
the client running an authorized tunnel; it is not a LAN/public service. Existing
qBittorrent authentication remains enabled. A reboot can end the tunnel; it must
then be restarted using an authorized SSH account. Normal torrent management
does not depend on this tunnel.
No new firewall rule, reverse proxy, public endpoint or Cloudflare setup is used.

Reference: [qBittorrent WebUI API v5](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)).
