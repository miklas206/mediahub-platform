import hashlib
import io
import json
import os
import stat
import sys
import tarfile
from types import SimpleNamespace

import pytest

import scripts.platform_update_host as host_module
from scripts.platform_update_host import HostUpdater, version_key

OPERATION = "a" * 32
CORE_REPOSITORY = "ghcr.io/example/mediahub-core"
AGENT_REPOSITORY = "ghcr.io/example/mediahub-agent"


def test_build_console_streams_output_and_propagates_failed_exit(tmp_path):
    lines = []
    source = tmp_path / "source"
    source.mkdir()
    HostUpdater._stream_build(
        [sys.executable, "-c", "print('#1 CACHED'); print('#2 DONE')", str(source)],
        dict(os.environ),
        lines.extend,
    )
    assert lines == ["#1 CACHED", "#2 DONE"]
    with pytest.raises(host_module.subprocess.CalledProcessError):
        HostUpdater._stream_build(
            [sys.executable, "-c", "import sys; print('build failed'); sys.exit(1)", str(source)],
            dict(os.environ),
            lines.extend,
        )
    assert lines[-1] == "build failed"
    assert list(tmp_path.iterdir()) == [source]


def test_build_console_redacts_secrets_and_bounds_status_size(tmp_path):
    updater = HostUpdater(tmp_path)
    for line in [
        "token=private-token",
        "Authorization: Bearer private-auth",
        "https://user:password@example.com/repo?secret=abc",
        "ghp_private",
        "-----BEGIN PRIVATE KEY-----",
        "private-key-body",
        "-----END PRIVATE KEY-----",
    ]:
        updater._append_log(line)
    output = "\n".join(updater.log_lines)
    for secret in (
        "private-token",
        "private-auth",
        "user:password",
        "abc",
        "ghp_private",
        "private-key-body",
    ):
        assert secret not in output
    for _ in range(100):
        updater._append_log("\u4e00" * 2000)
    assert len(updater.log_lines) == 40
    assert len(json.dumps({"logs": updater.log_lines})) < 60000


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
            if args[3] == "{{.Image}}":
                return "sha256:" + "4" * 64
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
    assert json.loads((root / "updates/status.json").read_text())["updateMode"] == "full"


