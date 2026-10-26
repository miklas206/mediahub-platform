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
- Browserkontrol af Hubben ved 1440, 768, 390 og 320 px: preview, gem/genindlæs, levende
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

Installeret live efter brugerens udtrykkelige godkendelse 26. oktober 2026:
MediaHub **0.6.75**, runtime-commit `17763261c8a2f54b3bf574a966af10025a34673a`.
Core-image, projektversion, rapporteret version og hostens installerede markører
stemmer overens. MediaSeed og MediaVPN har afgrænsede temaoverlays oven på deres
faktisk kørende images; deres øvrige kildekode og funktioner er bevaret.
MediaVPNs HTML bevarer den installerede 0.2.31-version. MediaUpload **0.1.38**
er installeret i sin egen CT109, mens Studio i CT102 fortsat fungerer som gateway.
Temaet er valgbart; eksisterende kontopræferencer er ikke overskrevet.

Private backups og buildkontekster på de respektive værter:

- CT107 Core: `/opt/mediahub/duck-pond-16b5259361e830fc`
- CT107 MediaSeed: `/opt/mediahub/local-apps/mediaseed/duck-pond-0b585138833f16a7`
- CT107 MediaVPN: `/opt/mediahub/local-apps/mediavpn/duck-pond-0e03cafbbdb0b6ef`
- CT109 MediaUpload: `/opt/mediaupload/duck-pond-before-0.1.38-r2`

Compose-filer og konsistente SQLite-backups er bevaret i private mapper.
MediaUploads syv afsluttede jobs samt hashes for opsætning, credentials og
bilag er sammenlignet før/efter og bevaret. Ingen brugeruploads eller ændringer
af mediefiler er udført som verifikation. Aktive VPN-tunneler er ikke erstattet.
Webapp-genstart kan aktivere de eksisterende supervisorers afstemning af klienter
og leases; det er ikke en ny tunnelkonfiguration eller en lækagetest.

Live sundhedstjek består for alle fire apps, og installerede filer matcher
udrulningens kildefiler. 13 ekstra browserkontroller består med faktisk serverede
assets: Hub ved 1440/768/390/320 px, begge SSO-apps ved 1440/390/320 px og
MediaUpload ved 1440/390/320 px. Browsernes API-/kontosvar er syntetiske, så gem,
SSO-arv og genindlæsning ikke ændrer rigtige konti eller opretter brugerjobs.
Dette er ikke et gennemført login med brugerens konto.

Tilbageførsel: gendan den respektive `compose.before.json` og start kun den
berørte `core`/`app` med `--no-deps --no-build`; de tidligere images er bevaret.
For Core skal også `installed-version` og `updates/installed-source.json`
gendannes fra samme backup, så markører og runtime stemmer. MediaUpload-backuppen
bevarer både den foregående installerede Python-pakke med metadata og source.
Ingen skemaændringer kræver databasegendannelse. Vælg et tidligere tema inden
en tilbageførsel, hvis Andedammen er gemt; andre temaer og præferencer er bevaret.

MediaUpload 0.1.38 udvider kun sin præcise, gateway-beskyttede statiske allowlist
med de fire temafiler. Gateway-login, CSRF og den stramme eksisterende CSP er
bevaret og testes sammen med 401/404-afvisninger. Medfølgende browserkontrol bruger
samme CSP. De pakkede ASGI-apps serverer henholdsvis 36, 20 og 6 assets uden
produktionsdata. Antal assets kan ændres, når appenes øvrige lokale arbejde pakkes.

## Beskyttet overførsel som å

26. oktober 2026: MediaSeeds eksisterende målte pakkebaner vises i Andedammen
som en smal å med svømmende ænder, drivende blomstrende åkander og kølvand.
Download og upload bevæger sig fortsat i modsatte retninger. Tæthed og hastighed
bevarer den eksisterende målelogik; antallet af synlige figurer begrænses på små
skærme. De fire forbindelsesikoner og deres rigtige status er bevaret.

Ændringen er afgrænset til CSS og HTML-cacheversion. Den almindelige animation
er bevaret i andre temaer. Temaets pauseknap, skjult fane, reduceret bevægelse
og de eksisterende blokeringer ved inaktiv forbindelse eller forældede målinger
gælder også åen. Der tilføjes ingen timere, afhængigheder eller datamigrationer.
Friske installationer og opdateringer får CSS fra den medfølgende apppakke;
kilde-manifestet er opdateret og tre bundletests består. Browserkontrol ved
1440/768/390/320 px dækker figurer, retning, pause, reduceret bevægelse,
forældede/blokerede/tomme trafikdata, temaskift og vandret overflow.

### Anden stiger om ved VPN

Anden hopper nu op på en åkande ved VPN-ikonet og fortsætter på bladet.
Boardingpunktet beregnes fra de faktiske ikonpositioner ved layoutændringer.
Download- og uploadretningen har hver deres synkroniserede CSS-keyframes;
and, blad og den målte trafik deler varighed og forsinkelse. Der bruges
ingen nye timere eller JavaScript-animationsløkker. Pause og reduceret bevægelse
gælder også bladet. Status, hastighedsmåling og adgang til VPN ændres ikke.

Den ældre medfølgende apprenderer får samme pakkemotor og en afgrænset kobling
til den eksisterende renderfunktion. Dens almindelige overførselsanimation
bevares uden for Andedammen. Det gør funktionen tilgængelig ved både frisk
installation og opdatering, uden at kopiere andre igangværende appfunktioner.
`frontend/e2e/duck-transfer-boarding.spec.ts` kontrollerer hoppingens placering
og bladets synlighed i begge retninger ved fire bredder, pause, reduceret
bevægelse, gamle/blokerede trafikdata og tilbagevenden til et andet tema.

Installeret live som et afgrænset MediaSeed-overlay
`mediahub-mediaseed:duck-boarding-6dadb84642d69cf9`. Installerede kildefiler
matcher, appen er sund, og øvrige containere er bevaret. Privat rollback-backup:
`/opt/mediahub/local-apps/mediaseed/duck-boarding-6dadb84642d69cf9`.
