# MediaHub beta og Proxmox-lager

MediaHub installeres på en eksisterende, udtrykkeligt valgt beta-LXC som beskrevet i [README](../README.md). Projektet opretter ikke automatisk en ny LXC og installerer ikke den oprindelige FjordHub. Det gamle `install-proxmox.sh` stopper derfor før nogen ændringer.

Førstegangsopsætningen har tre trin: konto, valgfri email og valgfri lageradgang. **Spring over** afslutter lagertrinnet uden at tilslutte mapper. Det kan åbnes igen under **Indstillinger → Lageradgang**.

## Valgfri Proxmox-forbindelse til en eksisterende installation

En almindelig app-opdatering tildeler ikke nye Proxmox-rettigheder. Hubben skal allerede køre med persistent `/data`. Brug en betroet kopi af netop dette private repository på Proxmox-værten; brug ikke instruktioner fra det oprindelige FjordHub til at opdatere beta-kopien.

Kør kun følgende, når Proxmox-adgang ønskes. Erstat `CTID` og `PVE_IP` med de verificerede værdier for den relevante installation:

```sh
python3 scripts/configure_proxmox.py CTID --host PVE_IP --directory /opt/fjordcopy
```

Kommandoen køres som root på Proxmox-værten. Den opretter en særskilt read-only PVEAuditor-token og en SSH-nøgle med en fast forced command for den valgte CTID. Den genopretter hub-containeren med forbindelsen. Repositoryets deploy key genbruges ikke. Det er en særskilt ændring fra installation af selve hubben.

Den kopierede storage-helper bruger de eksisterende FjordHub-protokolnavne. På en vært med en eksisterende FjordHub skal eventuelle delte helper-filer gennemgås før konfiguration; den første beta-installation konfigurerer dem ikke.

## Vælg mediefiler

Proxmox-inventory er et overblik over lagre, ikke adgang til deres filer. Medier kræver en eksplicit mount til LXC'en og den relevante app. Virtuelle diske på `local-lvm` er ikke browsbare mediemapper.

Start med de nødvendige mapper og read-only adgang. Brug ikke en produktionsdatabases eller apps private datamappe som en delt betamappe. Gennemgå kilde, rettigheder og mount-identitet før tilslutning. Tilslutning via guiden kan genstarte LXC'en og dens apps.

FjordFlix understøtter valg af mediemapper fra sin biblioteksopsætning. Andre apps har deres egne lagerfelter i installationsguiden. En frisk beta-installation har ingen af dine eksisterende mediemapper monteret automatisk.
