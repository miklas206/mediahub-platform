from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.seedbox_driver import ScopedDriver


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_removal_only_owned_stopped_containers_and_never_volumes():
    driver = ScopedDriver(None, None, None)
    driver.container = AsyncMock(
        side_effect=[
            {"Id": "torrent-id", "State": {"Running": False}},
            {"Id": "vpn-id", "State": {"Running": False}},
        ]
    )
    driver.request = AsyncMock()
    await driver.remove_runtime()
    assert [c.args[0] for c in driver.container.call_args_list] == ["torrent", "vpn"]
    assert [c.args for c in driver.request.call_args_list] == [
        ("DELETE", "/containers/torrent-id"),
        ("DELETE", "/containers/vpn-id"),
    ]
    assert all(
        c.kwargs["params"] == {"force": "false", "v": "false"}
        for c in driver.request.call_args_list
    )


@pytest.mark.anyio
async def test_removal_refuses_running_container():
    driver = ScopedDriver(None, None, None)
    driver.container = AsyncMock(return_value={"Id": "torrent-id", "State": {"Running": True}})
    driver.request = AsyncMock()
    with pytest.raises(ValueError):
        await driver.remove_runtime()
    driver.request.assert_not_called()


def test_destructive_flags_rejected():
    from agent.main import RemoveRuntimeRequest

    with pytest.raises(ValueError):
        RemoveRuntimeRequest(confirmedInstallationId="test-app", deleteDownloads=True)


@pytest.mark.anyio
async def test_uninstall_requires_exact_confirmation(tmp_path):
    from mediahub.errors import DomainError

    from agent.seedbox_control import SeedboxControl

    control = SeedboxControl(
        SimpleNamespace(policy=lambda: SimpleNamespace(workRoot=str(tmp_path))),
        None,
        None,
        SimpleNamespace(cached=None),
    )
    control.driver.binding = lambda: (None, SimpleNamespace(installationId="test-app"))
    with pytest.raises(DomainError):
        await control.uninstall("wrong")
    assert control.job is None


@pytest.mark.anyio
async def test_install_old_review_rejected_before_docker(tmp_path):
    from mediahub.errors import DomainError

    from agent.seedbox_control import SeedboxControl

    installer = SimpleNamespace(
        policy=lambda: SimpleNamespace(workRoot=str(tmp_path)),
        plan=lambda spec: {"digest": "new", "blockers": []},
    )
    control = SeedboxControl(installer, None, None, SimpleNamespace(cached=None))
    control.driver.binding = lambda: (None, "spec")
    with pytest.raises(DomainError):
        await control.install(SimpleNamespace(installation="spec", reviewedPlanDigest="old"))
    assert control.job is None
