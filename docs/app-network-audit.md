# App networking audit, 2026-10-14

## Intended behavior

* Cloudflare: select an installed app, zone and record name; configure DNS,
  tunnel ingress and the opening/SSO address. Preserve unrelated records.
* MediaVPN: select one uploaded full-tunnel Proton WireGuard profile and select
  installed supported apps inside MediaVPN or MediaHub. MediaSeed, Plex and
  Jellyfin are supported. Unmanaged FjordHub children need their own adapter.
* Provider keys remain in MediaVPN. Relays use separate local keys and do not
  create additional Proton sessions. Actual account session counts and failure
  behavior require verification on the target host.
* Health: show Docker healthcheck failures, restarting/stopped states and
  individual diagnostic messages. Service reachability is separate evidence.
* Updates: check Core, first-party GitHub sources and mapped upstream releases.
  Plex retains its publisher-image checker; cloudflared its GitHub checker.
  First-party installation remains bundled with Core. New upstream metadata does
  not silently install arbitrary source/images. Unknown installed versions must
  remain unknown rather than be presented as up to date.

## GitHub reference

Reviewed `qlerup/fjordhub` at `87c5c809c2b5d1022fd1568cf5c4fb68ea3186c3`
and `qlerup/fjordvpn` at `d1325416faf185e6e574ca917b9ef41b35aaaf5d`, directly
from GitHub, without reading the user's installed FjordVPN instance.

FjordVPN uses Gluetun, NAT-PMP, Caddy with DNS-01 certificates and Cloudflare
Origin Rules for inbound HTTPS through Proton's assigned port. Multiple hostnames
share one profile; torrents need a separate forwarded port. No upstream source
was copied.

This implementation uses Cloudflare Tunnel for inbound app domains and the
existing shared VPN relay for outbound traffic. They can run together. It does
not implement the reference's Proton inbound HTTPS/Origin Rules mode or arbitrary
per-port TCP forwarding. VPN DNS alone does not provide either feature.

## Faults addressed

* Hidden app routing, rejected tunnel creation and a reconciler that only
  processed VPN DNS.
* Stale installations appearing as VPN candidates and an unnecessary dependency
  on MediaSeed status when MediaSeed was not installed.
* Missing shared-app controls in MediaVPN itself. Delegated calls now use active
  package-bound SSO grants and require a global Hub administrator. CSRF remains
  enforced; management keys never reach the browser.
* Connector state was an installation snapshot rather than observed state.
  Bounded local Docker logs are retained for diagnosis.
* Container healthchecks were ignored or collapsed into unknown; remote status
  parsing discarded state, version and diagnostic messages.
* First-party version checks only inspected the bundle; mapped container apps
  had no upstream release metadata check.
* Unauthorized app mutations looked up the app before rejecting the caller.

The audit also found outdated tests for role policy, cache-busted icons, portals
and app ports, a collection-time rate-limit deadline, missing async test support
and Windows selecting unusable WSL bash. These test defects are separate from
runtime failures.

## Validation boundary

Tests use synthetic credentials, Docker/Cloudflare responses and VPN profiles.
No real DNS record, tunnel, VPN profile, server runtime or media was changed.
Production installation, real egress and loss-of-tunnel tests need the user's
live-test authorization. This is not a claim of 100 percent live verification.

## Read-only CT107 observation

The container inventory showed Core 0.5.35, MediaSeed 0.1.2, MediaVPN 0.1.3, Jellyfin and
one Proton/Gluetun container running with healthy checks and no recorded restarts.
The original qBittorrent container was stopped successfully while the VPN-bound
replacement was running. The one-shot dependency helper exited successfully.

The most recent 500 log lines within 24 hours yielded no matching error/warning
markers for the readable service logs. Jellyfin and the dependency helper used
an unreadable logging driver; that is missing evidence, not a clean log result.
New Plex/Jellyfin/container-app recipes now retain bounded local logs. Existing
containers are not modified by this source change. The helper's sensitive
provisioning output remains disabled; its application-level status is separate.

Local verification: 1,627 backend tests passed in the broad run, followed by the
four corrected GitHub-version fixtures passing on rerun; 11 platform-dependent
tests skipped. Additional focused regression checks passed. Frontend: 288 tests,
TypeScript and production build. MediaVPN: 90 Python tests (one UI opt-in skip)
and eight JavaScript tests. Six isolated Chromium interaction checks covered both
new flows at 1440, 390 and 320 pixels, without page errors or horizontal overflow.
No installed Chrome profile was used. The build retains its existing large-bundle
warning and the Python test stack reports Starlette/httpx deprecations.
