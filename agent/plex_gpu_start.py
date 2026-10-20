"""Stage the matching official fallback in Plex RAM before each guarded start."""

import uuid

from mediahub.errors import DomainError


async def prepare_vendor(runtime, policy, plan):
    if not plan.get("container", {}).get("Labels", {}).get("org.mediahub.plex.gpu.revision"):
        return
    mounts = plan["container"]["HostConfig"]["Mounts"]
    config = next(m for m in mounts if m.get("Target") == "/config")
    if config.get("Type") != "volume" or config.get("ReadOnly"):
        raise DomainError("plex_gpu_ram_required", "Plex GPU requires its original writable RAM volume", 409)
    install = runtime.policy()
    name = policy.container + "-gpu-vendor-" + uuid.uuid4().hex[:12]
    code = """set -eu
root=/config/.mediahub-gpu-vendor
test ! -L "$root"
mkdir -p "$root"
chmod 700 "$root"
test ! -L "$root/vendor.tmp"
cp '/usr/lib/plexmediaserver/Plex Transcoder' "$root/vendor.tmp"
chmod 755 "$root/vendor.tmp"
mv -f "$root/vendor.tmp" "$root/Plex Transcoder"
if test -e "$root/lib" && ! test -L "$root/lib"; then exit 1; fi
ln -sfn /usr/lib/plexmediaserver/lib "$root/lib"
"""
    await runtime.request("POST", "/containers/create?name=" + name, body={
        "Image": policy.imageId, "User": f"{install.uid}:{install.gid}",
        "Entrypoint": ["/bin/sh", "-c", code], "Cmd": [],
        "Labels": {"org.mediahub.package": "org.mediahub.plex",
                   "org.mediahub.installation": policy.installationId,
                   "org.mediahub.plex.role": "gpu-vendor-preparation"},
        "Healthcheck": {"Test": ["NONE"]},
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True,
                       "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                       "Mounts": [config], "Memory": 128 * 1024**2,
                       "MemorySwap": 128 * 1024**2, "PidsLimit": 32,
                       "LogConfig": {"Type": "none", "Config": {}}},
    })
    try:
        await runtime.request("POST", f"/containers/{name}/start")
        result = await runtime.request("POST", f"/containers/{name}/wait")
        if result.get("StatusCode") != 0:
            raise DomainError("plex_gpu_vendor_failed", "The official Plex fallback could not be prepared", 409)
    finally:
        await runtime.remove_helper(name)


async def activate_relay(runtime, policy, plan):
    if not plan.get("container", {}).get("Labels", {}).get("org.mediahub.plex.gpu.revision"):
        return
    execution = await runtime.request("POST", f"/containers/{policy.container}/exec", body={
        "AttachStdout": False, "AttachStderr": False,
        "Cmd": ["/usr/lib/plexmediaserver/Plex Transcoder", "--mediahub-check"],
    })
    await runtime.request("POST", f"/exec/{execution['Id']}/start",
                          body={"Detach": False, "Tty": False}, binary=True)
    state = await runtime.request("GET", f"/exec/{execution['Id']}/json")
    if state.get("ExitCode") != 0:
        raise DomainError("plex_gpu_relay_failed", "The private Plex GPU connection could not start", 409)
