# Beta theme lab

The five experimental styles draw on the user's October 13 concept images. They
share MediaHub's existing pages, navigation and real application state. No example
metrics, application installations or decorative connection status are added.

Open **Settings → General → Themes and appearance**. A theme previews immediately.
Use **Preview dialog** and **Preview notification** to compare feedback. **Save
colors** saves the full appearance to the current account; **Discard changes** or
leaving Settings restores the saved look. **MediaHub defaults** previews the
original appearance, which can then be saved.

| Theme | Direction |
| --- | --- |
| Midnight Glass | Navy surfaces, cyan edges, restrained lighting |
| Soft Orbit | Light pearl, lavender, rounded cards and soft shadows |
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
