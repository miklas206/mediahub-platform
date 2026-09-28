import hashlib
import io
import json
import os
import stat
import tarfile
from types import SimpleNamespace

import pytest

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
        if args[:2] == ["docker", "load"]:
            role = "core" if "core" in str(args[-1]) else "agent"
            digit = "3" if role == "core" else "4"
            return "Loaded image ID: sha256:" + digit * 64
        if args[:3] == ["docker", "image", "inspect"]:
            reference = args[-1]
            if "agent" in reference or reference == "sha256:" + "4" * 64:
                return "sha256:" + "4" * 64
            return "sha256:" + "3" * 64
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
            new_image = current["services"]["core"]["image"].startswith("mediahub-core:release-")
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
    assert compose["services"]["core"]["image"].startswith("mediahub-core:release-0.4.0-")
    assert compose["services"]["agent"]["image"].startswith("mediahub-agent:release-0.4.0-")
    assert compose["services"]["core"]["pull_policy"] == "never"
    assert compose["services"]["agent"]["pull_policy"] == "never"
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


def source_archive(path, entries=None):
    entries = entries or {
        "mediahub-source/pyproject.toml": b'[project]\nversion = "0.4.0"\n',
        "mediahub-source/docker/Dockerfile": b"FROM scratch\n",
        "mediahub-source/docker/Agent.Dockerfile": b"FROM scratch\n",
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def source_updater(tmp_path, monkeypatch):
    updater, root, commands = fixture(tmp_path, monkeypatch)
    policy = json.loads(updater.policy.read_text())
    policy["sourceRepository"] = "example/mediahub"
    updater.policy.write_text(json.dumps(policy))
    archive = updater.test_stage / "mediahub-source.tar.gz"
    source_archive(archive)
    updater.test_request["schemaVersion"] = 2
    updater.test_manifest = {
        "schemaVersion": 2,
        "version": "0.4.0",
        "source": {
            "name": archive.name,
            "repository": "example/mediahub",
            "commit": "a" * 40,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
        "updatePolicy": {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        },
    }
    monkeypatch.setattr(
        host_module.shutil, "disk_usage", lambda _: SimpleNamespace(free=50 * 1024**3)
    )
    return updater, root, commands


def test_source_builds_both_images_before_stopping_and_never_loads_images(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "succeeded"
    builds = [index for index, args in enumerate(commands) if args[:2] == ["docker", "build"]]
    stop = next(index for index, args in enumerate(commands) if "stop" in args)
    assert len(builds) == 2 and max(builds) < stop
    assert not any(args[:2] == ["docker", "load"] for args in commands)
    assert not list(root.glob("source-build-*"))


def test_failed_source_build_leaves_running_services_and_config_untouched(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    original = updater.compose.read_bytes()
    runner = updater.runner

    def fail_build(args, capture=True):
        if args[:2] == ["docker", "build"]:
            raise ValueError("simulated failed build")
        return runner(args, capture)

    updater.runner = fail_build
    updater.process()
    assert not any("stop" in args for args in commands)
    assert updater.compose.read_bytes() == original
    assert updater.installed_version.read_text().strip() == "0.3.0"
    assert json.loads((root / "updates/status.json").read_text())["state"] == "failed"
    assert not list(root.glob("source-build-*"))


def test_source_failed_health_rolls_back(tmp_path, monkeypatch):
    updater, root, _ = source_updater(tmp_path, monkeypatch)
    original = updater.compose.read_bytes()
    wait = updater._wait

    def fail_new(service, health=False, timeout=150):
        current = json.loads(updater.compose.read_text())
        if service == "core" and current["services"]["core"]["image"] == "sha256:" + "3" * 64:
            raise ValueError("new source image unhealthy")
        return wait(service, health, timeout)

    updater._wait = fail_new
    updater.process()
    assert updater.compose.read_bytes() == original
    assert json.loads((root / "updates/status.json").read_text())["state"] == "rolled_back"
    assert updater.installed_version.read_text().strip() == "0.3.0"


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "mediahub-source/../../escape",
        "mediahub-source/a\\b",
        "other/file",
    ],
)
def test_source_archive_rejects_path_escapes(tmp_path, name):
    archive = tmp_path / "source.tar.gz"
    source_archive(archive, {name: b"unsafe"})
    with pytest.raises(ValueError):
        HostUpdater._extract_source(archive, tmp_path / "unpacked")


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_source_archive_rejects_links_and_devices(tmp_path, kind):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("mediahub-source/unsafe")
        info.type = kind
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with pytest.raises(ValueError):
        HostUpdater._extract_source(path, tmp_path / "unpacked")


def test_source_untrusted_repository_stops_before_build_or_service_changes(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    updater.test_manifest["source"]["repository"] = "attacker/repo"
    updater.process()
    assert not any("stop" in args or "build" in args for args in commands)
    assert json.loads((root / "updates/status.json").read_text())["state"] == "failed"


def test_source_request_is_revalidated_and_claimed_by_host(tmp_path, monkeypatch):
    updater, root, _ = source_updater(tmp_path, monkeypatch)
    manifest = updater.test_stage / "mediahub-source-release.json"
    manifest.write_text(json.dumps(updater.test_manifest))
    request = {**updater.test_request, "manifestSha256": host_module.sha256(manifest)}
    request_path = root / "updates/request.json"
    request_path.write_text(json.dumps(request))
    actual, actual_manifest, stage = HostUpdater._validate_request(updater)
    assert actual == request and actual_manifest == updater.test_manifest
    assert stage == updater.test_stage
    assert not request_path.exists()
    assert (root / "updates" / f"running-{OPERATION}.json").exists()


def test_source_low_space_does_not_stop_services(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    monkeypatch.setattr(host_module.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024))
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "failed"
    assert not any("stop" in args or "build" in args for args in commands)


def test_source_archive_rejects_duplicate_files(tmp_path):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for _ in range(2):
            info = tarfile.TarInfo("mediahub-source/duplicate")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"a"))
    with pytest.raises(ValueError):
        HostUpdater._extract_source(path, tmp_path / "unpacked")


def test_source_build_client_does_not_inherit_host_credentials(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-must-not-reach-build")
    monkeypatch.setenv("DOCKER_CONFIG", "/root/secret-registry-config")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(host_module.subprocess, "run", run)
    HostUpdater._run(["docker", "build", "--tag", "test:source", str(source)], capture=False)
    _, options = calls[0]
    assert options["timeout"] == 1800
    assert "GITHUB_TOKEN" not in options["env"]
    assert options["env"]["DOCKER_CONFIG"] == str(tmp_path / "docker-client")
    assert options["env"]["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert options["stdout"] == host_module.subprocess.DEVNULL
    assert options["stderr"] == host_module.subprocess.DEVNULL


@pytest.mark.skipif(os.name == "nt", reason="Runtime image permissions require POSIX modes")
def test_extracted_source_is_readable_by_non_root_runtime_under_private_umask(tmp_path):
    workspace = tmp_path / "private-build"
    workspace.mkdir(mode=0o700)
    archive = workspace / "source.tar.gz"
    source_archive(archive)
    old_mask = os.umask(0o077)
    try:
        HostUpdater._extract_source(archive, workspace / "source")
    finally:
        os.umask(old_mask)
    assert stat.S_IMODE(workspace.stat().st_mode) == 0o700
    for path in (workspace / "source").rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644)


def test_configuration_copy_preserves_ownership_of_directories_and_files(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "private").mkdir(parents=True)
    (source / "private/token").write_text("test-only")
    host_module.shutil.copytree(source, destination)
    calls = []
    monkeypatch.setattr(
        host_module.os,
        "chown",
        lambda path, uid, gid, **kwargs: calls.append((path, uid, gid, kwargs)),
        raising=False,
    )
    HostUpdater._copy_ownership(source, destination)
    assert {call[0] for call in calls} == {
        destination,
        destination / "private",
        destination / "private/token",
    }
    for path, uid, gid, kwargs in calls:
        expected = (source / path.relative_to(destination)).stat()
        assert (uid, gid) == (expected.st_uid, expected.st_gid)
        assert kwargs == {"follow_symlinks": False}


def test_source_image_smoke_failure_never_stops_existing_services(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    original = updater.compose.read_bytes()
    runner = updater.runner

    def fail_smoke(args, capture=True):
        if args[:2] == ["docker", "run"]:
            raise ValueError("simulated unreadable runtime source")
        return runner(args, capture)

    updater.runner = fail_smoke
    updater.process()
    assert not any("stop" in args for args in commands)
    assert updater.compose.read_bytes() == original
    assert updater.installed_version.read_text().strip() == "0.3.0"
    assert json.loads((root / "updates/status.json").read_text())["state"] == "failed"
