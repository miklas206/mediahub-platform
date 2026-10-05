# Platform updates from GitHub source

MediaHub downloads **source code** from GitHub and builds Core and the local
Agent on the user's server. The update channel follows the configured repository's `main` branch.
The installed Git commit is compared with `main`; a new commit is an update even
when the version number is unchanged. No release or tag is required.
Push reviewed code to `main`, then use Check GitHub and Install update. Checks
never install automatically. The selected full commit SHA pins both metadata and
archive download even if main advances while the installation is downloading.

Checks and notifications never install software. Installation requires an
authenticated administrator action and retains the transactional rollback model.

## One-time transition from release checks

Existing installations need both this Core version and the updated host helper.
From the reviewed checkout on the MediaHub Linux host, run
`sudo python3 scripts/enable_source_updates.py --root /opt/mediahub --repository OWNER/REPO`.
This preserves repository trust and seeds the installed commit from the running
Core image's revision label. The UI gates installation on `mainBranchUpdates`
until the helper supports schema 3. No release is needed after this transition.

The Core downloads GitHub's archive for the pinned commit, bounds its compressed
and expanded size, rejects links/traversal, and repackages only build inputs. It
computes SHA-256 for the root helper's independent integrity check; this hash is
not a GitHub signature. GitHub HTTPS and the configured repository are the source
trust boundary. Tokens are sent only to api.github.com, never archive redirects.
The host stores the installed commit only after healthy startup and restores its
previous marker on rollback. Changing main with a force-push is also treated as
a code change; lower application version numbers are rejected at install time.

## Legacy release distribution and private access

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

### Automatic fast updates and incremental builds

Routine releases reuse Docker layers for unchanged inputs. Python runs directly
from the copied application source with dependencies from `requirements.lock`;
there is no per-release Python package installation. The frontend build uses a
package manifest without its release version, and the UI reads the installed
version from Core. A backend-only release therefore reuses the frontend bundle.
Changes to dependencies or build recipes still invalidate the affected layers.

The host helper fingerprints Agent inputs and records the result in the
root-owned `agent-build-cache.json` only after successful health checks. It reads
the Agent Dockerfile's local `COPY`/`ADD` inputs, including complete copied
directories, the recipe itself and Docker ignore files. Frontend, app-catalog and
Core-only changes therefore do not rebuild Agent unless its recipe actually
copies those files. Shared backend code, Agent code and dependencies remain
inputs. Distribution-version-only changes are ignored for Agent.

The update page advertises **Automatic fast update** when the installed host
helper supports it. After verifying and extracting the release, the helper chooses
**Fast update** when Agent's inputs and immutable image match the last successful
update and that image is actually running. Only Core is built and replaced; Agent
continues running. Core still builds to publish the new release version, and
Docker automatically reuses unchanged layers, including the frontend bundle.
Progress and console output identify the selected mode and the reason.

Missing or invalid cache evidence, a stopped or mismatched Agent, or changed Agent
inputs selects **Full update**. Unsupported recipe constructs (such as wildcard
sources, build-context mounts, build-stage copies or custom syntax) also select a
full build, rather than guessing which files matter. Both modes retain the usual
release verification, configuration snapshot, health checks and rollback. Neither
mode prunes Docker objects or changes media files.
If the fingerprint and the installed immutable image match, the Agent remains
running and only Core is built, snapshotted and replaced. Missing, invalid or
mismatched cache evidence causes a normal full build. The first update with the
new helper establishes the baseline. An unchanged Agent can report an older
distribution version because its executable code has not changed.

**Enabling automatic mode on existing hosts:** install the host helper from the
same reviewed checkout as this feature using the migration command below. The
command also publishes the root-owned `automaticFastUpdate` capability. Updating
Core alone does not upgrade that helper, so the UI indicates when a refresh is
needed. The revised fingerprint intentionally establishes a new baseline: the
first update is full; later eligible updates automatically use fast mode. New
Linux installations advertise this capability immediately.

**Existing hosts:** Core updates do not replace the root-owned host helper. From
a reviewed checkout of v0.4.18 or newer, run the existing migration command once
(with no update running or queued):

