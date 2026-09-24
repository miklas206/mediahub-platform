import json
from types import SimpleNamespace

import scripts.platform_update_host as host_module
from scripts.platform_update_host import HostUpdater, version_key

OPERATION = "a" * 32
CORE_REPOSITORY = "ghcr.io/example/mediahub-core"
AGENT_REPOSITORY = "ghcr.io/example/mediahub-agent"


class TestUpdater(HostUpdater):
    __test__ = False

    @staticmethod
    def _directory(path, owner=None):
        if not path.is_dir():
            raise ValueError("Missing test directory")
        return path

    @staticmethod
    def _trusted_file(path, limit=65536):
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _atomic_json(path, value, uid=10001, gid=10001):
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def _atomic_text(path, value, uid=0, gid=0):
        path.write_text(value + "\n", encoding="utf-8")

    def _validate_request(self):
        return self.test_request, self.test_manifest, self.test_stage


def fixture(tmp_path, monkeypatch, fail_new_core=False, image_repository=CORE_REPOSITORY):
    root = tmp_path / "mediahub"
    for name in ("updates", "update-backups", "data", "agent"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "data" / "mediahub.db").write_text("configuration", encoding="utf-8")
    (root / "agent" / "state.json").write_text("agent state", encoding="utf-8")
    compose = {
        "name": "mediahub-platform",
        "services": {
            "core": {"image": "sha256:" + "1" * 64},
            "agent": {"image": "sha256:" + "2" * 64},
        },
    }
    (root / "compose.json").write_text(json.dumps(compose), encoding="utf-8")
    (root / "installed-version").write_text("0.3.0\n", encoding="utf-8")
    (root / "update-policy.json").write_text(
        json.dumps(
            {
                "coreRepository": CORE_REPOSITORY,
                "agentRepository": AGENT_REPOSITORY,
            }
        ),
        encoding="utf-8",
    )
    stage = root / "updates" / "staging" / OPERATION
    stage.mkdir(parents=True)
    commands = []

    def runner(args, capture=True):
        commands.append(args)
        if args[:3] == ["docker", "compose", "-f"] and "ps" in args:
            return "container-" + args[-1]
        if args[:2] == ["docker", "inspect"]:
            return "healthy" if "Health" in args[3] else "true"
        return ""

    updater = TestUpdater(root, runner=runner, sleeper=lambda _: None)
    updater.test_request = {
        "schemaVersion": 1,
        "operationId": OPERATION,
        "fromVersion": "0.3.0",
        "toVersion": "0.4.0",
        "stage": f"staging/{OPERATION}",
        "manifestSha256": "f" * 64,
    }
    updater.test_manifest = {
        "schemaVersion": 1,
        "version": "0.4.0",
        "images": {
            "core": image_repository + "@sha256:" + "a" * 64,
            "agent": AGENT_REPOSITORY + "@sha256:" + "b" * 64,
        },
        "bundles": {
            "core": {"name": "mediahub-core-image.tar.gz", "sha256": "c" * 64},
            "agent": {"name": "mediahub-agent-image.tar.gz", "sha256": "d" * 64},
        },
        "updatePolicy": {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        },
    }
    updater.test_stage = stage
    monkeypatch.setattr(host_module.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        host_module,
        "fcntl",
        SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *_: None),
    )
    if fail_new_core:
        original_wait = updater._wait

        def wait(service, health=False, timeout=150):
            current = json.loads((root / "compose.json").read_text(encoding="utf-8"))
            new_image = "@sha256:" in current["services"]["core"]["image"]
            if service == "core" and health and new_image:
                raise ValueError("new Core failed health verification")
            return original_wait(service, health, timeout)

        updater._wait = wait
    return updater, root, commands


def test_version_comparison_accepts_only_stable_semantic_versions():
    assert version_key("0.4.0") > version_key("0.3.9")
    for invalid in ("v0.4.0", "0.4", "0.4.0-rc1", "../../etc/passwd"):
        try:
            version_key(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe version: {invalid}")


def test_successful_transaction_updates_both_images_and_trusted_version(tmp_path, monkeypatch):
    updater, root, commands = fixture(tmp_path, monkeypatch)
    updater.process()

    status = json.loads((root / "updates" / "status.json").read_text(encoding="utf-8"))
    compose = json.loads((root / "compose.json").read_text(encoding="utf-8"))
    assert status["state"] == "succeeded"
    assert status["progress"] == 100
    assert compose["services"]["core"]["image"].startswith(CORE_REPOSITORY + "@sha256:")
    assert compose["services"]["agent"]["image"].startswith(AGENT_REPOSITORY + "@sha256:")
    assert (root / "installed-version").read_text(encoding="utf-8") == "0.4.0\n"
    assert (root / "update-backups" / OPERATION / "data" / "mediahub.db").exists()
    assert any(command[:2] == ["docker", "load"] for command in commands)


def test_failed_health_check_restores_previous_configuration(tmp_path, monkeypatch):
    updater, root, _ = fixture(tmp_path, monkeypatch, fail_new_core=True)
    original = (root / "compose.json").read_text(encoding="utf-8")
    updater.process()

    status = json.loads((root / "updates" / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "rolled_back"
    assert json.loads((root / "compose.json").read_text(encoding="utf-8")) == json.loads(original)
    assert (root / "installed-version").read_text(encoding="utf-8") == "0.3.0\n"
    assert (root / "data" / "mediahub.db").read_text(encoding="utf-8") == "configuration"


def test_untrusted_image_repository_is_rejected_before_services_stop(tmp_path, monkeypatch):
    updater, root, commands = fixture(
        tmp_path,
        monkeypatch,
        image_repository="ghcr.io/attacker/untrusted-core",
    )
    updater.process()

    status = json.loads((root / "updates" / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "failed"
    assert "before any running service" in status["message"]
    assert not any("stop" in command for command in commands)
    assert (root / "installed-version").read_text(encoding="utf-8") == "0.3.0\n"
