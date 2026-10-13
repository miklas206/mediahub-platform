# Beta theme lab

The five experimental styles draw on the user's October 13 concept images. They
share MediaHub's existing pages, navigation and real application state. No example
metrics, application installations or decorative connection status are added.

Open **Settings → Appearance**. A theme previews immediately.
Use **Preview dialog** and **Preview notification** to compare feedback. **Save
colors** saves the full appearance to the current account; **Discard changes** or
leaving Settings restores the saved look. **MediaHub defaults** previews the
original appearance, which can then be saved.

| Theme | Direction |
| --- | --- |
| Midnight Glass | Navy surfaces, cyan edges, restrained lighting |
| Soft Orbit | Soft dark blue, gentle light, rounded cards and soft shadows |
| Precision Terminal | Matte graphite, mint accents, compact technical details |
| Floating Layers | Slate surfaces, blue accents and layered depth |
| Edge Signal | Neutral charcoal, amber and crisp borders |

Each theme supports light, dark, system or inherited workspace color mode. Density,
colors and reduced motion can be adjusted independently. Choosing another palette
keeps the chosen theme and layout. OS reduced-motion preferences remain respected.
Status colors continue to indicate health, warning and errors independently of the
accent. The old Classic theme is retained for comparison.

The account appearance contract adds validated `style`, `mode`, `density` and
`reducedMotion` fields. Existing four-field palettes load with compatible defaults;
no database schema migration is required. Other users' preferences are unaffected.

The second iteration also redesigns the independent MediaSeed and MediaVPN workspaces.
MediaHub has compact horizontal app cards, a stronger hero and clearer section hierarchy.
MediaSeed separates RSS, tracker and VPN forms from their lists/verification panels;
MediaVPN uses a connection-card grid and a clear empty state. Existing actions, real
status, authentication, torrent storage and fail-closed network behavior are preserved.

The default look is Midnight Glass. The latest iteration removes scenic wallpaper
from all active themes and their thumbnails. Subtle low-opacity radial light fields
create depth; Midnight and Floating use very slow drift. Each theme also changes
button shape, hover/press feedback and dialog/toast entry behavior. Reduced motion
removes these transitions and animations. Precision uses direct minimal feedback;
Soft Orbit uses rounded controls and soft lift; Edge Signal uses crisp underline
feedback. Existing notification auto-close and pause-on-hover/focus remain intact.

Appearance presents five compact theme cards, with Classic below, then grouped
interface controls. MediaSeed's Downloads view has measured transfer/count cards,
a compact torrent table and a real RSS summary rail. Missing torrent data displays
an em dash rather than fabricated zero rates. No VPN or torrent actions are started.

MediaHub passes the selected named theme only to its own MediaSeed/MediaVPN app links.
Each independent app also has a header theme selector remembered in that browser.
Custom hub palette colors remain hub account preferences.

## Deployment and rollback

Deploy only to the existing beta CT106. Keep previous images, Compose files and
consistent SQLite snapshots for all three apps. Recreate only their application
services; retain mounts, environment, keys, accounts, profiles and rollback data.
Do not restart proxies, torrent clients or VPN tunnels.

Core requires only the built frontend over the existing compatible Core image.
Independent apps require their current complete Python package and static assets:
the prior installed images predate account-language support. The existing additive
language migration has focused migration/authentication tests. A rollback can use
the previous images with the additional language columns retained; do not overwrite
newer unrelated account or application data with an old database snapshot.

## Reference workspace revision

The dedicated Appearance page now follows the supplied compact composition: five
actual UI miniatures, a separate Light choice, compact-layout/reduced-motion switches
and accent dots. Custom palettes, color fields, Classic and preview actions remain
under Advanced appearance. Save/discard still applies account preferences; Light uses
the existing midnight-glass style with light mode, so no contract/schema change is needed.

Home is a unified Apps & Services catalog with counted category/status filters and
consistent icon/title/status/description/action anatomy. A visible Uninstall button
uses the existing identity-checked removal flow only for removable apps. It preserves
existing media/app-data notices and never invokes removal from a theme selection.

Overview uses the same compact vocabulary: aggregate service status, CPU/RAM/storage,
connected apps, active downloads and recent activity. Independent-app observations
must be fresh and verified before aggregate health is green. A missing media-capacity
observation falls back to Core disk metrics with the explicit Core storage label.

MediaSeed places its live transfer metrics above navigation and renders compact
number/name/progress/speed/status/action rows beside RSS. Connection details remain
under VPN; blocked-download guidance and server-side enforcement are preserved.
Sparkline paths use real observed samples and stay empty until multiple samples exist.

## Equal Light card and custom accent wheel

All six main looks now use the same card geometry, including Light. The account
action is Save (Gem in Danish), and feedback refers to the entire appearance.
A custom-accent trigger beside the preset dots opens an in-app HSV color wheel
with keyboard-accessible hue/saturation/brightness sliders and validated hex input.
It previews only the current draft; Cancel/Escape restores the prior accent, Done
keeps the draft, and Save persists account preferences. No native browser prompt
or extra network request is needed to choose a color.

Shared environments use stronger low-contrast light fields and abstract curved
ribbons, with slow movement. No landscape image is used. OS and account reduced
motion disable both background layers. The environment stylesheet URL is versioned
to avoid serving an old Cloudflare-cached background.

Appearance refinement: each theme now has its own more visible abstract animated composition (glass arcs, orbit rings, terminal grid, floating planes or signal diagonals). Reduced motion remains supported; stylesheet cache version is ambient-6.
Color mode and dialog/notification previews are outside Advanced coloring. Compact layout is the single density control. Save, Discard changes and Defaults remain visible together; Defaults is a preview until Save. The redundant Classic button has been removed.

Sidebar selections differ by theme: glass rail, orbit pill/dot, terminal brackets, raised layered tab and signal underline/chevron. Light has a clean flat selection. Current-page semantics, keyboard focus and reduced motion are retained.

Theme identity refinement: bounded Soft Orbit control rounding prevents circular text cards. Each theme has a distinct system-font stack, icon stroke treatment and surface geometry. Hub sidebar uses different icon glyphs for Home/Overview/Settings, responding to live theme previews. Settings tabs remain visible on Appearance. Shared stylesheet version: ambient-8.

The redundant Light theme card has been removed. Five style cards define visual identity; Color mode independently selects light/dark/system. Changing style preserves the chosen color mode, and the selected style stays indicated in light mode.

Complete sidebar redesign: inset themed frame, grouped brand header, refined navigation spacing, status/account dock and restrained local clock. Theme-specific glass, soft, terminal, layered and signal skins extend to the sidebar surfaces and avatar. Mobile uses a bounded drawer with its own close button; routes, sign-out and real connection/uptime state are preserved.
