# Cloudflare app domains and VPN DNS

The Cloudflare app discovers accessible domains, DNS records and existing tunnels
through the encrypted scoped API credential. The app supports tunnel creation,
explicit adoption, local connector installation and installed-app route creation.
Existing Cloudflare resources are never deleted when changing this configuration.

## Permissions and setup

Use Zone > Zone > Read to discover the selected account's domains and Zone > DNS >
Edit to create and maintain DNS records. Account > Cloudflare Tunnel > Read is
optional for viewing existing tunnels; missing tunnel access does not block DNS
creation when domain/DNS access works. Reads cannot prove Edit permission, so a
write failure is reported on the record's synchronization status.

Install MediaVPN and start a verified VPN profile. In Cloudflare, select a discovered
domain and profile, then enter the relative record name, for example `seed`.
MediaHub fetches the profile's current public IP through its private machine API.
The browser cannot submit an arbitrary target IP. IPv4 creates an A record, IPv6
creates an AAAA record. Records are DNS-only (`proxied=false`, automatic TTL).

DNS maps a name to the VPN's public IP. It does not create inbound port forwarding,
open a service port, or make a private app publicly reachable. A/AAAA records do
not carry the VPN's forwarded port. A service must already be reachable through
the relevant provider forwarding/network path. The UI displays the observed VPN
forwarding port separately and does not put it in the DNS record.

## Automatic synchronization

The background check runs every 60 seconds. MediaVPN profile observations are
cached for 30 seconds; Cloudflare inventory remains cached for five minutes, with
explicit refresh at most every 30 seconds. No Cloudflare calls are made for an
unchanged, synchronized VPN DNS record. A stopped/unhealthy profile retains the
last DNS value and reports a blocked state. Each record has an automatic-sync
switch; Synchronize now explicitly checks the VPN DNS bindings.

A persistent intent journal is saved before creating a record. Records carry a
unique ownership comment. A retry recovers a successful creation with a lost
response only by that exact marker. Existing unrelated records are never adopted
or overwritten. Before changing an owned record's IP, the current name, type,
content, proxy mode and ownership comment are checked against the saved value.
External edits pause changes rather than being overwritten. Cloudflare does not
provide a transaction spanning the read and PATCH; concurrent external writes
remain a provider limitation. No private VPN key is sent to Cloudflare.

Tunnel-route journals are retained. Scheduled and manual synchronization maintain
both app routes and VPN DNS, respecting each automatic synchronization switch.

## Endpoints

- GET /api/v1/cloudflare/manage: account, cached inventory, VPN profiles and DNS status.
- PUT/DELETE /api/v1/cloudflare/manage/credentials: connect/disconnect API access.
- POST /api/v1/cloudflare/manage/discover: refresh domain, record and tunnel inventory.
- POST /api/v1/cloudflare/manage/vpn-dns: create a binding using zoneId, label and profileId.
- PUT /api/v1/cloudflare/manage/vpn-dns/<id>: change automatic synchronization.
- POST /api/v1/cloudflare/manage/sync: explicitly reconcile app routes and VPN DNS.
- POST /api/v1/cloudflare/manage/tunnels: create a remotely managed tunnel.

Direct DNS endpoints remain for integrations. App domains use managed tunnel
routes; VPN DNS is a separate optional workflow.

Tests simulate Cloudflare and MediaVPN, including IP changes, IPv6, conflicts,
unhealthy profiles and uncertain POST results. They do not change a real account,
DNS record, VPN profile or running server.

## Installed app domains

Choose an installed app, zone, record name and managed tunnel. MediaHub resolves
the private endpoint, creates a proxied CNAME, configures ingress and saves the
public HTTPS address for opening the app and SSO. Conflicts are reported per
route. This requires Zone DNS Edit and Account Cloudflare Tunnel Edit. Install
the local connector or use an existing connector that trusts the local app CA.

Connector container state is observed on refresh. Public HTTPS is probed by
Cloudflare Healthcheck; a successful API write is not proof of public reachability.
Stopped apps retain their routes and report unavailable until they run again.

Inbound domains use Cloudflare Tunnel. Applications may independently use the
shared Proton gateway for outbound traffic. Inbound HTTPS through Proton with
Origin Rules and arbitrary TCP port forwarding are not implemented in this release.
See [the audit](app-network-audit.md) for the GitHub reference and validation limits.
