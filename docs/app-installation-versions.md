# App installation versions and cleanup

New managed Plex and container-app installations fetch the publisher's `latest`
image at the time of installation. A successful pull and a matching publisher
digest are required, including when Docker has a cached image. An unavailable
registry stops the installation; the installer does not silently use the cache.
Plex accepts installation immediately and downloads/provisions in the background;
its private operation record exposes progress or failure and detects interruption
after a restart. Proxy timeouts therefore do not cancel a cold image download.
The created container uses the returned immutable publisher digest. Starting,
restarting or retrying an already installed container does not upgrade it.

The dedicated legacy Seedbox transaction fetches current Gluetun and qBittorrent
images during preflight and again when installing. Actual publisher pins are
stored in the private installation record and checked on later runtime actions.
Adopting existing containers preserves their versions and does not pull or
replace them. This legacy wizard is not the independent MediaSeed installer.

FjordHub's installer clones the current upstream default branch, pulls its
image-only Compose services and rebuilds from that source with fresh base images
and without a previous build cache. Its checkout and `.env` are needed for
subsequent operation and updates and remain in place.

Docker pulls stream directly into Docker's image store: they do not leave
downloaded tarballs on the media disk. Plex's temporary preparation container is
stopped and removed in `finally`, and private metadata writes remove their
temporary files. Image layers, configuration, encrypted credentials, install
records, rollback data and media are required durable state. No global image,
volume, container or media pruning is performed after app installation.
Core bootstrap no longer pre-downloads an old Plex image before the user chooses
to install Plex. The Proxmox bootstrap clones into a newly allocated temporary
workspace and removes that exact workspace after successful installation. It
checks the resolved path before removal. Failed installs retain their source
workspace for diagnosis; existing checkouts are never cleanup candidates.

MediaVPN now remains visible on the hub even before configuration, with a setup
page explaining its independent deployment. The fresh release still needs an
operator-provisioned MediaVPN/MediaSeed Compose installation and SSO registration;
this change does not add an automatic installer for those apps. Cloudflare is
an existing external connector/monitor, not a Docker installation owned by this
hub. These entries must not imply a working automatic install or healthy VPN.

Validation uses synthetic Docker responses, verifies warm-cache pulls, failed
pulls without fallback or container creation, immutable publisher pins,
Seedbox pin persistence and Plex helper cleanup. No real torrent, tunnel,
existing app installation or media file is changed by these tests.
