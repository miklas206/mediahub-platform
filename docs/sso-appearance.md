# SSO appearance (beta)

SSO exchange and current-session identity now include the authenticated user's validated appearance object and the hub's base `theme` mode. Preferences are resolved from the current account each time, rather than embedded permanently in a login code. Null keeps default appearance. No additional frontend-to-hub cross-origin request, token exposure, database migration or auth bypass is introduced.

MediaSeed and MediaVPN consume this public identity only for managed sessions. Their default is Follow MediaHub, with optional per-user/app theme overrides stored by each app and protected by its existing session/CSRF checks. Overrides do not modify hub preferences. Navigation remains specific to the app.

The pure `frontend/src/appearance-tokens.ts` module supplies validation and contrast-safe color tokens to the hub and generated standalone app bundles. `theme-presets.ts` is also included for override choices. Regenerate with `node scripts/sync-app-appearance.mjs` from frontend; parity tests check exact colors and identical app artifacts.

Integration tests use actual hub and app ASGI transports, exercise account-local live changes, overrides, invalid input, CSRF, restart persistence and revocation. Browser checks cover both real app frontends at 1440/390/320, system mode, custom colors, reduced motion, overrides and reset, failed saves, standalone isolation and overflow. Synthetic data only; no real torrent or VPN operations.

Implementation stays in the beta hub and app beta branches until explicitly promoted to main.
