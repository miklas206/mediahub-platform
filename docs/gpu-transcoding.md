# Optional GPU access for Jellyfin

MediaHub's Proxmox guide lists driver-ready NVIDIA, Intel and AMD GPUs before
creating the guest. Paste the displayed GPU ID to share that GPU with the new
MediaHub LXC, or press Enter for CPU only. `MEDIAHUB_GPU=<exact ID>` can preselect
the GPU when running the guide. Selection does not detach the GPU from Proxmox
or assign it exclusively to a VM. GPUs bound to VFIO or missing a working host
driver must be prepared by the operator first.

The guide uses free `devN` slots, preserving the VPN TUN device and storage.
Intel/AMD use only the selected `/dev/dri/renderD*` node. NVIDIA uses its selected
GPU UUID, control/UVM nodes and a read-only copy of the matching host userspace
driver libraries. It installs NVIDIA Container Toolkit **inside the guest**;
it does not install a guest kernel module or replace the Proxmox driver. The
guest Docker daemon is restarted to register the runtime during installation.
The LXC remains unprivileged, and Jellyfin does not gain privileged mode.

After MediaHub setup, open **Jellyfin → Set up → GPU transcoding**. The list
contains only operator-approved GPUs on the selected host. GPU selection is
optional and is included in the installation review. Unavailable GPUs cannot
be selected. MediaHub retains device mappings, supplemental groups and NVIDIA
runtime requests when restarting or recreating the app for a VPN change.
Core source updates retain the existing host Compose configuration and GPU
policy; they do not grant GPU access to other apps automatically.

GPU access does not configure Jellyfin's administrator account or playback
preferences. After Jellyfin's initial setup, go to **Dashboard → Playback →
Transcoding**, choose **NVIDIA NVENC**, **Intel Quick Sync (QSV)** or **VAAPI** as
appropriate, enable only codecs supported by the GPU and save. For Intel/AMD,
the selected render path is `/dev/dri/renderD…` inside Jellyfin as well. Test a
video that actually needs transcoding and inspect its FFmpeg log; direct play
does not exercise the GPU. See the official [Jellyfin hardware acceleration
guide](https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/).

## Add a GPU to an existing MediaHub LXC

If an earlier setup failed with `GPU permissions denied` on NVIDIA capability
nodes, use **Repair GPU access after an earlier setup** in the guide (v0.5.34+),
or pass `--repair-video-access` to the reviewed `setup-existing-gpu.py` tool.
It reduces matching existing grants to the selected GPU, control and UVM nodes,
backs up policy/Compose/inventory, recreates only Core/Agent with `--no-deps`
and reruns verification. It does not stop the LXC or restart Docker, and does
not change permissions on administrative NVIDIA nodes. Do not rerun the initial
sharing step on an LXC that already has the GPU mappings.

From **v0.5.31**, open **Settings → General → GPU setup** (Danish:
**Indstillinger → Generelt → GPU-opsætning**). This resumable guide includes
the preparation command for your LXC, approved GPU detection and a real
hardware-encoding test with progress and output. The Proxmox host-access step
still runs in the node shell: MediaHub cannot grant itself new host devices.
After the LXC returns, refresh detection and run the test inside MediaHub.
The guide can open Jellyfin installation with the tested host and GPU selected.
It never changes an existing Jellyfin installation automatically.

A Core update cannot grant new Proxmox devices to an already-running LXC.
First update MediaHub to **v0.5.29 or newer**. The tool checks that its running
Core/Agent support GPU grants before stopping anything.
Use the guided tool from the **Proxmox node shell**. It verifies the selected
guest really contains MediaHub before proposing changes. Download the three
reviewable scripts into a new folder:

```sh
mkdir -m 700 /root/mediahub-gpu-tools
for script in setup-existing-gpu.py proxmox_gpu.py gpu_setup.py; do
  curl -fL "https://raw.githubusercontent.com/miklas206/mediahub-platform/v0.5.29/scripts/$script" -o "/root/mediahub-gpu-tools/$script"
done
python3 /root/mediahub-gpu-tools/setup-existing-gpu.py
```

The guide asks for the existing MediaHub LXC ID, lists driver-ready GPUs and
asks for the selected GPU ID. Type `GPU` to authorize the displayed downtime.
It shuts down only that guest, shares the approved devices, starts it again,
prepares NVIDIA Container Toolkit when needed, merges the GPU host policy and
recreates MediaHub's controllers. Existing app/media volumes are retained.
The command does not enable GPU transcoding in an already-installed Jellyfin.
Use the GPU choice during Jellyfin installation and its own transcoding settings.

