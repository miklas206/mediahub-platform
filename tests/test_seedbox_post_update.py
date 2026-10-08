import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent.seedbox_control import SeedboxControl


@pytest.mark.parametrize(
    "running,latched,expected", [(True, False, 1), (False, False, 0), (True, True, 0)]
)
def test_restart_once_per_commit_respects_stopped_runtime(monkeypatch, running, latched, expected):
    async def scenario():
        monkeypatch.setenv("MEDIAHUB_SOURCE_COMMIT", "new-commit")
        control = SeedboxControl(None, None, None, None)
        control.initialize = Mock()
        control.driver = SimpleNamespace(binding=Mock())
        control.lifecycle = SimpleNamespace(
            state={
                "desiredRunning": running,
                "manualIntervention": ["vpn"] if latched else [],
                "runtimeAgentCommit": "old-commit",
            },
            persist=Mock(),
        )

        async def perform(action):
            assert action == "restart"
            assert control.lifecycle.state["runtimeAgentCommit"] == "new-commit"
            control.operation["state"] = "succeeded"

        control.perform = AsyncMock(side_effect=perform)
        control.emit = Mock()
        await control.restart_after_update()
        await control.restart_after_update()
        assert control.perform.await_count == expected

    asyncio.run(scenario())
