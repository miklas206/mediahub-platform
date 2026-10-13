# Cloudflare DNS bound to MediaVPN

The Cloudflare app discovers accessible domains, DNS records and existing tunnels
through the encrypted scoped API credential. Tunnels are displayed read-only in
the UI; tunnel creation is rejected by the API. Connector installation, token
downloads, tunnel adoption and tunnel route creation are not offered in the app.
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

Old tunnel-route journals are preserved for compatibility, but the scheduled
reconciler and current Synchronize action only maintain VPN DNS records. They do
not update tunnel ingress. Existing tunnel routes continue running in Cloudflare.

## Endpoints

- GET /api/v1/cloudflare/manage: account, cached inventory, VPN profiles and DNS status.
- PUT/DELETE /api/v1/cloudflare/manage/credentials: connect/disconnect API access.
- POST /api/v1/cloudflare/manage/discover: refresh domain, record and tunnel inventory.
- POST /api/v1/cloudflare/manage/vpn-dns: create a binding using zoneId, label and profileId.
- PUT /api/v1/cloudflare/manage/vpn-dns/<id>: change automatic synchronization.
- POST /api/v1/cloudflare/manage/sync: explicitly reconcile VPN DNS.
- POST /api/v1/cloudflare/manage/tunnels: rejected (405).

Legacy direct DNS and route-management endpoints remain for existing integrations;
new app workflows use VPN DNS. No legacy mutation action is exposed in the UI.

Tests simulate Cloudflare and MediaVPN, including IP changes, IPv6, conflicts,
unhealthy profiles and uncertain POST results. They do not change a real account,
DNS record, VPN profile or running server.
