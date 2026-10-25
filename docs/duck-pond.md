# Andedammen / Duck Pond

Nyt valgbart fællestema, lavet efter brugerens ønske 26. oktober 2026.
Temaet bruger gyldne gummiænder, smaragdgrønt vand, siv, åkander, ildfluer og
vandringe. Alt er original SVG/CSS/JavaScript uden billedtjenester, lyd, eksterne
kald eller ekstra runtime-afhængigheder. Opaque flader holder tekst og faktiske
statusoplysninger læsbare. Appfunktioner, netværk, medier og andre brugeres valg
ændres ikke af temaet.

## Brug og dækning

- MediaHub: Indstillinger → Udseende → Andedammen → Gem. Preview kan kasseres.
- MediaSeed og MediaVPN: Følg MediaHub arver den gemte kontoindstilling. Temaet kan
  også vælges som appens eksisterende personlige override eller lokalt uden SSO.
- MediaUpload: Tema → Andedammen i headeren. Denne app har selvstændig login- og
  temastyring; valget gemmes lokalt i browseren uden nye adgangs- eller SSO-koblinger.
- Hub-kort og Hub-indstillinger for Plex, Jellyfin og andre tjenester følger temaet.
  De eksterne afspilleres egne webklienter styres fortsat af deres respektive apps;
  temaet injicerer ikke kode i dem.

Pause dammen stopper kun baggrundens dekoration og huskes lokalt i browseren.
Systemets og kontoens reducerede bevægelse stopper animationen. Skjulte browserfaner
pauser CSS-animationerne. Ved temaskift fjernes både dam og pauseknap. Baggrunden
er inert, aria-hidden, har ingen pointer-events og lægger ingen grafik oven på
kontrollerne. Der oprettes højst én scene; ingen requestAnimationFrame-løkke,
WebGL, canvas, partikelgenerator eller kontinuerlige JavaScript-timere.

## Kilde og installation

Kanoniske filer: `frontend/public/themes/duck-pond.{js,css}` og `duck.svg`.
Paletten ligger i `theme-presets.ts`; validering i `appearance-tokens.ts` og
Core-kontrakten accepterer kun den navngivne identifikator `duck-pond`.
`node frontend/scripts/sync-app-appearance.mjs` genererer farvemotoren og kopierer
fælles assets til de medfølgende MediaSeed/MediaVPN-pakker og til de kanoniske
lokale appcheckouts, når de findes. MediaUpload bruger de samme assets i sin
flade static-pakke. Ved ændringer i fælles filer opdateres cacheversionerne i de
respektive HTML-indgange og den medfølgende source-manifest.

Både friske installationer og appopdateringer med denne kilde pakker assets
normalt. Der er ingen pakkeinstallationer, nye devices, mounts, credentials eller
skemamigrationer. Core og apps skal alle have temaændringen; en Core-opdatering
alene opgraderer ikke uafhængige kørende apps. Lokale appcheckouts indeholder
allerede andet igangværende arbejde, som temaopgaven hverken nulstiller eller
publicerer som en samlet apprelease.

## Verifikation

- Hele frontend-enhedstestsuiten: 348 tests består, inklusive paletkontrast i lys og
  mørk tilstand og identiske genererede farvemotorer/andeassets i bundlerne.
- TypeScript- og produktionsbuild består.
- Browserkontrol af Hubben ved 1440, 390 og 320 px: preview, gem/genindlæs, levende
  bevægelse, pause, reduceret bevægelse, temaskift og ingen vandret overflow.
- Begge appfrontends ved samme bredder: SSO-arv, samme farvetokens, dammens
  reducerede bevægelse, overrides, fejl ved gem, sprog og tilbage til standard.
- MediaUpload ved samme bredder: original forberedelsesskærm, lokalt valg,
  genindlæsning og tilbage til standard. Alle API-svar er syntetiske; ingen uploads.
- 13 fokuserede Core-/pakke-Python-tests og en MediaUpload-test består. De dækker Core-kontopræferencer, stram navnevalidering, gamle paletter,
  apppræferencer i eksisterende SQLite-data efter genstart, andre brugeres bevarede
  valg, medfølgende source-manifest og releasepakning.
- Tre selvstændige wheels bygges uden nye dependencies; deres rigtige statiske
  assets serveres fra isolerede midlertidige ASGI-apps. Ingen produktionsdata bruges.

Reference: fuldt aktuelt `qlerup/fjordhub` main,
`e02fa79971625962c57ca88be39302bc690be764`, især `static`-tema/appearance-flowet.
Selve dammens grafik og animation er skrevet til MediaHubs fælles temakontrakt.

## Status og tilbageførsel

Kilden klargøres som MediaHub 0.6.75 og skubbes til main. Dette er ikke en live
installation. Projektets AGENTS.md kræver udtrykkelig tilladelse før produktionen
opdateres eller genstartes. Intet kørende system er ændret under udvikling/test.

Ved godkendt udrulning: tag konsistente backups, opdatér kun de nødvendige
app-/Core-services og bevar mounts, secrets, VPN-tunneler og torrentklient. Bevar
de nuværende appimages og øvrige lokale rettelser. En scoped theme-overlay må
ikke erstatte de nyere MediaSeed-funktioner med en ældre medfølgende appkodebase.
Tilbageførsel bruger de foregående images og Compose-filer. Ingen skemaændringer
kræver databasegendannelse. Det gemte Duck Pond-valg kan kasseres/nulstilles via
den almindelige temakontrol; andre temaer og præferencer er bevaret.

MediaUpload 0.1.38 udvider kun sin præcise, gateway-beskyttede statiske allowlist
med de fire temafiler. Gateway-login, CSRF og den stramme eksisterende CSP er
bevaret og testes sammen med 401/404-afvisninger. Medfølgende browserkontrol bruger
samme CSP. De pakkede ASGI-apps serverer henholdsvis 36, 20 og 6 assets uden
produktionsdata. Antal assets kan ændres, når appenes øvrige lokale arbejde pakkes.
