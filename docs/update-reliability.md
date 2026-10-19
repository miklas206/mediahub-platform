# Pålidelige opdateringer (0.6.60)

Core-opdateringen kører på værten under én eksklusiv lås. En midlertidig
Docker-, helbreds- eller filsystemfejl giver højst tre forsøg i alt med 10 og
20 sekunders ventetid. Operationens identitet og log bevares, også når Core
genstarter. Allerede byggede images genbruges inden for samme operation.
Efter ændringer i tjenesterne skal den gamle version først være gendannet og
helbredskontrolleret. Mislykket gendannelse stopper forløbet. Manglende diskplads,
rettigheder, ugyldige manifests og ejerskabsfejl udløser ikke automatiske genforsøg.
En mistet HTTP-forbindelse gentager aldrig en installationsanmodning.

Den observerede fejl på serveren var en ny `mediahub.db-shm` mellem kopiering og
ejerskabskopiering. SQLite-databasen sikkerhedskopieres nu med online backup-API'et,
inklusive committed WAL-data, uden løse WAL/SHM-filer. Ejerskab kopieres for de
filer, der faktisk findes i snapshot. Øvrige filfejl skjules ikke.

“Opdater alle” vælger kun positive, aktuelle kontroller og kontrollerer igen før
hver installation. Core køres sidst. Samme version og samme commit springes over;
ændret commit med samme version understøttes, mens nedgradering afvises.
Ukendt installeret appversion vises som en konkret kontrolfejl og udløser ikke en
vilkårlig geninstallation. Gamle gemte køer bevarer deres afgrænsede tidsfrist;
nye Core-køer tillader de tre værtsforsøg.

## Versionskilder

| App | Installeret identitet | Seneste kilde og opdatering |
| --- | --- | --- |
| Core | Runtimeversion og rod-ejet installeret commit | Konfigureret MediaHub-repository, commit-fastlåst main |
| Separat Agent | Agentens egen version og commit | Det konfigurerede Hub-repository; separat SSH-forløb |
| MediaSeed / MediaVPN | Den ejede appcontainers versions- og commitlabels | Appens eget GitHub-repository; uafhængig opdatering |
| Plex | PMS-identitet til visning; valideret publisher-digest til opdatering | LinuxServer-imagets registrymetadata; read-only kontrol |
| Jellyfin / Prowlarr / Radarr / Sonarr / autobrr | Valideret OCI/LinuxServer-versionslabel | Seneste stabile GitHub-release; manuel opdatering fremgår særskilt |
| Healthcheck | Indbygget i Core | Opdateres sammen med Core |
| Ekstern FjordHub | Forvaltes i sin egen integration | Brug FjordHubs egen opdatering; ingen automatisk Core-erstatning |

Plex-containere genskabt efter lagerændringer kan have et immutable image-id som
reference. Publisheren genfindes kun fra netop det godkendte images RepoDigests.
Ukendt publisher, arkitektur eller inkompatible manifesttyper giver ingen
påstået opdatering. Stoppede apps vises neutralt med “Kører ikke” og “Start app”.

## Klargøring, verifikation og gendannelse

Frisk installation kopierer værtsopdateringen fra den aktuelle kilde. Almindelig
appklargøring efter Core-opgradering eftermonterer samme værtsfil idempotent.
Der tilføjes ingen pakker, credentials eller databaser til brugerens opsætning.
En ældre værtsopdaterer skal selv gennemføre overgangen til denne udgave, før
den har de nye genforsøg. Den kan om nødvendigt opfriskes gennem det eksisterende
reviewede `enable_source_updates.py --refresh-helper`-forløb.

Automatiske tests dækker snapshots med committed WAL, samtidige sidecars,
bevarede ejerskaber, begrænsede genforsøg, gentagen rollback, afvist rollback,
versionssammenligning, frisk klargøring og opgradering. Browsercheck dækker
Start/Stop-handlinger og bekræftelse. Den eksisterende servers Plex er startet
med den rettede kontrol i et isoleret engangsforløb og er verificeret sund;
Core-imaget blev ikke erstattet. Faktisk nyinstallation og fuld fysisk
genstart indgår ikke i denne verifikation.

Udgivelseskontrol: kildeudgivelsen kan installeres gennem det normale forløb.
Sikkerhedskopier og fejlede konfigurationsmapper bevares til gendannelse;
mislykket gendannelse kræver administratorgennemgang før et nyt forsøg.
Ingen mediefiler, biblioteker, torrents eller VPN-profiler nulstilles.
