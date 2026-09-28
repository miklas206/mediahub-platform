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
returns the approved storage roots and at most 100 existing direct child folders
as opaque identifiers plus display labels. The Downloads top folder remains the
default for compatibility.

Hidden folders, symbolic links, files, nested paths and non-printable names are
not offered. The Agent resolves the selected opaque identifier again immediately
before sending the request to qBittorrent. A removed, renamed or forged choice is
rejected. This keeps system paths and all unapproved storage unavailable. The
Agent rechecks every selected location immediately before adding the torrent.
Read-only media mounts can never be made a destination.

Torrent jobs are paused by default. Removing a job continues to keep downloaded
files. Private magnet URLs and uploaded torrent bytes remain excluded from events
and logs.

During a rolling upgrade, a newer Core remains compatible with an older remote
Agent: the UI falls back to the Downloads top folder and Core omits the new
destination field. Additional folder and logical-storage choices appear only
after the matching Agent release is active and the host mappings are configured.

## Device diagnostics

Raw block-device identity and mount inventory is not part of the daily Seedbox
page. It is available, collapsed by default, under **Settings → Maintenance →
Seedbox device diagnostics** for troubleshooting. Device presence does not by
itself prove that the qBittorrent process can write to a mount; the normal storage
guard remains authoritative.
