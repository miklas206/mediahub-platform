# Existing installation discovery and planning

Discovery is opt-in, authenticated and read-only through Agent. With no explicitly configured
Docker socket it reports unavailable; Core still runs. Never attach production Docker or media
to the development environment just to remove a warning.

Only GET engine version, container list and inspect are used. The output is allowlisted:
container identity/image/status/health, ports, network names/mode, mounts, environment variable
NAMES, numeric PUID/PGID and an allowlisted VPN protocol. Secrets, tokens, passkeys, labels and
arbitrary environment VALUES are not returned. Mount paths/container names are administrator-only
operational information. Image matching identifies *possible* Plex, qBittorrent and VPN containers;
shared network namespaces are evidence, not proof of VPN health or a working kill-switch.

Development fixtures require BOTH Agent dev mode and fixtures enabled. They are synthetic,
visibly labelled and always block execution. Neither flag is enabled by default.

Discovered records persist as pending imports. Selection records `selected`; review produces
`ready` or `blocked` based on runtime, ports, source/target paths and duplicate ownership.
Even a ready plan has `executable: false`. Apply stores the findings and source references only.
No download, rename, move, restart, stop, compose deployment or migration exists in Phase 2.
Port collisions with a currently running source are expected blockers for a later cutover plan.

Back up real configuration and media independently before any future migration. A generated plan
is not a backup, and an empty spare disk is not a verified backup.
