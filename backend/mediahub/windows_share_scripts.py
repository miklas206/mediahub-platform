"""Downloadable, user-run Windows helpers. Generating a script never contacts a share.

The API supplies only LAN connection metadata; credentials are requested on the PC.
Keep these scripts compatible with Windows PowerShell 5.1 and emit downloads with
``utf8_bom_script`` so Danish instructions survive its legacy encoding default.
"""

from mediahub.windows_share import WindowsShareConfiguration


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _configuration(host: str, share: str, drive: str, username: str | None) -> str:
    # Use the same boundary contract as saved settings to avoid download failures
    # for valid names such as .hidden and normalize lowercase drive letters.
    configuration = WindowsShareConfiguration(
        server=host, shareName=share, driveLetter=drive,
        username="" if username is None else username,
    )
    return "\n".join(
        (
            "$ServerAddress = " + _literal(configuration.server),
            "$SharePath = " + _literal("\\\\" + configuration.server + "\\" + configuration.shareName),
            "$DriveName = " + _literal(configuration.driveLetter),
            "$SuggestedUsername = " + _literal(configuration.username),
            "$LocalPath = $DriveName + ':'",
        )
    )


def utf8_bom_script(script: str) -> bytes:
    """Encode an inspectable .ps1 download for Windows PowerShell 5.1."""
    return script.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8-sig")


