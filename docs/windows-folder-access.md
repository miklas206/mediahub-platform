# Storage and Windows network drives

MediaHub 0.6.51 adds **Settings → Storage** (Danish: **Indstillinger → Lager**)
for administrators. It mounts NAS shares on the Linux Docker host and creates
SMB3 Windows shares from selected approved storage folders. It does not format,
move or delete media, change existing filesystem permissions, or automatically
replace running apps' storage mappings.

## Connect a NAS

1. Open **Settings → Storage** and wait for automatic server preparation. If the
   controller is unavailable, the page explains the prerequisite and offers
   **Prepare server**. A supported Linux installation with the root host updater
   and Docker is required.
2. Enter a label, the NAS's private IPv4 address, its existing SMB share name,
   NAS username and NAS password. Use the share name alone, not a Linux path or
   complete UNC path. For example, the share in `\\192.168.1.60\Media` is `Media`.
3. Leave **Read-only access** enabled for browsing. Disable it only if the
   connection needs write access and the NAS account permits it.
4. Choose **Connect NAS**. Confirm that its status becomes Connected. A failed
   mount remains disconnected and can be retried using Reconnect. Remove and
   recreate the connection if its credentials or source need changing.
5. Saved enabled NAS connections reconnect at host startup. Disconnect preserves
   files and the saved login. Remove disconnects and forgets the saved login.
   Remove attached Windows shares first. Busy mounts are never force-unmounted.

The first version supports SMB3.1.1 NAS mounts. It installs `cifs-utils`
automatically on the supported Debian/Ubuntu host. The kernel must allow CIFS
mounting. In an LXC, Proxmox may require an explicit host-side grant or an
administrator-provisioned mount; MediaHub does not weaken the container's
security settings. NFS and DNS-based NAS addresses are not supported by this form.

NAS mounts live at fixed `<installation-root>/network-storage/<id>` targets.
The server leaves an unmounted target inaccessible instead of writing to the
system disk. Credentials stay in root-only files outside Core's data mount and
are never returned to the browser, placed in command arguments, or stored in Git.
App attachment remains a separate approved configuration step; this feature does
not attach newly mounted NAS storage to existing running apps.

## Share a folder with Windows

1. Under **Share with Windows**, choose a connected storage folder. From 0.6.52,
   **Main folder (all subfolders)** shares the verified media mount itself,
   including Movies, TV, Downloads and other folders below that mount. Separate
   folder shares remain available. This does not include separate NAS mounts.
2. Enter a unique share name containing letters, digits, hyphens or underscores.
3. Choose read-only or write access. Sharing cannot make a read-only NAS writable,
   and existing filesystem permissions still apply.
4. For the first share, create a Windows sharing password of at least 12
   characters. All managed shares use the separate SMB account `mediahub`.
5. Choose **Create Windows share**, then expand **Connect this folder in Windows**.
   The guide shows this server's actual UNC path.
6. On your Windows PC, press **Windows + E**, right-click **This PC**, and choose
   **Map network drive**. Select a free drive letter and paste the displayed UNC
   path. Select **Reconnect at sign-in** and **Connect using different credentials**.
7. Enter `mediahub` and the Windows sharing password. This password is separate
   from both your MediaHub account and your NAS login.

Removing a share closes its Windows connections and preserves the files.
Changing the sharing password affects all managed shares; reconnect mapped
Windows drives using the new password. It does not change NAS or MediaHub login.

The isolated managed Samba container publishes TCP 445 only on the configured
private LAN address. It does not enable SMB1, guest access, router forwarding or
an Internet domain. A running service is not proof that a Windows PC has verified
access; follow the guide from the actual PC.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| Server preparation pending | Wait for app preparation, then use Prepare server. Other host updates take priority. |
| NAS mount fails | Check the NAS share/login and the Linux host's CIFS mount permission. An LXC may need Proxmox administrator preparation. |
| Storage disconnected | Reconnect its disk/NAS. MediaHub refuses to substitute a system-disk directory. |
| Windows share will not start | Confirm that the LAN address exists and port 445 is free; another SMB service is not stopped or replaced. |
| Windows access denied | Use the separate SMB account/password; check existing filesystem permissions. |
| Windows error 1219 | Close this server's open files and resolve its specific old session in Credential Manager. Do not disconnect all network drives. |
| NAS cannot disconnect | Remove its managed Windows shares and stop applications using the mount. Never force an active mount offline. |

