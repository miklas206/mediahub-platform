import hashlib
import json
from pathlib import Path


def test_reviewed_bundle_matches_manifest_and_relay_protocol():
    root = Path(__file__).resolve().parents[1]
    bundle = root / "bundled"
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
