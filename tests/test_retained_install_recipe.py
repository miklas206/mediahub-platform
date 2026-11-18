import json
import os
from pathlib import Path

import pytest

from scripts import prepare_managed_install as exporter


@pytest.mark.skipif(os.name != "posix", reason="Managed Docker recipes use POSIX owners and modes")
@pytest.mark.parametrize(
    "scenario", ["valid", "other-selected", "wrong-owner-id", "public", "missing"]
)
def test_removed_sibling_recipe_survives_only_for_matching_installation(
    tmp_path, monkeypatch, scenario
):
    package = "org.mediahub.mediaseed"
    recipes = tmp_path / "managed-install-recipes"
    recipes.mkdir()
    recipe = recipes / "mediaseed.json"
    content = json.dumps(
        {"packageId": package, "installationId": "original", "containers": [{"name": "app"}]}
    )
    recipe.write_text(content)
    recipe.chmod(0o644 if scenario == "public" else 0o600)
    if scenario == "missing":
        recipe.unlink()
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                package: {
                    "project": "mediahub-mediaseed",
                    "installationId": "changed" if scenario == "wrong-owner-id" else "original",
                    "installFile": "/data/managed-install-recipes/mediaseed.json",
                }
            }
        )
    )
    calls = []

    def absent(command):
        calls.append(command)
        return b""

    monkeypatch.setattr(exporter.subprocess, "check_output", absent)

    args = (policy, tmp_path, Path("/data"), os.getuid(), os.getgid())
    if scenario in {"wrong-owner-id", "public", "missing"}:
        with pytest.raises(RuntimeError, match="Prepare the approved"):
            exporter.prepare(*args)
    else:
        exporter.prepare(*args, "org.mediahub.mediavpn" if scenario == "other-selected" else None)
        assert recipe.read_text() == content
        assert len(calls) == int(scenario == "valid")
