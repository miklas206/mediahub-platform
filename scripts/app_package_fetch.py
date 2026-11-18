#!/usr/bin/env python3
"""Download and verify one published MediaHub app into a versioned directory."""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PROJECT = "miklas206/mediahub-app-releases"
APPS = ("mediaupload", "video-downloader", "plex-gpu-transcoder")
RELEASE_KEY = b"-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAecGfD1y1sCS6XAinBoah72pMjhqPQUsbJS5Ed7jtpc4=\n-----END PUBLIC KEY-----\n"
LIMIT = 32 * 1024 * 1024


def fetch(url, limit):
    with urllib.request.urlopen(url, timeout=45) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("HTTPS required")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Download exceeds its size limit")
    return data


def signed_index(app):
    manifest = json.loads(
        fetch(f"https://raw.githubusercontent.com/{PROJECT}/main/apps/{app}.json", 16384)
    )
    signature = base64.b64decode(manifest.pop("signature"), validate=True)
    if len(signature) != 64:
        raise ValueError("Invalid release signature")
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        (folder / "key").write_bytes(RELEASE_KEY)
        (folder / "signature").write_bytes(signature)
        (folder / "body").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="ascii"
        )
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(folder / "key"),
                "-rawin",
                "-in",
                str(folder / "body"),
                "-sigfile",
                str(folder / "signature"),
            ],
            capture_output=True,
        )
        if result.returncode:
            raise ValueError("Release signature verification failed")
    return manifest


def number(version):
    if not isinstance(version, str) or not re.fullmatch(
        r"(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)){2}", version
    ):
        raise ValueError("Invalid release version")
    return tuple(map(int, version.split(".")))


def retrieve(app, destination, approved=None, hub_version=None, installed=None):
    manifest = signed_index(app)
    if approved:
        minimum = number(approved["version"])
        offered = number(manifest["version"])
        if offered < minimum or (offered == minimum and manifest["sha256"] != approved["sha256"]):
            raise ValueError("Published package does not match the reviewed release")
        if number(manifest["minimumHub"]) > number(hub_version):
            raise ValueError("Update MediaHub first to use this release")
    if installed and number(manifest["version"]) < number(installed):
        raise ValueError("Package downgrade refused")
    version = manifest["version"]
    if manifest["app"] != app or not re.fullmatch(
        r"(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)){2}", version
    ):
        raise ValueError("Unexpected application or version")
    tag = f"{app}-v{version}"
    data = fetch(f"https://github.com/{PROJECT}/releases/download/{tag}/{tag}.tar.gz", LIMIT)
    digest = hashlib.sha256(data).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Release checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / tag
    stage = Path(tempfile.mkdtemp(prefix=".download-", dir=destination))
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            seen = set()
            size = 0
            for member in archive:
                parts = member.name.split("/")
                if (
                    not member.isfile()
                    or any(p in ("", ".", "..") for p in parts)
                    or member.name in seen
                    or len(seen) >= 2048
                ):
                    raise ValueError("Unexpected file in package")
                seen.add(member.name)
                size += member.size
                if size > LIMIT:
                    raise ValueError("Unpacked package exceeds its size limit")
                path = stage.joinpath(*parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as output:
                    shutil.copyfileobj(archive.extractfile(member), output)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
        if not (stage / "VERSION").is_file() or (stage / "VERSION").read_text().strip() != version:
            raise ValueError("Package version differs from index")
        if not (stage / "README.md").is_file():
            raise ValueError("Missing installation instructions")
        if target.exists():
            # Confirm the entire existing release before reusing it on retry.
            entries = list(target.rglob("*"))
            if target.is_symlink() or any(p.is_symlink() for p in entries):
                raise ValueError(f"Unexpected link in existing release: {target}")
            actual = {p.relative_to(target).as_posix() for p in entries if p.is_file()}
            extra = actual - seen
            for name in extra:
                rel = Path(name)
                source = re.fullmatch(
                    r"([A-Za-z0-9_]+)\.cpython-[0-9]+(?:\.opt-[12])?\.pyc", rel.name
                )
                if (
                    rel.parent.name != "__pycache__"
                    or not source
                    or (rel.parent.parent / (source[1] + ".py")).as_posix() not in seen
                ):
                    raise ValueError(f"Existing release directory has local changes: {target}")
            if seen - actual or any(
                (target / name).read_bytes() != (stage / name).read_bytes() for name in seen
            ):
                raise ValueError(f"Existing release directory has local changes: {target}")
            # Python's installer imports create derived files. Discard only caches of
            # identified, verified modules so execution always uses the published source.
            for name in extra:
                (target / name).unlink(missing_ok=True)
        else:
            stage.chmod(0o755)
            os.rename(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", choices=APPS)
    parser.add_argument("--directory", type=Path, default=Path("mediahub-releases"))
    args = parser.parse_args()
    print(retrieve(args.app, args.directory).resolve())
