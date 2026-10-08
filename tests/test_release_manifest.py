import json
import subprocess
import sys
from pathlib import Path


def test_release_manifest_identifies_private_update_bundles(tmp_path):
    core = tmp_path / "mediahub-core-image.tar.gz"
    agent = tmp_path / "mediahub-agent-image.tar.gz"
    core.write_bytes(b"core-image")
    agent.write_bytes(b"agent-image")
    output = tmp_path / "mediahub-release.json"
    digest = "a" * 64
    subprocess.run(
        [
            sys.executable,
            str(Path("scripts/release_manifest.py").resolve()),
            "--version",
            "v0.3.0",
            "--core",
            f"ghcr.io/example/mediahub-core@sha256:{digest}",
            "--agent",
            f"ghcr.io/example/mediahub-agent@sha256:{digest}",
            "--core-bundle",
            str(core),
            "--agent-bundle",
            str(agent),
            "--output",
            str(output),
        ],
        check=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["version"] == "0.3.0"
    assert payload["bundles"]["core"]["name"] == core.name
    assert len(payload["bundles"]["core"]["sha256"]) == 64
    assert payload["bundles"]["agent"]["name"] == agent.name
