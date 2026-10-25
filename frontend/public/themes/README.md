# Visual environments

Original generated landscape assets (`orbit-mountains.webp`, `edge-horizon.webp`)
were created with OpenAI image generation for MediaHub's beta redesign. They are
background artwork, with no embedded UI or status information. The wave and ridge
SVGs are native project artwork. No reference screenshot is used as a background.

`environment.css` is mirrored into the independent MediaSeed and MediaVPN apps.
Keep these copies identical when updating the shared environments. Each app keeps
its own layout stylesheet and functions. `theme.js` in each app accepts only the
named theme identifiers; query parameters never supply CSS, HTML or asset URLs.

Andedammen / Duck Pond is original native SVG/CSS artwork with a shared,
pausable decorative scene. See `docs/duck-pond.md` for scope, generation, packaging
and verification. `duck-pond.js` never reads or writes app/network/media settings.
