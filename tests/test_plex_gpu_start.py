import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError

from agent.plex_gpu_start import activate_relay, prepare_vendor


def setup(enabled=True, exit_code=0):
    ram = {"Type": "volume", "Source": "plex-runtime", "Target": "/config", "ReadOnly": False}
    plan = {"container": {"Labels": {"org.mediahub.plex.gpu.revision": "digest"} if enabled else {},
                          "HostConfig": {"Mounts": [ram, {"Target": "/media/private"}]}}}
    runtime = SimpleNamespace(policy=lambda: SimpleNamespace(uid=1000, gid=1000),
        request=AsyncMock(side_effect=[{}, {}, {"StatusCode": exit_code}]),
        remove_helper=AsyncMock())
    policy = SimpleNamespace(container="plex-main", imageId="sha256:current-official",
                             installationId="plex-main")
    return runtime, policy, plan


def test_fresh_install_without_sidecar_has_no_gpu_requirements():
    runtime, policy, plan = setup(False)
    asyncio.run(prepare_vendor(runtime, policy, plan))
    asyncio.run(activate_relay(runtime, policy, plan))
    runtime.request.assert_not_called()


@pytest.mark.parametrize("image", ["sha256:old-official", "sha256:updated-official"])
def test_each_start_prepares_fallback_from_exact_current_image_in_original_ram(image):
    runtime, policy, plan = setup()
    policy.imageId = image
    asyncio.run(prepare_vendor(runtime, policy, plan))
    body = runtime.request.call_args_list[0].kwargs["body"]
    assert body["Image"] == image and body["User"] == "1000:1000"
    assert body["HostConfig"]["Mounts"] == [plan["container"]["HostConfig"]["Mounts"][0]]
    assert body["HostConfig"]["NetworkMode"] == "none"
    assert body["HostConfig"]["ReadonlyRootfs"] is True
    assert "/usr/lib/plexmediaserver/lib" in body["Entrypoint"][-1]
    runtime.remove_helper.assert_awaited_once()


def test_failed_preparation_cleans_helper_and_blocks_start():
    runtime, policy, plan = setup(exit_code=1)
    with pytest.raises(DomainError, match="fallback"):
        asyncio.run(prepare_vendor(runtime, policy, plan))
    runtime.remove_helper.assert_awaited_once()


def test_fallback_never_copies_configuration_into_persistent_bind():
    runtime, policy, plan = setup()
    plan["container"]["HostConfig"]["Mounts"][0]["Type"] = "bind"
    with pytest.raises(DomainError, match="RAM"):
        asyncio.run(prepare_vendor(runtime, policy, plan))
    runtime.request.assert_not_called()


def test_connection_uses_fixed_owned_plex_executable_and_checks_exit():
    runtime, policy, plan = setup()
    runtime.request.side_effect = [{"Id": "owned-exec"}, b"", {"ExitCode": 0}]
    asyncio.run(activate_relay(runtime, policy, plan))
    first = runtime.request.call_args_list[0]
    assert first.args == ("POST", "/containers/plex-main/exec")
    assert first.kwargs["body"]["Cmd"] == [
        "/usr/lib/plexmediaserver/Plex Transcoder", "--mediahub-check"]
