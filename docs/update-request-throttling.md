# Shared GitHub update metadata

Core discovery, independent Agent discovery and MainBranchWatch share one
GitHubMetadata cache per Core service. Concurrent reads serialize through the
cache so GET /updates/platform, POST /updates/check and scheduled checks do not
repeat the same GitHub calls. Main metadata is reused for five minutes, pinned
pyproject metadata for one hour, and complete checks for 60 seconds. Installed
version comparisons remain specific to each component. No automatic retries or
software installations are introduced.

A 403 with rate-limit headers or 429 pauses metadata reads for that credential
identity across repository paths. The deadline respects Retry-After (seconds
or HTTP date) and x-ratelimit-reset, with one hour fallback if neither is usable.
Changing credentials selects a separate identity. Cache/cooldown state is in
memory and resets when Core restarts. HTTP error bodies and credentials are not
written to the update summary. Existing deployment-key Git metadata is unchanged.

Core throttling is reported as deferred, including retryAt and the prior verified
version marked stale when available. Other failed sources still remain failures.
The Updates page uses one error popup; per-source diagnostics remain in expandable
details and operation history. A cached check may take up to five minutes to see
new main commits; do not force repeated refreshes to evade a provider cooldown.

Reference: https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api
