# Architecture — Phase 1

## Boundaries

HTTP routes validate contracts and delegate to services. AuthService, AppManager, StorageManager,
SettingsService, SystemService and EventBus own business logic. SQLAlchemy sessions are the persistence
boundary; a separate generic repository wrapper would add little in this small foundation.

Each service opens a short transaction. Mutable app data is separate from frontend/static artifacts.
SQLite lives on the local Core data filesystem with WAL and foreign keys enabled. Alembic's immutable
initial migration contains explicit schema definitions, not imports of mutable application metadata.

No Docker connection exists in startup, API routes or the mock adapter. The optional read-only adapter
under agent/ only accepts an injected transport; Unix transport must be explicitly provisioned later.

## Deliberate changes from the design report

1. **No bundled reverse proxy.** Core serves its built frontend, HTTP API and SSE on one local port.
2. **Single-process foundation.** Durable workers, outbox delivery and a privileged agent are deferred;
   this phase executes only short, database-only mock actions.
3. **Local CLI bootstrap.** No unauthenticated network endpoint can create the first administrator.
   `/api/auth/status` reports setup state for a future wizard.
4. **Explicit frontend components.** React, Tailwind and semantic controls are used without adding a
   second UI component dependency in the foundation. Shared cards, badges and layout establish consistency.
5. **Source-checkout distribution.** The wheel is backend-only. Compose assembles the complete application.

## Events and realtime

Events and activity references commit in one database transaction. The live bus publishes after commit.
A crash between commit and publication can lose a live notification, not the stored event. This is a
foundation, not a durable outbox. Browser reconnect receives a fresh system and app-health snapshot.
Activity can be reloaded from SQLite. Last-Event-ID replay and multi-worker coordination are deferred.

SSE uses a bounded queue per subscriber (32 records), 32 subscribers maximum, a three-second default
metrics cadence, heartbeat, session validity checks and automatic browser reconnect. Slow consumers
receive recent data rather than causing unbounded memory growth. Raw metrics are not stored every tick.

## Metrics

Metrics describe the OS running Core. On Windows this is the development PC. cgroup v2 memory and CPU
limits are respected when available. Cache is exposed separately. Disk usage refers to the Core data
filesystem; it does not add together external media capacity. Network rates are deltas, not counters
mislabelled as speeds. An initial missing rate displays as unknown.

## LXC target

The production goal remains an unprivileged LXC named MediaHub. Nested Docker, firewall, UID mapping,
GPU and /dev/net/tun require a separate Linux acceptance test before deployment. No host-wide security
relaxation, Proxmox modifications or existing VM stop is part of Phase 1.