def generate_password_reset_script(host: str, share: str, drive: str, username: str | None = None) -> str:
    """Reset an existing local Samba account through a user-owned SSH terminal.

    No password goes through Core, command arguments, or a generated file.
    The user supplies a separate server administrator account at run time.
    """
    return r'''[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
param([string]$SmbUsername = '', [string]$ServerAdmin = '', [string]$IdentityFile = '')
''' + _configuration(host, share, drive, username) + r'''
$ErrorActionPreference = 'Stop'
Write-Host ('MediaHub - Nulstil SMB-adgangskode paa ' + $ServerAddress)
Write-Host 'Dette er til en Linux/Samba-server med SSH og en eksisterende lokal SMB-konto.'
Write-Host 'Du skal kende serverens administratorlogin. Den gamle SMB-kode er ikke noedvendig.'
Write-Host 'Hvis serveren kun tillader SSH-noegler, skal du bruge en allerede godkendt noegle via -IdentityFile.'
Write-Host 'NAS eller Windows-server: brug serverens egen kontoadministration i stedet.'
Write-Host 'Adgangskoder indtastes skjult i denne terminal via SSH og sendes ikke til MediaHub.'
Write-Host 'Andre pc-er skal bruge den nye SMB-kode ved naeste login. Ctrl+C afbryder.'
if ([string]::IsNullOrWhiteSpace($SmbUsername)) {
    $SmbUsername = Read-Host -Prompt ('Lokal SMB-bruger (Enter bruger ' + $SuggestedUsername + ')')
    if ([string]::IsNullOrWhiteSpace($SmbUsername)) { $SmbUsername = $SuggestedUsername }
}
if ($SmbUsername -cnotmatch '^[a-zA-Z_][a-zA-Z0-9_.-]{0,31}$') {
    throw 'Angiv den eksisterende lokale Samba-bruger, uden domaene, mellemrum eller kommandoer.'
}
if ([string]::IsNullOrWhiteSpace($ServerAdmin)) {
    $ServerAdmin = Read-Host -Prompt 'Serverens SSH-administrator (fx mediahub; ikke din Windows-bruger)'
}
if ($ServerAdmin -cnotmatch '^[a-zA-Z_][a-zA-Z0-9_.-]{0,31}$') {
    throw 'Angiv et lokalt SSH-login uden domaene eller kommandoer.'
}
if (-not $PSCmdlet.ShouldProcess(($ServerAddress + ' / ' + $SmbUsername), 'Saet en ny adgangskode for denne eksisterende SMB-konto')) { return }
$Ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
if (-not (Test-Path -LiteralPath $Ssh -PathType Leaf)) {
    throw 'Windows OpenSSH-klient mangler. Installer OpenSSH Client under Windows valgfrie funktioner, eller nulstil kontoen fra serverens terminal.'
}
$SshArguments = @('-t', '-o', 'StrictHostKeyChecking=ask', '-o', 'ConnectTimeout=10', '-l', $ServerAdmin)
if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
    if (-not (Test-Path -LiteralPath $IdentityFile -PathType Leaf)) {
        throw 'Den valgte SSH-noegle findes ikke. Angiv stien til en eksisterende privat noegle, som serveren accepterer.'
    }
    $KeyPath = (Get-Item -LiteralPath $IdentityFile).FullName
    $SshArguments += @('-o', 'IdentitiesOnly=yes', '-i', $KeyPath)
}
Write-Host 'Foerste forbindelse: sammenlign SSH-fingeraftrykket med serverens, foer du godkender det.'
Write-Host 'SSH-login og evt. sudo-login bruger serverens administratorkode. New SMB password er den nye SMB-kode; indtast den to gange.'
$RemoteCommand = @'
set -eu
for tool in smbpasswd pdbedit testparm; do
    command -v "$tool" >/dev/null 2>&1 || { echo 'Samba tools missing. Use the NAS/server account administration.' >&2; exit 20; }
done
admin=''
if [ "$(id -u)" != 0 ]; then
    command -v sudo >/dev/null 2>&1 || { echo 'Administrator access required.' >&2; exit 21; }
    sudo -v || exit 21
    admin=sudo
fi
sync=$($admin testparm -s --parameter-name='unix password sync' 2>/dev/null) || exit 22
case "$sync" in
    No|no) ;;
    *) echo 'Unix password sync enabled or unknown. Ask the server administrator to reset SMB without changing the Linux password.' >&2; exit 22 ;;
esac
$admin pdbedit -L | cut -d: -f1 | grep -Fxq '__SMB_USER__' || { echo 'Existing local Samba account not found. No account created.' >&2; exit 23; }
$admin smbpasswd '__SMB_USER__'
'@
$RemoteCommand = $RemoteCommand.Replace('__SMB_USER__', $SmbUsername).Replace("`r", '')
& $Ssh @SshArguments $ServerAddress $RemoteCommand
if ($LASTEXITCODE -eq 255) {
    Write-Warning 'SSH-forbindelsen mislykkedes. Ved Permission denied (publickey) tillader serveren kun en godkendt SSH-noegle; SMB-koden kan ikke bruges til dette login.'
    Write-Host 'Koer igen med -IdentityFile og stien til din eksisterende SSH-noegle. Aendr ikke serverens loginregler for at faa dette vaerktoej til at virke.'
    Write-Host 'Alternativ: aabn selve Samba-serverens konsol (fx VM-konsollen i Proxmox) og log ind som administrator.'
    Write-Host 'Vis de eksisterende SMB-brugere med: sudo pdbedit -L'
    Write-Host ('Nulstil den valgte SMB-bruger med: sudo smbpasswd ' + $SmbUsername)
    throw 'SSH kunne ikke oprette forbindelse. Nulstillingen blev ikke bekraeftet. Se vejledningen ovenfor.'
}
if ($LASTEXITCODE -ne 0) {
    throw 'Nulstillingen blev ikke bekraeftet. Se serverens fejl ovenfor. Kontrollér SSH-login, sudo-adgang og den eksisterende Samba-konto.'
}
Write-Host 'Serveren har bekraeftet den nye SMB-adgangskode.' -ForegroundColor Green
Write-Host ('Luk filer paa ' + $LocalPath + ' og afbryd kun dette netvaerksdrev i Stifinder.')
Write-Host ('Aabn Windows Legitimationsstyring, og fjern kun et gammelt gemt Windows-login til ' + $ServerAddress + ', hvis det findes.')
Write-Host ('Forbind igen til ' + $SharePath + ' med SMB-brugeren ' + $SmbUsername + ' og din nye kode.')
Write-Host 'Dette vaerktoej aendrer ikke dine Windows-drev, delingsrettigheder eller mediefiler.'
'''


