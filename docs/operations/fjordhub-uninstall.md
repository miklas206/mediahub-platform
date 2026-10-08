# Remove a MediaHub-managed FjordHub installation

Open **App Store → FjordHub → Uninstall FjordHub**. This entry is also available
when the FjordHub integration is disconnected or installation reported failure.
It uses the latest recorded deployment and supports a dedicated Proxmox LXC
created by the MediaHub installer. Shared Debian hosts require manual cleanup.

Enter the recorded Proxmox host's SSH password, verify its fingerprint and choose
**Preview uninstall**. The preview lists the LXC ID, its system and app-data
disks, Docker containers, dedicated Proxmox accounts and preserved external bind
mounts. Confirm that all media you want to keep are on external storage, then
type the LXC ID to enable **Permanently uninstall FjordHub**. The password is not
persisted. Keep MediaHub running until the operation finishes.

The operation revalidates the preview, shuts down the guest, checks its storage
again and asks Proxmox to remove the guest and its two identified managed disks.
This removes FjordHub, its apps (including FjordFlix), Docker images/volumes,
source and configuration held on those disks. Dedicated MediaHub-created
Proxmox accounts are removed, as is the MediaHub integration whose URL matches
the guest URL recorded by the installer. Unrelated integrations are retained.

External bind source directories, including a shared MediaHub media drive, are
never traversed or deleted. Unknown managed/device disks, unused volumes,
snapshots, pending configuration, protection flags, changed ownership and
detected media on internal disks block removal. The media check examines common
Docker media destinations and FjordFlix's default media directory; it is not a
complete file-content classification. The operator must review the disk list
and confirm that no wanted media are stored on either disk. Media mounts created
inside the guest rather than through Proxmox bind mounts may require manual
review. A stopped guest must be started for the ownership/media inspection.

Recognized NVIDIA driver-file and GPU-device passthrough entries are preserved
and listed separately from media storage in the preview. Every repeated
`lxc.mount.entry` is checked; an unknown entry still blocks removal even if a
recognized GPU entry follows it. Standard kernel automounts are also accepted.

Proxmox must report the LXC and both disks gone before removal is reported as
complete. Failure remains **incomplete**, not success. If the LXC has already
been removed, another preview can recover the recorded cleanup plan and retry
account/connection cleanup. Remaining disks require manual inspection; the
operation does not force-delete them or prune unreferenced storage.

MediaHub installation history and a small recovery record under
`/var/lib/mediahub/fjordhub-uninstall/` on the Proxmox host are retained. No SSH
password or API token is stored in that record. Existing external backups and
shared storage are not part of removal.
