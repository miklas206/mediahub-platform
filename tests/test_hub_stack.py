import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.hub_stack import hub_stack
from scripts.platform_update_host import HostUpdater


def original_stack():
    return {
        "name": "mediahub-platform",
        "services": {
            "core": {
                "image": "hub-image", "ports": ["192.168.1.111:18765:18765"],
                "networks": ["control", "lan"], "environment": {"MEDIAHUB_BASE_URL": "https://192.168.1.111:18765"},
                "volumes": ["/opt/mediahub/data:/data", "/opt/mediahub/tls-core:/tls:ro", "/storage:/storage:ro"],
            },
            "agent": {
                "image": "runtime-image", "group_add": ["999", "1000"],
                "environment": {"MEDIAHUB_AGENT_STATE_DIR": "/state", "MEDIAHUB_AGENT_TOKEN_FILE": "/state/token"},
                "volumes": ["/opt/mediahub/agent:/state", "/opt/mediahub/tls-agent:/tls:ro", "/storage:/storage", "/var/run/docker.sock:/var/run/docker.sock:ro"],
            },
        },
    }


def test_hub_stack_preserves_state_and_https_without_mutating_input():
    original = original_stack()
    before = deepcopy(original)
    migrated, routing = hub_stack(original, Path("/opt/mediahub"))
    assert original == before
    assert set(migrated["services"]) == {"core", "proxy"}
    hub = migrated["services"]["core"]
    assert "ports" not in hub
    assert "/opt/mediahub/data:/data" in hub["volumes"]
    assert "/opt/mediahub/agent:/state" in hub["volumes"]
    assert "/opt/mediahub/tls-core:/tls:ro" in hub["volumes"]
    assert "/opt/mediahub/tls-agent:/tls:ro" not in hub["volumes"]
    assert "/storage:/storage" in hub["volumes"]
    assert "/storage:/storage:ro" not in hub["volumes"]
    assert hub["environment"]["MEDIAHUB_RUNTIME_MODE"] == "embedded"
    assert migrated["services"]["proxy"]["ports"] == before["services"]["core"]["ports"]
    assert all("docker.sock" not in volume for volume in migrated["services"]["proxy"]["volumes"])
    assert routing["tcp"]["routers"]["hub"]["tls"] == {"passthrough": True}


def test_hub_stack_rejects_other_projects_and_nonstandard_stacks():
    original = original_stack()
    original["name"] = "production-other"
    with pytest.raises(ValueError):
        hub_stack(original, Path("/opt/mediahub"))


def test_embedded_updater_snapshots_both_account_and_runtime_state(tmp_path):
    migrated, _ = hub_stack(original_stack(), tmp_path)
    (tmp_path / "compose.json").write_text(json.dumps(migrated))
    updater = HostUpdater(tmp_path)
    updater.changed_roles = ("core",)
    assert updater._embedded()
    assert updater._state_directories() == ("data", "agent")
    original = original_stack()
    original["services"]["external-app"] = {}
    with pytest.raises(ValueError):
        hub_stack(original, Path("/opt/mediahub"))