It then checks all four layers:

1. Character devices exist and the selected GPU is approved in MediaHub's policy.
2. Running Core/Agent containers have those device mappings and can read/write
   the nodes as their ordinary container user, without a privileged/root test.
3. The NVIDIA runtime and exact GPU UUID are available when using NVIDIA.
4. Official Jellyfin FFmpeg encodes ten generated frames using **NVENC**, **QSV**
   or **VAAPI** in a disposable container. There is no CPU fallback, media
   mount, LAN access or app credential passed to this test container.

The guide prints success only after the encoder exits successfully. Failure
shows the failed layer and FFmpeg output when relevant. It retains the
configuration backups for inspection and never deletes app/media volumes.
The test downloads the official Jellyfin image and resolves its immutable image
ID before running it; this needs internet access and space in Docker's image
cache. Test containers are removed, including an owned leftover after timeout.

To repeat diagnostics later without changing GPU configuration or restarting
the guest, substitute the actual CTID:

```sh
python3 /root/mediahub-gpu-tools/setup-existing-gpu.py --ctid YOUR_CTID --test-only
```

For scripted setup, `--ctid`, `--gpu` and `--yes` explicitly authorize the same
stopping/restarting steps. `--root` supports a non-default MediaHub installation
folder. Existing/conflicting Proxmox GPU mappings are refused before shutdown;
use diagnostics and inspect those mappings instead of blindly replacing them.

### Manual preparation

Use the helpers below from a reviewed current **main** checkout. These are
operator commands; publishing this feature does not run them on your server.
Schedule downtime: stopping the LXC stops its apps, and NVIDIA preparation
restarts the guest Docker daemon.

On the **Proxmox host**, list available GPUs:

```sh
python3 scripts/proxmox_gpu.py --list
```

Stop the correct MediaHub guest, then substitute its CTID and an exact ID from
the list. Use a new inventory filename; existing files are deliberately refused.

```sh
pct shutdown YOUR_CTID
python3 scripts/proxmox_gpu.py --ctid YOUR_CTID --gpu 'EXACT_GPU_ID' --inventory /root/mediahub-gpus.json
pct start YOUR_CTID
pct push YOUR_CTID /root/mediahub-gpus.json /etc/mediahub-gpus.json --perms 0600
```

Inside the **MediaHub guest**, from a reviewed current main checkout:

```sh
python3 scripts/gpu_setup.py --inventory /etc/mediahub-gpus.json --root /opt/mediahub
docker compose -f /opt/mediahub/compose.json up -d
```

This merges the explicit grant and controller device mappings into the existing
policy and Compose file, with private `*.before-gpu` backups. It preserves
volumes, accounts, TLS, VPN settings and media. Review the backups/configuration
if a step fails; do not delete app data or recreate the entire MediaHub guest.
The helpers refuse conflicting mappings and a running Proxmox guest. An
already-installed Jellyfin keeps its previous CPU/GPU choice; this version's
selector is in the new-install flow. Reinstallation retains Jellyfin app data
and media, but still requires the normal explicit uninstall/install actions.

NVIDIA prerequisites: a working `nvidia-smi`, `/dev/nvidia-uvm` and matching
`libcuda`, `libnvidia-ml`, `libnvidia-encode` and `libnvcuvid` libraries on Proxmox.
If UVM is absent, prepare the host's `nvidia_uvm` module before using the guide.
The helper enables that module at host boot when no existing MediaHub module
configuration is present. Host NVIDIA driver upgrades require
refreshing the matching guest library bindings during maintenance; the helper
refuses to overwrite an existing NVIDIA binding automatically. Do not assume
an old staged driver remains compatible after a host driver upgrade.

For a native Linux Docker host, create a root-owned, non-writable GPU inventory
with the same approved device/UUID schema, run `gpu_setup.py`, then pass
`--gpu-policy /etc/mediahub-gpus.json` to `install_linux.py` for a new install.
NVIDIA requires an already working host driver. Windows Docker Desktop GPU
configuration and exclusive PCI passthrough to VMs are outside this guide.

Implementation validation uses isolated tests for discovery, device scoping,
plan confirmation, unavailable/revoked grants, VPN recreation and preservation
of existing storage/TUN mappings. Actual Proxmox passthrough and an FFmpeg GPU
transcode must still be verified on the target hardware after installation.
