import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from hub_stack import hub_stack


def run(*arguments):
    subprocess.run([str(value) for value in arguments], check=True)


def migrate(root: Path, source: Path, apply: bool):
    if os.geteuid() != 0 or Path("/etc/pve").exists():
        raise ValueError("Run only as root inside the authorized beta guest")
    root = root.resolve(strict=True)
    source = source.resolve(strict=True)
    original = json.loads((root / "compose.json").read_text())
    updated, routing = hub_stack(original, root)
    print("Migration preserves existing data, runtime policies and storage mounts.")
    if not apply:
        print("Preflight passed. No installation changes made.")
        return
    tag = "mediahub-core:hub-migration-" + str(int(time.time()))
    run("docker", "build", "-f", source / "docker/Dockerfile", "-t", tag, source)
    run("docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", tag,
        "-c", "python -c 'import agent.main, mediahub.main' && docker compose version")
    run("docker", "pull", updated["services"]["proxy"]["image"])
    updated["services"]["core"]["image"] = tag
    updated["services"]["core"].pop("build", None)
    backup = root / ("hub-migration-backup-" + str(int(time.time())))
    backup.mkdir(mode=0o700)
    compose = root / "compose.json"
    updater = root / "platform_update_host.py"
    shutil.copy2(compose, backup / "compose.json")
    shutil.copy2(updater, backup / updater.name)
    stopped = False
    snapshot_ready = False
    try:
        run("systemctl", "stop", "mediahub-platform-update.path")
        if (root / "updates/request.json").exists():
            raise ValueError("An update request is pending; complete it before migration")
        run("docker", "compose", "-f", compose, "stop", "-t", "30", "core", "agent")
        stopped = True
        for name in ("data", "agent"):
            run("cp", "-a", root / name, backup / name)
        snapshot_ready = True
        (root / "hub-proxy.json").write_text(json.dumps(routing, indent=2))
        (root / "hub-proxy.json").chmod(0o644)
        compose.write_text(json.dumps(updated, indent=2))
        shutil.copy2(source / "scripts/platform_update_host.py", updater)
        updater.chmod(0o700)
        run("docker", "compose", "-f", compose, "up", "-d", "--no-deps", "--wait",
            "--wait-timeout", "180", "core", "proxy")
        print("Hub and proxy started; separate Agent remains stopped. Backup:", backup)
    except Exception:
        if stopped:
            run("docker", "compose", "-f", compose, "stop", "-t", "30", "core")
            if "proxy" in json.loads(compose.read_text())["services"]:
                run("docker", "compose", "-f", compose, "rm", "-s", "-f", "proxy")
            shutil.copy2(backup / "compose.json", compose)
            shutil.copy2(backup / updater.name, updater)
            if snapshot_ready:
                for name in ("data", "agent"):
                    failed = backup / (name + "-failed")
                    (root / name).rename(failed)
                    run("cp", "-a", backup / name, root / name)
            run("docker", "compose", "-f", compose, "up", "-d", "--no-deps", "core", "agent")
        raise
    finally:
        run("systemctl", "start", "mediahub-platform-update.path")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate the authorized beta without resetting data")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    migrate(arguments.root, arguments.source, arguments.apply)