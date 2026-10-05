"""Explicit Linux migration/refresh of the root-owned updater, not app deployment.

Run from a reviewed checkout. --refresh-helper preserves existing repository trust;
--repository deliberately enables source updates. Core updates only replace images,
so existing hosts must refresh this helper separately to enable new host operations.
No containers are stopped; no media is touched. Backups support administrator rollback.
"""

import argparse
import json
import os
import re
from pathlib import Path

if __package__:
    from .platform_update_host import HostUpdater, fcntl
else:
    from platform_update_host import HostUpdater, fcntl

SYSTEMD_DROPIN = Path("/etc/systemd/system/mediahub-platform-update.service.d")


def enable(root, repository=None):
    if os.name != "posix" or os.geteuid() != 0 or fcntl is None:
        raise ValueError("Run on the MediaHub Linux host as root")
    if not root.is_absolute() or root == Path("/") or root.resolve() != root or root.is_symlink():
        raise ValueError("Use the existing bounded MediaHub installation root")
    if repository is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Use a GitHub owner/repository")
    updater = HostUpdater(root)
    updater._directory(root, owner=0)
    updater._directory(updater.updates, owner=10001)
    updater._trusted_file(updater.compose, 2 * 1024**2)
    updater._trusted_policy()
    helper = root / "platform_update_host.py"
    previous_helper = updater._trusted_file(helper, 1024**2)
    previous_policy = updater._trusted_file(updater.policy)
    with (updater.updates / "host-updater.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (updater.updates / "request.json").exists() or any(
            updater.updates.glob("maintenance-running-*.json")
        ):
            raise ValueError("Finish the pending update or maintenance before refreshing the helper")
        policy = json.loads(previous_policy)
        if repository is not None:
            if policy.get("sourceRepository", repository) != repository:
                raise ValueError("Existing source trust must not be silently replaced")
            policy["sourceRepository"] = repository
        repository = policy.get("sourceRepository")
        if repository is not None and (
            not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        ):
            raise ValueError("Invalid existing source repository trust")
        source = Path(__file__).with_name("platform_update_host.py").read_text()
        if repository is not None:
            # Only source-enabled hosts need BuildKit's registry networking.
            SYSTEMD_DROPIN.mkdir(mode=0o755, exist_ok=True)
            updater._directory(SYSTEMD_DROPIN, owner=0)
            override = SYSTEMD_DROPIN / "source-build.conf"
            content = "[Service]\nRestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n"
            if override.exists() and updater._trusted_file(override).strip() != content.strip():
                raise ValueError("Refusing to replace an unrelated systemd override")
        for name, value in (
            ("platform_update_host.py.before-source", previous_helper),
            ("update-policy.json.before-source", previous_policy),
        ):
            backup = root / name
            if not backup.exists():
                updater._atomic_text(backup, value)
        if policy != json.loads(previous_policy):
            updater._atomic_json(updater.policy, policy, uid=0, gid=0)
        updater._atomic_text(helper, source)
        if repository is not None:
            updater._atomic_text(override, content)
            updater.command("systemctl", "daemon-reload", capture=False)
        # Advertise only after helper and explicit trust are installed. Public metadata only.
        # Existing source-built images already carry their exact Git revision.
        # Seed the marker for installations created before commit-based updates.
        if repository is not None and not updater.installed_source():
            core_id = updater._compose_command("ps", "-q", "core")
            if core_id:
                revision = updater.command(
                    "docker",
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                    core_id,
                )
                if re.fullmatch(r"[a-f0-9]{40}", revision):
                    updater.write_installed_source({"repository": repository, "commit": revision})
        capabilities = updater.updates / "host-capabilities.json"
        updater._atomic_json(
            capabilities,
            {
                "sourceBuild": repository is not None,
                "automaticFastUpdate": repository is not None,
                "mainBranchUpdates": repository is not None,
                "maintenance": True,
            },
            uid=0,
            gid=0,
        )
        capabilities.chmod(0o644)
    print("Host updater refreshed. No services restarted and no media changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/mediahub"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--repository", help="Explicitly enable source updates from this repository")
    mode.add_argument(
        "--refresh-helper", action="store_true", help="Refresh helper while preserving existing trust"
    )
    args = parser.parse_args()
    enable(args.root, args.repository)
