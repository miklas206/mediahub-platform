"""Bounded app configuration reset. Callers supply only verified host policy mounts."""

import os
import shutil
from pathlib import Path
from uuid import uuid4

from mediahub.errors import DomainError


def clear_directory(root, keep=()):
    root = Path(root)
    if not root.is_absolute() or root == Path(root.anchor) or root.resolve() != root:
        raise ValueError("Unsafe application configuration directory")
    if not root.exists():
        return
    if not root.is_dir():
        raise ValueError("Application configuration is not a directory")
    # Validate the complete tree before removing anything. Never cross a mount.
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names:
            child = Path(directory) / name
            if not child.is_symlink() and os.path.ismount(child):
                raise ValueError("Nested mount in application configuration")
    for child in root.iterdir():
        if child.name in keep:
            continue
        if child.is_symlink() or not child.is_dir():
            child.unlink()
        else:
            shutil.rmtree(child)


async def reset_mounts(request, image, mounts, *, keep=(), initialize_seed=False, uid=0, gid=0):
    """Use an existing pinned Python image without network, socket or media access."""
    name = "mediahub-config-reset-" + uuid4().hex
    code = Path(__file__).read_text().split("async def reset_mounts", 1)[0]
    # The helper image contains Python, but need not contain MediaHub modules.
    code = code.replace("from mediahub.errors import DomainError", "")
    code += f"\nos.setegid({gid}); os.seteuid({uid})\n"
    for mount in mounts:
        code += f"clear_directory({mount['Target']!r}, {keep if mount['Target'] == '/data' else ()!r})\n"
    if initialize_seed:
        code += "from mediaseed.client_init import initialize\ninitialize()\n"
    created = await request(
        "POST",
        "/containers/create?name=" + name,
        body={
            "Image": image,
            "User": "0:0",
            "Entrypoint": ["python", "-c", code],
            "Labels": {"org.mediahub.maintenance": "config-reset"},
            "HostConfig": {
                "Mounts": mounts,
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "SecurityOpt": ["no-new-privileges:true"],
                "Memory": 128 * 1024**2,
                "PidsLimit": 32,
                "RestartPolicy": {"Name": "no"},
            },
        },
    )
    identifier = created["Id"]
    try:
        await request("POST", "/containers/" + identifier + "/start")
        result = await request("POST", "/containers/" + identifier + "/wait?condition=not-running")
        if result.get("StatusCode") != 0:
            raise DomainError(
                "reset_failed",
                "App configuration reset failed; retry removal before reinstalling",
                409,
            )
    finally:
        await request("DELETE", "/containers/" + identifier + "?force=false&v=false")
