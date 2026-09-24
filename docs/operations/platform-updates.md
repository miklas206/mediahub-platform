# Platform updates from GitHub

MediaHub separates release discovery, download verification and privileged host
mutation. A scheduled check may create a notification, but it never installs
software. Installation always requires an authenticated administrator action.

## Release discovery and private repositories

Core contacts only GitHub's fixed API origin for the configured
`owner/repository`. It never executes a branch, raw script URL or release notes.
Public repositories require no credential. A private repository uses a
repository-scoped, read-only GitHub credential entered over MediaHub HTTPS.

Use a fine-grained token restricted to the one repository with **Contents:
read**. Core stores it in the encrypted release secret store and returns only
configured/not-configured state. It is never placed in a URL, response, event or
log. The host updater never receives the token and has no Internet-capable
address family.

Settings offers Off, hourly, 6-hourly, 12-hourly, daily, every three days and
weekly checks. A successful check stores only version/status metadata. A new
combination of available versions creates one persistent notification and an
Updates-menu badge. Repeating the same check does not create duplicate alerts.

## Required release assets

Tagging a reviewed stable commit as `vX.Y.Z` runs the release workflow. It builds
and publishes immutable Core and Agent images and attaches exactly these update
inputs to the GitHub Release:

- `mediahub-release.json`
- `mediahub-core-image.tar.gz`
- `mediahub-agent-image.tar.gz`

Each asset must have GitHub-reported SHA-256 metadata, a bounded size, an exact
GitHub repository path and an exact GitHub asset API path. Core streams the
downloads into its restricted update spool, checks size and digest while
writing, validates the strict manifest and verifies each bundle again against
the manifest. Redirects are limited to GitHub's release-asset hosts and the
repository credential is not forwarded to the asset host.

Optional registry attestations may be unavailable for a private user-owned
repository. They do not replace or weaken the exact digest checks on the offline
release bundles.

## Privileged host boundary

Core cannot change `compose.json` or talk to the host Docker socket. After all
unprivileged checks pass, it atomically creates one small `request.json` in the
spool. A systemd path unit starts the root-owned host helper.

The host helper:

1. has no network address family and receives no GitHub credential;
2. revalidates the request, manifest, bundle hashes, file types and bounded paths;
3. accepts only stable upgrades newer than the root-owned installed-version marker;
4. accepts only Core and Agent image repositories listed in the root-owned
   `update-policy.json` created at installation;
5. checks rollback space, stops only Core and local Agent, and creates a new
   configuration snapshot outside media storage;
6. loads the two offline image bundles and verifies that both immutable image
   digest references exist;
7. starts Agent first, then Core, and waits for the configured health checks;
8. records the new trusted version only after health succeeds;
9. restores the previous compose/configuration automatically if replacement or
   health verification fails.

Movies, TV, downloads and all other media mounts are outside both backup and
rollback paths. The helper never formats, moves, deletes or rewrites media. The
two newest successful configuration snapshots are retained; failed-state
directories are retained for administrator recovery rather than deleted.

## Runtime files

The standard installation uses these paths beneath the bounded installation
root (normally `/opt/mediahub`):

```text
compose.json                         root-owned deployment
installed-version                   root-owned rollback/downgrade guard
update-policy.json                  root-owned trusted GHCR repositories
platform_update_host.py             root-owned networkless helper
updates/                             Core-owned staging/status spool
update-backups/                      root-owned configuration snapshots
```

The service units are `mediahub-platform-update.path` and
`mediahub-platform-update.service`. The service uses `NoNewPrivileges`, a strict
filesystem view, a private temporary directory, `AF_UNIX` only and write access
limited to the MediaHub installation root and Docker's Unix socket.

## Failure and recovery

The Updates card shows download, backup, replacement and verification progress
inside the MediaHub card. A short browser disconnect is expected while Core is
replaced; the page reconnects to the same HTTPS address. Terminal states are:

- `succeeded`: both services passed health checks and the trusted version moved forward;
- `rolled_back`: the update failed and the previous deployment was restored;
- `failed`: the request was rejected before mutation, or update and automatic
  rollback both require administrator recovery.

Do not delete the newest `update-backups` directory or failed-state directories
until the installation is confirmed healthy. Never work around a failed release
by changing the root-owned trust policy to an unrelated image repository.

## Existing installations

An installation created before v0.4.0 needs one controlled bootstrap deployment
to add the spool mount, root-owned trust files and systemd helper. Preserve the
existing Core database, Agent state, TLS identities, encrypted secrets, storage
mappings and all media. Once that bootstrap is verified, later complete releases
can be installed from the MediaHub button without direct host changes.
