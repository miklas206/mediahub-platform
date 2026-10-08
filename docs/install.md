# Guided MediaHub Installation

## Choose your platform

Use **one** of the two scripts below for a new installation. They build and start
the real MediaHub Core and Agent, create new persistent Docker volumes and set
up HTTPS. No existing media drive is connected, formatted or migrated.
An existing installation or conflicting volume name causes the scripts to stop.
Do not delete existing files or volumes to force a retry.

Apps are intended to run as separate Docker services on the **same MediaHub
host**, inside its single Proxmox LXC when using Proxmox. Cloudflare is the
exception and may remain on its own host. This bootstrap currently installs
Core and Agent only: it does **not** yet configure local Seedbox/VPN, Plex
installation policies, host-driven updates or existing media mounts. Do not
mistake a working dashboard for a completed app installation.

### Windows with Docker Desktop

1. Install and start Docker Desktop using Linux containers. Windows PowerShell
	5.1 or newer is required. Keep Docker Desktop running while using MediaHub.
2. Open **PowerShell**, not a terminal inside a container.
3. Download the installer from this repository. You can review it in an editor
	before executing it; the command does not open an editor automatically:

```powershell
$installer = Join-Path $env:TEMP 'mediahub-install-docker.ps1'
Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/miklas206/mediahub-platform/main/scripts/install-docker.ps1' -OutFile $installer
```

4. Run the downloaded script:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\mediahub-install-docker.ps1"
```

5. Read the summary and type `INSTALL` to accept. The default output folder is
	`MediaHub-Guided` in your Windows user folder. Images may take several minutes
	to build. Wait for both HTTPS health checks to pass.
6. The script prints the new public CA fingerprint and asks whether to trust its
	certificate. Type `TRUST` only if you approve this installation's local CA.
	It imports only the public certificate into your current Windows user's
	trusted roots, not a private key. Otherwise import the verified public
	`ca.pem` manually before opening the browser.
7. Open **https://127.0.0.1:18765** on this computer. Do not use `localhost`:
	the configured browser origin is `127.0.0.1`. Do not bypass TLS warnings.
8. No installation token is required. Keep the installation private until you
	create the first administrator: the first visitor can claim an unconfigured server.
9. Choose an administrator username and a unique password of at least 12
	characters. Confirm the password. Save any two-factor recovery codes.
	Use the new `/storage` folders for testing, and skip Plex until its host
	policy is prepared. Do not point this test at your only copy of media.

The address is local to this computer, not exposed to the LAN or internet.
The script downloads the default branch; it is not a pinned stable release.
You need Docker Desktop installed, but not Git, Python or OpenSSL on Windows.

To update an existing Docker Desktop test installation, download the script again
using step 3, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\mediahub-install-docker.ps1" -Update
```

Type `UPDATE` to confirm. This builds the latest default-branch Core and Agent
images and restarts their containers. Existing accounts, storage, credentials and
certificates are retained; setup is not reset. Back up important test data first,
since database migrations may run. Use `-InstallDirectory` if you originally chose
a different folder. Do not delete the installation folder or Docker volumes to update.

To stop or start later, replace the folder below if you chose a different one:

```powershell
docker compose -f "$HOME\MediaHub-Guided\compose.json" stop
docker compose -f "$HOME\MediaHub-Guided\compose.json" start
docker compose -f "$HOME\MediaHub-Guided\compose.json" ps
```

Keep the installation folder and its Docker volumes. **Never use `down -v`,
`volume prune` or factory reset to update this installation.** Stopping the
containers keeps their data. This script is not an update or repair command.

### Proxmox

This path creates **one new MediaHub LXC**, not one LXC per app. It never
replaces LXC 102 or any other existing guest. The script currently supports
amd64 Proxmox, a Debian 13 template and a DHCP-enabled local network.
It installs Docker inside the new guest, not on the Proxmox hypervisor.

1. In the Proxmox web interface select your **node**, then **Shell**.
2. Download and review the installer:

```sh
curl -fL https://raw.githubusercontent.com/miklas206/mediahub-platform/main/scripts/install-proxmox.sh -o /root/mediahub-install-proxmox.sh
less /root/mediahub-install-proxmox.sh
```

Press `q` to close the reader, then start:

```sh
bash /root/mediahub-install-proxmox.sh
```

3. Answer the questions below. Press Enter only when the displayed default
	actually matches your host. If unsure about storage, stop before confirming.

