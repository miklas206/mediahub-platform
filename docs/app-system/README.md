# App framework

Manifests are YAML with schemaVersion 1, validated against strict Pydantic models. Generate JSON Schema
with `python scripts/export_contracts.py`. Files are limited to 128 KiB; YAML tags, anchors and aliases
are rejected. Unknown fields, invalid references, port ranges and capability names are rejected.

The registry validates duplicate IDs, Core compatibility, missing dependencies and dependency cycles.
Version ranges use Python packaging SpecifierSet syntax: `>=0.1.0,<0.2.0` (comma separated).
App version strings use Semver syntax. Avoid build-metadata-sensitive dependency selection in Phase 1.
Optional dependencies are declared but not auto-installed or activated.

The lifecycle Protocol includes install/uninstall/start/stop/restart/update/status/health/logs/configure.
Core's manager delegates through the registered adapter; it does not contain Plex-specific logic.
The only enabled adapter is MockAdapter. Its states are persisted in SQLite and actions touch no real
services. Unsupported updates return an explicit not-implemented error rather than fake success.

No manifest can load arbitrary Python, Compose fragments, shell hooks or elevated capabilities.
Schema capabilities declare intent only. Real capability grants and runtime operations belong to the
future policy agent. Third-party plugin loading, signed catalogs and container installation are not
implemented in Phase 1.

Health has status healthy/degraded/unhealthy/unknown, summary, checks and lastChecked. A stopped mock
app is unknown, not falsely unhealthy. API app list adds health alongside persisted state.

Read-only Docker foundation filters container ownership by `org.mediahub.instance` and excludes
environment variables, arbitrary labels, commands and internal errors from inspection responses.
Raw container logs are intentionally not exposed before a provider-aware secret-redaction design.
