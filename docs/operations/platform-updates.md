# Platform updates from GitHub source

MediaHub downloads **source code** from GitHub and builds Core and the local
Agent on the user's server. Normal releases no longer build or distribute Docker
images in GitHub Actions. Like FjordHub, the server builds the software it runs;
unlike FjordHub's branch tracking, MediaHub still selects numbered stable releases.
A push to `main` alone is not an update: tag a reviewed, tested version `vX.Y.Z`.
The tag must match `pyproject.toml`.

Checks and notifications never install software. Installation requires an
authenticated administrator action and retains the transactional rollback model.

## Source distribution and private access

The release workflow uses `git archive` at the exact tagged commit and an explicit
tracked source allowlist. Local `.qa`, `.git`, temporary files, untracked secrets,
server configuration and media are not included. The two update assets are:

- `mediahub-source-release.json`: schema 2, version, repository, commit and hash.
- `mediahub-source.tar.gz`: source tree with the `mediahub-source/` prefix.

Core talks only to the fixed GitHub API and approved GitHub asset hosts. Each
asset requires bounded size and GitHub-reported SHA-256 metadata. Both Core and
the host helper validate the archive hash against the manifest. SHA-256 checks
prove integrity against those metadata; they are not an independent publisher
signature. The configured GitHub repository is a software trust boundary.

Private repositories use a repository-scoped fine-grained token with Contents:
read, entered over HTTPS and stored encrypted. Tokens are never passed to the
host helper, Docker builds, URLs, logs or API responses. Redirects never forward
the Authorization header to asset hosts.

## Installation sequence

1. Download and validate source into the Core-owned update spool.
2. The root-owned helper checks the explicit `sourceRepository` allowlist and
   stable version against its installed-version marker.
3. Copy source into a private root-owned build directory and recheck its hash.
   Reject links, special devices, duplicate entries, absolute paths, traversal,
   excessive file counts and oversized expanded archives. Validate source version.
4. Build Core and local Agent using their Dockerfiles. Current services keep
   running. The source context contains no host secrets or data mounts. Build
   output is not sent to the UI/logs; progress identifies each build stage.
   Run isolated non-root image smoke checks without network, host mounts or
   production state before stopping the old version.
5. Only after both builds succeed, check snapshot capacity, stop Core/local Agent
   and back up their configuration/state (not media).
6. Replace their images with the exact locally built image IDs, with pulls disabled.
7. Start local Agent then Core, check readiness, record the new version.
8. If replacement/health fails, attempt restoration of the previous images and
   configuration. A build failure never stops the existing services.

This does **not** upgrade Agents on other hosts, qBittorrent, Gluetun, Plex or
cloudflared. Those require their own app/host update workflows. Download storage,
movies, TV and other media are outside the transaction and rollback paths.

## Requirements and resource implications

The host requires Python 3.11+, Docker with working builds, Compose and systemd.
At least 8 GiB free on the installation filesystem is required before source
builds, plus configuration snapshot capacity. Docker's own data filesystem also
needs sufficient free space. Build failure, including insufficient Docker space,
leaves running services untouched. Builds consume CPU/RAM and can be slower on
small servers. Each image build is bounded to 30 minutes; the UI observes up to
75 minutes. The UI timeout does not cancel a host transaction.

**Docker, BuildKit's client and build containers need outbound access** to fetch
base images, registry authorization and locked dependencies. The updater unit
therefore permits AF_UNIX, AF_INET and AF_INET6; no inbound port is opened.
BuildKit uses temporary client configuration without host registry credentials.
Source builds are not offline updates. Builds use normal isolated Docker build
networking, not the host network, privileged mode or mounts of application data.

## New and existing installations

The new-install script installs the source-capable helper and root-owned
`updates/host-capabilities.json` automatically. `--source-repository owner/repo`
can specify a fork; its default is derived from the configured image prefix.
Changing the UI repository alone does not silently expand root-level trust.

Existing installations need a **one-time host-helper migration**, from a reviewed
checkout containing both scripts:

```sh
sudo python3 scripts/enable_source_updates.py --root /opt/mediahub --repository OWNER/REPOSITORY
```

Use the actual trusted repository in place of `OWNER/REPOSITORY`. This changes
the root-owned helper, policy, public capability marker and a narrowly named
systemd drop-in allowing outbound build networking. It reloads unit definitions,
not running services. It keeps the
original helper/policy in `*.before-source`, refuses a pending/running update and
does not restart services. It copies no private keys and changes no firewall,
SSH, storage, Cloudflare or TLS settings. Core also needs this source-aware
version before it can submit source requests.

For the one-time Core transition, the release workflow has an explicit manual
`legacy_images` option that additionally builds the old schema-1 image bundles.
Old Core clients can install those bundles using their existing update button.
New clients prefer source assets and refuse source installation until the host
capability is present. Normal tagged releases publish source only; there is no
automatic fallback to unverified source execution.

Bootstrap rollback: with no update active, restore the helper and policy from
their protected `*.before-source` copies, remove the capability marker and
`/etc/systemd/system/mediahub-platform-update.service.d/source-build.conf`, then
run `systemctl daemon-reload`. A
source-aware Core will then disable source installation. Do not alter media.

## Progress and failure recovery

The update card reports download, build, backup, replacement and verification.
Only replacement causes a short Core disconnect. `succeeded` means local health
checks passed; `rolled_back` means restoration succeeded; `failed` requires
review of the protected status file. No raw credentials or build output is shown.
The two newest successful configuration snapshots are retained. Failed-state
directories remain for administrator recovery. Do not delete recovery state until
the deployment is confirmed healthy. Docker build cache is not automatically
pruned, because it may be shared with other applications.

This implementation has automated source/staging/transaction tests. Running those
tests is not evidence of a real Docker build, deployment or rollback on a server;
record those separately when the migration is actually executed.
