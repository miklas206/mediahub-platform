# MediaHub beta — fjordcopy

MediaHub is the primary hub for the apps and services from the original MediaHub: **Seedbox, Plex, Jellyfin, Cloudflare, FjordHub and Windows folder access**, with **Healthcheck** built into the hub.

This beta uses the original MediaHub Core, Agent and React application as its functional foundation. FjordHub is an optional application inside MediaHub. Its own apps stay grouped inside its integration. The hub remains usable independently of FjordHub.

## Hub and apps

The home page presents your apps, their real connection/install status, search and the next action. Unconfigured apps have setup actions; they are not labelled as installed.

| App | What stays available |
| --- | --- |
| Seedbox | Torrents, RSS, feeds, VPN and existing Agent workflows |
| Plex | Installation, libraries, playback, resources and updates |
| Jellyfin | Existing managed installation and app access |
| Cloudflare Tunnel | Tunnel profiles, connector health and route monitoring |
| FjordHub | Separate installation/connection, own dashboard and nested apps |
| Windows folder access | SMB connection and drive-mapping guidance |
| Healthcheck | Existing Core, Agent, storage and app diagnostics |

Shared storage, updates, backups, accounts, security, activity and host management stay in MediaHub. The previous detailed dashboard remains at `/overview`. Healthcheck is directly available at `/maintenance`; opening that page does not run cleanup.

## Architecture

```text
Browser -> HTTPS MediaHub Core (hub, accounts, app pages, integrations)
                         |
                         +-> authenticated local/remote Agents
                         |      +-> Seedbox, Plex, Jellyfin and approved storage
                         |
                         +-> Cloudflare monitoring
                         +-> FjordHub (separate application with its own apps)
```

Core does not receive the Docker socket. The existing Agent policies, verified TLS, encrypted settings and storage boundaries remain in place. Host addresses and app locations are configuration, not hardcoded parts of the product.

## Beta deployment

Repository: [miklas206/fjordcopy](https://github.com/miklas206/fjordcopy), branch `main`.

This is a beta redesign. The current transition reuses the compatible original beta Core/Agent installation and its persistent state. It does not attach production Agents or copy production databases. Preserve the Core database together with its `secrets.key`, TLS trust, Agent credentials, runtime configuration and image references before changing an existing installation.

The original deployment instructions remain in [docs/install.md](docs/install.md). This repository is private: automated unauthenticated GitHub downloads require repository access to be provisioned first. Use an authenticated checkout for installation; do not use the original MediaHub repository as this beta's update source.

For private main-branch updates, the beta supports a dedicated **read-only GitHub deploy key**, mounted read-only into Core. Configure `MEDIAHUB_SOURCE_GIT_REPOSITORY` for the exact repository and `MEDIAHUB_SOURCE_GIT_SSH_DIR` for a directory containing `id_ed25519` and verified `known_hosts`. The directory must be readable by the Core user. Git uses strict host verification. Update archives still pass through the existing digest checks, host source policy, backups and rollback workflow. The usual encrypted GitHub-token flow remains available when SSH source access is not configured.

Both the platform's `release_repository` setting and the host updater's `sourceRepository` policy must select the beta repository. Changing a Git remote alone does not update this trust boundary. A source update is separate from updating remotely installed apps and Agents.

## Transition from the first beta attempt

The initial beta accidentally used a renamed FjordHub runtime. That implementation is retained in Git history and branch `archive/fjordhub-based-beta-6dfaca5`, but is no longer the application foundation.

The corrected beta retains the administrator created during that attempt by transferring the validated Argon2 password hash within the beta guest, keeping the original database for recovery. Sessions and application access tokens are not copied. The original MediaHub login normalizes the username; the password remains unchanged. Extra profile fields remain in the preserved source database and migration metadata.

## Development

Use the original project's Python and frontend requirements: [pyproject.toml](pyproject.toml), [requirements.lock](requirements.lock), and [frontend/package.json](frontend/package.json). Build both Core and Agent from this checkout. Keep temporary test state, secrets and media out of the source tree and Docker build contexts.

Run focused tests for the changed app flows, TypeScript, relevant ESLint and browser checks at desktop/mobile widths before deploying. Mocked browser fixtures prove UI behavior; they do not prove an external app is installed on the beta host.

## Origin

The functional baseline is [miklas206/mediahub-platform](https://github.com/miklas206/mediahub-platform), commit `98fa2819afafa90bbcda03891acaa753eb35f1c6`. Its history, Apache-2.0 [license](LICENSE), notices and original app functionality are preserved. FjordHub inspired the hub-oriented organization and remains an independently managed app.
