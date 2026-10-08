"""Package tracked Git source for local-server builds, never local secrets/junk."""

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path


def package(repository, revision, output, expected_version=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Use a GitHub owner/repository")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Use a full immutable commit SHA")
    raw = subprocess.check_output(["git", "show", f"{revision}:pyproject.toml"], text=True)
    version = tomllib.loads(raw)["project"]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Source requires a stable version")
    if expected_version is not None and expected_version != "v" + version:
        raise ValueError("Release tag must match the source project version")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "mediahub-source.tar.gz"
    # An explicit tracked-file allowlist keeps QA artifacts and credentials out.
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            "--prefix=mediahub-source/",
            "--output",
            str(archive),
            revision,
            "backend",
            "agent",
            "apps",
            "frontend",
            "docker",
            "pyproject.toml",
            "requirements.lock",
            "README.md",
            "LICENSE",
            "alembic.ini",
            ".dockerignore",
        ],
        check=True,
    )
    manifest = {
        "schemaVersion": 2,
        "version": version,
        "source": {
            "name": archive.name,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "repository": repository,
            "commit": revision,
        },
        "updatePolicy": {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        },
    }
    (output / "mediahub-source-release.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, default=Path("."))
    parser.add_argument("--version", required=True, help="Expected stable vX.Y.Z tag")
    args = parser.parse_args()
    package(args.repository, args.commit, args.output, args.version)
