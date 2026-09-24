# Optional FjordHub integration

FjordHub is an external, optional read-only integration, **not a MediaHub Agent**.
Authentication uses a bearer **Access Token**, not an API Key. No production token
has been configured and no live FjordHub API compatibility is claimed.

`IntegrationProvider` returns a normalized `IntegrationSnapshot`. Only the
`FjordHubClient` adapter knows the provisional v1 paths/response format. Core and
Seedbox lifecycle must not depend on those upstream details. Replace or adapt this
client when the developer publishes the final contract; do not migrate the Core
schema to a speculative API.

The proposed adapter uses GET only, dynamic apps, scoped storage/metrics/events,
bounded responses and timeouts, no redirects, TLS validation by default, and typed
offline/authentication/scope/version/rate-limit results. Reflected Access Tokens
are redacted from remote metadata. Mock transport tests are the acceptance boundary
until the final API is available. Seedbox completion is independent of FjordHub.
