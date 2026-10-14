# Guided MediaVPN gateway

MediaHub 0.6.0 includes MediaVPN 0.2.0. Cloudflare is a gateway integration,
not a separate app in the catalog, app list or Updates page.

## Set up a new installation

1. Install MediaHub with the guided Proxmox installer, or its Linux installer
   in a supported VM. Install MediaVPN and the apps you want from MediaHub.
2. Open MediaVPN from MediaHub. The **Shared VPN gateway** guide checks the
   managed Docker runtime, architecture, TUN and private storage.
3. In Proton, generate a P2P WireGuard configuration with NAT-PMP enabled and
   Moderate NAT disabled. Upload that configuration in the profile step.
   A paid Proton plan supporting port forwarding is required.
4. Create a Cloudflare API token scoped to your chosen zones with Zone Read,
   DNS Edit, Origin Rules Edit and Zone Settings Read. Enter the token and
   Cloudflare account ID once. Set those zones to **Full (strict)** SSL/TLS.
5. Choose the installed apps, zone and subdomain, then activate. MediaHub
   resolves the private addresses; MediaVPN uses one provider profile,
   obtains certificates with DNS-01 and starts its Traefik gateway. MediaHub
   creates owned proxied A-records and an owned Origin Rule per zone.
6. Wait for **Public HTTPS verified** before treating the domain as ready.
   Configured DNS, a healthy provider and a valid certificate are separate
   checks. Use the per-app internet-access choices for outbound VPN routing.

The API token is never returned to the browser after saving. It remains encrypted
in MediaHub and is delivered server-to-server to a protected credential file
used by Traefik's DNS challenge. The provider key stays in MediaVPN.

## Traffic and requirements

Inbound HTTPS follows Cloudflare -> the current Proton public IP/forwarded port
-> Traefik in the provider namespace -> the selected private app. The existing
Hub Traefik stays independent. A separate NAT-PMP helper obtains/renews a TCP/UDP
torrent mapping; qBittorrent's internal listen port and external announce port
are verified separately. No extra Proton provider profile is started per app.

Missing/expired leases, mismatched ports, changed provider generation or missing
VPN routing block the dependent torrent function. Direct access to the public
web listener is restricted to Cloudflare socket addresses; spoofed forwarding
headers do not grant access. Local HTTPS origins retain CA/SNI verification.

No Caddy, xcaddy or Go build dependency is used. The helper copies the official
Traefik 3.3.7 binary and uses Python for runtime supervision/lease management.
Updates and fresh installations prepare the app, native VPN relay, Traefik
gateway and provider images before marking prerequisites ready. This does not
start a real VPN or reinstall an app that the user removed.

## Proxmox portability

The installer supports Linux Docker on amd64 and arm64, selects a matching
Debian 13 template, discovers active storage/bridges and proposes resources based
on available CPU/RAM. GPU is optional. It maps and opens TUN, with compatibility
for older device-configuration syntax. Block-volume UUIDs and mounted ZFS dataset
GUIDs provide storage identity; unavailable or ambiguous storage stops setup.

This is not a guarantee for every historical Proxmox version or arbitrary
hardware/driver configuration. Cgroup v2, supported container templates/images,
enough storage/RAM and outbound provider/ACME access are required. Where a node
cannot provide these, the guide reports the missing prerequisite. Use a DHCP
reservation or a stable LAN address for the host's published app addresses.

## Existing installations and rollback

Existing Cloudflare tunnels, records, tokens and saved app data are retained.
Old app links lead to MediaVPN. The gateway will not take over an unrelated
A/CNAME or overwrite externally edited rules. Use a free subdomain first, verify
it, and explicitly migrate an old hostname afterwards. Retired app presentation
does not authorize deletion of an existing working public connection.

Disabling public domains stops their new runtime, removes only verified owned
DNS/rules and restores the prior app opening address if it was not manually
changed in the meantime. Selected outbound VPN apps remain a separate choice.
Stop public domains and wait for cleanup before rotating/disconnecting credentials.

Healthcheck cleanup targets exact owned obsolete helper images only. It protects
all running/stopped container references, current helper requirements, previous
images and rollback recipes. It does not delete media, volumes, other people's
Caddy/Traefik installations, or use broad Docker builder/system pruning.

## Verification boundary

Unit/integration tests use synthetic provider responses and credentials. An
actual isolated Traefik image build and offline HTTP/HTTPS routing checks were
performed without network, host ports, real credentials, TUN or app data. Both
normal Host/TLS operation and rejection of spoofed peers/SNI mismatch were tested.
The setup guide is browser-tested in Danish/English at desktop/mobile widths.

Real ACME issuance, public DNS/SSO, simultaneous Proton lease acceptance and
physical loss-of-VPN behavior still require verification with the user's chosen
profile after installation. The proxy does not claim public readiness until
its live HTTPS probe reaches the exact intended app route.

References: [Proton NAT-PMP setup](https://protonvpn.com/support/port-forwarding-manual-setup),
[Cloudflare Origin Rules](https://developers.cloudflare.com/rules/origin-rules/),
[Traefik routing](https://doc.traefik.io/traefik/v3.3/routing/routers/).

Release checks: 1,744 Core backend tests passed (11 platform-dependent skips),
296 frontend tests, 139 MediaVPN Python tests (one opt-in skip), 10 JavaScript
tests and 12 isolated Danish/English browser flows at 1440/390/320 pixels.
Additional focused checks cover host-helper replacement, image preparation,
safe cleanup, exact proxy markers and backward-compatible source archives.
TypeScript, relevant lint, shell syntax and production build passed. Existing
test-library deprecations and the large JavaScript bundle warning remain.
