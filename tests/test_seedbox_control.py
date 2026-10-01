import asyncio
from types import SimpleNamespace

import pytest

from agent.seedbox_control import SeedboxControl


@pytest.fixture
def anyio_backend():
    return "asyncio"


def controller(tmp_path):
    installer = SimpleNamespace(policy=lambda: SimpleNamespace(workRoot=str(tmp_path)))
    return SeedboxControl(installer, None, lambda: {}, SimpleNamespace(cached=None))


def test_no_implicit_autostart_and_persisted_intent(tmp_path):
    control = controller(tmp_path)
    control.initialize()
    assert control.public()["desiredRunning"] is False
    control.lifecycle.state["desiredRunning"] = True
    control.lifecycle.persist()
    second = controller(tmp_path)
    second.initialize()
    assert second.public()["desiredRunning"] is True


@pytest.mark.parametrize("contents", ["not json", "{}", '{"desiredRunning":"true"}'])
def test_corrupt_state_is_not_reset_to_auto_start(tmp_path, contents):
    (tmp_path / "lifecycle.json").write_text(contents)
    with pytest.raises(ValueError):
        controller(tmp_path).initialize()


@pytest.mark.anyio
async def test_only_one_pending_action_and_no_raw_error(tmp_path):
    from mediahub.errors import DomainError

    control = controller(tmp_path)
    control.initialize()
    gate = asyncio.Event()

    async def action(name):
        await gate.wait()
        raise ValueError("private-key-must-not-escape")

    control.lifecycle.action = action
    assert (await control.submit("start"))["state"] == "accepted"
    with pytest.raises(DomainError):
        await control.submit("stop")
    gate.set()
    await control.job
    assert control.public()["operation"]["state"] == "failed"
    assert "private-key" not in str(control.public())


@pytest.mark.anyio
async def test_arbitrary_action_rejected_before_initialization(tmp_path):
    from mediahub.errors import DomainError

    control = controller(tmp_path)
    with pytest.raises(DomainError):
        await control.submit("delete-all")
    assert control.lifecycle is None


@pytest.mark.anyio
async def test_removed_status_requires_missing_containers_not_just_old_marker(tmp_path):
    from unittest.mock import AsyncMock

    import httpx

    from agent.install_files import save_json

    control = controller(tmp_path)
    control.initialize()
    control.driver.binding = lambda: (
        SimpleNamespace(workRoot=str(tmp_path)),
        SimpleNamespace(installationId="seedbox-test"),
    )
    assert (await control.uninstall_status())["state"] == "ready"
    save_json(tmp_path / "runtime-removal.json", {"installationId": "seedbox-test"})
    control.driver.container = AsyncMock(return_value={"Id": "still-present"})
    assert (await control.uninstall_status())["state"] == "ready"

    def missing(_):
        response = httpx.Response(404, request=httpx.Request("GET", "http://docker/container"))
        raise httpx.HTTPStatusError("missing", request=response.request, response=response)

    control.driver.container = AsyncMock(side_effect=missing)
    assert (await control.uninstall_status())["state"] == "succeeded"
