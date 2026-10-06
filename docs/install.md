# Guided MediaHub Installation

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
3. In the server console, run the setup-token command printed by the installer.
	For the default installation it is:

```sh
sudo docker compose -f /opt/mediahub/compose.json exec core mediahub bootstrap-token
```

4. Enter that one-time setup token in MediaHub's setup page. Treat it like a
	password; do not post it in an issue or screenshot.
5. Follow the browser wizard to create the administrator account and register
	storage. Use a unique password with at least **12 characters**, and enter it
	again in **Confirm password**.
6. If enabling two-factor authentication, scan its QR code with an authenticator
	app and keep the recovery codes somewhere safe before continuing. You can
	also enable it later in **Settings > Security**.
7. Install Plex if wanted, or leave that optional step for later. A Plex claim
	token connects the new server to your Plex account; it is not the setup token.

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