```sh
sudo python3 scripts/enable_source_updates.py --root /opt/mediahub --repository miklas206/mediahub-platform
```

Use your configured repository if this is a fork. The command refreshes the helper
without installing a Core release or restarting running applications. Without this
refresh, the Dockerfile cache improvements apply but the old helper still processes
both services. Subsequent normal updates need no helper refresh for this feature.
Release downloads still contain the complete verified source archive; incremental
behavior concerns builds and service replacement, not byte-range patch downloads.

### Transaction status

Starting with 0.4.20, expand **Console** on the update progress card to see recent
status and build output. Temporary disconnections retain the last real percentage,
steps and history; successful completion keeps the console available to read.
The updated host helper publishes the last 40 sanitized build lines, while the
browser retains up to 120 observed lines. It is a rolling console, not a complete
downloadable build transcript. Common credential patterns are redacted before
publication; raw temporary build output stays in the private build workspace and
is removed afterward. No interactive commands can be entered through this view.

Existing hosts need the same one-time `scripts/enable_source_updates.py` command
above, from a checkout of **v0.4.20 or newer**, to publish Docker output. Updating
Core alone enables stable progress and status-message history but cannot make an
old host helper emit build logs. Do not refresh the helper during an active update.

The update card reports download, build, backup, replacement and verification.
Only replacement causes a short Core disconnect. `succeeded` means local health
checks passed; `rolled_back` means restoration succeeded; `failed` requires
review of the protected status file. Build output is bounded and redacted.
The two newest successful configuration snapshots are retained. Failed-state
directories remain for administrator recovery. Do not delete recovery state until
the deployment is confirmed healthy. Successful updates prune unused build cache
older than 24 hours while keeping a 4 GB cache budget.

## Faster shutdown during updates

Core closes browser event streams before the HTTP server drains active requests
during shutdown. Keeping the dashboard or update page open no longer leaves an
indefinite event stream holding shutdown until Docker's stop timeout. Ordinary
requests still drain normally; configuration snapshots and rollback are unchanged.
This improvement applies once the running Core contains the fix: the update that
first installs it still stops the previous version using its previous behavior.

## Manual maintenance

Settings → Maintenance → **Run maintenance** performs health checks and requests
host-side cleanup. It runs independently of the browser and reports recovered
system disk space. Updates and maintenance cannot run concurrently.

Cleanup removes only known update archive/manifest files in old staging folders,
unused MediaHub source images that are not referenced by any container or rollback
snapshot, and unused Docker build cache older than 24 hours. Manual maintenance
does not retain the automatic update's 4 GB cache budget. Subsequent builds may
need to rebuild cached layers, including those shared with other applications.
It never prunes volumes or containers, scans media folders, or deletes app data,
configuration, rollback backups or unknown files. Failed recovery directories
remain available for investigation.

Existing installations require an explicit administrator refresh of the host helper
from a reviewed checkout containing the maintenance implementation, as root on the
MediaHub host. Adjust `--root` if the installation is not at `/opt/mediahub`:

```sh
sudo python3 scripts/enable_source_updates.py --root /opt/mediahub --refresh-helper
```

This mode preserves existing repository trust. Source-enabled hosts retain source
updates; image-only hosts gain maintenance without enabling source updates or
changing the updater's network restrictions. Use the existing `--repository
OWNER/REPOSITORY` mode only when deliberately enabling source updates; it is not
required for this refresh and cannot be combined with `--refresh-helper`.

Do this while no update or maintenance operation is active. Updating Core alone
only replaces application images, not the root-owned host helper. The UI reports
missing support until the real helper is installed and advertises its maintenance
capability; editing the capability file alone is not a supported migration.
The refresh retains the first helper/policy backups for administrator rollback,
does not run cleanup, and does not restart app containers. New installations
include the capability automatically.

The standard system disk allocation is 64 GiB, separate from media storage.
Existing guests must be expanded in Proxmox; installing code does not resize them.

This implementation has automated source/staging/transaction tests. Running those
tests is not evidence of a real Docker build, deployment or rollback on a server;
record those separately when the migration is actually executed.