## Installation, upgrade and rollback

Fresh installation stages the reviewed host controller and installs its systemd
service. Existing installations stage the same code during app preparation and
ask the existing root updater to install or refresh the controller. The request
cannot replace an in-flight update. Server-side authentication, administrator
role, CSRF and local socket peer identity are checked before storage mutations.
No new Core database migration is needed. State lives in root-only
`storage-private/state.json`; Windows authentication uses Samba's private passdb.
Existing independent app storage, login, media mounts and stopped intent remain
unchanged. Failed Windows share replacement restores the previous owned service.

Rolling Core back does not delete storage state or media. Before removing the
host feature, remove its Windows shares and disconnect its NAS mounts through
Storage. Stop only `mediahub-storage.service` and the owned
`mediahub-storage-smb` service if manual administrator recovery is necessary;
do not prune Docker or delete media. NAS mounts can be busy even after Core stops.

Validation covers synthetic fresh/older configurations, repeated preparation,
missing mounts, authorization, secret handling, rollback, desktop/mobile browser
flows and an isolated SMB server with test files. No real NAS credential, media
folder, physical reboot or actual Windows drive mapping is included in those tests.

References: [Microsoft Windows drive mapping](https://support.microsoft.com/en-us/windows/experience/connectivity-networking/file-sharing-over-a-network-in-windows),
[Samba configuration](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html),
[Samba account commands](https://www.samba.org/samba/docs/current/man-html/smbpasswd.8.html),
[CIFS mounting](https://man7.org/linux/man-pages/man8/mount.cifs.8.html).

## Legacy connection profiles

The previous Windows folder-access API only saved connection details and
provided local PowerShell helpers; it never created SMB servers. Existing
profiles and their recovery tools remain compatible. The new Storage tab manages
its own server shares and does not silently import or alter legacy credentials.

## Forgotten SMB password

The **Reset SMB password** card downloads `reset-password.ps1`. This tool is for
an existing local account on a Linux/Samba server with SSH. It requires a separate
server administrator login with root or sudo rights; the old SMB password is not
required. NAS and Windows server accounts must be reset using their own account
administration. If the administrator login is also lost, use server recovery.

Run the downloaded file from normal Windows PowerShell after reviewing it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\reset-password.ps1"
```

Enter the local Samba account and the SSH administrator account, confirm the
selected server/account, and verify the SSH host fingerprint on first connection.
SSH and sudo ask for administrator authentication; `New SMB password` asks for
the new share password twice in the same terminal. MediaHub receives no password.
The tool uses Windows OpenSSH Client and checks that the Samba account exists.
It stops if Unix password synchronization is enabled or cannot be verified.
It neither creates accounts nor changes shares, folder permissions or media.

After success, close open files on the affected mapped drive and disconnect only
that drive in File Explorer. Remove an outdated Windows credential for that
server in Credential Manager if present. Then reconnect with the SMB account and
new password. Other devices may need the new password on their next sign-in.
Existing sessions are not forcibly disconnected by the reset tool.

Downloads are restricted to MediaHub administrators. Generating or downloading
the file does not contact the server or perform a password reset.


### SSH accepts public keys only

`Permission denied (publickey)` occurs before any Samba command runs. Use an
existing private SSH key authorized for the server administrator account:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\reset-password.ps1" -IdentityFile "$env:USERPROFILE\.ssh\id_ed25519"
```

Replace the example key path with the real one. The private key stays on the PC;
it is not uploaded to MediaHub. Do not enable password authentication to work
around this error. If no authorized key is available, open the Samba server's
console (for example its VM console in Proxmox) and log in as a server admin.
Inside that server, run `sudo pdbedit -L` to identify the local SMB account and
`sudo smbpasswd ACCOUNT` to reset that existing account. A root session can omit
sudo. These commands belong inside the Samba server, not on the Proxmox host.
The SMB account may differ from the Windows display name or SSH administrator.