# Potentially blocking read operations run in an owned, hidden child process.
# Its only output is small JSON metadata; killing it cannot affect another shell.
# In particular Test-Path/Get-PSDrive on an offline SMB server cannot stall the UI
# indefinitely. No execution-policy change, credentials, or file writes are needed.
_COMMON = r'''
$ErrorActionPreference = 'Stop'

function Invoke-BoundedRead {
    param([scriptblock]$Operation, [string[]]$Values = @(), [int]$TimeoutSeconds = 8)
    $Arguments = @($Values | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ' '
    $ChildCode = @'
$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
'@ + "`n" + '$Value = & {' + $Operation.ToString() + "`n} " + $Arguments + "`n" + @'
    @{ Ok = $true; Value = $Value } | ConvertTo-Json -Depth 5 -Compress
} catch {
    $Exception = $_.Exception
    while ($Exception.InnerException) { $Exception = $Exception.InnerException }
    $Code = $Exception.HResult -band 65535
    if ($Exception -is [System.ComponentModel.Win32Exception]) { $Code = $Exception.NativeErrorCode }
    @{ Ok = $false; Code = $Code } | ConvertTo-Json -Compress
}
'@
    $Executable = Join-Path $PSHOME 'powershell.exe'
    if (-not [System.IO.File]::Exists($Executable)) { $Executable = Join-Path $PSHOME 'pwsh.exe' }
    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo.FileName = $Executable
    $Process.StartInfo.Arguments = '-NoLogo -NoProfile -NonInteractive -EncodedCommand ' +
        [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($ChildCode))
    $Process.StartInfo.UseShellExecute = $false
    $Process.StartInfo.CreateNoWindow = $true
    $Process.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $Process.StartInfo.RedirectStandardOutput = $true
    $Process.StartInfo.RedirectStandardError = $true
    $Process.StartInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    try {
        $null = $Process.Start()
        # Drain both pipes while the worker is running. Waiting for exit first
        # deadlocks once even a valid inventory exceeds the pipe's small buffer.
        $OutputTask = $Process.StandardOutput.ReadToEndAsync()
        $ErrorTask = $Process.StandardError.ReadToEndAsync()
        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            $Process.Kill()
            $null = $Process.WaitForExit(1000)
            return [pscustomobject]@{ Ok = $false; TimedOut = $true; Code = 0 }
        }
        $Readers = [System.Threading.Tasks.Task[]]@($OutputTask, $ErrorTask)
        if (-not [System.Threading.Tasks.Task]::WaitAll($Readers, 1000)) {
            return [pscustomobject]@{ Ok = $false; TimedOut = $true; Code = 0 }
        }
        $Output = $OutputTask.Result
        if ($Process.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($Output)) {
            return [pscustomobject]@{ Ok = $false; TimedOut = $false; Code = 0 }
        }
        return $Output | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{ Ok = $false; TimedOut = $false; Code = 0 }
    } finally {
        # A failed reader/startup path must not leave our own worker running.
        try {
            if (-not $Process.HasExited) {
                $Process.Kill()
                $null = $Process.WaitForExit(1000)
            }
        } catch { }
        $Process.Dispose()
    }
}

function Show-ErrorGuidance {
    param([int]$Code = 0)
    switch ($Code) {
        53 { Write-Warning 'Fejl 53: Netværksstien blev ikke fundet. Kontrollér LAN-adresse, lokal netværksadgang og TCP 445.' }
        67 { Write-Warning 'Fejl 67: Delingsnavnet blev ikke fundet. Kontrollér det præcise SMB-delingsnavn på serveren.' }
        5 { Write-Warning 'Fejl 5: Adgang nægtet. Kontrollér SMB-bruger, adgangskode og rettigheder til deling og mapper.' }
        1219 { Write-Warning 'Fejl 1219: Windows bruger allerede en anden konto mod denne server. Luk åbne filer, gennemgå forbindelserne, og afbryd kun den konkrete konflikt manuelt, hvis det er sikkert.' }
        default { Write-Warning 'Kontrollen kunne ikke fuldføres. Kør diagnosticeringsscriptet, og kontrollér LAN, delingsnavn og SMB-konto. En timeout er ikke bevis for manglende rettigheder.' }
    }
}

function Get-LocalInventory {
    Invoke-BoundedRead -Values @($ServerAddress, $DriveName) -Operation {
        param($ServerAddress, $DriveName)
        $LocalPath = $DriveName + ':'
        # Read only metadata: do not access Root/Free of an unrelated drive.
        $Mappings = @(Get-SmbMapping -ErrorAction Stop | Where-Object { $_.LocalPath -eq $LocalPath } |
            Select-Object -Property LocalPath, RemotePath, Status)
        $Remembered = Get-ItemProperty -LiteralPath ('HKCU:\Network\' + $DriveName) -ErrorAction SilentlyContinue
        $Drive = Get-PSDrive -Name $DriveName -ErrorAction SilentlyContinue
        $ConnectionsKnown = $true
        try {
            $Connections = @(Get-SmbConnection -ErrorAction Stop |
                Where-Object { $_.ServerName -eq $ServerAddress } |
                Select-Object -First 20 -Property ShareName, UserName, Credential, Dialect)
        } catch {
            $ConnectionsKnown = $false
            $Connections = @()
        }
        [pscustomobject]@{
            Mappings = $Mappings; RememberedPath = $Remembered.RemotePath
            DriveExists = [bool]$Drive; Connections = $Connections; ConnectionsKnown = $ConnectionsKnown
        }
    }
}

function Test-ServerPort {
    Invoke-BoundedRead -TimeoutSeconds 6 -Values @($ServerAddress) -Operation {
        param($ServerAddress)
        $Client = New-Object System.Net.Sockets.TcpClient
        try {
            $Pending = $Client.BeginConnect($ServerAddress, 445, $null, $null)
            try {
                if (-not $Pending.AsyncWaitHandle.WaitOne(3000)) { return $false }
                $Client.EndConnect($Pending)
                return $Client.Connected
            } finally { $Pending.AsyncWaitHandle.Close() }
        } finally { $Client.Close() }
    }
}

Write-Host ''
Write-Host ('MediaHub · Windows-mediedrev ' + $LocalPath + ' → ' + $SharePath)
Write-Host 'Kør som din normale Windows-bruger, der også bruger Stifinder. Ikke som administrator.'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if ($Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning 'Dette vindue er startet som administrator. Drevet kan derfor være usynligt i din normale Stifinder. Åbn et normalt PowerShell-vindue i stedet.'
}
Write-Host 'Kræver lokal netværksadgang og SMB 2/3 med en brugerkonto. Ingen SMB1, gæsteadgang eller firewallændringer aktiveres.'
Write-Host 'VPN: Tillad dit lokale LAN i din Windows-VPN. Seedboxens torrent-VPN giver ikke i sig selv adgang til hjemmenetværket.'
'''

