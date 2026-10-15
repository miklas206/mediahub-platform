"""Export trusted, already provisioned Compose apps as private install recipes.

Run on the Docker host. No container is started, stopped, removed or modified.
This is operator preparation, never an HTTP-controlled command or Docker spec.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path


def prepare(policy_path, data_dir, container_data_dir, uid, gid):
    policy = json.loads(policy_path.read_text())
    destination = data_dir / "managed-install-recipes"
    destination.mkdir(mode=0o700, exist_ok=True)
    os.chown(destination, uid, gid)
    config_keys = {
        "User",
        "Env",
        "Cmd",
        "Entrypoint",
        "WorkingDir",
        "Labels",
        "ExposedPorts",
        "Healthcheck",
        "StopSignal",
    }
    host_keys = {
        "Binds",
        "Mounts",
        "NetworkMode",
        "PortBindings",
        "RestartPolicy",
        "AutoRemove",
        "VolumeDriver",
        "VolumesFrom",
        "CapAdd",
        "CapDrop",
        "Devices",
        "DeviceRequests",
        "Privileged",
        "ReadonlyRootfs",
        "SecurityOpt",
        "Tmpfs",
        "ShmSize",
        "PidsLimit",
        "Memory",
        "MemorySwap",
        "MemoryReservation",
        "NanoCpus",
        "CpuShares",
        "CpuQuota",
        "CpuPeriod",
        "CpusetCpus",
        "Ulimits",
        "LogConfig",
        "GroupAdd",
        "Dns",
        "DnsSearch",
        "DnsOptions",
        "ExtraHosts",
        "Init",
        "Runtime",
        "IpcMode",
        "PidMode",
        "UtsMode",
        "UsernsMode",
    }
    for package, entry in policy.items():
        assert package in {"org.mediahub.mediaseed", "org.mediahub.mediavpn"}
        ids = (
            subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    "label=com.docker.compose.project=" + entry["project"],
                ]
            )
            .decode()
            .split()
        )
        if not ids:
            raise RuntimeError("Prepare the approved Compose app before exporting its installer")
        containers = json.loads(subprocess.check_output(["docker", "inspect", *ids]))
        recipes = []
        for item in containers:
            # Initialization jobs stay completed; don't rerun them on reinstall.
            if item["Config"]["Labels"].get("com.docker.compose.service", "").endswith("-init"):
                continue
            spec = {k: v for k, v in item["Config"].items() if k in config_keys and v is not None}
            spec["Image"] = item["Image"]
            spec["HostConfig"] = {
                k: v for k, v in item["HostConfig"].items() if k in host_keys and v is not None
            }
            spec["NetworkingConfig"] = {
                "EndpointsConfig": {
                    network: {"Aliases": endpoint.get("Aliases") or []}
                    for network, endpoint in item["NetworkSettings"]["Networks"].items()
                }
            }
            recipes.append(
                {
                    "name": item["Name"].lstrip("/"),
                    "spec": spec,
                    "volumes": [m["Name"] for m in item["Mounts"] if m["Type"] == "volume"],
                    "networks": list(item["NetworkSettings"]["Networks"]),
                }
            )
        # Supporting services first; HTTP app health is verified after all start.
        recipes.sort(
            key=lambda item: item["spec"]["Labels"].get("com.docker.compose.service") == "app"
        )
        value = {
            "packageId": package,
            "installationId": entry["installationId"],
            "containers": recipes,
        }
        filename = package.rsplit(".", 1)[-1] + ".json"
        path = destination / filename
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream)
        os.chown(path, uid, gid)
        entry["installFile"] = str(container_data_dir / "managed-install-recipes" / filename)
        print(package, "approved services:", len(recipes))
    backup = policy_path.with_suffix(policy_path.suffix + ".before-install")
    if not backup.exists():
        backup.write_bytes(policy_path.read_bytes())
        backup.chmod(0o600)
    # Preserve an existing bind-mounted policy inode.
    policy_path.write_text(json.dumps(policy))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--container-data-dir", type=Path, default=Path("/data"))
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    args = parser.parse_args()
    prepare(args.policy, args.data_dir, args.container_data_dir, args.uid, args.gid)
