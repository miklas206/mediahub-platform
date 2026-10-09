# MediaHub beta / fjordcopy

- MediaHub is the primary hub for its original apps: Seedbox, Plex, Jellyfin, Cloudflare Tunnel, Windows folder access, and the built-in Healthcheck. FjordHub remains a separate optional app inside MediaHub.
- Architecture direction, authorized 2026-10-09: follow FjordHub's hub-managed independent Docker Compose apps and separate hub updater, with MediaHub's own branding, visual style and app catalog. The existing Core/Agent/React implementation is a migration source, not a mandatory final architecture. See docs/beta-hub-migration.md. Migrate in tested steps; do not substitute FjordHub's app catalog for MediaHub's own apps.
- Preserve the existing app workflows, per-host runtime policies, authentication, encrypted secrets, storage boundaries and external integrations. Show actual installed/connected state; never pretend catalog entries are installed.
- Keep secondary FjordHub apps under their parent FjordHub integration. The main hub must work independently of FjordHub.
- Keep server addresses, identities, storage paths and credentials configurable. No live data, environment files, private keys or databases belong in Git.
- Run focused checks for changed functionality, commit and push to this repository. Distinguish local tests, pushed source and the installed beta version.
- This task explicitly authorizes deployment to the existing beta LXC only. Preserve its user account and rollback data. Do not alter the original production MediaHub or its apps.
- Keep the Apache-2.0 license and original MediaHub attribution. The earlier FjordHub-based attempt remains in Git history and the archive branch for recovery.
