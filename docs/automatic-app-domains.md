# Automatic app domains and gateway fixes

MediaHub 0.5.38 bundles MediaVPN 0.1.5 and MediaSeed 0.1.3.

## Domain setup

Connect a scoped Cloudflare account once, choose an installed app, select a zone
and enter the subdomain. **Set up domain automatically** creates a dedicated
MediaHub tunnel, installs its local connector, and saves DNS, ingress and the
app's HTTPS/SSO address. The task runs in the background with persisted progress.
Normal setup no longer asks users to choose tunnel IDs or install a connector
as a separate step. Manual tunnels and VPN DNS remain under advanced settings.

`POST /api/v1/cloudflare/manage/publish` accepts `zoneId`, `label`, `packageId`
and returns HTTP 202. The existing GET management endpoint reports `setup`.
The saved random tunnel identity makes retry after a lost creation response
recoverable. Conflicting records are never overwritten. Local origins and host
ownership are checked before changes and again after image installation.

If the hostname already belongs to a manually managed route, that route and
connector are retained. The status explicitly says to check the existing
connector separately. A configured route is not proof of public HTTPS access.

The cloudflared publisher is now allowed by the image validator. Its private
token file is readable by connector UID 10001 while remaining mode 0600.

## Gateway and diagnostics

A real CT107 read-only inspection found the shared Proton gateway and MediaSeed
verified, using one provider container. Jellyfin's relay was healthy but its app
was absent: the saved app bind referenced a missing disposable cache directory.
VPN recreation now checks approved mounted storage and prepares that exact cache
before stopping/recreating the app. It never creates replacement configuration
or media directories during recovery. Missing configuration remains a visible
blocking error. Uninstalling an already absent app clears desired-running state,
preventing the shared VPN supervisor from recreating it afterwards.

Shared app readiness requires the app itself to be running in the correct VPN
namespace; a healthy relay alone is insufficient. Specific recovery errors are
shown in both MediaHub and MediaVPN. Stored lifecycle state is not rewritten just
to show green: actual health remains authoritative.

Own-app version checks now read the app package metadata from the configured
MediaHub update repository and use the same credentials/deploy key as Core.
They no longer require access to separate private app repositories. HTTP metadata
is pinned to a checked commit; SSH metadata paths are explicitly allowlisted.
Missing repository or unknown installed version remains unchecked, and an older
remote bundle is not called a newer update.

## Danish encoding

Repaired 22 Hub, 24 MediaVPN and 3 MediaSeed translation values. Literal ASCII
question marks had replaced Danish UTF-8 characters. The previous PowerShell
pipeline used US-ASCII when passing source text to Python. New regressions check
all catalog values for lossy encoding, plus actual translation and preservation
of user values containing ÆØÅæøå. Two old browser fixtures were also repaired.

When generating source from PowerShell, avoid piping non-ASCII source through its
default `$OutputEncoding`. Prefer UTF-8 file APIs or the patch tool; terminal
rendering is not proof of the bytes saved in a source file.

## Recommended next architecture

Use one MediaVPN flow for profile, Cloudflare access, installed app selection and
domains. Keep Cloudflare credentials and ownership logic as a reusable backend
integration; a separate mandatory Cloudflare app is unnecessary.

The automatic domain feature delivered here still uses **Cloudflare Tunnel**.
The FjordVPN-style inbound path through Proton is a different networking feature:
Cloudflare proxied A + Origin Rule -> current Proton NAT-PMP port -> Caddy in the
VPN namespace -> an approved local app. It also needs DNS-01 certificate issuance,
renewal, reconnection handling, and a separate TCP/UDP NAT-PMP lease for torrents.
Moving the UI alone cannot provide this.

References inspected directly on GitHub and in official docs:

* [FjordVPN reference](https://github.com/qlerup/fjordvpn/tree/d1325416faf185e6e574ca917b9ef41b35aaaf5d)
* [Cloudflare Origin Rules](https://developers.cloudflare.com/rules/origin-rules/)
* [Origin Rule destination ports](https://developers.cloudflare.com/rules/origin-rules/features/)
* [Proton port forwarding requirements](https://protonvpn.com/support/port-forwarding-manual-setup)

The source changes do not deploy, restart services, change real DNS, or modify
existing VPN profiles/media. Live egress, outage behavior, TLS and SSO still need
verification after the user installs the release.

## Checks for this release

181 focused backend tests passed across Cloudflare automation, image validation,
shared VPN, container lifecycle, managed apps, bundled sources and update access.
The full frontend unit suite passed 292 tests; TypeScript, relevant ESLint and
the production build passed. MediaVPN passed 90 Python tests and 10 JavaScript
tests; one opt-in browser test was skipped. MediaSeed passed its four localization
Python tests and four encoding/localization JavaScript tests. Twelve isolated
Chromium checks verified the domain form and VPN app selection in Danish and
English at 1440, 390 and 320 pixels, with no page errors or horizontal overflow.

The existing large JavaScript bundle warning and test-library deprecations remain.
They are distinct from the corrected encoding, connector, update-source and
Jellyfin recovery failures.