| Question | Meaning |
| --- | --- |
| New container ID | A free ID, or Enter for Proxmox's next free ID. Existing guests are rejected. |
| Container storage | Storage for the new 64 GiB system disk, normally `local-lvm`. |
| Template storage | Storage for the downloaded Debian template, normally `local`. |
| Network bridge | Your LAN bridge, normally `vmbr0`. |
| Type INSTALL | Confirm the new guest with 6 CPU cores, 16384 MiB RAM and no swap. |

Review free storage and RAM before confirming. Thin-provisioned storage may be
overbooked even if creating the disk succeeds. The script does not change host
storage settings, extend pools or remove old guests to make room.

4. Wait for the new LXC, Docker, image builds and both HTTPS health checks.
	The final output shows your new guest's HTTPS address and CT ID.
5. Use the printed `pct pull` command to retrieve only the public CA. Transfer
	it to the browser computer, verify the printed fingerprint and import it as
	described in the certificate section below. Never transfer private keys.
6. Open the printed HTTPS address and create the administrator as in the Windows
	steps. Keep the installation private until the first administrator is created.

The new Docker volumes initially live on the **new system disk**, not your
existing media drives. This makes a new trial independent of existing media;
it is not a recommendation to fill the system disk with a production library.
Adding existing media needs an explicit mount/access plan. Do not attach a raw
disk twice or recursively change its permissions.

Proxmox status: shell syntax is checked; **this new end-to-end Proxmox installer
has not been run on a live host**. A failure retains the new guest and data for
inspection; no automatic destructive cleanup runs.

### If either script fails

Stop at the error. Keep the new installation folder, guest and volumes. Record
the failed stage and inspect status/logs locally before attempting repair.
Never share credentials or full configuration backups.
The script refuses existing volumes intentionally: this protects data, but
means a failed install cannot simply be restarted as a new installation.

Server certificates expire after **90 days**. Renewal is still operator-managed;
see [certificate renewal](certificates.md). The scripts do not yet provide
automatic renewal or a complete beginner-friendly app/update lifecycle.

## Advanced: prepared Linux host installation

The remainder describes the older `install.sh` path with explicit storage policy
and systemd host updating. It is **not** the Docker Desktop bootstrap. Do not
mix its paths or commands with the guided scripts above.

This guide is for a **new installation**. You do not need to write code, but you
do need a prepared Linux server. Follow the steps in order. If a check fails,
stop at that step instead of guessing or deleting files to try again.

Already have MediaHub? Use **Updates** inside MediaHub. Do not run this installer
over your existing setup. Moving an existing Seedbox is a separate migration.

## 1. Check what you have

A **server** is the computer that keeps MediaHub running. Your laptop or phone
opens MediaHub in a browser; it does not run these installation commands.
A **terminal** is the server's text window where you enter commands.

Before continuing, every item below must be ready:

