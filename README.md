# MediaHub

MediaHub is the hub for MediaSeed, MediaVPN, Plex, Jellyfin, Cloudflare and the optional FjordHub integration. Healthcheck is built in. The Overview shows app health, downloads, tracker account data and VPN use when the relevant apps are configured.

Release source: [miklas206/mediahub-platform](https://github.com/miklas206/mediahub-platform), branch `main`. The separate beta repository is [miklas206/fjordcopy](https://github.com/miklas206/fjordcopy).

## Runtime and storage

The hub stack runs the Core and local Agent in one process, behind an HTTPS passthrough proxy. Its Docker socket access and installation policies are privileged host capabilities. Independent MediaSeed and MediaVPN applications have separate Compose projects, data and credentials. Remote Agents remain supported.

Media mounts are external to the hub database and app data. Reinstalling the hub must preserve those mounts and their contents. Configure the existing movie, series, other-media and download paths explicitly; never format, recursively change ownership, or delete a media directory during app cleanup.

A fresh installation opens the administrator setup wizard. App data and accounts are not copied from beta. Independent MediaSeed/MediaVPN provisioning currently requires operator-owned Compose configuration; a configured address alone does not install an app. See [app management](docs/app-runtime.md) and [installation](docs/install.md).

## Updates

Build from an authenticated checkout when repository access is required. The hub's `release_repository` setting and host updater's `sourceRepository` policy must both select `miklas206/mediahub-platform`.

Private source updates support a dedicated read-only GitHub deploy key through `MEDIAHUB_SOURCE_GIT_REPOSITORY` and `MEDIAHUB_SOURCE_GIT_SSH_DIR`. Keep host verification enabled and private keys outside source archives. The encrypted GitHub-token flow is also available. Hub source updates and independent app updates are separate operations.

Normal upgrades keep rollback snapshots of the database, secrets, runtime policies and pinned images. Destructive fresh reinstalls require explicit authorization and verification that external media remains intact before old app state is removed.

## Development and attribution

Use [pyproject.toml](pyproject.toml), [requirements.lock](requirements.lock) and [frontend/package.json](frontend/package.json). Run focused Python tests, TypeScript, relevant frontend tests and builds. Keep secrets, production data, logs and media outside Git and build contexts.

This release promotes the MediaHub beta implementation while retaining the MediaHub history and Apache-2.0 [license](LICENSE). FjordHub inspired the hub-oriented organization and remains an independently managed optional app.
