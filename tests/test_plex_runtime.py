import asyncio
import io
import tarfile
from types import SimpleNamespace

import pytest
from mediahub.errors import DomainError

from agent.plex_runtime import PlexRuntime


@pytest.mark.parametrize("reinstall", [False, True])
def test_fresh_install_pulls_latest_pins_result_and_removes_prepare_helper(tmp_path, monkeypatch, reinstall):
    from unittest.mock import AsyncMock, Mock

    from mediahub.apps.plex import PlexInstallation, PlexInstallRequest

    from agent.plex_install import PlexInstallPolicy, installation_plan

    policy = PlexInstallPolicy(
        hostId="local", bindAddress="192.168.1.10",
        image="lscr.io/linuxserver/plex@sha256:" + "a" * 64,
        initImage="sha256:" + "b" * 64,
        storage={kind: {"label": kind, "kind": kind, "path": str(tmp_path / kind)}
                 for kind in ("movies", "tv", "appdata")},
        hostMountSnapshot=str(tmp_path / "snapshot"),
        requiredFilesystemUuids={str(tmp_path): "verified-media"},
        storageMarkers={str(tmp_path / "marker"): "verified-media"},
    )
    control = SimpleNamespace(
        lock=asyncio.Lock(), socket="unused", policy_file=tmp_path / "managed.json",
        storage_verified=AsyncMock(return_value=True), save_intent=Mock(), record=Mock(),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.policy = lambda: policy
    runtime.reset_configuration = AsyncMock()
    runtime.helper = AsyncMock(return_value="owned-prepare-helper")
    runtime.archive_write = AsyncMock()
    publisher = "lscr.io/linuxserver/plex@sha256:" + "c" * 64
    pull = AsyncMock(return_value={"Id": "sha256:" + "d" * 64, "RepoDigests": [publisher]})
    monkeypatch.setattr("agent.plex_runtime.pull_latest", pull)
    calls = []

    async def request(method, path, body=None, **kwargs):
        calls.append((method, path))
        if path.startswith("/containers/json?"):
            return []
        if path == "/volumes":
            assert runtime.operation["phase"] == "storage"
            assert runtime.operation["progress"] == 50
            return {"Volumes": [{**plan["runtimeVolume"], "Options": plan["runtimeVolume"]["DriverOpts"]}] if reinstall else []}
        if path.startswith("/containers/create"):
            assert runtime.operation["phase"] == "container"
            assert runtime.operation["progress"] == 80
            assert body["Image"] == publisher
        if path == "/containers/mediahub-plex-main/start":
            assert runtime.operation["phase"] == "start"
            assert runtime.operation["progress"] == 90
        if path.endswith("/json"):
            return {"Mounts": []}
        return {}

    runtime.request = request
    spec = PlexInstallation(moviesStorageIds=["movies"], appdataStorageId="appdata")
    plan = installation_plan(policy, spec)
    if reinstall:
        from agent.install_files import save_json
        control.policy_file.write_text("retained ownership policy")
        control.policy = lambda: SimpleNamespace(installationId=spec.installationId, vpnEnabled=False)
        save_json(tmp_path / "plex-removal.json", {"installationId": spec.installationId})
        runtime.vault.put(spec.installationId, b'<Preferences MachineIdentifier="preserved-identity"/>')
    assert plan["container"]["Image"] == "lscr.io/linuxserver/plex:latest"
    async def run():
        result = await runtime.queue_install(PlexInstallRequest(
            installation=spec, reviewedPlanDigest=plan["planDigest"],
        ))
        pull.assert_not_awaited()
        await runtime.install_task
        assert runtime.operation["state"] == "succeeded"
        assert runtime.operation["progress"] == 100
        assert runtime.operation["phase"] == "complete"
        assert runtime.operation["indeterminate"] is False
        return result

    result = asyncio.run(run())
    assert result["state"] == "accepted"
    pull.assert_awaited_once_with("unused", "lscr.io/linuxserver/plex")
    assert calls[-2:] == [("POST", "/containers/owned-prepare-helper/stop?t=2"),
                          ("DELETE", "/containers/owned-prepare-helper")]
    assert not any("/images/" in path and method == "DELETE" for method, path in calls)
    assert not list(tmp_path.glob(".metadata-*"))
    if reinstall:
        assert b'preserved-identity' not in runtime.vault.get(spec.installationId)
        assert not (tmp_path / "plex-removal.json").exists()
        assert not any(path == "/volumes/create" for _, path in calls)
        assert not any(method == "DELETE" and path.startswith("/volumes/") for method, path in calls)



def test_queued_install_failure_is_visible_and_survives_restart(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from agent.plex_control import PlexControl

    control = SimpleNamespace(lock=asyncio.Lock(), policy_file=tmp_path / "missing.json")
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.policy = lambda: SimpleNamespace(hostId="local")
    monkeypatch.setattr("agent.plex_runtime.installation_plan", lambda *args: {"planDigest": "reviewed"})
    async def fail_install(_):
        runtime.install_progress("download", 10, "Downloading app image", indeterminate=True)
        from agent.install_files import read_json
        persisted = read_json(runtime.install_operation_path)
        assert persisted["phase"] == "download"
        assert persisted["indeterminate"] is True
        raise DomainError("download_failed", "Image download failed", 503)

    runtime.install = AsyncMock(side_effect=fail_install)
    body = SimpleNamespace(installation=SimpleNamespace(installationId="plex-test"), reviewedPlanDigest="reviewed")

    async def run():
        assert (await runtime.queue_install(body))["state"] == "accepted"
        with pytest.raises(DomainError, match="Another Plex operation"):
            await runtime.queue_install(body)
        await runtime.install_task

    asyncio.run(run())
    restarted = PlexRuntime(control, None, tmp_path)
    assert restarted.operation["state"] == "failed"
    assert restarted.operation["phase"] == "download"
    assert restarted.operation["progress"] == 10
    assert restarted.operation["indeterminate"] is False
    report = asyncio.run(PlexControl.status(SimpleNamespace(runtime=restarted, policy_file=control.policy_file)))
    assert report["health"] == "unknown"
    assert report["operation"]["message"] == "Image download failed"


@pytest.mark.parametrize("status,path,code", [
    (404, "/images/approved-image/json", "plex_image_missing"),
    (500, "/images/approved-image/json", "plex_provision_failed"),
    (404, "/containers/plex/json", "plex_provision_failed"),
])
def test_missing_install_image_has_actionable_error_without_docker_details(
    tmp_path, monkeypatch, status, path, code
):
    import httpx

    original = httpx.AsyncClient

    def client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(status, json={"message": "private-runtime-detail"})
        )
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    runtime = PlexRuntime(SimpleNamespace(socket="unused"), None, tmp_path)
    with pytest.raises(DomainError) as error:
        asyncio.run(runtime.request("GET", path))
    assert error.value.code == code
    assert "private-runtime-detail" not in str(error.value)


def archive(content, kind=tarfile.REGTYPE):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as stream:
        entry = tarfile.TarInfo("Preferences.xml")
        entry.size, entry.type = len(content), kind
        stream.addfile(entry, io.BytesIO(content))
    return output.getvalue()


def test_preferences_are_encrypted_and_not_public(tmp_path):
    runtime = PlexRuntime(None, None, tmp_path)
    secret = b'<Preferences PlexOnlineToken="unit-test-private-token" />'

    async def request(*args, **kwargs):
        if args[1].startswith("/exec/") and args[1].endswith("/json"):
            return {"ExitCode": 0}
        if args[1].endswith("/json"):
            return {"State": {"Running": True}}
        if args[1].endswith("/exec"):
            return {"Id": "test-exec"}
        return b"\x01\0\0\0" + len(secret).to_bytes(4, "big") + secret

    runtime.request = request
    policy = SimpleNamespace(container="test-plex", installationId="plex-test")
    asyncio.run(runtime.checkpoint(policy))
    assert runtime.vault.get("plex-test") == secret
    for path in (tmp_path / "plex-secrets").iterdir():
        assert b"unit-test-private-token" not in path.read_bytes()
    secret = b'<Preferences PlexOnlineToken="rotated-private-token" />'
    asyncio.run(runtime.checkpoint(policy))
    assert runtime.vault.get("plex-test") == secret


@pytest.mark.parametrize(
    "content",
    [
        b"broken XML",
        b"<NotPreferences/>",
        b"",
        b"x" * 131073,
    ],
    ids=["invalid-xml", "wrong-root", "empty", "oversize"],
)
def test_preferences_reject_invalid_runtime_output(tmp_path, content):
    runtime = PlexRuntime(None, None, tmp_path)

    async def request(*args, **kwargs):
        if args[1].startswith("/exec/") and args[1].endswith("/json"):
            return {"ExitCode": 0}
        if args[1].endswith("/json"):
            return {"State": {"Running": True}}
        if args[1].endswith("/exec"):
            return {"Id": "test-exec"}
        return b"\x01\0\0\0" + len(content).to_bytes(4, "big") + content

    runtime.request = request
    with pytest.raises(DomainError):
        asyncio.run(runtime.preferences(SimpleNamespace(container="test-plex")))


def test_restore_tar_has_private_permissions(tmp_path):
    runtime = PlexRuntime(None, None, tmp_path)
    seen = []

    async def request(*args, **kwargs):
        with tarfile.open(fileobj=io.BytesIO(kwargs["payload"])) as stream:
            seen.extend(stream.getmembers())

    runtime.request = request
    asyncio.run(runtime.archive_write("test-helper", {"Preferences.xml": b"test"}, 1000, 1000))
    assert len(seen) == 1
    assert seen[0].mode == 0o600
    assert seen[0].uid == seen[0].gid == 1000


@pytest.mark.parametrize("new_image", [False, True])
def test_update_check_uses_publisher_digest_without_mutation(tmp_path, new_image):
    from unittest.mock import AsyncMock

    installed = "sha256:" + "a" * 64
    latest = "sha256:" + ("b" if new_image else "a") * 64
    image = "lscr.io/linuxserver/plex@" + installed
    policy = SimpleNamespace(imageId="sha256:" + "c" * 64)
    control = SimpleNamespace(
        policy=lambda: policy,
        lock=asyncio.Lock(),
        inspect=AsyncMock(return_value={"Config": {"Image": image}}),
        plex_get=AsyncMock(),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.request = AsyncMock(
        side_effect=[
            {"RepoDigests": [image], "Os": "linux", "Architecture": "amd64"},
            {
                "Descriptor": {
                    "digest": latest,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                },
                "Platforms": [{"os": "linux", "architecture": "amd64"}],
            },
            {
                "Descriptor": {
                    "digest": installed,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                }
            },
        ]
    )
    result = asyncio.run(runtime.update_check())
    assert result["supported"] is True
    assert result["updateAvailable"] is new_image
    assert result["updateSource"] == "container-image"
    assert result["installedVersion"] == installed
    assert result["latestVersion"] == latest
    assert not result["downloadRequested"] and not result["installationRequested"]
    assert all(call.args[0] == "GET" for call in runtime.request.call_args_list)
    assert (
        runtime.request.call_args_list[1].args[1]
        == "/distribution/lscr.io/linuxserver/plex:latest/json"
    )
    control.plex_get.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        "unsupported",
        "unknown-installed",
        "unknown-latest",
        "incompatible",
        "unavailable",
        "manifest-mismatch",
        "missing-platform",
    ],
)
def test_update_check_unknown_or_unsupported_cannot_enable_update(tmp_path, case):
    from unittest.mock import AsyncMock

    image = "lscr.io/linuxserver/plex@sha256:" + "a" * 64
    control = SimpleNamespace(
        policy=lambda: SimpleNamespace(imageId="sha256:" + "c" * 64),
        lock=asyncio.Lock(),
        inspect=AsyncMock(
            return_value={"Config": {"Image": "other:latest" if case == "unsupported" else image}}
        ),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.request = AsyncMock(
        side_effect=[
            {
                "RepoDigests": [] if case == "unknown-installed" else [image],
                "Os": "linux",
                "Architecture": "amd64",
            },
            DomainError("plex_provision_failed", "Unavailable", 503)
            if case == "unavailable"
            else {
                "Descriptor": {
                    "digest": "unknown" if case == "unknown-latest" else "sha256:" + "b" * 64,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                },
                "Platforms": []
                if case == "missing-platform"
                else [
                    {"os": "linux", "architecture": "arm64" if case == "incompatible" else "amd64"}
                ],
            },
            {
                "Descriptor": {
                    "digest": "sha256:" + "a" * 64,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                }
            },
        ]
    )
    if case in ("unknown-latest", "unavailable"):
        with pytest.raises(DomainError):
            asyncio.run(runtime.update_check())
    else:
        result = asyncio.run(runtime.update_check())
        assert result["supported"] is False
        assert result["updateAvailable"] is False
        assert result["reason"]
    assert all(call.args[0] == "GET" for call in runtime.request.call_args_list)


def test_update_same_image_does_not_stop_restart_or_snapshot(tmp_path):
    from unittest.mock import AsyncMock, Mock

    policy = SimpleNamespace(imageId="sha256:" + "a" * 64)
    control = SimpleNamespace(
        policy=lambda: policy,
        lock=asyncio.Lock(),
        inspect=AsyncMock(return_value={"State": {"Running": True}}),
        storage_verified=AsyncMock(return_value=True),
        save_intent=Mock(),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.pull_image = AsyncMock(return_value={"Id": policy.imageId})
    runtime.stop = AsyncMock()
    runtime.start = AsyncMock()
    runtime.snapshot_appdata = AsyncMock()
    runtime.request = AsyncMock()
    asyncio.run(runtime._update())
    assert runtime.operation == {"state": "succeeded", "message": "Plex is already up to date"}
    runtime.stop.assert_not_called()
    runtime.start.assert_not_called()
    runtime.snapshot_appdata.assert_not_called()
    runtime.request.assert_not_called()
    control.save_intent.assert_not_called()


def test_concurrent_updates_admit_only_one_background_transaction(tmp_path):
    from unittest.mock import AsyncMock

    async def scenario():
        inspected = 0
        both_entered = asyncio.Event()
        finish = asyncio.Event()

        async def inspect(_):
            nonlocal inspected
            inspected += 1
            if inspected == 2:
                both_entered.set()
            await both_entered.wait()
            return {}

        async def transaction():
            await finish.wait()

        control = SimpleNamespace(policy=lambda: None, inspect=inspect)
        runtime = PlexRuntime(control, None, tmp_path)
        runtime._update = AsyncMock(side_effect=transaction)
        results = await asyncio.gather(runtime.update(), runtime.update(), return_exceptions=True)
        assert (
            sum(
                isinstance(result, DomainError) and result.code == "plex_busy" for result in results
            )
            == 1
        )
        assert sum(isinstance(result, dict) for result in results) == 1
        finish.set()
        await runtime.update_task
        runtime._update.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("receipt,containers,expected", [
    (None, [], False),
    ({"installationId": "other-install"}, [], False),
    ({"installationId": "plex-test"}, [{"Id": "still-present"}], False),
    ({"installationId": "plex-test"}, [], True),
])
def test_reinstall_requires_matching_removal_and_absent_owned_containers(tmp_path, receipt, containers, expected):
    from unittest.mock import AsyncMock

    from agent.install_files import save_json

    policy_file = tmp_path / "managed.json"
    policy_file.write_text("retained ownership")
    control = SimpleNamespace(policy_file=policy_file, policy=lambda: SimpleNamespace(
        installationId="plex-test", vpnEnabled=False))
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.request = AsyncMock(return_value=containers)
    runtime.reset_configuration = AsyncMock()
    if receipt is not None:
        save_json(tmp_path / "plex-removal.json", receipt)
    assert asyncio.run(runtime.can_reinstall("plex-test")) is expected
    assert asyncio.run(runtime.can_reinstall("other-install")) is False
    assert policy_file.read_text() == "retained ownership"
    assert not any(call.args[0] != "GET" for call in runtime.request.await_args_list)


@pytest.mark.parametrize('owned', [True, False])
def test_reinstall_recovers_only_stopped_owned_prepare_helper(tmp_path, owned):
    from unittest.mock import AsyncMock
    from agent.install_files import save_json, read_json
    policy_file = tmp_path / 'managed.json'
    policy_file.write_text('retained')
    policy = SimpleNamespace(installationId='plex-test', vpnEnabled=False)
    runtime = PlexRuntime(SimpleNamespace(policy_file=policy_file, policy=lambda: policy), None, tmp_path)
    save_json(tmp_path / 'plex-removal.json', {'installationId': 'plex-test'})
    helper = {'Id': 'helper', 'Names': ['/mediahub-plex-test-prepare']}
    actual = {'Name': '/mediahub-plex-test-prepare', 'State': {'Running': False},
              'Config': {'Labels': {'org.mediahub.package': 'org.mediahub.plex' if owned else 'foreign', 'org.mediahub.installation': 'plex-test'}}}
    runtime.request = AsyncMock(side_effect=[[helper], actual, {}, []] if owned else [[helper], actual])
    runtime.reset_configuration = AsyncMock()
    assert asyncio.run(runtime.can_reinstall('plex-test')) is owned
    if owned:
        assert runtime.request.call_args_list[2].args == ('DELETE', '/containers/helper?force=false&v=false')
        runtime.reset_configuration.assert_awaited_once_with('plex-test')
        assert read_json(tmp_path / 'plex-removal.json')['configurationReset']
    else:
        runtime.reset_configuration.assert_not_awaited()
        assert all(call.args[0] == 'GET' for call in runtime.request.call_args_list)


def test_exited_preparation_helper_is_deleted_after_stop_reports_already_stopped(tmp_path):
    from unittest.mock import AsyncMock
    runtime = PlexRuntime(SimpleNamespace(), None, tmp_path)
    runtime.request = AsyncMock(side_effect=[DomainError('stopped', 'Already stopped', 409), {}])
    asyncio.run(runtime.remove_helper('owned-prepare'))
    assert runtime.request.call_args_list[-1].args == ('DELETE', '/containers/owned-prepare')


@pytest.mark.parametrize("running,mounted,matching", [(True, True, True), (False, True, True), (True, False, True), (True, True, False)])
def test_failed_start_recovery_requires_owned_running_runtime_and_storage(tmp_path, running, mounted, matching):
    from unittest.mock import AsyncMock
    policy = SimpleNamespace(installationId='plex-main' if matching else 'other-plex')
    control = SimpleNamespace(policy=lambda: policy,
                              inspect=AsyncMock(return_value={'State': {'Running': running}}),
                              storage_verified=AsyncMock(return_value=mounted))
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.operation = {'action': 'install', 'state': 'failed', 'phase': 'start', 'installationId': 'plex-main'}
    result = asyncio.run(runtime.installation_status())['operation']
    assert (result['state'] == 'succeeded') is (running and mounted and matching)
    if not matching:
        control.inspect.assert_not_called()
