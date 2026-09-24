import json
import time
from pathlib import Path

import pytest
from mediahub.apps.manifest import DeviceRequirement
from pydantic import ValidationError

from agent.devices import (
    block_inventory,
    device_report,
    required_device_health,
    snapshot_inventory,
    usb_inventory,
)


def test_usb_discovery_readonly_and_missing_serial(tmp_path):
    path = tmp_path / "1-2"
    path.mkdir()
    (path / "idVendor").write_text("1234\n")
    (path / "idProduct").write_text("abcd\n")
    before = {p.name: p.read_bytes() for p in path.iterdir()}
    result = usb_inventory(tmp_path)
    assert result["available"] and result["devices"][0]["serial"] is None
    assert {p.name: p.read_bytes() for p in path.iterdir()} == before
    assert not usb_inventory(None)["available"]
    assert not usb_inventory(Path("/nonexistent-usb-inventory"))["available"]


def test_device_health_missing_unknown_present_ambiguous():
    requirement = DeviceRequirement(id="archive", type="usb", selectorRef="archive_device")
    selectors = {"archive_device": {"vendorId": "1234", "productId": "abcd", "serial": "example"}}
    device = {
        "type": "usb",
        "vendorId": "1234",
        "productId": "abcd",
        "serial": "example",
        "connected": True,
    }

    def check(inventory):
        return required_device_health([requirement], selectors, inventory)[0]

    assert check({"available": False})["status"] == "critical"
    assert check({"available": True, "devices": []})["status"] == "critical"
    assert check({"available": True, "devices": [device]})["status"] == "healthy"
    assert check({"available": True, "devices": [device, device]})["status"] == "critical"
    assert (
        required_device_health([requirement], {}, {"available": True, "devices": [device]})[0][
            "status"
        ]
        == "critical"
    )


def test_raw_disk_identity_does_not_require_usb_visibility():
    requirement = DeviceRequirement(
        id="archive", type="block", selectorRef="archive", missingHealth="degraded"
    )
    inventory = {
        "available": True,
        "devices": [{"type": "block", "serial": "test-disk", "connected": True}],
    }
    assert (
        required_device_health([requirement], {"archive": {"serial": "test-disk"}}, inventory)[0][
            "status"
        ]
        == "healthy"
    )
    assert required_device_health([requirement], {}, inventory)[0]["status"] == "degraded"
    with pytest.raises(ValidationError):
        DeviceRequirement(id="archive", type="usb", selectorRef="archive", vendorId="1234")


def test_block_sysfs_report_and_loss(tmp_path):
    disk = tmp_path / "sdc" / "device"
    disk.mkdir(parents=True)
    serial = disk / "serial"
    serial.write_text("test-archive\n")
    requirement = DeviceRequirement(id="archive", type="block", selectorRef="archive")
    selectors = {"archive": {"serial": "test-archive"}}
    assert block_inventory(tmp_path)["devices"][0]["serial"] == "test-archive"
    report = device_report(None, tmp_path, [requirement], selectors)
    assert report["health"] == "healthy"
    assert report["requiredCount"] == 1
    assert report["sources"]["usb"]["available"] is False
    serial.unlink()
    assert device_report(None, tmp_path, [requirement], selectors)["health"] == "critical"
    assert device_report(None, None, [], {})["requiredCount"] == 0


def test_agent_device_report_requires_authentication(tmp_path):
    from fastapi.testclient import TestClient

    from agent.main import AgentConfig, create_agent, initialize

    config = AgentConfig(
        state_dir=tmp_path,
        token_file=tmp_path / "token",
        required_devices=[DeviceRequirement(id="archive", type="block", selectorRef="archive")],
        _env_file=None,
    )
    initialize(config)
    with TestClient(create_agent(config)) as client:
        assert client.get("/v1/status").status_code == 401
        client.headers["Authorization"] = "Bearer " + config.token_file.read_text()
        response = client.get("/v1/status")
        assert response.status_code == 200
        assert response.json()["devices"]["health"] == "critical"


def test_host_snapshot_expiry_and_mount_requirements(tmp_path):
    path = tmp_path / "devices.json"
    device = {
        "type": "block",
        "connected": True,
        "uuid": "test-uuid",
        "model": "Example disk",
        "sizeBytes": 1000,
        "readOnly": False,
        "mounts": [{"path": "/archive", "readOnly": False}],
    }
    data = {
        "schemaVersion": 1,
        "observedAt": time.time(),
        "available": True,
        "scope": "host-mount-namespace",
        "devices": [device],
    }
    path.write_text(json.dumps(data))
    requirement = DeviceRequirement(
        id="archive", type="block", selectorRef="archive", mountRequired=True, writeRequired=True
    )
    selectors = {"archive": {"uuid": "test-uuid", "mountPath": "/archive"}}

    def report():
        return device_report(None, None, [requirement], selectors, path)

    assert report()["health"] == "healthy"
    device["mounts"][0]["readOnly"] = True
    path.write_text(json.dumps(data))
    assert report()["health"] == "critical"
    assert report()["checks"][0]["connected"] is True
    data["observedAt"] -= 100
    path.write_text(json.dumps(data))
    assert snapshot_inventory(path)["available"] is False
    assert report()["health"] == "critical"
    path.write_text("broken json")
    assert report()["health"] == "critical"


def test_mount_requirement_validation():
    with pytest.raises(ValidationError):
        DeviceRequirement(id="disk", type="usb", selectorRef="disk", mountRequired=True)
    with pytest.raises(ValidationError):
        DeviceRequirement(id="disk", type="block", selectorRef="disk", writeRequired=True)
