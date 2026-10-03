# Windows folder access

The optional **Windows folder access** app connects an existing SMB media share
to Windows Explorer. Install the connection profile from the App Store, follow
the Windows guide, and return to the app if access stops working.

## Guided setup

1. On the storage server or NAS, confirm that the intended media folders are
   already exposed through an authenticated SMB2/SMB3 share. Use a dedicated
   account with access to those folders. Check both share permissions and the
   underlying filesystem permissions. Keep SMB on the private network.
2. In MediaHub's App Store, open **Windows folder access**. Enter the server's
   private IPv4 address, the share name, an optional Windows/SMB username and a
   preferred drive letter. Save the connection. This registers the MediaHub app;
   it does not install Samba, create a server share or change folder permissions.
3. On the Windows PC, open File Explorer, choose **This PC**, then **Map network
   drive**. Select an unused drive letter and paste the UNC path shown in MediaHub.
   Enable reconnecting at sign-in. If the share uses another account, select the
   option to connect using different credentials. Enter the share account's
   password in Windows, not in MediaHub.
4. Open the mapped drive and the intended media folder. The optional downloaded
   connection script performs the mapping with a local credential prompt. It
   refuses to replace an occupied drive letter or disconnect unrelated shares.

Microsoft's [network file sharing guide](https://support.microsoft.com/en-us/windows/experience/connectivity-networking/file-sharing-over-a-network-in-windows)
documents the File Explorer mapping flow. Server administrators can use the
official [Samba configuration reference](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html)
for share access, protocol settings and capacity reporting.

## Troubleshooting

The app separates two perspectives:

- **MediaHub Core check:** a bounded TCP connection to the configured private
  server on port 445. A successful connection only establishes that this port
  responds from Core. It does not authenticate to the share, verify that the
  share exists, or prove that a Windows PC can reach it.
- **Windows diagnostic tool:** run the downloaded script on the affected PC. It
  checks that PC's connection and mapping, reports access results and suggests
  the next step. The diagnostic run does not modify mappings or media files.

Use the symptoms shown by the tool and the app:

| Symptom | What to check next |
| --- | --- |
| Server/port unavailable, error 53 | Confirm the server is running, its IP has not changed, and this PC is on the intended LAN. Inspect the server's SMB service and network rules. |
| Share not found, error 67 | Compare the saved share name with the name published by the NAS/Samba server. A Linux folder path is not the share name. |
| Access denied, error 5 | Verify the dedicated share username and password, then both share and filesystem permissions. A MediaHub login is not automatically a Samba login. |
| Multiple credentials, error 1219 | Windows may already have a connection to the same server under another identity. Close files on that server and resolve that specific connection in Windows. Do not disconnect all network drives. |
| Drive letter occupied | Choose another drive letter. Do not overwrite a local disk or another mapped share. |
| Disconnected after sign-in | Reconnect the expected mapping after the network is available. If the server address changed, update the saved profile and map it again. |
| Unexpectedly little free space | Compare free space at the share root with the actual media subfolder and storage pool. A Samba share containing mounted media can accidentally report its system disk. The administrator should verify mounts and the share's `dfree command`; do not bypass missing mounts. |

The first version accepts private IPv4 addresses on the home network. Access
away from home requires a separately configured private VPN with a route to that
network. The Seedbox's outgoing torrent VPN does not itself provide inbound
Windows access. Do not publish SMB directly through an Internet router.

## Running downloaded helpers

Review the script, then run it in a normal Windows PowerShell session under the
same Windows account that uses File Explorer. Mapping from an elevated session
can put the drive in a different logon context. The generated files use UTF-8
with a BOM for Windows PowerShell 5.1.

If the PC's script policy blocks a helper, use the manual File Explorer guide
and the app's troubleshooting steps, or follow the organization's approved
script policy. The helpers do not change execution policy, disable a firewall,
enable SMB1, enable guest access, or store a password in MediaHub.

## Storage and removal

MediaHub stores only the private server address, share name, optional username
and preferred drive letter. The Windows share password stays in the Windows
credential prompt/session. Downloaded scripts contain the saved connection
details but no password. Removing this app removes MediaHub's saved connection
and monitoring; it leaves server shares, media files and Windows drive mappings
in place.


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
