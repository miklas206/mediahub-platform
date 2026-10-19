import hashlib
import json
import shlex
import tarfile
from pathlib import Path

from mediahub.platform_source import normalize_source


def test_reviewed_bundle_matches_manifest_and_relay_protocol():
    root = Path(__file__).resolve().parents[1]
    bundle = root / "docker/bundled"
    manifest = json.loads((bundle / "source-manifest.json").read_text())
    assert manifest
    for name, digest in manifest.items():
        path = bundle / name
        content = path.read_bytes()
        if path.suffix.lower() in {
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
        } or path.name in {"Dockerfile", "LICENSE"}:
            content = content.replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == digest, name
        assert path.suffix not in {".token", ".sqlite", ".key", ".pem", ".conf"}
        assert path.name != ".env"
    for name in ("runtime.py", "Dockerfile"):
        assert (bundle / "mediavpn/mediavpn/relay_image" / name).read_bytes().replace(
            b"\r\n", b"\n"
        ) == (root / "agent/relay_image" / name).read_bytes().replace(b"\r\n", b"\n")


def test_compatibility_runtime_scripts_match_reviewed_host_helpers():
    root = Path(__file__).resolve().parents[1]
    for name in (
        "prepare_local_apps.py",
        "prepare_managed_install.py",
        "platform_update_host.py",
        "storage_host.py",
        "app_storage_host.py",
    ):
        assert (root / "scripts" / name).read_bytes().replace(b"\r\n", b"\n") == (
            root / "docker/runtime-scripts" / name
        ).read_bytes().replace(b"\r\n", b"\n")


def test_all_core_docker_copy_inputs_survive_legacy_source_normalization(tmp_path):
    """A new updater cannot fix the old updater that must build it first."""
    root = Path(__file__).resolve().parents[1]
    inputs = set()
    for line in (root / "docker/Dockerfile").read_text().splitlines():
        if line.startswith("COPY ") and "--from=" not in line:
            inputs.update(shlex.split(line)[1:-1])
    files = set()
    for name in inputs:
        path = root / name
        assert path.exists(), name
        files.update(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else files.add(
            path
        )
    raw = tmp_path / "github.tar.gz"
    with tarfile.open(raw, "w:gz") as archive:
        for path in sorted(files):
            archive.add(path, arcname="repo-head/" + path.relative_to(root).as_posix())
    normalized = tmp_path / "source.tar.gz"
    normalize_source(raw, normalized)
    with tarfile.open(normalized) as archive:
        names = set(archive.getnames())
        for name in inputs:
            target = "mediahub-source/" + name.rstrip("/")
            assert target in names or any(row.startswith(target + "/") for row in names), name
        assert "mediahub-source/docker/bundled/source-manifest.json" in names
        assert "mediahub-source/docker/runtime-scripts/prepare_local_apps.py" in names
