# MediaHub release

- MediaHub is the primary hub for MediaSeed, MediaVPN, Plex, Jellyfin and the built-in Healthcheck. FjordHub remains a separate optional app inside MediaHub.
- Storage revision authorized 2026-10-19: add administrator-only Storage under Settings for explicit NAS mounts and authenticated LAN Windows shares. This supersedes the previous removal of Storage from Settings; keep standalone Storage/Windows-folder shortcuts hidden. Preserve existing media and app mappings.
- Navigation revision authorized 2026-10-09: remove Storage, Windows folder access and Backups pages and shortcuts from the user interface. Keep internal storage and rollback mechanisms required by apps. Move Healthcheck, Activity, Logs, Updates and Integrations into Settings; manage hub administrator accounts in the Settings Users tab. Do not expose ordinary-user or app-access roles without enforcing their permissions server-side.
- Architecture direction, authorized 2026-10-09: follow FjordHub's hub-managed independent Docker Compose apps and separate hub updater, with MediaHub's own branding, visual style and app catalog. The existing Core/Agent/React implementation is a migration source, not a mandatory final architecture. See docs/beta-hub-migration.md. Migrate in tested steps; do not substitute FjordHub's app catalog for MediaHub's own apps.
- Preserve the existing app workflows, per-host runtime policies, authentication, encrypted secrets, storage boundaries and external integrations. Show actual installed/connected state; never pretend catalog entries are installed.
- Keep secondary FjordHub apps under their parent FjordHub integration. The main hub must work independently of FjordHub.
- Keep server addresses, identities, storage paths and credentials configurable. No live data, environment files, private keys or databases belong in Git.
- UI action results and transient errors must use NotificationPopup, not inline banners. Use success/info for successful results and danger only for errors. Popups appear at the top, close automatically, and pause while hovered or focused. Keep progress, consoles, required setup guidance and security recovery data on the page.
- Run focused checks for changed functionality, commit and push to this repository. Distinguish local tests, pushed source and the installed release version.
- Deployments and destructive operations require explicit task authorization. Preserve external media mounts and mediefiler. Never copy beta users, app data or VPN credentials into release implicitly.
- Keep the Apache-2.0 license and original MediaHub attribution. The earlier FjordHub-based attempt remains in Git history and the archive branch for recovery.

# Main development and optional UI beta (2026-10-13)

- Normal fixes are implemented, checked, committed and pushed directly to `miklas206/mediahub-platform`. Follow the release version/tag workflow; the user installs main. Do not deploy/restart production without explicit task authorization.
- `miklas206/fjordcopy` is an optional UI experiment workspace. Use beta for experiments only when the user requests it; synchronizing source does not authorize a beta deployment.
- Preserve runtime update channels: beta/CT106 follows `miklas206/fjordcopy`; main/CT107 follows `miklas206/mediahub-platform`. Never copy runtime settings, databases, media, users, VPN profiles or credentials between them.
- Before synchronizing repositories, retain completed authorized fixes in main and preserve recoverable Git history. Copy source only; verify matching tracked trees and report pushed source separately from installed runtime.
- MediaSeed/MediaVPN work locally using the host's prepared HTTPS LAN origins. A domain is optional and only overrides the local address when explicitly configured in app Settings.

# Integrated VPN gateway (2026-10-14)

- Cloudflare is a backend integration for MediaVPN's guided app domains, not a separate catalog/app/Updates card. Preserve legacy tunnels and data until explicit migration.
- Use Traefik for the gateway inside the single selected Proton namespace; the existing Hub Traefik stays independent. Do not reintroduce Caddy/xcaddy/Go build dependencies.
- New features must include guided prerequisites and automatic preparation for fresh installs and updates, with no personal host/IP/hardware assumptions. Support native amd64/arm64 where Docker, TUN, storage and provider capabilities pass validation; do not claim universal physical validation.
- Healthcheck cleanup must verify ownership and current/stopped-container/rollback references before removing obsolete helpers. No blanket Docker pruning or deletion of other apps/media.
