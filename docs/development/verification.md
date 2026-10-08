# Phase 1 verification — 2026-09-15

## Implemented

Separate Core foundation, real local auth, database and migrations, typed manifests/registry,
database-only mock lifecycle, read-only storage checks, typed settings, structured logs, activity,
real system metrics and authenticated SSE. Responsive dashboard and all requested navigation routes.
Updates and Backups are explicitly deferred, not fake implementations.

## Repository Structure

frontend/, backend/mediahub/, backend/migrations/, apps/mock/, agent/, packages/contracts/,
docker/, docs/, scripts/, tests/, .github/. A new local Git repository was initialized only here.
No commit, push, GitHub repository or public deployment was created.

## Tech Stack

Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite WAL, Argon2id, React 19, TypeScript, Vite,
Tailwind CSS, SSE, pytest, Vitest and Playwright. Runtime package versions are captured in requirements.lock
and frontend/pnpm-lock.yaml. Application version is 0.1.0-dev (Python package 0.1.0.dev0).

## Running Services

- New Core: http://127.0.0.1:18765, running on the development PC.
- Same process serves the built frontend, REST API and SSE; no proxy is installed.
- New SQLite database under .data/, migration 0001; one clearly marked mock app.
- No production Docker connection or media mount.
- QA server on 18766 was stopped by its runner after each test.
- No persistent Vite server is required for the built frontend.

The new development database intentionally has no administrator yet. The user must select credentials
using the local admin command. Browser tests used a random-password account in a different QA database.

## Tests

| Check | Result |
|---|---|
| pytest | 32 passed |
| Vitest | 2 passed |
| Playwright | 1 end-to-end scenario passed |
| Python Ruff lint | Passed |
| Python Ruff format check | 25 files passed |
| Frontend ESLint | Passed, no remaining rule warnings |
| TypeScript tsc -b | Passed |
| Vite production build | Passed |
| Python wheel + source build | Passed |
| JSON Schema / OpenAPI export | Passed |
| Running /api/health | HTTP 200, healthy, 0.1.0-dev |
| Running / | HTTP 200, built frontend |
| Unauthenticated /api/apps | HTTP 401 |
| SQLite integrity_check | ok |
| Alembic schema | 0001; metadata comparison test passed |
| Desktop and 390px mobile screenshots | Inspected; mobile has no horizontal overflow |

Browser test verifies login, actual metrics, changing SSE timestamps, mock stop/start, activity,
settings persistence after reload, mobile navigation, logout and no JavaScript page errors.
Backend tests cover CSRF, origin rejection, rate limiting, hashed session tokens, expiry/revocation,
manifest errors, duplicate YAML keys, dependency cycles, errors without secrets, storage permission
denial, unchanged test-file contents/mtime, schema consistency and Docker read-only filtering.

## Known Issues

- Docker Engine is not installed on the development PC. Compose structure is tested, but the Linux
  image build, container startup, non-root volume permissions and cgroup behavior have NOT been
  runtime-verified here. A CI container smoke test is provided but has not run on GitHub.
- Target Proxmox LXC has not been created or changed in this phase.
- Two upstream Starlette test-client deprecation warnings remain; tests pass. ESLint 9's package
  installer also reports that its major is no longer supported. Toolchain refresh is required before
  a public stable release; this is a pinned, tested development toolchain, not a security certification.
- Windows directory ACLs are inherited. No production audit, encrypted secret vault or TOTP yet.
- Event delivery is live snapshot-based, not durable outbox/replay. Throttle and bus are single-process.
- Raw Docker logs, real Docker mutations, signed app installation and a privileged agent are not enabled.
- Backend wheel alone is not a complete installation; use the source checkout or future-tested image.
- The full old-container runtime check could not be authenticated; existing SSH key was rejected.

## Decisions Made

- Bring your own proxy, superseding the initial Caddy proposal.
- CLI-only initial administrator setup; no remotely claimable uninitialized server.
- No writable filesystem probes. Storage checks are explicitly advisory.
- Approved-root storage validation; default root is the new Core data directory only.
- Only a mock app can execute lifecycle actions. Existing services remain outside the new platform.
- Environment metrics are labelled as the development runtime, not falsely reported as Proxmox metrics.

## What Was Intentionally Left For Phase 2

Complete first-run wizard, richer storage discovery and safe mapping workflows, import planning,
mount identity checks and LXC deployment validation. Actual production migration needs its own approval.
Later phases add real Seedbox/VPN and Plex, durable jobs, updates/backups and extended authentication.
No Phase 2 work was started.

## Exact Commands To Start Development

From the new repository on this Windows PC:

```powershell
.\.venv\Scripts\python.exe -m mediahub.cli admin
# Run serve only when the current development server has been stopped:
.\.venv\Scripts\python.exe -m mediahub.cli serve
```

For frontend editing in a second terminal: `pnpm --dir frontend dev`, then open 15173.
The root README contains clone-to-run commands and Docker commands for another development machine.

## Exact URL To Open MediaHub

http://127.0.0.1:18765

This URL is on the development PC, not the Proxmox server. It is intentionally loopback-only.

## Existing Environment Safety Check

No old installation files, configurations, containers, volumes, service states, media directories,
firewall rules or Proxmox settings were changed by this Phase 1 implementation.
All authored project files, test databases and builds are within the new mediahub-platform directory.
Dependency managers also used their normal local caches; no global package upgrades were performed.

Read-only LAN checks: Proxmox page HTTP 200; existing MediaHub's normal hostname HTTP 200;
existing Plex /identity HTTP 200. A direct HTTPS request to the old hub's IP hit a TLS/SNI error;
the normal hostname succeeded. No existing service was restarted to resolve it.

The old SSH key was rejected, so qBittorrent/VPN container status and unchanged container IDs were
not independently verified in this phase. This limitation must not be presented as a successful check.

## Networking / External Access Notes

No Caddy, Nginx, Traefik, Cloudflare Tunnel, DNS change, certificate or port forwarding was installed.
Core serves HTTP directly. HTTPS base URL enables Secure cookies; exact origins and explicit trusted
proxy IPs are configurable. SSE responses disable buffering and send heartbeats. External ingress is
the operator's choice and responsibility. No public access is enabled by this development setup.
