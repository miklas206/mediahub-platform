# Rapport: tekst og panelrammer

Ændring: MediaHub 0.6.21. Rapporten omfatter MediaHubs brugerflade samt lokale browserkontroller af de selvstændige MediaVPN- og MediaSeed-apps. Kontrollerne bruger syntetiske API-svar og ændrer ikke serverdata.

## Fund og rettelser

| Fund | Årsag | Rettelse |
| --- | --- | --- |
| Plex-kontopanelets overskrift og tekst stod helt op ad kanten. | Komponenten brugte `.panel` uden den fælles overskrifts- og indholdsstruktur. | Tilføjet `.panel-heading` og `.phase-content` med normal indvendig afstand. |
| Plex-domænepanelet havde samme problem; formularen havde afstand, men overskrift og forklaring havde ingen. | Formularens egen padding skjulte, at resten af panelet manglede en indholdsbeholder. | Samme panelstruktur som øvrige opsætningspaneler; undgået dobbelt padding omkring formularen. |
| MediaVPN-linket stod på engelsk i den danske domæneopsætning. | Den konkrete oversættelsesnøgle manglede. | Tilføjet “Åbn MediaVPN”. |
| Almindelige brugeres appkort havde direkte tekst uden den fælles indvendige afstand. | Kortets indhold lå direkte i `.panel`. | Genbrugt `.phase-content` på kortene. Dette fund er fra kodegennemgang; medlemsvisningen indgår ikke i browsermatricen nedenfor. |
| Plex- og MediaVPN-åbningshandlingerne lignede almindelig tekst frem for tydelige knapper. | Åbningslinks brugte ingen eller en ikke-eksisterende knapklasse. | Bruger nu den eksisterende `button-link`-stil, også i Plex-popup'en. |

Derudover er den fælles panelstil styrket: indhold i flex/grid kan krympe, lange domæner og tekst kan brydes, overskriftsrækken kan ombrydes, og handlinger holder sig inden for deres række. Det er forebyggende rettelser; der hævdes ikke særskilte reproducerede fejl for alle disse tilfælde.

## Gennemgået i browser

Skærmbredder: **1440, 768, 390 og 320 pixels**.

- MediaHub: hovedside, oversigt, alle ni almindelige indstillingsfaner samt opsætning af MediaVPN, MediaSeed, Plex og Jellyfin. I alt 15 adresser/visninger ved hver af de fire bredder. API-data er testdata; ikke alle muligheder og tilstande er udfyldt på hver side.
- Plex-installationens driftsside: kontotilknytning, popup, domæneformular, afstand til panelkanter og et subdomæne på 100 tegn. Kontrolleret ved alle fire bredder.
- MediaVPN: Forbindelse, Apps og domæner, Cloudflare, indstillingsdialog og ny forbindelsesdialog. Dansk og engelsk ved alle fire bredder, inklusive et langt profilnavn.
- MediaSeed: Downloads, RSS, Trackere, VPN, indstillingsdialog og tilføj torrent-dialog. Dansk og engelsk ved alle fire bredder. Fanerne bruger primært tomme og uopsatte tilstande.
- Begge apps: eksisterende test af kontoudseende, temaer og indstillingsdialog ved 1440, 390 og 320 pixels.
- MediaHub: eksisterende bekræftelsesdialoger og popup-kontroller, inklusive smal mobilvisning.

Den nye kontrol måler tekstlinjernes faktiske position i browseren i forhold til deres nærmeste kort eller dialog. Den kontrollerer også sidens vandrette bredde. Plex-testen måler særskilt afstand mellem overskrift og panelkant. Bevidst rulbare tabeller, rulbare dialogers lodrette indhold og forkortede filnavne med ellipsis behandles som tilsigtet adfærd.

## Verifikation og begrænsninger

- De 37 forskellige browserkontroller i den beskrevne matrix er gennemført. Plex-forløbet er desuden gentaget som kontrol af genbesøg og kontotilknytning.
- TypeScript, målrettet ESLint, Plex-opsætningens komponenttest og produktionsbuild er bestået.
- Den samlede kørsel på Vites udviklingsserver gav 35 beståede kontroller og to periodiske fejl, hvor Plex-siden blev stående på “Loading app status” efter genindlæsning. Plex-forløbet er derfor også kørt på det byggede produktionsfrontend ved alle fire bredder og gentaget. Udviklingsserverens periodiske indlæsningsproblem er ikke rettet i denne layoutændring; det er adskilt fra tekstkontrollen og registreret her frem for skjult som en bestået samlet kørsel.
- Skærmbilleder af de ændrede Plex-paneler og appdialoger gemmes som lokale kontrolbilag.
- Der er ikke fundet yderligere tekst, der går uden for rammerne, i de gennemførte appkontroller. Det er ikke en garanti for alle kombinationer af brugerdata, browserzoom, udseende og fejltilstande.
- Plex' egen webklient og andre tredjepartsapps er ikke ændret. Der er ingen ændring af VPN, domænevalg, mediefiler, installationstilstand eller kontooplysninger.
- Rettelsen er almindelig frontend-kode og kræver ingen datamigrering eller ekstra afhængigheder. Den samme kode bruges ved frisk installation og ved opdatering.
- Serveren er ikke opdateret eller genstartet som del af denne layoutgennemgang. Main og versions-tag er leveringsmålet; den installerede version må ikke udledes af kildekoden.
