# Brug NAS-lager i MediaSeed og Plex

NAS-forbindelsen oprettes under **Indstillinger → Lager**. Når den står som
forbundet, kan den tilknyttes under **NAS-lager til apps** på samme side eller i
appens indstillinger. Tilknytningen er ekstra lager: nuværende downloads,
mediebiblioteker, adgangskoder og appdata bliver liggende.

## Plex

1. Stop Plex fra MediaHub.
2. Vælg NAS-lageret under Plex, og vælg **Tilknyt lager**.
3. Start Plex igen.
4. Åbn Plex → Indstillinger → Administrer → Biblioteker. Opret eller redigér et
   bibliotek, og vælg Tilføj mapper.
5. Vælg den viste sti, `/media/nas/<lager-id>/files`, og den ønskede undermappe
   med film eller serier. Gem biblioteket.

Plex får læseadgang, også når NAS-forbindelsen tillader skrivning. Plex'
konfiguration og transkodningsmapper flyttes ikke til NAS'en. Der oprettes ikke
automatisk et bibliotek med forkert indholdstype. Lagerets tilgængelighed indgår
i Plex' eksisterende start- og overvågningskontrol.

## MediaSeed

1. Opdatér MediaVPN til **0.2.31 eller nyere**. NAS-forbindelsen skal tillade ændringer og have et NAS-login med skriveadgang.
2. Stop MediaSeed og MediaVPN fra MediaHub.
3. Vælg NAS-lageret under MediaSeed, og vælg **Tilknyt lager**.
4. Start MediaVPN og derefter MediaSeed igen.
5. Vælg NAS-lageret som placering, når du tilføjer en torrent eller et RSS-feed.

Både MediaSeed, det oprindelige qBittorrent og den VPN-beskyttede torrentklient
får samme placering. Appopdateringer bevarer valget og de eksisterende lokale
mapper. Ingen eksisterende torrent flyttes automatisk.

### Skrivecache i en LXC

Den brugerrumsbaserede SMB-driver skal bruge `writes`-cache til torrenters
vilkårlige skrivning, læsning og ændring af filstørrelse. Ved første tilknytning
til MediaSeed vælger serveren automatisk et verificeret lokalt medielager med
mindst 20 GiB ledigt. Cachen ligger under
`<mediemappe>/.mediahub-nas-cache/<installation>/<lager-id>`, og stien vises under
den gemte NAS-forbindelse. Den må ikke ligge på systemets rod-filsystem.

Der skal være plads til de aktive torrentfiler på mediedrevet. Målet er højst
100 GiB cache med mindst 10 GiB fri plads og oprydning af afsluttede cachefiler
efter en time. Det er oprydningsmål, ikke hårde grænser: åbne filer og endnu ikke
overførte data bliver bevaret. Lukkede filer overføres normalt efter fem sekunder;
netværksfejl genforsøges. Genstart bruger samme cache og NAS-identitet. Cachen er
bundet til det verificerede mediefilsystem, så et forsvundet drev ikke omdirigerer
skrivning til systemdisken.

En eksisterende forbindelse uden skrivecache skal være fri for app- og
Windows-tilknytninger, før denne ændring kan gennemføres. NAS-filer bevares.
Native CIFS på en almindelig Linux-vært kræver ikke denne skrivecache.

## Fjern tilknytningen

Stop appen (ved MediaSeed også MediaVPN), og vælg **Fjern fra app**. Filerne på
NAS'en slettes ikke. Fjern tilknytninger og Windows-delinger, før NAS-forbindelsen
kan afbrydes eller fjernes. En aktiv skrivecache skal have bekræftet alle ventende
overførsler først; kontrollen er kun tilgængelig via en root-privat Unix-socket.

Hvis en ændring bliver afbrudt, viser siden **Gendan tidligere tilknytning**.
Lad appsene være stoppet, og brug knappen til at gendanne de tidligere containere
og indstillinger. Gendannelsen starter ikke apps eller sletter mediefiler.

## Installation og opdatering

Den almindelige installation og opdatering installerer begge host-moduler og
den tilhørende agentkontrol. Eksisterende NAS-login og appkonfigurationer bevares.
Delte, afgrænsede mount-visninger genskabes før Docker ved opstart og genforbinder
NAS-underlageret med de eksisterende appcontainere. Manglende NAS-lager giver ikke
en skrivbar erstatningsmappe på systemdisken.

Verifikation omfatter automatiske tests for rettigheder, afbrudte ændringer,
gendannelse og opgradering samt isolerede Linux/Docker/FUSE-tests med testfiler.
De isolerede tests ændrer ikke brugerens Plex-biblioteker, torrents eller NAS-filer.

Driverdetaljer: [rclone VFS-skrivecache](https://rclone.org/commands/rclone_mount/#vfs-file-caching) og [cache-status](https://rclone.org/rc/#vfs-stats-stats-for-a-vfs).

Udgivelsestjek: ingen kendte blokeringer for kildeudgivelsen. Frisk klargøring og opgradering er automatisk testet; en fysisk nyinstallation og fuld værtsgenstart er ikke udført. Installer Core 0.6.59 og MediaVPN 0.2.31, kontrollér NAS-forbindelsen, og tilknyt derefter lageret med appsene stoppet. Gendannelse af en afbrudt tilknytning bevarer data og appindstillinger; brug den indbyggede gendan-knap før appsene startes igen.
