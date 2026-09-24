"""Create the small, machine-readable manifest attached to a GitHub Release."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from packaging.version import Version

IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}$")


def digest(path: Path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--core", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--core-bundle", type=Path, required=True)
    parser.add_argument("--agent-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version = str(Version(args.version.removeprefix("v")))
    for value in (args.core, args.agent):
        if not IMAGE.fullmatch(value):
            parser.error("Images must be immutable lowercase GHCR digest references")
    for bundle in (args.core_bundle, args.agent_bundle):
        if not bundle.is_file() or bundle.stat().st_size < 1:
            parser.error("Image bundles must be non-empty regular files")
    payload = {
        "schemaVersion": 1,
        "version": version,
        "images": {"core": args.core, "agent": args.agent},
        "bundles": {
            "core": {
                "name": args.core_bundle.name,
                "sha256": digest(args.core_bundle),
            },
            "agent": {
                "name": args.agent_bundle.name,
                "sha256": digest(args.agent_bundle),
            },
        },
        "updatePolicy": {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