_CONNECT = r'''

Write-Host 'Scriptet opretter kun det valgte netværksdrev efter din bekræftelse. Eksisterende drev og forbindelser bevares.'
$Inventory = Get-LocalInventory
if (-not $Inventory.Ok) {
    Write-Warning 'Eksisterende drev kunne ikke kontrolleres sikkert. Intet ændres. Kør diagnosticeringen eller vælg et andet drevbogstav.'
    return
}
$State = $Inventory.Value
$Existing = @($State.Mappings)
if ($Existing.Count -gt 0 -or $State.RememberedPath -or $State.DriveExists -or
    (Get-PSDrive -Name $DriveName -ErrorAction SilentlyContinue)) {
    if (($Existing.Count -gt 0 -and $Existing[0].RemotePath -eq $SharePath) -or $State.RememberedPath -eq $SharePath) {
        Write-Host 'Det ønskede drev er allerede registreret. Intet ændres, heller ikke hvis det vises som utilgængeligt. Kør diagnosticeringen.'
    } else {
        Write-Warning 'Drevbogstavet er optaget eller husket til en anden placering. Vælg et ledigt bogstav i MediaHub. Det eksisterende drev bliver ikke overskrevet.'
    }
    return
}
if (@($State.Connections).Count -gt 0) {
    Write-Warning 'Der findes allerede SMB-forbindelser til serveren. Brug samme SMB-konto for at undgå fejl 1219. Scriptet afbryder ingen forbindelser.'
}
$Port = Test-ServerPort
if (-not $Port.Ok -or -not $Port.Value) {
    Show-ErrorGuidance -Code 53
    return
}
if (-not $PSCmdlet.ShouldProcess(($LocalPath + ' → ' + $SharePath), 'Opret vedvarende netværksdrev for din Windows-bruger')) {
    return
}
$Credential = $null
$Password = $null
try {
    Write-Host 'Indtast kontoen til SMB-delingen på filserveren. Det er ikke nødvendigvis din Windows- eller MediaHub-konto.'
    Write-Host 'Glemt adgangskode? Annuller med Ctrl+C, og få den ændret på din NAS eller Samba-server. MediaHub kan ikke hente den.'
    $UsernamePrompt = 'SMB-brugernavn (tomt felt annullerer)'
    if ($SuggestedUsername) { $UsernamePrompt = ('SMB-brugernavn [Enter bruger ' + $SuggestedUsername + ']') }
    $Username = Read-Host -Prompt $UsernamePrompt
    if ([string]::IsNullOrWhiteSpace($Username)) { $Username = $SuggestedUsername }
    if ([string]::IsNullOrWhiteSpace($Username)) { Write-Host 'Annulleret. Intet drev blev oprettet.'; return }
    $Password = Read-Host -Prompt 'SMB-adgangskode (skjult; tomt felt annullerer)' -AsSecureString
    if ($null -eq $Password -or $Password.Length -eq 0) { Write-Host 'Annulleret. Intet drev blev oprettet.'; return }
    $Credential = [System.Management.Automation.PSCredential]::new($Username, $Password)
    # Recheck after the interactive prompt. New-PSDrive also refuses an occupied name.
    $Recheck = Get-LocalInventory
    if (-not $Recheck.Ok -or @($Recheck.Value.Mappings).Count -gt 0 -or
        $Recheck.Value.RememberedPath -or $Recheck.Value.DriveExists -or
        (Get-PSDrive -Name $DriveName -ErrorAction SilentlyContinue)) {
        Write-Warning 'Drevbogstavet er ikke længere sikkert ledigt. Intet ændres.'
        return
    }
    New-PSDrive -Name $DriveName -PSProvider FileSystem -Root $SharePath -Credential $Credential -Persist -Scope Global -ErrorAction Stop | Out-Null
    Write-Host ('Drevet er tilsluttet. Åbn ' + $LocalPath + '\ i Stifinder.')
    Write-Host 'Windows husker drevet ved næste login. Genopkobling kræver tilgængeligt LAN, server og gyldige legitimationsoplysninger; Windows kan bede om login igen.'
} catch {
    $Exception = $_.Exception
    while ($Exception.InnerException) { $Exception = $Exception.InnerException }
    $Code = $Exception.HResult -band 65535
    if ($Exception -is [System.ComponentModel.Win32Exception]) { $Code = $Exception.NativeErrorCode }
    Show-ErrorGuidance -Code $Code
} finally {
    $Credential = $null
    if ($null -ne $Password) { $Password.Dispose(); $Password = $null }
}
'''

