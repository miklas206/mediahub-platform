# Developer workflow

Use the quick start in the root README. Python tests use a fresh temporary directory per fixture and
never contact production. The mock app is a real stateful test adapter, clearly labelled in the UI.

## Migrations

Run `mediahub migrate` or `python -m mediahub.cli migrate`. Startup also upgrades the new database to
head for development convenience. Do not point MEDIAHUB_DATA_DIR at an existing unrelated application.
For a new schema change: `alembic revision --autogenerate -m "description"`, inspect the migration and
test both clean install and upgrade of a previous database. Future production updates must take a
consistent backup before migration; automatic production migration is not claimed by Phase 1.

## Contracts

`python scripts/export_contracts.py` regenerates the manifest JSON Schema and OpenAPI file. Source schemas
are strict and credentials have length bounds. Error responses do not echo submitted input values.
Frontend DTO generation is a future developer-experience improvement, not silently claimed as complete.

## Safety

The development server defaults to 127.0.0.1:18765. Vite uses 15173. QA uses 18766 with a random account
and a separate directory under .qa. None of these ports is a production service port.
Do not run QA against an existing server; its script creates and tears down its own server process.

## Supported execution

Python 3.12 and Node.js 22.12+ are the initial targets. A Windows source run is tested locally. Linux
container execution requires the CI Docker smoke test before marking the Docker artifact verified.
The provided CI workflow performs build, unit tests and a loopback-only container startup test.

Frontend dependency build policy explicitly permits esbuild only. If pnpm detects a changed store
between sandboxed and normal execution, rerun install in one consistent environment; do not run
concurrent package installations. No global package upgrade is required.
