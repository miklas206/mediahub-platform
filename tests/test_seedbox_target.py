import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.seedbox_wizard_api import TargetSelection, choose_target
from sqlalchemy import select


def test_target_requires_https_and_remote_host(logged_in):
    request = SimpleNamespace(app=logged_in.app, url=SimpleNamespace(scheme="http"))
    with pytest.raises(DomainError):
        asyncio.run(choose_target(TargetSelection(hostId="dedicated"), request))
    request.url.scheme = "https"
    with pytest.raises(DomainError):
        asyncio.run(choose_target(TargetSelection(hostId="local"), request))


def test_target_requires_matching_policy_and_rw_mapping(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    request = SimpleNamespace(app=logged_in.app, url=SimpleNamespace(scheme="https"))
    installation = {"hostId": "dedicated", "downloadsStorageId": "downloads"}
    client = SimpleNamespace(
        config=SimpleNamespace(agent_url="https://agent.invalid"),
        request=AsyncMock(return_value={"installation": installation}),
    )
    monkeypatch.setattr(svc.hosts, "client", lambda _: client)
    with pytest.raises(DomainError):
        asyncio.run(choose_target(TargetSelection(hostId="dedicated"), request))
    # Wrong host identity cannot bind even when the response came over TLS.
    installation["hostId"] = "different"
    with pytest.raises(DomainError):
        asyncio.run(choose_target(TargetSelection(hostId="dedicated"), request))
    with svc.sessions() as db:
        assert db.scalar(select(Setting).where(Setting.key == "seedbox_installation")) is None
