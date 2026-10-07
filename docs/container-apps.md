# Container apps in the App Store

Jellyfin, Prowlarr, Radarr, Sonarr and optional autobrr use a shared guided
installation page. Each runs in its own digest-pinned container. This change
does not install, update or restart anything until an administrator explicitly
reviews and confirms an installation in MediaHub over HTTPS.

## Host preparation

New installations made with `scripts/install_linux.py` generate
`agent/container-apps.json` and configure
`MEDIAHUB_AGENT_CONTAINER_APPS_POLICY_FILE=/state/container-apps.json`.

Existing installations and separately paired Agents require an operator-owned
policy file and this environment variable on the chosen Agent. Core and Agent
must both be updated. Configure this on the Docker guest, never on the Proxmox
hypervisor. The installer deliberately does not invent or modify host trust.

Example policy structure (replace every example with approved host values):

```json
{
  "hostId": "local",
  "bindAddress": "192.168.1.110",
  "uid": 10001,
  "gid": 1000,
  "hostMountSnapshot": "/host-evidence/snapshot.json",
  "requiredFilesystemUuids": {"/media": "approved-filesystem-uuid"},
  "storageMarkers": {"/media/.mediahub-marker": "approved-filesystem-uuid"},
  "storage": {
    "config": {"label": "App data", "kind": "appdata", "path": "/media/appdata"},
    "films": {"label": "Movies", "kind": "movies", "path": "/media/movies"},
    "series": {"label": "TV", "kind": "tv", "path": "/media/tv"},
    "downloads": {"label": "Downloads", "kind": "downloads", "path": "/media/downloads"}
  }
}
```

Reuse the existing approved mount evidence and marker, not placeholder values.
The snapshot must describe the host mount namespace and be refreshed at least
every 30 seconds. Bind directories must be visible at identical paths on the
Agent and Docker host. They must already exist on the verified storage.
UID/GID must have the needed access; with a non-root Agent, use its UID for
configuration ownership. No recursive ownership or permission changes are made.

On the installation page choose the host and logical storage IDs, then review
and confirm the plan. Changed plans must be reviewed again. Host paths, images,
container names and arbitrary Docker settings cannot be supplied by the browser.

## Storage and network

| App | LAN port | Container mounts |
| --- | --- | --- |
| Jellyfin | 8096 | `/config`, `/cache`, optional read-only `/movies` and `/tv` |
| Prowlarr | 9696 | `/config` |
| Radarr | 7878 | `/config`, writable `/movies`, writable `/downloads` |
| Sonarr | 8989 | `/config`, writable `/tv`, writable `/downloads` |
| autobrr | 7474 | `/config` |

Configuration is under `mediahub-<app>` in the selected app-data directory.
Jellyfin cache is kept in its configuration directory and mounted at `/cache`.
All apps run as the policy's non-root UID/GID with capabilities dropped and no
new privileges. LinuxServer services receive a UID-owned `/run` tmpfs.

Only the policy's private LAN address is published. No public route, reverse
proxy, router forwarding, host networking, GPU or Docker socket is exposed to
these apps. An owned `mediahub-apps` bridge allows the apps to communicate using
`mediahub-prowlarr`, `mediahub-radarr`, etc. Their external web interfaces use
HTTP on the LAN; configure each app's own authentication before adding secrets
and do not publish these ports to the Internet. These containers are not VPN
gateways. Existing Seedbox torrent transfers retain their separate VPN flow.

## Operation and limitations

Installation acceptance is not successful startup. The page polls Docker
runtime state and sanitized installation failures. A running container is not
reported as a verified healthy app: application-level health is not yet checked.
Start, stop, restart and runtime-only removal use ownership, image and mount
verification. Removal preserves configuration, cache, media and downloads.

The Agent monitors approved storage every five seconds, stops owned apps when
storage verification fails, and resumes desired-running apps when it recovers.
Docker auto-restart is disabled so it cannot bypass that check. Agent shutdown
does not stop the apps; the guard is unavailable until the Agent returns.
Installation tasks interrupted by Agent shutdown can be retried using the
durable ownership record. Foreign or mismatched containers are never removed.

Configure libraries, indexers, authentication and download clients in each app
after installation. No NordicBytes credentials, API scraping, automatic filters,
download-client links or removal of completed downloads are configured here.
Do not enable client-removal rules that conflict with tracker seeding obligations.
External apps do not yet follow MediaHub's proposed five-download/15-minute queue.
Enable automatic downloading only after its separate integration is implemented.

For a Seedbox on another host, configure an explicitly authorized reachable
client endpoint and remote path mapping. Shared `/downloads` paths inside Radarr
and Sonarr do not automatically map the remote client's paths. Keep source files
seeding and choose copy/hardlink import rather than moving source downloads.
Separate bind mounts may prevent hardlinks even on one filesystem.

The current images are immutable registry manifests resolved on 2026-10-07.
Automatic app image updates and GPU acceleration are not implemented in this
version. Back up each app's configuration directory independently; existing
Plex/Seedbox backup APIs do not cover these apps.