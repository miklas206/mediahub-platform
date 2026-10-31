# Prisme theme-aware logos and navigation (0.6.78)

User approved Prisme app logos and simpler Frie Flader/Bue-inspired navigation on 2026-10-31. This supersedes the previous monochrome-only artwork guidance. FjordHub remains unchanged. Plex/Jellyfin and supporting service marks are customized inside MediaHub, not changes to those third-party applications.

Canonical logo geometry: `frontend/src/brand-marks.json`; navigation: `frontend/src/nav-marks.json`. Logos use layered SVG gradients from the existing contrast-adjusted `--accent` and `--indigo` tokens. Navigation inherits currentColor to retain active/disabled semantics. Inline gradient IDs are unique in React and hydrated standalone pages. The shared standalone runtime never mutates React-owned logos. No account, navigation, media or credential migrations are required.

Generate checked-in public and bundled assets with `node frontend/scripts/sync-brand-icons.mjs`. On the shared workspace, add `--workspace` to update the canonical sibling MediaSeed, MediaVPN, MediaUpload and VideoDownloaderExtension sources. This only touches brand assets and template branding; it does not synchronize unrelated app changes. Render native Hub PNGs with `MEDIAHUB_ICON_BROWSER=/usr/bin/chromium node frontend/scripts/render-brand-pngs.mjs`. Native OS icons use a static default palette; web logos and favicons follow the live theme.

Fresh installs consume the generated assets in the source release. Updates receive the same assets and `prisme-1` cache keys. Bundle checksums are refreshed only for touched files. Existing standalone header marks are upgraded idempotently and dynamic navigation is decorated without changing labels, roles, listeners or destinations.

Validation: focused React tests; Chromium theme/light/custom-color and runtime tests; standalone-template upgrade and duplicate-ID tests; production frontend build; bundled source/version tests. Upstream reference: qlerup/fjordhub main 4ff5b4a4066bc3050ae827612f7e153f91ba798e, templates/base.html (shared navigation semantics, currentColor icons).

Release publication does not restart production. Rollback uses the previous source release; no user data changes are required.
