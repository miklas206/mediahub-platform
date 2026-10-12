# MediaHub beta: FjordHub-style architecture

Direction authorized on 2026-10-09. Scope: `miklas206/fjordcopy` and the beta only.
Production `miklas206/mediahub-platform` is not a migration target.

## Target

Use FjordHub's responsibility boundaries, not its branding or app catalog:

- One hub owns app discovery, setup, identity, permissions and local lifecycle.
- Apps are independent Docker Compose projects with their own configuration,
  persistent data and domain-specific services.
- A separate updater owns hub updates so restarting the hub does not stop apps.
- Reverse-proxy routing supports hub and app access; direct app ports remain
  configurable where required.
- Host helpers are restricted to explicit operations, not unrestricted commands.
- MediaHub keeps its own appearance, icons, terminology and supported apps.

The source reference is qlerup/fjordhub commit
`b63d176985cecdd6a8f88588d62f6d74e197598f`. Its hub uses Flask/Gunicorn, Jinja,
static JavaScript, direct Docker/Compose access, Traefik and an updater service.
Its SSH storage helper is not equivalent to MediaHub's general Agent.
A read-only Docker socket bind does not make Docker control unprivileged.

## Migration Gates

1. Simplify the existing app home while retaining real installed/connected state
   and MediaHub styling. Keep diagnostics on their dedicated pages.
2. Implement and test the hub-owned Compose lifecycle for one supported app,
   including install, restart, update and uninstall-with-data-preservation.
3. Move app definitions to an explicit manifest contract without losing current
   configuration, storage validation, encrypted credentials or access policies.
4. Migrate hub identity, sessions, per-app permissions and persistent settings
   with a tested account/data migration and rollback path.
5. Introduce the separate hub updater and routing. Verify app containers stay
   running during hub self-update and rollback.
6. Replace remaining runtime dependencies and frontend delivery in controlled
   steps. Remove the old Agent only after no live workflow depends on it.

## Single-Hub Installation Profile

New installations can select `install.sh --hub-stack` with the normal storage
and LAN options. Existing authorized beta installations use
`python3 scripts/migrate_hub_stack.py --root /opt/mediahub --apply` from a
reviewed source checkout. Without `--apply`, this performs a read-only preflight.
Never run this on production or the Proxmox hypervisor.

This profile embeds the existing validated runtime in the hub process using an
internal ASGI transport; it does not publish the runtime routes or an Agent port.
Traefik forwards TLS to the hub without replacing browser certificates. Accounts,
policies and mounted app storage remain at their original paths. Migration builds
before downtime and snapshots account/runtime state for rollback. The old Agent
container is stopped rather than deleting its data.

The updater remains a separate systemd host service, not yet a container. Source
updates rebuild only the hub and snapshot both hub and runtime state. Independent
app containers are not update targets. Flask/Jinja parity and manifest-driven
Compose lifecycle for every app remain separate migration work. This is not a
claim that the full FjordHub architecture has already been reproduced.

## Deployment Boundaries

Preserve the existing beta user account, app data and rollback material.
Do not reset shared or externally mounted storage. No production deployment.
Source push, locally validated behavior and installed beta version must be
reported separately. An architecture migration requires executable validation
of auth, storage and lifecycle, not only editor diagnostics.