"""Copy reviewed source only; private app repos need no deploy token at install time."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sync(source_root, destination):
    manifest = {}
    for kind in ("mediavpn", "mediaseed"):
        root = source_root / kind
        target = destination / kind
        allowed = [
            "Dockerfile",
            "pyproject.toml",
            "LICENSE",
            "compose.yaml",
            "compose.hub.yaml",
            "compose.runtime.yaml",
            "compose.vpn.yaml",
            "hub-proxy.yaml",
        ]
        files = [root / name for name in allowed if (root / name).is_file()]
        files += [
            p
            for p in (root / kind).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and (
                p.suffix == ".py"
                or "static" in p.relative_to(root).parts
                or "relay_image" in p.relative_to(root).parts
                or "gateway_image" in p.relative_to(root).parts
            )
        ]
        for path in sorted(files):
            relative = path.relative_to(root)
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
            content = output.read_bytes()
            if output.suffix.lower() in {
                ".py",
                ".js",
                ".css",
                ".html",
                ".svg",
                ".json",
                ".toml",
                ".yaml",
                ".yml",
                ".md",
                ".txt",
            } or output.name in {"Dockerfile", "LICENSE"}:
                content = content.replace(b"\r\n", b"\n")
            manifest[kind + "/" + relative.as_posix()] = hashlib.sha256(content).hexdigest()
    (destination / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    sync(args.source_root, args.destination)
