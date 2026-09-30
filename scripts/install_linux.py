"""Interactive, new-install-only Linux bootstrap. Existing media is never modified.

Requires a Docker host with Compose, Python 3, OpenSSL, systemd and an already
mounted data disk. Does not install a hypervisor, format disks, mount storage,
open firewalls or change an existing deployment.
"""

import argparse
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]


def safe_path(value):
    """Keep generated mount/systemd configuration unambiguous; no interpolation."""
    path = Path(value)
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path)):
        raise ValueError(
            "Use an absolute path containing letters, digits, dots, dashes or underscores"
        )
    if path.resolve() != path or path.is_symlink():
        raise ValueError("Paths must not contain symlinks or parent traversal")
    return path


def command(*args, capture=True):
    return (
        subprocess.run(
            list(map(str, args)),
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        ).stdout
        or ""
    )


def new_file(path, content, mode=0o600, uid=0, gid=0):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    os.chown(path, uid, gid)


def choose_directory(label, default, root):
    raw = input(f"{label} [{default}]: ").strip() or str(default)
    path = safe_path(raw)
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
        raise ValueError("Use an absolute path without symbolic links")
    if root not in path.parents or path == root:
        raise ValueError("Choose a subdirectory of the approved data disk")
    if not path.exists():
        path.mkdir(mode=0o2770, parents=False)
        os.chown(path, 1000, 1000)
        path.chmod(0o2770)
    elif not path.is_dir():
        raise ValueError("Storage must be a directory")
    # Never chmod/chown existing folders.
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/opt/mediahub")
    parser.add_argument("--lan-ip")
    parser.add_argument("--storage")
    parser.add_argument(
        "--release-image-prefix",
        default="ghcr.io/miklas206/mediahub-platform",
        help="Trusted lowercase GHCR prefix for Core and Agent release images",
    )
    parser.add_argument(
        "--device-snapshot", help="Optional existing host-generated metadata file for an LXC"
    )
    parser.add_argument("--source-repository", help="Trusted GitHub owner/repo for source updates")
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Run on the new Linux Docker host as root")
    if Path("/etc/pve").exists():
        raise ValueError("Do not install on the Proxmox hypervisor. Use a new guest")
    print(
        "MediaHub standard minimum: 6 vCPU and 16 GiB RAM (16384 MiB). "
        "Allocate these to this VM/LXC before installation. "
        "This installer does not resize the guest or existing app limits."
    )
    image_prefix = args.release_image_prefix
    if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+", image_prefix):
        raise ValueError("Release image prefix must be a lowercase GHCR repository")
    source_repository = args.source_repository or image_prefix.removeprefix("ghcr.io/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source_repository):
        raise ValueError("Source repository must be a GitHub owner/repository")
    project_version = tomllib.loads((SOURCE / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", project_version):
        raise ValueError("Installer requires a stable semantic project version")
    for executable in ["docker", "openssl", "findmnt", "systemctl", "lsblk"]:
        if not shutil.which(executable):
            raise ValueError(f"Install prerequisite first: {executable}")
    command("docker", "compose", "version")
    if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        raise ValueError("A cgroup v2 host is required for swap and resource limits")
    root = safe_path(args.root)
    if not root.is_absolute() or root.exists() or root.is_symlink() or root.resolve() != root:
        raise ValueError("Installation root must be a new absolute path without symlinks")
    address = args.lan_ip or input("Server LAN IPv4 address: ").strip()
    ip = ipaddress.ip_address(address)
    if (
        ip.version != 4
        or not ip.is_private
        or ip.is_loopback
        or ip.is_unspecified
        or ip.is_link_local
    ):
        raise ValueError("Use the private LAN IPv4 of this host")
    storage = safe_path(args.storage or input("Existing mounted media disk path: ").strip())
    if (
        not storage.is_absolute()
        or storage.resolve() != storage
        or not storage.is_dir()
        or storage == Path("/")
    ):
        raise ValueError("Choose an existing non-root data mount")
    mount = json.loads(
        command("findmnt", "--json", "--target", storage, "--output", "TARGET,SOURCE,FSTYPE,UUID")
    )["filesystems"][0]
    if Path(mount["target"]) != storage or not mount.get("uuid"):
        raise ValueError("Storage must be its own mounted filesystem with a stable UUID")
    print(
        f"Data filesystem: {mount['fstype']}; UUID: {mount['uuid']}. No formatting or media migration."
    )
    if input("Create a new MediaHub installation using this disk? Type YES: ").strip() != "YES":
        return
    # All persistent writes below target this new installation or new subfolders.
    root.mkdir(mode=0o700)
    for name in [
        "data",
        "agent",
        "tls-core",
        "tls-agent",
        "trust",
        "authority",
        "evidence",
        "updates",
    ]:
        path = root / name
        path.mkdir(mode=0o700)
        os.chown(path, 10001, 10001)
    update_staging = root / "updates" / "staging"
    update_staging.mkdir(mode=0o700)
    os.chown(update_staging, 10001, 10001)
    (root / "update-backups").mkdir(mode=0o700)
    folders = {
        kind: choose_directory(kind.replace("_", " ").title(), storage / kind, storage)
        for kind in ["movies", "tv", "other", "downloads", "appdata"]
    }
    if len(set(folders.values())) != len(folders) or any(
        a in b.parents for a in folders.values() for b in folders.values() if a != b
    ):
        raise ValueError("Media and app-data folders must not overlap")
    marker = storage / (".mediahub-" + secrets.token_hex(8))
    new_file(marker, mount["uuid"], 0o444)
    print("Building reviewed source images. This can take several minutes.")
    command(
        "docker",
        "build",
        "-f",
        SOURCE / "docker/Agent.Dockerfile",
        "-t",
        "mediahub-agent:local",
        SOURCE,
        capture=False,
    )
    command(
        "docker",
        "build",
        "-f",
        SOURCE / "docker/Dockerfile",
        "-t",
        "mediahub-core:local",
        SOURCE,
        capture=False,
    )
    agent_image = command(
        "docker", "image", "inspect", "--format", "{{.Id}}", "mediahub-agent:local"
    ).strip()
    core_image = command(
        "docker", "image", "inspect", "--format", "{{.Id}}", "mediahub-core:local"
    ).strip()
    authority = root / "authority"
    ca_key = authority / "ca.key"
    ca = authority / "ca.pem"
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:3072",
        "-nodes",
        "-days",
        "3650",
        "-subj",
        "/CN=MediaHub Local CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout",
        ca_key,
        "-out",
        ca,
    )
    ca_key.chmod(0o600)
    os.chown(authority, 0, 0)
    for role, san in [
        ("core", f"IP:{address},IP:127.0.0.1,DNS:core"),
        ("agent", "DNS:agent,IP:127.0.0.1"),
    ]:
        folder = root / ("tls-" + role)
        key = folder / "server.key"
        cert = folder / "server.pem"
        csr = authority / (role + ".csr")
        ext = authority / (role + ".ext")
        new_file(
            ext,
            "subjectAltName="
            + san
            + "\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n",
        )
        command(
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:3072",
            "-nodes",
            "-subj",
            "/CN=" + role,
            "-keyout",
            key,
            "-out",
            csr,
        )
        command(
            "openssl",
            "x509",
            "-req",
            "-in",
            csr,
            "-CA",
            ca,
            "-CAkey",
            ca_key,
            "-CAcreateserial",
            "-days",
            "90",
            "-extfile",
            ext,
            "-out",
            cert,
        )
        for p in [key, cert]:
            p.chmod(0o600)
            os.chown(p, 10001, 10001)
    new_file(root / "trust/ca.pem", ca.read_text(), 0o644, 10001, 10001)
    new_file(root / "agent/token", secrets.token_urlsafe(48), 0o600, 10001, 10001)
    evidence = (
        safe_path(args.device_snapshot) if args.device_snapshot else root / "evidence/snapshot.json"
    )
    if args.device_snapshot:
        if not evidence.is_file():
            raise ValueError("Host device snapshot missing")
    else:
        shutil.copyfile(SOURCE / "agent/device_snapshot.py", root / "device_snapshot.py")
        # The collector writes only sanitized host metadata, never mounts a disk.
        service = "mediahub-" + secrets.token_hex(4)
        new_file(root / "evidence-service", service + "\n")
        collector = [sys.executable, str(root / "device_snapshot.py"), str(evidence)]
        command(*collector)
        unit = (
            "[Unit]\nDescription=MediaHub read-only host metadata\n[Service]\nType=oneshot\nExecStart="
            + " ".join(collector)
            + "\nExecStartPost=/bin/chown 10001:10001 "
            + str(evidence)
            + "\n"
        )
        new_file(Path("/etc/systemd/system") / (service + ".service"), unit, 0o644)
        new_file(
            Path("/etc/systemd/system") / (service + ".timer"),
            "[Timer]\nOnBootSec=5\nOnUnitActiveSec=10\n[Install]\nWantedBy=timers.target\n",
            0o644,
        )
        command("systemctl", "daemon-reload")
        command("systemctl", "enable", "--now", service + ".timer")
        os.chown(evidence, 10001, 10001)
    plex_image = "lscr.io/linuxserver/plex@sha256:be083133dfe001b6caed5a321720e6db9d38fdde1ea8f9d29340d40057a7fa53"
    command("docker", "pull", plex_image, capture=False)
    policy = {
        "hostId": "local",
        "bindAddress": address,
        "image": plex_image,
        "initImage": agent_image,
        "uid": 1000,
        "gid": 1000,
        "tmpfsNoSwap": False,
        "controlNetwork": "mediahub-platform_control",
        "hostMountSnapshot": "/host-evidence/" + evidence.name,
        "requiredFilesystemUuids": {str(storage): mount["uuid"]},
        "storageMarkers": {str(marker): mount["uuid"]},
        "storage": {
            kind: {"label": kind.title(), "kind": kind, "path": str(path)}
            for kind, path in folders.items()
            if kind != "downloads"
        },
    }
    new_file(root / "agent/plex-install.json", json.dumps(policy), 0o600, 10001, 10001)
    common = {
        "restart": "unless-stopped",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "ulimits": {"core": {"soft": 0, "hard": 0}},
        "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
    }
    agent = {
        **common,
        "image": agent_image,
        "mem_limit": "512m",
        "memswap_limit": "512m",
        "networks": ["control"],
        "group_add": [str(Path("/var/run/docker.sock").stat().st_gid), "1000", "10001"],
        "volumes": [
            f"{root}/agent:/state",
            f"{root}/tls-agent:/tls:ro",
            f"{root}/trust:/trust:ro",
            f"{storage}:{storage}",
            f"{evidence.parent}:/host-evidence:ro",
            "/var/run/docker.sock:/var/run/docker.sock:ro",
        ],
        "environment": {
            "MEDIAHUB_AGENT_STATE_DIR": "/state",
            "MEDIAHUB_AGENT_TOKEN_FILE": "/state/token",
            "MEDIAHUB_AGENT_LISTEN_HOST": "0.0.0.0",
            "MEDIAHUB_AGENT_TLS_CERT": "/tls/server.pem",
            "MEDIAHUB_AGENT_TLS_KEY": "/tls/server.key",
            "MEDIAHUB_AGENT_DOCKER_SOCKET": "/var/run/docker.sock",
            "MEDIAHUB_AGENT_STORAGE_ROOTS": json.dumps([str(storage)]),
            "MEDIAHUB_AGENT_CREATE_ENABLED": "true",
            "MEDIAHUB_AGENT_DEVICE_SNAPSHOT_FILE": "/host-evidence/" + evidence.name,
            "MEDIAHUB_AGENT_PLEX_INSTALL_POLICY_FILE": "/state/plex-install.json",
            "MEDIAHUB_AGENT_PLEX_POLICY_FILE": "/state/plex-managed.json",
        },
        "healthcheck": {"disable": True},
    }
    core = {
        **common,
        "image": core_image,
        "mem_limit": "512m",
        "memswap_limit": "512m",
        "networks": ["control", "lan"],
        "ports": [f"{address}:18765:18765"],
        "group_add": ["1000"],
        "volumes": [
            f"{root}/data:/data",
            f"{root}/updates:/updates",
            f"{root}/agent/token:/agent-token:ro",
            f"{root}/tls-core:/tls:ro",
            f"{root}/trust:/trust:ro",
            f"{storage}:{storage}:ro",
        ],
        "environment": {
            "MEDIAHUB_AGENT_URL": "https://agent:18767",
            "MEDIAHUB_AGENT_TOKEN_FILE": "/agent-token",
            "MEDIAHUB_AGENT_CA_FILE": "/trust/ca.pem",
            "MEDIAHUB_BASE_URL": f"https://{address}:18765",
            "MEDIAHUB_ALLOWED_ORIGINS": json.dumps([f"https://{address}:18765"]),
            "MEDIAHUB_BROWSER_TLS_CERT": "/tls/server.pem",
            "MEDIAHUB_BROWSER_TLS_KEY": "/tls/server.key",
            "MEDIAHUB_STORAGE_ROOTS": json.dumps([str(storage)]),
            "MEDIAHUB_SEEDBOX_REQUIRES_REMOTE_HOST": "true",
            "MEDIAHUB_PLATFORM_UPDATE_SPOOL": "/updates",
        },
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                "import ssl,urllib.request;urllib.request.urlopen('https://127.0.0.1:18765/api/health',context=ssl.create_default_context(cafile='/trust/ca.pem'),timeout=4)",
            ],
            "interval": "30s",
            "timeout": "5s",
        },
    }
    compose = {
        "name": "mediahub-platform",
        "services": {"core": core, "agent": agent},
        "networks": {"control": {"internal": True}, "lan": {}},
    }
    new_file(root / "compose.json", json.dumps(compose, indent=2))
    new_file(root / "installed-version", project_version + "\n", 0o600)
    new_file(
        root / "update-policy.json",
        json.dumps(
            {
                "coreRepository": image_prefix + "-core",
                "agentRepository": image_prefix + "-agent",
                "sourceRepository": source_repository,
            },
            indent=2,
        )
        + "\n",
        0o600,
    )
    updater_script = root / "platform_update_host.py"
    new_file(
        updater_script,
        (SOURCE / "scripts/platform_update_host.py").read_text(encoding="utf-8"),
        0o700,
    )
    updater_name = "mediahub-platform-update"
    new_file(
        root / "updates/host-capabilities.json",
        '{"sourceBuild": true, "automaticFastUpdate": true, "mainBranchUpdates": true}\n',
        0o644,
    )
    new_file(
        Path("/etc/systemd/system") / (updater_name + ".service"),
        "[Unit]\n"
        "Description=MediaHub transactional platform update\n"
        "Requires=docker.service\n"
        "After=docker.service\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/python3 {updater_script} --root {root}\n"
        "User=root\n"
        "Group=root\n"
        "UMask=0077\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "ProtectHome=true\n"
        "ProtectSystem=strict\n"
        f"ReadWritePaths={root} /var/run/docker.sock\n"
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n",
        0o644,
    )
    new_file(
        Path("/etc/systemd/system") / (updater_name + ".path"),
        "[Unit]\nDescription=Watch for verified MediaHub updates\n"
        "[Path]\n"
        f"PathExists={root}/updates/request.json\n"
        f"Unit={updater_name}.service\n"
        "[Install]\nWantedBy=multi-user.target\n",
        0o644,
    )
    command("systemctl", "daemon-reload")
    command("systemctl", "enable", "--now", updater_name + ".path")
    command("docker", "compose", "-f", root / "compose.json", "up", "-d", capture=False)
    print(f"Open https://{address}:18765 after importing ONLY {root}/trust/ca.pem on your client.")
    print("Never copy authority/ca.key or disable certificate validation.")
    print(
        f"Bootstrap token: run docker compose -f {root}/compose.json exec core mediahub bootstrap-token locally."
    )
    print(
        "Complete the browser wizard, including optional Plex installation. No public access was configured."
    )
    print(
        "Server certificates expire in 90 days. See docs/certificates.md for renewal and rotation."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # No raw command stderr: dependency tools can include sensitive paths/config.
        print(
            str(error)
            if isinstance(error, ValueError)
            else "Installation step failed; existing media was not changed. Inspect the new installation before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)
