# Phase 2 verification — 15 September 2026

## Implemented

Phase 2 implemented in the separate Windows development checkout. Explicit setup state, Agent,
safe storage, catalog configuration, discovery and non-executable plans build on Phase 1.
No Phase 3 work was started. Core remains version 0.1.0-dev; Agent reports 0.2.0-dev / protocol 1.

## Setup Wizard

Ten steps, local-token administrator bootstrap, authenticated database-backed progress and review.
Fresh installations open the wizard; configured installations open the dashboard after sign-in.
Apply is revision-checked and does not install apps. Progress is saved on Continue/add-storage;
unsaved edits and pre-authentication welcome/check choices are not persisted.

## Storage System

Directory-only Agent browser, approved roots, existing/new paths with exact confirmation,
filesystem capacity and advisory permission/ownership checks. Protected paths, traversal and
symlinks/junctions are blocked. Mapping edits do not move files. New local creation is restricted
to this project's `.agent/storage-sandbox`; no production media root is approved.

## Agent

Separate authenticated loopback service. Generated token is private and is not returned to UI.
Health/version/system/runtime/discovery/directory checks implemented. The local Agent is connected,
fixtures disabled. Core has no Docker socket.

## Runtime/Docker Support

Docker engine detection through an explicitly configured Agent socket, CLI/Compose version checks,
read-only list/inspect adapter and runtime status. Docker and Compose are absent on this Windows
runtime; this is reported as unavailable, not an installation success. Core works independently.

## Existing Installation Discovery

Conservative Plex/qBittorrent/VPN image matching, sanitized mounts/ports/network/health metadata,
environment names, numeric UID/GID, allowlisted protocol, shared namespace evidence. Fixtures need
explicit development flags. Read-only SSH retry was denied; no key/authentication changes attempted.
Real-host Docker inspection therefore remains unverified.

## App Catalog

Real Plex/Seedbox metadata manifests appear as Coming Soon. Normal mode hides the mock app.
Configuration forms come from manifest fields. Preview includes containers/images/ports/storage/
secrets/dependencies/network; all plans are non-executable. Image digests are intentionally unresolved
for unavailable apps, not fabricated. Storage preview mappings are transient, not deployed mounts.

## Import Planning

Pending imports persist discovered/selected/ready/blocked states. Runtime, path/access, duplicate
candidate, port and mapping checks block unsafe readiness. Apply saves plans only. No imported state,
container mutations or media migration implemented.

## Security

Argon2id login, session/CSRF/origin protections, bootstrap token, separate Agent token, encrypted
manifest secrets with configured-only readback. Docker socket absent from both default services.
Git and Docker ignore new secret/state directories. BYO proxy; no ingress changes or 2FA claims.

## Tests

- 48 backend tests passed, including Phase 1-to-2 database migration and preservation tests.
- 2 frontend unit tests passed.
- 2 browser scenarios passed: Phase 1 regression and Phase 2 fresh/resume/admin/test-directory/
  manifest form/fixture discovery/import selection/review/apply/dashboard/skip-wizard flow.
- TypeScript, ESLint, Ruff and Python formatting checks passed; Vite production build passed.
- Desktop/mobile screenshots reviewed in `.qa`; tests wait for data and navigation transitions.
- Production Compose YAML parsed and checked for Core/Agent-only services, no published Agent port.
- Local Core health and connected Agent verified; real new Core left unclaimed for the user.

One escalated backend run failed because its identity could not access pytest's existing temporary
directory. The final backend run in the normal development environment passed all 48 tests.
Two upstream Starlette/httpx/AnyIO deprecation warnings remain; they are not test failures.

## Known Issues

Not production-audited. Linux Docker/LXC execution and host volume ownership still need target-host
validation. Internet connectivity is explicitly not probed. Windows ACL checks are advisory and
directory-creation safety assumes a private root, not a hostile local process racing paths.
Core must run single-worker. Preview storage mappings are not durable installation configuration.
Agent status is manually refreshable rather than a continuous VPN monitor. The compatibility-only
Phase 1 storage API remains; the new UI uses Agent storage.

## Linux/Proxmox Readiness

Core/Agent Dockerfiles and a non-root, resource-limited production skeleton with private networking,
separate persistent volumes, no existing mounts and no proxy. Linux assumptions and initialization
are documented. No VM/LXC was created, converted or modified.

## Changes From Original Architecture

Separate installation state from administrator existence; introduce local bootstrap trust, a
token-authenticated Agent boundary, central path policy, encrypted app configuration and pending
network settings requiring explicit activation. Preserve the less-privileged Core design.

## What Is Ready For Phase 3

Versioned Agent boundary, catalog schemas, config forms, storage validation, discovery model,
pending imports and install previews provide the foundation for a separately approved execution phase.

## What Is NOT Yet Implemented

Real app lifecycle, migration, VPN deployment/port forwarding, Plex/qBittorrent management,
GPU passthrough, updates/backups, TOTP/SSO, reverse proxy/DNS/router automation and production deployment.

## Existing Environment Safety Check

Existing services changed: **No**. Existing media/download/config data changed: **No**.
Existing directories moved: **No**. Existing containers stopped: **No**.
Only new local development/QA processes were started/stopped; the previous new Core was restarted
to load Phase 2. Read-only reachability checks returned HTTP 200 for existing Proxmox, MediaHub and
Plex. These checks establish reachability, not full service/VPN health. Phase 3 is not started.