_DIAGNOSTICS = r'''

Write-Host 'Læsekontrol: Ingen filer oprettes, og ingen drev, legitimationsoplysninger eller serverindstillinger ændres.'
Write-Host 'En adgangskontrol kan åbne en normal SMB-session med din eksisterende Windows-konto. Den beviser ikke skriverettigheder.'
Write-Host 'DNS: Den gemte adresse er en IP-adresse, så denne forbindelse kræver ikke navneopslag. Hvis en anden genvej bruger et servernavn, kontrollér at navnet peger på samme LAN-adresse.'
Write-Host ''
Write-Host '1. Drev og eksisterende forbindelser (højst 8 sekunder)'
$Inventory = Get-LocalInventory
$ExpectedMapping = $false
if (-not $Inventory.Ok) {
    Write-Warning 'Drevoversigten kunne ikke læses inden for tidsgrænsen eller med denne Windows-konto. Resultatet er ukendt.'
} else {
    $State = $Inventory.Value
    $Mappings = @($State.Mappings)
    if ($Mappings.Count -gt 0) {
        foreach ($Mapping in $Mappings) {
            Write-Host ($Mapping.LocalPath + ' → ' + $Mapping.RemotePath + ' · ' + $Mapping.Status)
            if ($Mapping.RemotePath -eq $SharePath) { $ExpectedMapping = $true }
            else { Write-Warning 'Drevbogstavet peger et andet sted hen. Vælg et ledigt drevbogstav; dette script ændrer ikke drevet.' }
        }
    } elseif ($State.RememberedPath) {
        Write-Host ('Windows husker ' + $LocalPath + ' → ' + $State.RememberedPath)
        Write-Warning 'Drevet er gemt, men ikke aktivt her. Kontrollér LAN, samme Windows-bruger og kontoens adgang.'
    } elseif ($State.DriveExists) {
        Write-Warning 'Drevbogstavet er optaget af et andet drev. Vælg et ledigt bogstav i MediaHub.'
    } else {
        Write-Host 'Drevbogstavet er ledigt. Tilslutningsscriptet kan oprette forbindelsen efter din bekræftelse.'
    }
    if (-not $State.ConnectionsKnown) {
        Write-Host 'Detaljer om aktive SMB-konti kunne ikke læses. Det er ikke i sig selv en adgangsfejl til delingen.'
    }
    foreach ($Connection in @($State.Connections)) {
        # Credential is an account name from Get-SmbConnection, never a password.
        $Account = [string]$Connection.Credential
        if (-not $Account) { $Account = [string]$Connection.UserName }
        Write-Host ('Aktiv SMB-konto: ' + $Account + ' · Deling: ' + $Connection.ShareName + ' · SMB ' + $Connection.Dialect)
        if ($SuggestedUsername -and $Account -ine $SuggestedUsername) {
            Write-Warning 'Kontonavnet afviger fra det foreslåede login (domænepræfikser kan forklare forskellen). Kontrollér kontoen før et nyt login; forskellige konti kan give fejl 1219.'
        }
        if ([string]$Connection.Dialect -like '1.*') { Write-Warning 'SMB1 observeret: Opgradér serverens SMB-konfiguration til SMB 2/3. Scriptet ændrer ikke Windows eller serveren.' }
    }
}
Write-Host ''
Write-Host '2. TCP 445 fra denne Windows-pc (højst 6 sekunder)'
$Port = Test-ServerPort
if ($Port.Ok -and $Port.Value) {
    Write-Host 'TCP 445 svarer. Dette beviser kun netværksforbindelsen, ikke delingsnavn eller login.'
    Write-Host ''
    Write-Host '3. Adgang til delingens rod med din aktuelle konto (højst 8 sekunder)'
    $Access = Invoke-BoundedRead -Values @($SharePath) -Operation {
        param($SharePath)
        if (-not (Test-Path -LiteralPath $SharePath -PathType Container -ErrorAction Stop)) {
            return $false
        }
        # Attributes alone do not prove browse permission. Advance the lazy
        # enumerator once, including an empty accessible directory; disclose no names.
        $Entries = [IO.Directory]::EnumerateFileSystemEntries($SharePath).GetEnumerator()
        try {
            $null = $Entries.MoveNext()
            return $true
        } finally {
            $Entries.Dispose()
        }
    }
    if ($Access.Ok -and $Access.Value) { Write-Host 'Delingens rod kan læses. Mapper kan stadig have andre rettigheder; der er ikke forsøgt at skrive.' }
    elseif (-not $Access.Ok) { Show-ErrorGuidance -Code $Access.Code }
    else { Write-Warning 'Delingen kunne ikke åbnes med den aktuelle konto. Kontrollér delingsnavn og login (typisk fejl 67 eller 5). Der er ikke bedt om en ny adgangskode.' }
    if ($Access.Ok -and $Access.Value -and $ExpectedMapping) {
        Write-Host ''
        Write-Host '4. Serverens rapporterede ledige plads på det forventede drev (højst 8 sekunder)'
        $Space = Invoke-BoundedRead -Values @($DriveName, $SharePath) -Operation {
            param($DriveName, $SharePath)
            $Mapping = @(Get-SmbMapping -ErrorAction Stop | Where-Object {
                $_.LocalPath -eq ($DriveName + ':') -and $_.RemotePath -eq $SharePath
            })
            if ($Mapping.Count -ne 1) { throw 'Mapping changed during diagnostics' }
            $Drive = Get-PSDrive -Name $DriveName -ErrorAction Stop
            [pscustomobject]@{ Free = $Drive.Free; Used = $Drive.Used }
        }
        if ($Space.Ok -and $null -ne $Space.Value.Free) {
            Write-Host ('Ledigt rapporteret af serveren: {0:N1} GiB' -f ($Space.Value.Free / 1GB))
        } else { Write-Warning 'Ledig plads kunne ikke læses sikkert inden for tidsgrænsen. Der vises ingen antaget kapacitet.' }
    } else { Write-Host 'Pladskontrol springes over, indtil det forventede drev er tilsluttet og delingen kan læses.' }
} else {
    Show-ErrorGuidance -Code 53
    Write-Host 'Adgangs- og pladskontrol springes over. Kontrollér pcens LAN/VPN, serverens adresse og SMB-tjenesten. Slå ikke firewall eller VPN-beskyttelse fra som genvej.'
}
Write-Host ''
Write-Host 'Forkert ledig plads: Sammenlign med lagerpuljen i MediaHub. Hvis drevroden viser en lille systemdisk, men undermappen viser lagerpuljen, skal serverens SMB-delingsrod/kapacitetsrapportering (Samba dfree) gennemgås. Kvoter kan også begrænse pladsen. Scriptet ændrer ikke lagermonteringer.'
Write-Host 'Fejlkoder: 53 = netværkssti, 67 = delingsnavn, 5 = adgang, 1219 = forskellige SMB-konti til samme server.'
Write-Host 'Ved fejl 1219: Luk berørte filer og gennemgå kun forbindelser til denne server. Afbryd aldrig alle netværksdrev som standardløsning.'
Write-Host 'Kontrollen er afsluttet. Oplysningerne bliver i dette vindue og sendes ikke til MediaHub.'
'''


def generate_connect_script(host: str, share: str, drive: str, username: str | None = None) -> str:
    """Generate the explicit, confirmed mapping action; no execution happens here."""
    return (
        "#Requires -Version 5.1\n"
        "# MediaHub: læs scriptet, og kør det selv i et normalt PowerShell-vindue.\n"
        "[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]\nparam()\n"
        + _configuration(host, share, drive, username)
        + _COMMON
        + _CONNECT
    )


def generate_diagnostics_script(host: str, share: str, drive: str, username: str | None = None) -> str:
    """Generate bounded local-PC diagnostics without creating/removing mappings."""
    return (
        "#Requires -Version 5.1\n"
        "# MediaHub: læsekontrol af Windows-mediedrev. Ingen upload af resultatet.\n"
        "[CmdletBinding()]\nparam()\n"
        + _configuration(host, share, drive, username)
        + _COMMON
        + _DIAGNOSTICS
    )
