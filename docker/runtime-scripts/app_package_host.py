"""Activate reviewed optional packages on the local MediaHub Docker host."""

import argparse
import ipaddress
import json
import os
import re
import secrets
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from app_package_fetch import retrieve
from storage_host import StorageHost


class Prerequisite(Exception):
    pass


def provide_certificate(root, home, lan):
    folder = home / "tls"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    cert, key = folder / "server.pem", folder / "server-key.pem"
    if cert.exists() or key.exists():
        return
    with tempfile.TemporaryDirectory(dir=folder) as directory:
        temp = Path(directory)
        request = temp / "request"
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:3072",
                "-nodes",
                "-subj",
                "/CN=" + lan,
                "-keyout",
                str(temp / "key"),
                "-out",
                str(request),
            ],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        settings = temp / "extensions"
        settings.write_text(
            "basicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:"
            + lan
            + "\n"
        )
        subprocess.run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(request),
                "-CA",
                str(root / "authority/ca.pem"),
                "-CAkey",
                str(root / "authority/ca.key"),
                "-set_serial",
                str(secrets.randbits(120) or 1),
                "-days",
                "365",
                "-extfile",
                str(settings),
                "-out",
                str(temp / "cert"),
            ],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        (temp / "key").chmod(0o600)
        (temp / "key").replace(key)
        (temp / "cert").replace(cert)


def save_login(root, app, value):
    # Core reads the first-run credential only after an administrator requests it.
    with tempfile.NamedTemporaryFile(dir=root, delete=False, mode="w") as f:
        json.dump(value, f)
        os.fchown(f.fileno(), 10001, 10001)
    os.replace(f.name, root / "updates" / ("first-login-" + app + ".json"))


def install(root, app, location_id):
    approved = json.loads(Path(__file__).with_name("app-package-releases.json").read_text())[app]
    storage = StorageHost(root)
    lan = str(ipaddress.IPv4Address(storage.policy()["lan"]))
    if app == "plex-gpu-transcoder":
        if not (root / "agent/plex-managed.json").is_file():
            raise Prerequisite("Install Plex in MediaHub first.")
        if not all(
            (Path("/dev") / n).is_char_device() for n in ("nvidia0", "nvidiactl", "nvidia-uvm")
        ):
            raise Prerequisite("Prepare a compatible NVIDIA GPU on this Plex host first.")
    video_home = root / "local-apps/videodownloader"
    upload_home = Path("/opt/mediaupload-docker")
    existing = (
        (video_home / "config.env").is_file()
        if app == "video-downloader"
        else (upload_home / "settings.json").is_file()
    )
    source = None
    if app != "plex-gpu-transcoder" and not existing:
        if not location_id:
            raise Prerequisite("Select a storage location for the first installation.")
        location = next(
            (row for row in storage.locations() if row["id"] == location_id and row["ready"]), None
        )
        if not location or (app == "video-downloader" and location.get("readOnly")):
            raise Prerequisite("Reconnect the selected storage or choose another location.")
        source = Path(location["source"])
    packages = root / "app-packages"
    packages.mkdir(mode=0o755, exist_ok=True)
    if (
        packages.resolve() != packages
        or packages.stat().st_uid != 0
        or packages.stat().st_mode & 0o022
    ):
        raise Prerequisite("Check ownership of the app package directory.")
    receipt = packages / (app + "-installed")
    installed = receipt.read_text().strip() if receipt.is_file() else None
    pending_login = packages / (app + "-first-login.pending")
    if app != "plex-gpu-transcoder" and not existing:
        pending_login.touch(mode=0o600, exist_ok=True)
    release = retrieve(
        app, packages, approved, (root / "installed-version").read_text().strip(), installed
    )
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if app == "plex-gpu-transcoder":
        command = [
            "/usr/bin/python3",
            str(release / "install.py"),
            "--root",
            str(root / app),
            "--agent-state",
            str(root / "agent"),
        ]
    elif app == "video-downloader":
        env["APP_HOME"] = str(video_home)
        if source is not None:
            env.update(
                PUBLIC_ORIGIN=f"https://{lan}:18810",
                BIND_ADDRESS=lan,
                DOWNLOADS_DIR=str(source),
                TLS_CA_CERT=str(root / "authority/ca.pem"),
                TLS_CA_KEY=str(root / "authority/ca.key"),
            )
        command = ["/bin/bash", str(release / "server/install.sh")]
    else:
        command = ["/usr/bin/python3", str(release / "install.py")]
        if source is not None:
            upload_home.mkdir(mode=0o700, exist_ok=True)
            provide_certificate(root, upload_home, lan)
            command.extend(
                ["--library", str(source), "--origin", f"https://{lan}:18820", "--bind", lan]
            )
    subprocess.run(command, env=env, check=True, timeout=2700)
    version = (release / "VERSION").read_text().strip()
    result = {"version": version}
    if app == "video-downloader":
        pairs = dict(
            line.split("=", 1)
            for line in (video_home / "config.env").read_text().splitlines()
            if "=" in line
        )
        url = shlex.split(pairs["PUBLIC_ORIGIN"])[0]
        if urlsplit(url).scheme == "https" and urlsplit(url).hostname:
            result["url"] = url
        token = json.loads((video_home / "data/auth.json").read_text()).get("setupToken")
        if (
            pending_login.exists()
            and isinstance(token, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token)
        ):
            save_login(root, app, {"setupUrl": url + "/#setup=" + token})
    elif app == "mediaupload":
        result["url"] = json.loads((upload_home / "settings.json").read_text())["UPLOAD_ORIGIN"]
        if pending_login.exists():
            save_login(
                root,
                app,
                {
                    "username": "admin",
                    "password": (upload_home / "initial-password").read_text().strip(),
                },
            )
    with tempfile.NamedTemporaryFile(dir=packages, delete=False, mode="w") as saved:
        saved.write(version)
    os.replace(saved.name, receipt)
    pending_login.unlink(missing_ok=True)
    return result


def write_status(root, app, operation, **status):
    target = root / "updates" / ("package-" + app + ".json")
    # Write via a root-exclusive temporary inode in the parent. Core owns updates/.
    with tempfile.NamedTemporaryFile(dir=root, delete=False, mode="w") as f:
        json.dump(dict(operationId=operation, **status), f)
        os.fchown(f.fileno(), 10001, 10001)
    os.replace(f.name, target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("app", choices=("plex-gpu-transcoder", "video-downloader", "mediaupload"))
    parser.add_argument("operation")
    parser.add_argument("location", nargs="?", default="")
    args = parser.parse_args()
    if os.geteuid() or not re.fullmatch(r"[a-f0-9]{32}", args.operation):
        parser.error("Invalid host operation")
    try:
        write_status(args.root, args.app, args.operation, state="running")
        result = install(args.root, args.app, args.location)
        write_status(args.root, args.app, args.operation, state="succeeded", **result)
    except (Prerequisite, OSError, ValueError, subprocess.SubprocessError) as error:
        message = (
            str(error)
            if isinstance(error, Prerequisite)
            else "Installation failed. Check the host installation log and retry when the app is idle."
        )
        write_status(args.root, args.app, args.operation, state="failed", message=message)
        raise