- A new Debian/Ubuntu Linux server, VM or prepared unprivileged LXC.
- At least **6 CPU cores and 16 GB RAM (16384 MiB)** assigned to it.
- Docker Engine with Compose v2, Python **3.11 or newer**, OpenSSL and Git.
- systemd and cgroup v2, required for service management and resource limits.
- An existing, mounted data filesystem separate from the system disk, with a
  stable UUID (the filesystem's unique identifier).
- The server's local IPv4 address and exact data-drive mount path.
- Administrator access to the server and a backup of irreplaceable media.

**Not ready yet? Stop here.** The current installer does not create a VM/LXC,
install Docker, format a disk or mount a drive. This guide does not yet provide
a complete beginner-only server preparation wizard. Do not improvise disk
commands on the only copy of your media.

On Proxmox, open the console of the **new MediaHub guest**, not the Proxmox host's
Shell and not an existing app's container. LXC additionally requires Docker
nesting and [host-generated device evidence](deployment/devices.md).
Do not assume an ordinary LXC bind mount will pass the storage checks.
Never attach the same raw disk writable to two guests.

## 2. Open the server terminal and check it

Use the server's local console or the console of its VM/LXC. All `sh` command
blocks below run there, **not in Windows PowerShell**. Enter one block at a time.
If you are already logged in as `root`, omit `sudo` from commands that use it.

```sh
python3 --version
git --version
docker --version
sudo docker compose version
openssl version
systemctl --version
test -f /sys/fs/cgroup/cgroup.controllers && echo "cgroup v2 is available"
```

Expected: version information, Python 3.11 or newer, Compose v2, and the final
message `cgroup v2 is available`. A missing command or an error means server
preparation is incomplete. Do not continue until that is resolved.

Find the server's addresses:

```sh
hostname -I
```

Use its local IPv4 address, for example `192.168.1.50`. The example is **not**
your address. Do not use `127.0.0.1`, a Docker address or the Proxmox host's IP.
If several addresses are shown and you cannot identify the guest's LAN address,
check the guest's network settings before proceeding.

Inspect mounted filesystems without changing them:

```sh
findmnt -o TARGET,SOURCE,FSTYPE,UUID
```

Find your data drive's row. Its `TARGET` is the mount path; it must have a UUID
and must not be `/` (the system disk). Do not use a normal folder just because
its name looks like a drive. If you cannot identify the row, stop.

## 3. Get the MediaHub project

Run these commands from a folder where your login user can create files:

```sh
git clone https://github.com/miklas206/mediahub-platform.git
cd mediahub-platform
git status --short
```

Expected: the clone finishes and the last command prints nothing, meaning the
downloaded files have no local edits. If the folder already exists, do not
delete it or install over it; determine whether it belongs to an existing setup.

This downloads the repository's default branch, not a guaranteed stable release.
Read its release notes and installation scripts before running them with
administrator access. If you cannot approve that code yourself, use a trusted
administrator. Do not paste an unreviewed download command directly into a shell.

## 4. Run the installer and answer its questions

Stay in the `mediahub-platform` folder:

```sh
sudo sh install.sh
```

For LXC, the person preparing the guest must also provide the verified host
snapshot path through the installer's `--device-snapshot` option, as described
in [device evidence](deployment/devices.md). The ordinary command above is not
a complete LXC preparation procedure. Stop if this has not been arranged.

If asked for your Linux password, type it and press Enter. The terminal may show
no characters while you type; this is normal. Never publish that password.

The default installation folder is `/opt/mediahub`. It must not already exist.
The installer then asks the following questions in order:

| Question on screen | What to enter |
| --- | --- |
| `Server LAN IPv4 address:` | The MediaHub server's address from step 2. |
| `Existing mounted media disk path:` | The exact data-drive `TARGET` from step 2. |
| `Create a new MediaHub installation using this disk? Type YES:` | Check the displayed filesystem and UUID. Type `YES` only if they match your intended data drive. Otherwise press Enter to cancel. |
| `Movies [...]` | The full path of your movies folder on that data drive. |
| `Tv [...]` | The full path of your TV folder on that data drive. |
| `Other [...]` | The full path for other media on that data drive. |
| `Downloads [...]` | The full path for downloads on that data drive. |
| `Appdata [...]` | A separate folder for application settings on that data drive. |

Square brackets show a suggested path. Press Enter to accept it **only if it is
the path you want**. If your films already live elsewhere on the drive, enter
that existing folder; accepting a new empty folder does not move your films.
Paths must be absolute, have no spaces or symbolic links, and be inside the
approved data drive. These five folders must be separate, not inside each other.

The installer leaves existing folder permissions unchanged. It creates missing
chosen folders, an installation directory and a small storage-identification
file. It builds Docker images and starts MediaHub and its local Agent. Building
can take several minutes; wait for the final instructions, not just a build line.

**If installation fails:** stop. It may have created part of the new installation.
Do not remove `/opt/mediahub`, format the drive or change media permissions to
make a retry work. See the troubleshooting table below.

## 5. Trust this installation's public certificate

MediaHub uses HTTPS to protect your login. Before opening it, your computer must
trust this installation's public certificate. This is a one-time client setup,
not a reason to turn off browser security.

For the default installation, display the public certificate and its fingerprint
in the trusted server console:

```sh
sudo cat /opt/mediahub/trust/ca.pem
sudo openssl x509 -in /opt/mediahub/trust/ca.pem -noout -fingerprint -sha256
```

Transfer **only** that public `ca.pem` to your browser computer using a trusted
method. If using the console's clipboard, preserve the entire certificate block,
including `BEGIN CERTIFICATE` and `END CERTIFICATE`, in a plain-text certificate
file. Compare its SHA-256 fingerprint with the server before trusting it.
Do not copy anything from `authority`, any `.key` file or the Agent token.

On Windows, open the public certificate file, choose **Install Certificate**,
choose **Current User**, then **Place all certificates in the following store**
and **Trusted Root Certification Authorities**. Review the certificate before
finishing. If you do not have an import option, or the fingerprint cannot be
verified, stop rather than dismissing a browser warning.

On another operating system, use its certificate settings to import and trust
this verified public CA for your browser. Exact client steps vary; this guide
does not yet cover every browser/device. See [certificate safety and renewal](certificates.md).

## 6. Open MediaHub and create your account

1. Open the **exact HTTPS address printed by the installer** on a computer on
	the same local network. It has port `18765`, for example
	`https://192.168.1.50:18765`. Replace the example IP with yours.
2. Confirm there is no certificate warning. If there is, stop and check step 5.
3. No installation token is required. Keep the installation private: the first
	visitor can create the administrator on an unconfigured server.
4. Follow the browser wizard to create the administrator account and register
	storage. Use a unique password with at least **12 characters**, and enter it
	again in **Confirm password**.
5. If enabling two-factor authentication, scan its QR code with an authenticator
	app and keep the recovery codes somewhere safe before continuing. You can
	also enable it later in **Settings > Security**.
6. Install Plex if wanted, or leave that optional step for later. A Plex claim
	token connects the new server to your Plex account; it is separate from MediaHub setup.

**Success means:** you can sign in, open the dashboard and see your registered
storage. Plex may not be installed yet. No public internet access is configured.
You do not need Cloudflare to use MediaHub on your local network.

## 7. Add optional apps without guessing

Plex is supported through the setup wizard and its app page.

Seedbox currently needs a **separate prepared host**, a scoped Agent, approved
Downloads storage and verified HTTPS pairing. The core installer does not create
that host or automatically migrate an existing Seedbox. Only after those are
ready, choose **Apps > Seedbox > Install** and follow the Proton WireGuard and
torrent-client setup. See [Seedbox daily use](operations/seedbox-daily-use.md).
The [LXC trial plan](operations/seedbox-lxc-migration.md) is preparation guidance,
not a released automatic migration wizard.

Other catalog entries do not necessarily have working installers. Do not assume
every app is installed simply because its name appears in MediaHub.

## When something goes wrong

| What you see | What to do next |
| --- | --- |
| `Install prerequisite first` or `command not found` | Complete server preparation. Do not keep retrying the installer. |
| `Do not install on the Proxmox hypervisor` | Open the new guest's console, not the host Shell. |
| `Installation root must be a new absolute path` | `/opt/mediahub` already exists or the path is unsuitable. Inspect it before choosing another path; never delete it blindly. |
| `Storage must be its own mounted filesystem with a stable UUID` | Check the data-drive row from step 2. LXC/NFS/mergerfs setups need explicit compatibility review, not a guessed folder. |
| `Media and app-data folders must not overlap` | Choose distinct folders; do not use one as the parent of another. Inspect any newly created installation before retrying. |
| `Installation step failed` | Keep the partial installation and media intact. Record the stage and error; do not run cleanup commands. |
| Browser cannot connect | Verify the printed IP/port, that you are on the same LAN and the service status below. Do not expose the app publicly to fix LAN access. |
| Browser shows a certificate warning | Check the public CA import, fingerprint, exact IP and certificate expiry. Do not bypass the warning. |
| Plex or Seedbox cannot see files | Check the selected paths, mount identity and existing access permissions. Do not use recursive ownership changes as a shortcut. |

Read-only service status for the default installation:

```sh
sudo docker compose -f /opt/mediahub/compose.json ps
```

For a support request, include your OS, VM/LXC type, installation stage and exact
error. Remove passwords, tokens, private keys and personal information. Review
logs before sharing them. Never attach a full `.env` file or private backup.

## Persistence and recovery

The generated `compose.json` pins the exact built image IDs. The installation
also creates a root-owned trusted release-image policy, installed-version marker,
networkless transactional host updater and a systemd path watcher. Keep the
installation root and data filesystem persistent. Missing media storage blocks
Plex; missing Downloads storage blocks Seedbox. Before restarting a Docker host,
ensure its data mount is configured to start before Docker and guard against a
local-directory fallback. See the storage and Seedbox operations documents.

Read [Backups](backups.md), [Certificates](certificates.md) and
[Security](../SECURITY.md) before using the installation for irreplaceable data.
Host setup and remote Seedbox enrollment remain administrator tasks; the browser
does not provision a Proxmox VM or guess which disk is safe to mount.

## Updates

Plex update/check/rollback is available in MediaHub. Core and its local Agent can
be updated from the Updates page when the configured GitHub Release contains all
three bounded, digest-identified assets. Core verifies and stages the assets;
the root-owned, networkless helper then snapshots configuration, loads both exact
image digests, starts Agent and Core, verifies health, and restores the previous
configuration automatically if verification fails. Media mounts are never part
of that transaction.

Automatic checks are configurable from Settings and only create a notification.
They never install software. Every Core/Agent installation requires an explicit
administrator click. Seedbox/VPN image updates remain pinned and separately
coordinated because they must preserve fail-closed networking. Do not use an
unattended `latest` image replacement for the VPN namespace or app databases.
See [Platform updates](operations/platform-updates.md) for the trust model,
status files and rollback procedure.
