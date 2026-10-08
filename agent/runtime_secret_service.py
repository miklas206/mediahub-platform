"""Host-side service entrypoint. Install root-owned; configure paths via arguments."""

import ctypes
import json
import os
import resource
import subprocess
import sys
from pathlib import Path

from agent.ram_secrets import RuntimeSecrets


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:
        raise ValueError("Cannot disable process dumps")
    action, root_arg, uid_arg, gid_arg = sys.argv[1:]
    root, uid, gid = Path(root_arg), int(uid_arg), int(gid_arg)
    if not root.is_absolute() or root.resolve() != root or root == Path("/"):
        raise ValueError("Invalid runtime root")
    runtime = RuntimeSecrets(root)
    if action == "prepare":
        if len(Path("/proc/swaps").read_text().splitlines()) != 1:
            raise ValueError("Swap enabled")
        directory = runtime.directory
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("Unsafe runtime directory")
        if not os.path.ismount(directory):
            if any(directory.iterdir()):
                raise ValueError("Refusing to hide existing disk files")
            subprocess.run(
                [
                    "mount",
                    "-t",
                    "tmpfs",
                    "-o",
                    f"size=1m,mode=0700,uid={uid},gid={gid},noswap,noexec,nosuid,nodev",
                    "mediahub-secrets",
                    str(directory),
                ],
                check=True,
                capture_output=True,
            )
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    if action == "stage":
        # Migration only: do not change or remove source files here.
        config = runtime.store._read(root / "secrets/vpn.conf", 65536).decode()
        qbit = json.loads(runtime.store._read(root / "secrets/qbit.json", 4096))
        payload = json.dumps(
            {"vpnConfig": config, "webUsername": qbit["username"], "webPassword": qbit["password"]}
        ).encode()
        runtime.store.put("seedbox-runtime", payload)
        if runtime.store.get("seedbox-runtime") != payload:
            raise ValueError("Encrypted roundtrip failed")
    elif action == "prepare":
        runtime.materialize()
    elif action == "clear":
        runtime.clear()
    else:
        raise ValueError("Unsupported action")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never serialize exception objects, locals or decrypted input.
        print(
            "Runtime secret service blocked; inspect mount/permissions/trust prerequisites",
            file=sys.stderr,
        )
        sys.exit(1)
