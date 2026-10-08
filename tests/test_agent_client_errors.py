import asyncio
from types import SimpleNamespace

import httpx
import pytest
from mediahub.agent_client import AgentClient
from mediahub.errors import DomainError


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "code,message",
    [
        (
            "storage_eacces",
            "Permission denied while creating folder: /media/Film/Movie (EACCES; Agent UID=10001, GID=10001, groups=[1000])",
        ),
        (
            "storage_erofs",
            "Storage is mounted read-only while creating folder: /media/Film/Movie (EROFS)",
        ),
        ("creation_disabled", "Directory creation is disabled on this agent"),
        ("path_not_allowed", "Path is outside the agent's approved storage roots"),
    ],
)
def test_403_keeps_agent_diagnosis_across_real_http_client(monkeypatch, stream, code, message):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, json={"code": code, "message": message})
    )

    def client(**kwargs):
        kwargs["transport"] = transport
        return original(**kwargs)

    monkeypatch.setattr("mediahub.agent_client.httpx.AsyncClient", client)
    agent = AgentClient(
        SimpleNamespace(agent_url="http://agent", agent_socket=None), token="x" * 48
    )

    async def content():
        yield b"test"

    with pytest.raises(DomainError) as caught:
        asyncio.run(
            agent.upload_chunk("session", "/media/Film", 0, content(), 4)
            if stream
            else agent.request("POST", "/v1/directories/create", {"path": "/media/Film/Movie"})
        )
    assert caught.value.status == 403
    assert caught.value.code == code
    assert caught.value.message == message


def test_authentication_stays_separate_and_does_not_echo_response():
    with pytest.raises(DomainError) as caught:
        AgentClient._response_body(httpx.Response(401, json={"message": "sensitive"}))
    assert caught.value.code == "agent_rejected"
    assert "authentication" in caught.value.message
    assert "sensitive" not in caught.value.message


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, text="<html>private proxy output</html>"),
        httpx.Response(403, json={"message": ["invalid"], "code": 42}),
        httpx.Response(403, json=None),
    ],
)
def test_malformed_denial_is_still_denial(response):
    with pytest.raises(DomainError) as caught:
        AgentClient._response_body(response)
    assert caught.value.status == 403
    assert caught.value.code == "agent_error"
    assert "private proxy" not in caught.value.message
