# Persistent Plex and VPN lifecycle diagnostics

After updating MediaHub and its bundled MediaVPN, open Settings > Logs. The Core
view also loads persistent Agent and MediaVPN lifecycle entries. Plex's own logs
view loads persistent Plex entries. Administrator access is required.

The new journal is created automatically on first use in the existing persistent
Agent state directory and MediaVPN data directory as `lifecycle.sqlite`. Fresh
installs and upgrades use the same additive initialization; existing configuration,
profiles, media and credentials are not migrated or changed. No extra package,
device, container capability or host service is required. Docker observation runs
only when the existing Docker runtime is enabled.

Each component retains its latest 2,000 entries, across process restarts and
container replacements. The UI requests up to 200 entries per component. Identical
blocked/error observations are limited to once per minute to preserve useful
history. Core's original process log buffer remains in memory.

Recorded evidence includes:

- Authenticated VPN server-selection, start/stop, forwarding, and gateway actions.
  `origin=user` distinguishes direct app actions from `hub` and `supervisor`.
  Hub user IDs are included when available; passwords/session identities are not.
- Operation IDs linking controller decisions to their dependent lifecycle actions.
  Provider/container IDs and start generations link events between controllers.
- Runtime replacement mismatches: country selection, shared endpoint, allowed web
  targets, forwarding mode, runtime revision and stopped provider.
- Provider public IP/port changes, selected server, failed verification stage,
  Docker health state, stale health evidence and missing/unverified ports.
- Plex storage/desired-state/VPN stops, recovery starts, relay health, namespace,
  image and generation changes. Exceptions record type, application error code,
  HTTP status and the final source filename/function/line, without exception text.
- Passive owner-scoped Docker create/start/stop/kill/die/destroy/restart/OOM and
  health events. Exit code, signal and OOM state are kept after container removal;
  relay health events also sample handshake age when available. `sourceTimestamp`
  is the Docker event time; `timestamp` is when the journal recorded it.

Do not infer that every exit 137 is OOM: a controlled stop timeout also causes
SIGKILL. Compare the preceding controller decision, Docker signal and OOM flag.
Docker's restart count also resets when a controller replaces the container.

The observer never retains exec commands, arbitrary labels, raw Docker output,
exception messages, request bodies, URLs, cookies or private keys. Only explicit
scalar diagnostic fields are accepted. The SQLite file is private (0600 on Linux).
Observability errors never block a safety stop; unavailable diagnostic storage is
reported rather than silently returning an empty history.

This improves causal evidence; it is not a guarantee of total forensic coverage.
Docker does not identify the caller of arbitrary external Docker commands, so
those events explicitly report `docker_event_caller_not_reported`. Power loss,
process kill before recording, observer downtime, removed storage, or exhausted
retention can leave gaps. Observer startup/interruption entries delimit coverage.
No third-party process crash message is reconstructed from a missing old log.

Automated validation uses synthetic runtime fixtures. It covers fresh/older data
directories, persistence, operation correlation, retention, write failure, API
authentication, secret exclusion and removed-container events. Live stability and
actual incident evidence require installation and subsequent observation.
