param([string]$InstallDirectory = (Join-Path $HOME 'MediaHub-Guided'))
$ErrorActionPreference = 'Stop'
$InstallDirectory = [System.IO.Path]::GetFullPath($InstallDirectory)
if ($InstallDirectory.Contains(',')) { throw 'The installation folder must not contain commas.' }

function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw 'Docker step failed. Keep the installation folder and volumes; do not delete media or retry blindly.' }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install and start Docker Desktop first, then use Linux containers.' }
$server = & docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $server -ne 'linux') { throw 'Start Docker Desktop with Linux containers before continuing.' }
Invoke-Docker compose version
if (Test-Path -LiteralPath $InstallDirectory) { throw "Folder already exists: $InstallDirectory. This installer is new-install-only." }
$existing = & docker volume ls --format '{{.Name}}'
if ($LASTEXITCODE -ne 0) { throw 'Cannot list Docker volumes.' }
if ($existing | Where-Object { $_ -like 'mediahub-guided-*' }) { throw 'MediaHub guided volumes already exist. They will not be overwritten.' }
$containers = & docker ps -a --filter label=com.docker.compose.project=mediahub-guided --format '{{.ID}}'
if ($LASTEXITCODE -ne 0 -or $containers) { throw 'Cannot safely create a new MediaHub guided project. Inspect existing containers.' }
$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 18765)
try { $listener.Start() } finally { $listener.Stop() }
Write-Host 'This installs MediaHub Core and Agent locally, builds images and creates new Docker volumes.'
Write-Host 'No existing media is mounted. Plex/Seedbox host preparation is not included. Docker Desktop must stay running.'
if ((Read-Host 'Type INSTALL to continue') -cne 'INSTALL') { return }
New-Item -ItemType Directory -Path $InstallDirectory | Out-Null
$source = Join-Path $InstallDirectory 'source'
$localSource = Split-Path $PSScriptRoot
if (Test-Path (Join-Path $localSource 'docker/Dockerfile')) {
    $source = $localSource
} else {
    $archive = Join-Path $InstallDirectory 'source.zip'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/miklas206/mediahub-platform/archive/refs/heads/main.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $source
    $source = Join-Path $source 'mediahub-platform-main'
}
Invoke-Docker build -f (Join-Path $source 'docker/Agent.Dockerfile') -t mediahub-guided-agent:local $source
Invoke-Docker build -f (Join-Path $source 'docker/Dockerfile') -t mediahub-guided-core:local $source
$volumes = @('data','state','storage','credentials','core-tls','agent-tls','trust','authority')
$mounts = @()
foreach ($volume in $volumes) {
    Invoke-Docker volume create --label mediahub.guided=true "mediahub-guided-$volume"
    $mounts += @('--mount', "type=volume,src=mediahub-guided-$volume,dst=/bootstrap/$volume")
}
$helper = Join-Path $source 'scripts/docker_bootstrap.py'
Invoke-Docker run --rm --network none --user 0 --entrypoint python @mounts --mount "type=bind,src=$helper,dst=/bootstrap.py,readonly" --mount "type=bind,src=$InstallDirectory,dst=/output" mediahub-guided-agent:local /bootstrap.py
$compose = Join-Path $InstallDirectory 'compose.json'
Invoke-Docker compose -f $compose config --quiet
Invoke-Docker compose -f $compose up -d --wait --wait-timeout 180
Write-Host 'MediaHub and Agent passed their HTTPS health checks.'
Write-Host 'Import only the public ca.pem certificate from this installation. Never disable browser certificate checks.'
if ((Read-Host 'Trust this new local public certificate for your Windows user? Type TRUST') -ceq 'TRUST') {
    Import-Certificate -FilePath (Join-Path $InstallDirectory 'ca.pem') -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
}
Write-Host 'Open https://127.0.0.1:18765 and use the browser setup wizard.'
Write-Host "Read your private installation token with: docker compose -f `"$compose`" exec core mediahub bootstrap-token"
Write-Host 'Use at least 12 characters for your administrator password. Skip Plex until its host is prepared.'
Write-Host 'Certificates expire in 90 days; see the certificate renewal guide.'
Write-Host 'Keep the installation folder and Docker volumes. Never use down -v or volume prune to update this installation.'