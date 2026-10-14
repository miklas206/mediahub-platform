# App installation progress and failed Plex recovery

MediaHub 0.6.1 shows installation progress for every hub-owned installer:

| Installer | Progress source |
| --- | --- |
| Plex | Durable Agent phases: preparation, download, storage, container creation, start, completion |
| Jellyfin, Prowlarr, Radarr, Sonarr, autobrr | Agent container-install operation and phases |
| MediaSeed, MediaVPN | Managed installation operation, containers, health and hub registration |
| FjordHub | Active SSH deployment state and console; indeterminate until completion |
| Legacy dedicated Seedbox | Completed transaction steps and safety checks |

Image downloads have an animated bar when byte-level progress is unknown.
Displayed phase percentages describe the installation workflow, not bytes or
time remaining. A 100% bar requires a successful backend operation. Plex's
container-start completion is separate from subsequent account/library readiness.
Healthcheck is built into Core and has no separate app installation. Cloudflare
is a MediaVPN integration; apps managed inside FjordHub keep FjordHub's own UI.

Progress is restored from server state after reloading. Temporary status failures
retain the last received progress and polling continues without resubmitting an
installation. An ongoing FjordHub deployment opens its installation step again.

## Remove a failed Plex installation

After updating Core and its embedded Agent, use **Uninstall** on the Plex card
and confirm the removal. A failure before Plex's managed runtime policy was
written can use the durable, server-created installation record instead. No
installation identity or container ownership is inferred from user-entered paths.

The failed-install cleanup checks exact package/installation labels and expected
Plex/helper names. A managed main container additionally passes its normal image
and mount ownership checks. It stops/removes only verified containers, preserves
media, app data, encrypted credentials and Docker volumes, then checks that no
containers for that installation remain. MediaHub retains its registration until
the Agent confirms removal. An active installation cannot be removed concurrently.

Validation uses synthetic Agent/Docker responses and an isolated Playwright
Chromium with mocked API responses. It does not install or remove a live app.
