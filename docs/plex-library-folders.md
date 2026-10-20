# Plex-biblioteker og mapper

I Plex-appens indstillinger i MediaHub vises **Plex-biblioteker og mapper**.
Oversigten hentes fra Plex og viser aktuelle biblioteksnavne og mappevalg,
også når de er ændret direkte i Plex.

Vælg **Redigér mapper** ved et bibliotek. Fjern uønskede mapper fra listen,
eller vælg et tilknyttet medielager og navigér til en undermappe. Brug **Brug
denne mappe** og derefter **Gem mapper**. Eksisterende ekstra mappevalg bevares,
medmindre de aktivt fjernes. Appdata og andre ubemyndigede stier kan ikke vælges.

**Opret Plex-bibliotek** opretter et film-, serie- eller andet videobibliotek med
de valgte mapper. Et eksisterende bibliotek skal beholde mindst én mappe. Skal
hele biblioteket væk, bruges **Fjern bibliotek**: bekræftelsen forklarer, at det
fjerner bibliotekets metadata og indstillinger, mens mediefilerne bevares.
Medie-mounts er fortsat skrivebeskyttede, og API'et kalder aldrig filsletning.

Plex skal køre, så bibliotekernes aktuelle indhold og mappeadgang kan verificeres.
Tilføj ekstra NAS-lager gennem den eksisterende **NAS-lager til apps**-sektion:
stop Plex ved ændring af selve lagertilknytningen, og start det igen bagefter.
Derefter kan NAS-mapperne vælges til bibliotekerne her. Almindelige ændringer af
biblioteksmapper genstarter ikke Plex og ændrer ikke containerens mounts eller
adgang til lageret. Fjern NAS-tilknytningen separat, hvis hele lageradgangen skal
ophøre.

Har en anden klient ændret samme bibliotek, afviser MediaHub en forældet kladde.
Annullér redigeringen, opdatér bibliotekslisten, og gennemgå valgene igen. Ved et
uklart svar eller timeout kontrolleres oversigten før genforsøg; gentaget oprettelse
med samme biblioteksnavn, type og mapper giver ikke et ekstra bibliotek.

## Nyinstallation og opdatering

Ved nyinstallation opretter MediaHub installationsvalgets standardbiblioteker
en enkelt gang. En gemt bootstrap-markør afslutter processen efter succes.
Efterfølgende sletninger og ændringer i Plex genskabes ikke ved Agent-genstart.
En eksplicit biblioteksredigering afslutter også en eventuel resterende bootstrap.

Ved opdatering af en ældre installation uden markøren overtager MediaHub Plex'
aktuelle biblioteker. Den gamle installationsplan genanvendes ikke til at oprette
manglende biblioteker. Eksisterende databaser, konti, krypterede indstillinger,
mediefiler og mountvalg ændres ikke ved denne overgang. Core og Agent skal
opdateres sammen gennem MediaHubs normale opdateringsforløb. Der tilføjes ingen
nye pakker eller værtsprivilegier.

Verifikation: syntetiske API- og transporttests for mappegrænser, samtidige
redigeringer, utilgængelige NAS-mapper, bekræftet biblioteksfjernelse, HTTPS/CSRF,
nyinstallation og genstart af ældre installationer. Browsertests dækker oprettelse,
mappeændring, fjernelse og direkte Plex-navneændringer ved 320, 390 og 1440 pixels.
Plex' mappebrowser er live verificeret med en læseforespørgsel. Ingen eksisterende
produktionsbiblioteker er ændret som test, og rettelsen er ikke live installeret
som del af kildeudgivelsen.

Den fokuserede Python-regression består med 235 tests. Den samlede GitHub-CI var
allerede rød før denne ændring: kørslen for 0.6.70 havde 24 testfejl i andre flows
(app-lister, Cloudflare, containeropsætning, SSO og værtsklargøring). De fejl er
ikke ændret eller skjult i denne rettelse. En bestået fokuseret test er derfor
ikke en påstand om, at hele repoets CI er grøn.
