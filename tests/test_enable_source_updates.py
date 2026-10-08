import json
from types import SimpleNamespace

import pytest

import scripts.enable_source_updates as migration
from scripts.platform_update_host import HostUpdater


def migration_fixture(tmp_path, monkeypatch, source=True):
    root = tmp_path / "mediahub"
    root.mkdir()
    (root / "updates").mkdir()
    (root / "compose.json").write_text("{}")
    policy = {
        "coreRepository": "ghcr.io/example/core",
        "agentRepository": "ghcr.io/example/agent",
    }
    if source:
        policy["sourceRepository"] = "example/mediahub"
    (root / "update-policy.json").write_text(json.dumps(policy))
    (root / "platform_update_host.py").write_text("old helper")
    events = []

    class MigrationUpdater(HostUpdater):
        @staticmethod
        def _directory(path, owner=None):
            assert path.is_dir()
            return path

        @staticmethod
        def _trusted_file(path, limit=65536):
            return path.read_text()

        @staticmethod
        def _atomic_text(path, value, uid=0, gid=0):
            events.append(path.name)
            path.write_text(value)

        @staticmethod
        def _atomic_json(path, value, uid=10001, gid=10001):
            events.append(path.name)
            assert uid == gid == 0
            path.write_text(json.dumps(value))

        def installed_source(self):
            return {"commit": "a" * 40}

        def command(self, *args, **kwargs):
            events.append(args)
            return ""

    monkeypatch.setattr(migration, "HostUpdater", MigrationUpdater)
    monkeypatch.setattr(migration, "os", SimpleNamespace(name="posix", geteuid=lambda: 0))
    monkeypatch.setattr(
        migration, "fcntl", SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)
    )
    monkeypatch.setattr(migration, "SYSTEMD_DROPIN", tmp_path / "systemd-dropin")
    return root, policy, events


@pytest.mark.parametrize("source", [True, False])
def test_refresh_installs_real_helper_before_capabilities_and_preserves_trust(
    tmp_path, monkeypatch, source
):
    root, policy, events = migration_fixture(tmp_path, monkeypatch, source)
    migration.enable(root)
    assert json.loads((root / "update-policy.json").read_text()) == policy
    helper = (root / "platform_update_host.py").read_text()
    assert helper == migration.Path(migration.__file__).with_name("platform_update_host.py").read_text()
    assert "def _maintenance(" in helper
    capabilities = json.loads((root / "updates/host-capabilities.json").read_text())
    assert capabilities == {
        "sourceBuild": source,
        "automaticFastUpdate": source,
        "mainBranchUpdates": source,
        "maintenance": True,
    }
    assert events.index("platform_update_host.py") < events.index("host-capabilities.json")
    assert (root / "platform_update_host.py.before-source").read_text() == "old helper"
    assert "update-policy.json" not in events
    assert migration.SYSTEMD_DROPIN.exists() is source
    migration.enable(root)
    assert (root / "platform_update_host.py.before-source").read_text() == "old helper"


def test_existing_image_host_can_still_explicitly_enable_source(tmp_path, monkeypatch):
    root, policy, events = migration_fixture(tmp_path, monkeypatch, source=False)
    migration.enable(root, "example/mediahub")
    policy["sourceRepository"] = "example/mediahub"
    assert json.loads((root / "update-policy.json").read_text()) == policy
    assert json.loads((root / "updates/host-capabilities.json").read_text())["sourceBuild"] is True
    assert ("systemctl", "daemon-reload") in events


@pytest.mark.parametrize("blocked", ["repository", "override", "request", "maintenance"])
def test_refresh_preflight_does_not_install_or_advertise_on_conflict(
    tmp_path, monkeypatch, blocked
):
    root, policy, events = migration_fixture(tmp_path, monkeypatch)
    repository = None
    if blocked == "repository":
        repository = "other/repository"
    elif blocked == "override":
        migration.SYSTEMD_DROPIN.mkdir()
        (migration.SYSTEMD_DROPIN / "source-build.conf").write_text("[Service]\nPrivateNetwork=yes\n")
    elif blocked == "request":
        (root / "updates/request.json").write_text("{}")
    else:
        (root / ("updates/maintenance-running-" + "a" * 32 + ".json")).write_text("{}")
    with pytest.raises(ValueError):
        migration.enable(root, repository)
    assert events == []
    assert (root / "platform_update_host.py").read_text() == "old helper"
    assert json.loads((root / "update-policy.json").read_text()) == policy
    assert not (root / "updates/host-capabilities.json").exists()


def test_failed_helper_install_does_not_advertise_maintenance(tmp_path, monkeypatch):
    root, _, _ = migration_fixture(tmp_path, monkeypatch)
    original = migration.HostUpdater._atomic_text

    def fail_helper(path, value, **kwargs):
        if path.name == "platform_update_host.py":
            raise OSError("failed helper installation")
        original(path, value, **kwargs)

    monkeypatch.setattr(migration.HostUpdater, "_atomic_text", staticmethod(fail_helper))
    with pytest.raises(OSError):
        migration.enable(root)
    assert not (root / "updates/host-capabilities.json").exists()
    assert (root / "platform_update_host.py").read_text() == "old helper"
