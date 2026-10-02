"""Explicit one-time Linux migration of the root-owned updater, not app deployment.

Run from a reviewed checkout. No containers are stopped; no media is touched.
The old helper and policy are retained for administrator rollback.
"""

import argparse
import json
import os
import re
from pathlib import Path

from platform_update_host import HostUpdater, fcntl


def enable(root, repository):
    if os.name != "posix" or os.geteuid() != 0 or fcntl is None:
        raise ValueError("Run on the MediaHub Linux host as root")
    if not root.is_absolute() or root == Path("/") or root.resolve() != root or root.is_symlink():
        raise ValueError("Use the existing bounded MediaHub installation root")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
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
        if (updater.updates / "request.json").exists():
            raise ValueError("Finish the pending update before migrating the helper")
        for name, value in (
            ("platform_update_host.py.before-source", previous_helper),
            ("update-policy.json.before-source", previous_policy),
        ):
            backup = root / name
            if not backup.exists():
                updater._atomic_text(backup, value)
        policy = json.loads(previous_policy)
        if policy.get("sourceRepository", repository) != repository:
            raise ValueError("Existing source trust must not be silently replaced")
        policy["sourceRepository"] = repository
        updater._atomic_json(updater.policy, policy, uid=0, gid=0)
        source = Path(__file__).with_name("platform_update_host.py").read_text()
        updater._atomic_text(helper, source)
        # BuildKit's client may fetch registry auth tokens as well as the daemon
        # pulling dependencies. No ports/listeners/firewall rules are opened.
        dropin = Path("/etc/systemd/system/mediahub-platform-update.service.d")
        dropin.mkdir(mode=0o755, exist_ok=True)
        updater._directory(dropin, owner=0)
        override = dropin / "source-build.conf"
        content = "[Service]\nRestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n"
        if override.exists() and updater._trusted_file(override).strip() != content.strip():
            raise ValueError("Refusing to replace an unrelated systemd override")
        updater._atomic_text(override, content)
        updater.command("systemctl", "daemon-reload", capture=False)
        # Advertise only after helper and explicit trust are installed. Public metadata only.
        # Existing source-built images already carry their exact Git revision.
        # Seed the marker for installations created before commit-based updates.
        if not updater.installed_source():
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
                "sourceBuild": True,
                "automaticFastUpdate": True,
                "mainBranchUpdates": True,
                "maintenance": True,
            },
            uid=0,
            gid=0,
        )
        capabilities.chmod(0o644)
    print("Source-build updater enabled. No services restarted and no media changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/mediahub"))
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    enable(args.root, args.repository)