def cached_source_updater(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    extracted = tmp_path / "fingerprint-source"
    updater._extract_source(updater.test_stage / "mediahub-source.tar.gz", extracted)
    cache = {
        "agentFingerprint": updater._agent_fingerprint(extracted),
        "agentImage": "sha256:" + "4" * 64,
    }
    (root / "agent-build-cache.json").write_text(json.dumps(cache), encoding="utf-8")
    compose = json.loads(updater.compose.read_text())
    compose["services"]["agent"]["image"] = cache["agentImage"]
    updater.compose.write_text(json.dumps(compose), encoding="utf-8")
    return updater, root, commands


def test_unchanged_agent_is_not_built_stopped_recreated_or_snapshotted(tmp_path, monkeypatch):
    updater, root, commands = cached_source_updater(tmp_path, monkeypatch)
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "succeeded"
    builds = [args for args in commands if args[:2] == ["docker", "build"]]
    assert len(builds) == 1 and "mediahub-core:" in builds[0][builds[0].index("--tag") + 1]
    mutations = [
        args
        for args in commands
        if args[:2] == ["docker", "compose"] and ("stop" in args or "up" in args)
    ]
    assert mutations and all("agent" not in args for args in mutations)
    backup = root / "update-backups" / OPERATION
    assert (backup / "data/mediahub.db").is_file()
    assert not (backup / "agent").exists()
    status = json.loads((root / "updates/status.json").read_text())
    assert status["updateMode"] == "fast"
    assert status["changedServices"] == ["core"]
    assert "only Core" in status["updateReason"]
    assert any(step["label"] == "Fast update: build Core only" for step in status["steps"])


@pytest.mark.parametrize("invalid", ["corrupt", "changed", "different-image", "missing-image"])
def test_agent_cache_miss_builds_and_updates_both_roles(tmp_path, monkeypatch, invalid):
    updater, root, commands = cached_source_updater(tmp_path, monkeypatch)
    cache_path = root / "agent-build-cache.json"
    cache = json.loads(cache_path.read_text())
    if invalid == "corrupt":
        cache_path.write_text("invalid json")
    elif invalid == "changed":
        cache["agentFingerprint"] = "0" * 64
        cache_path.write_text(json.dumps(cache))
    elif invalid == "different-image":
        cache["agentImage"] = "sha256:" + "5" * 64
        cache_path.write_text(json.dumps(cache))
    else:
        runner = updater.runner

        def missing_image(args, capture=True):
            if args[:3] == ["docker", "image", "inspect"] and args[-1] == cache["agentImage"]:
                raise ValueError("Image removed")
            return runner(args, capture)

        updater.runner = missing_image
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "succeeded"
    assert len([args for args in commands if args[:2] == ["docker", "build"]]) == 2
    assert any("stop" in args and "agent" in args for args in commands)


def test_core_only_rollback_preserves_running_agent_state(tmp_path, monkeypatch):
    updater, root, commands = cached_source_updater(tmp_path, monkeypatch)
    original_compose = updater.compose.read_bytes()
    original_cache = (root / "agent-build-cache.json").read_bytes()
    wait = updater._wait
    failed = False

    def fail_once(service, health=False, timeout=150):
        nonlocal failed
        if service == "core" and health and not failed:
            failed = True
            (root / "agent/state.json").write_text("Agent continued working")
            raise ValueError("Core unhealthy")
        return wait(service, health, timeout)

    updater._wait = fail_once
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "rolled_back"
    assert updater.compose.read_bytes() == original_compose
    assert (root / "agent-build-cache.json").read_bytes() == original_cache
    assert (root / "agent/state.json").read_text() == "Agent continued working"
    assert not any("agent" in args and ("up" in args or "stop" in args) for args in commands)


@pytest.mark.parametrize("drift", ["running-image", "stopped", "missing-container"])
def test_fast_update_requires_the_verified_agent_to_be_running(tmp_path, monkeypatch, drift):
    updater, root, commands = cached_source_updater(tmp_path, monkeypatch)
    runner = updater.runner

    def drifted(args, capture=True):
        if drift == "missing-container" and args[:2] == ["docker", "compose"] and "ps" in args:
            return ""
        if args[:2] == ["docker", "inspect"]:
            if drift == "running-image" and args[3] == "{{.Image}}":
                return "sha256:" + "9" * 64
            if drift == "stopped" and args[3] == "{{.State.Running}}":
                return "false"
        return runner(args, capture)

    updater.runner = drifted
    updater._wait = lambda *args, **kwargs: None
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["updateMode"] == "full"
    assert len([args for args in commands if args[:2] == ["docker", "build"]]) == 2


@pytest.mark.parametrize(
    "copy", ["COPY agent/ ./agent/", 'COPY ["agent/", "./agent/"]', "COPY\tagent/ ./agent/"]
)
def test_agent_fingerprint_follows_recipe_inputs_including_new_directories(tmp_path, copy):
    (tmp_path / "docker").mkdir()
    (tmp_path / "agent").mkdir()
    (tmp_path / "apps").mkdir()
    (tmp_path / "agent/main.py").write_text("agent = 1")
    app = tmp_path / "apps/catalog.json"
    app.write_text("old")
    recipe = tmp_path / "docker/Agent.Dockerfile"
    recipe.write_text("FROM python\n" + copy + "\n")
    baseline = HostUpdater._agent_fingerprint(tmp_path)
    assert baseline is not None
    app.write_text("new")
    assert HostUpdater._agent_fingerprint(tmp_path) == baseline
    recipe.write_text(recipe.read_text() + "COPY apps/ ./apps/\n")
    with_apps = HostUpdater._agent_fingerprint(tmp_path)
    assert with_apps != baseline
    app.write_text("newer")
    assert HostUpdater._agent_fingerprint(tmp_path) != with_apps
    before_directory = HostUpdater._agent_fingerprint(tmp_path)
    (tmp_path / "agent/empty").mkdir()
    assert HostUpdater._agent_fingerprint(tmp_path) != before_directory
    before_ignore = HostUpdater._agent_fingerprint(tmp_path)
    (tmp_path / ".dockerignore").write_text("agent/empty\n")
    assert HostUpdater._agent_fingerprint(tmp_path) != before_ignore


@pytest.mark.parametrize(
    "recipe",
    [
        "COPY $INPUT /app/",
        "COPY *.py /app/",
        "COPY --from=builder /output /app/",
        "RUN --mount=type=bind,target=/src build",
        "ONBUILD COPY . /app/",
        "COPY missing /app/",
        "COPY ../outside /app/",
        "ADD https://example.com/code /app/",
        "# escape=`\nCOPY agent /app/",
        "COPY <<EOF /app/code\nexample\nEOF",
    ],
)
def test_unknown_agent_recipe_disables_fast_reuse(tmp_path, recipe):
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker/Agent.Dockerfile").write_text("FROM python\n" + recipe + "\n")
    assert HostUpdater._agent_fingerprint(tmp_path) is None
    assert HostUpdater(tmp_path)._reusable_agent(None) is None


def test_agent_fingerprint_ignores_ui_and_release_version_but_tracks_runtime(tmp_path):
    source = tmp_path / "source"
    for name in ("frontend", "backend/mediahub", "agent", "docker"):
        (source / name).mkdir(parents=True, exist_ok=True)
    files = {
        "pyproject.toml": '[project]\nversion = "0.4.17"\n',
        "backend/mediahub/__init__.py": '__version__ = "0.4.17"\n',
        "backend/mediahub/api.py": "shared = 1\n",
        "agent/main.py": "agent = 1\n",
        "requirements.lock": "dependency==1\n",
        "docker/Agent.Dockerfile": "FROM python\nCOPY pyproject.toml requirements.lock ./\nCOPY backend/ ./backend/\nCOPY agent/ ./agent/\n",
        "frontend/package.json": '{"version":"0.4.17"}',
        "frontend/ui.tsx": "old UI",
        "docker/Dockerfile": "old Core recipe",
    }
    for name, content in files.items():
        (source / name).write_text(content, encoding="utf-8")
    fingerprint = HostUpdater._agent_fingerprint(source)
    for name in ("pyproject.toml", "backend/mediahub/__init__.py", "frontend/package.json"):
        path = source / name
        path.write_text(path.read_text().replace("0.4.17", "0.4.18"), encoding="utf-8")
    (source / "frontend/ui.tsx").write_text("new UI")
    (source / "docker/Dockerfile").write_text("new Core recipe")
    assert HostUpdater._agent_fingerprint(source) == fingerprint
    for name in (
        "agent/main.py",
        "backend/mediahub/api.py",
        "requirements.lock",
        "docker/Agent.Dockerfile",
    ):
        path = source / name
        original = path.read_bytes()
        path.write_bytes(original + b"changed\n")
        assert HostUpdater._agent_fingerprint(source) != fingerprint
        path.write_bytes(original)
    (source / "agent/main.py").unlink()
    assert HostUpdater._agent_fingerprint(source) != fingerprint


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
    status = json.loads((root / "updates/status.json").read_text())
    assert status["state"] == "failed"
    assert "0.00 GiB free" in status["message"]
    assert "8 GiB required" in status["message"]
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


def test_same_version_commit_update_and_duplicate_rejection(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    updater.installed_version.write_text("0.4.0")
    updater.test_request.update(schemaVersion=3, fromVersion="0.4.0", fromCommit="b" * 40)
    updater.test_manifest["schemaVersion"] = 3
    updater.write_installed_source({"repository": "example/mediahub", "commit": "b" * 40})
    updater.process()
    assert updater.installed_source()["commit"] == "a" * 40
    assert json.loads((root / "updates/status.json").read_text())["state"] == "succeeded"
    commands.clear()
    updater.test_request["fromCommit"] = "a" * 40
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "failed"
    assert not any("stop" in args for args in commands)


def test_commit_marker_preserved_when_new_source_fails_health(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    updater.installed_version.write_text("0.4.0")
    updater.test_request.update(schemaVersion=3, fromVersion="0.4.0", fromCommit="b" * 40)
    updater.test_manifest["schemaVersion"] = 3
    updater.write_installed_source({"repository": "example/mediahub", "commit": "b" * 40})
    wait = updater._wait
    failed = False

    def fail_once(service, health=False, timeout=150):
        nonlocal failed
        if service == "core" and health and not failed:
            failed = True
            raise ValueError("New core failed")
        return wait(service, health, timeout)

    updater._wait = fail_once
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "rolled_back"
    assert updater.installed_source()["commit"] == "b" * 40
    assert updater.installed_version.read_text() == "0.4.0"


def test_schema3_request_is_validated_before_becoming_running(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    request = dict(updater.test_request, schemaVersion=3, fromCommit="b" * 40)
    manifest = dict(updater.test_manifest, schemaVersion=3)
    manifest_path = updater.test_stage / "mediahub-source-release.json"
    manifest_path.write_text(json.dumps(manifest))
    request["manifestSha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    request_path = root / "updates/request.json"
    request_path.write_text(json.dumps(request))
    accepted, source, stage = HostUpdater._validate_request(updater)
    assert accepted["fromCommit"] == "b" * 40
    assert source["schemaVersion"] == 3
    assert not request_path.exists()
    del request["fromCommit"]
    request_path.write_text(json.dumps(request))
    with pytest.raises(ValueError, match="Unexpected update request fields"):
        HostUpdater._validate_request(updater)


def test_commit_request_rejects_stale_installed_commit_before_stopping(tmp_path, monkeypatch):
    updater, root, commands = source_updater(tmp_path, monkeypatch)
    updater.test_request.update(schemaVersion=3, fromCommit="b" * 40)
    updater.test_manifest["schemaVersion"] = 3
    updater.write_installed_source({"repository": "example/mediahub", "commit": "c" * 40})
    updater.process()
    assert json.loads((root / "updates/status.json").read_text())["state"] == "failed"
    assert not any("stop" in args for args in commands)
