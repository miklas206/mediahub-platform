"""Build a source-only archive from an allowlist. Never bundles instance data/secrets."""

import argparse
import hashlib
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ".dockerignore",
    "pyproject.toml",
    "requirements.lock",
    "README.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    ".env.example",
    "install.sh",
    "alembic.ini",
    "compose.production.yaml",
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
    "frontend/pnpm-workspace.yaml",
    "frontend/index.html",
    "frontend/tsconfig.json",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.node.json",
    "frontend/vite.config.ts",
]
DIRECTORIES = [
    "backend",
    "agent",
    "apps",
    "docker",
    "docs",
    "scripts",
    "frontend/src",
    "frontend/public",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="mediahub-v020")
    args = parser.parse_args()
    if not args.name.replace("-", "").isalnum():
        parser.error("Archive name must contain only letters, digits and hyphens")
    output = ROOT / ".qa" / "release"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (args.name + ".tar.gz")
    paths = [ROOT / name for name in FILES]
    for name in DIRECTORIES:
        paths.extend(
            p
            for p in (ROOT / name).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )
    with tarfile.open(archive, "w:gz") as bundle:
        for path in paths:
            if path.exists() and not path.is_symlink():
                bundle.add(
                    path, arcname=str(path.relative_to(ROOT)).replace("\\", "/"), recursive=False
                )
    print(archive)
    print(hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
