# Optional Plex GPU sidecar

An operator-installed Plex GPU adapter can run in its own Docker container on
MediaHub's existing Plex host. The uploaded adapter remains a separate local
project; MediaHub does not redistribute it or change Plex account entitlements.

The operator installer registers the exact image ID and Plex installation in
`plex-gpu-transcoder.json` in private Agent state and the paired host binding
`plex_gpu_installation`. A fresh hub without this explicit registration creates
no GPU app and makes no GPU requests. At startup, an installed component is
registered idempotently with its observed state. The app shows GPU measurements,
connection status, a LAN dashboard link, and start/stop/restart controls which
address only the owned GPU container. Media files are mounted read-only.

A linked Plex plan mounts a static client over Plex's transcoder executable and
uses a private Unix socket for jobs and local Plex callbacks. Plex retains its
original image, non-root user, read-only root filesystem, identity, libraries,
encrypted preferences, RAM configuration volume and VPN namespace. Before each
guarded Plex start, a network-isolated helper copies the original transcoder
from that exact official image into the existing RAM volume. This also prepares
the matching fallback after an official Plex update. A fixed executable check
starts the private callback relay after Plex starts. No Docker socket or TCP
command interface is exposed to the adapter. Unsupported jobs and unavailable
workers use the original transcoder. The separate adapter currently delegates
HDR to the original transcoder until tone mapping is validated.

The dashboard reports whole-card encoder usage; other GPU applications can
contribute. Direct Play creates no transcode job. An idle GPU can correctly show
zero encoder usage. Server profile and browser tests do not certify every
physical TV, console or mobile application.

The operator installer keeps a guarded rollback container and the previous
private Plex plan. Disable the link with the local installer's `--disable`
command before removing the sidecar. Generic app removal is deliberately not
offered while Plex depends on the adapter client. Update the registered image ID
and reconcile read-only media mappings through the installer when upgrading the
adapter or changing Plex's media mappings.
