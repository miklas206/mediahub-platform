# Theme-aware first-party marks (beta)

MediaHub, MediaSeed and MediaVPN have distinct monochrome marks drawn on a shared 32-unit grid. No gradients, fixed internal background, external font or third-party artwork is required. UI marks use currentColor via --accent, which is already adjusted for contrast by the appearance engine. Preserve the silhouettes and stroke weight at 16/24/48 pixels.

Hub ServiceIcon renders inline first-party SVG; third-party product marks keep their existing artwork. App headers and login screens use the same inline geometry. Managed defaults and account-local app overrides both update the CSS accent, so no account/theme API change is needed.

Browser favicons update from the resolved accent and surface, with an opaque backplate for contrast against browser chrome. The observer watches root appearance attributes, coalesces updates into animation frames and avoids duplicate writes. SVG attributes are constructed with DOM methods and serialized, never by inserting arbitrary CSS/user text as markup. Static SVG and PNG assets retain a default palette for initial loading and OS installation icons. Installed OS shortcuts cannot follow live web-page CSS; their images use the new mark in the default palette.

Canonical geometry: frontend/src/brand-marks.json. Run node scripts/sync-brand-icons.mjs from frontend to regenerate SVGs, app inline marks, shared CSS and favicon runtime. Render static installation PNGs with node scripts/render-brand-pngs.mjs using MEDIAHUB_ICON_BROWSER to select isolated Playwright Chromium. Keep versioned brand asset URLs fresh when changing generated files. Preserve existing accounts, overrides, mounts and media; all changes are visual.
