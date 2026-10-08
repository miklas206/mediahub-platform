# Seedbox daily-use controls

The Seedbox page is the normal operator surface for VPN status, qBittorrent
status and bounded torrent actions. qBittorrent's own Web UI remains an advanced
recovery surface and is not exposed publicly.

## Live app health

The app detail page and the sidebar shortcuts use the same remote health source.
The sidebar refreshes when an app-health event arrives, when the browser regains
focus and every ten seconds while the page is visible. `critical` maps to
`unhealthy`; an offline or unverifiable Agent maps to `unknown`, never Healthy.

## Download destinations

Downloads is always available. An operator may additionally grant named logical
storage such as Movies, TV Shows or Other as a writable torrent destination.
Each extra destination must be enabled explicitly in the trusted Agent host
policy; a writable mount alone is not enough. MediaHub never accepts an absolute
path, relative path or arbitrary host path from the browser. Instead, the Agent
returns only approved storage roots as opaque identifiers plus their configured
media names. Downloads remains the default. Existing content folders, including
movie-title folders, are not additional destinations.

The Agent resolves the selected opaque identifier again immediately before
sending the request to qBittorrent. Removed roots, forged IDs and IDs previously
issued for child folders are rejected. Read-only or unapproved storage is never
a destination. Existing torrent jobs inside approved roots retain their actions.

Torrent jobs are paused by default. Removing a job continues to keep downloaded
files. Private magnet URLs and uploaded torrent bytes remain excluded from events
and logs.

During a rolling upgrade, a newer Core remains compatible with an older remote
Agent: the UI falls back to the Downloads top folder and Core omits the new
destination field. Additional logical-storage choices appear only
after the matching Agent release is active and the host mappings are configured.

## Device diagnostics

Raw block-device identity and mount inventory is not part of the daily Seedbox
page. It is available, collapsed by default, under **Settings → Maintenance →
Seedbox device diagnostics** for troubleshooting. Device presence does not by
itself prove that the qBittorrent process can write to a mount; the normal storage
guard remains authoritative.
