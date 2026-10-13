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

This round covers MediaHub Home, Overview, Settings, shared cards, confirmations and
notifications. MediaSeed and MediaVPN retain their independent applications; their
concept screenshots are references for subsequent iterations.

## Deployment and rollback

Deploy only to the existing beta CT106. Keep the previous Core image, Compose file
and a consistent SQLite backup. Recreate only the Core service; retain its mounts,
environment, account database, keys and rollback data. The independent app services
and production MediaHub are outside this deployment.

Frontend assets and `backend/mediahub/contracts.py` are the runtime changes. For a
layered deployment, use the verified existing Core image as a base and copy the
built frontend and that contract file; label the image with the source commit.

Before rolling back to code predating these appearance fields, strip the four new
keys from **only** the nested `appearance` object in saved `user.preferences:*`
settings, or keep the compatible new contract in the rollback image. Do not restore
an old database over newer unrelated account/app changes. Reverting the theme via
the UI requires no runtime rollback and is the preferred way to compare looks.
