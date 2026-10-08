# MediaHub App Store

The App Store is the discovery and guided-installation surface. The **Apps**
page shows only software and integrations that have actually been installed or
connected.

Catalog manifests may provide requirements, official source links and a guided
setup contract. A catalog entry must never imply that an external service is
installed merely because MediaHub can monitor it.

## Cloudflare Tunnel

The guided flow distinguishes values MediaHub can detect from values only the
administrator can provide. MediaHub can suggest its current private origin and
health endpoints. The administrator must choose the Tunnel, public hostnames,
connector placement, certificate path and optional metrics URL. No account-wide
API token is requested, and TLS verification is not bypassed.

## FjordHub

FjordHub is deployed from the official `qlerup/fjordhub` repository. The guide
collects the target Linux paths, persistent app-data path, port and timezone,
then shows the reviewed upstream Docker Compose commands. It warns that Docker
socket access is host-administrator access. After deployment, FjordHub remains
an optional external integration connected with its read-only Access Token; it
is not registered as a MediaHub Agent.

The current App Store intentionally does not execute arbitrary source code as
root. A future one-click lifecycle must add pinned artifacts, host policies,
transactional rollback and health verification before it may replace this
explicit guided deployment.
