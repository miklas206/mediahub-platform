import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from mediahub.agent_client import AgentClient
from mediahub.config import Config
from mediahub.errors import DomainError
from mediahub.main import create_app
from pydantic import ValidationError


@pytest.mark.parametrize(
    "url", ["https://agent:18767", "https://localhost:18767", "http://127.0.0.1:18767"]
)
def test_local_agent_supports_validated_https(url):
    assert Config(_env_file=None, agent_url=url).agent_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:18767",
        "https://user:pass@agent:18767",
        "https://agent:18767/path",
        "https://agent:18767?token=not-real",
        "ftp://agent:18767",
    ],
)
def test_local_agent_rejects_untrusted_transport(url):
    with pytest.raises(ValidationError):
        Config(_env_file=None, agent_url=url)


@pytest.mark.asyncio
async def test_embedded_runtime_uses_internal_transport_without_tls_files(tmp_path):
    runtime = FastAPI()
    token = "test-token-" + "a" * 48

    @runtime.get("/v1/status")
    async def status(request: Request):
        assert request.headers["authorization"] == "Bearer " + token
        return {"docker": {"available": True}}

    config = Config(_env_file=None, agent_ca_file=tmp_path / "missing-ca.pem")
    client = AgentClient(config, token=token, local_app=runtime)
    assert (await client.status())["connected"] is True


@pytest.mark.asyncio
async def test_embedded_runtime_preserves_policy_errors():
    runtime = FastAPI()

    @runtime.post("/v1/directories")
    async def denied():
        return JSONResponse({"code": "path_denied", "message": "Outside approved storage"}, 403)

    client = AgentClient(Config(_env_file=None), token="a" * 48, local_app=runtime)
    with pytest.raises(DomainError) as error:
        await client.request("POST", "/v1/directories", {"path": "/etc"})
    assert error.value.code == "path_denied"


def test_embedded_hub_starts_real_runtime_without_public_runtime_routes(tmp_path, monkeypatch):
    state = tmp_path / "runtime"
    state.mkdir()
    (state / "token").write_text("a" * 48)
    monkeypatch.setenv("MEDIAHUB_AGENT_STATE_DIR", str(state))
    monkeypatch.setenv("MEDIAHUB_AGENT_TOKEN_FILE", str(state / "token"))
    monkeypatch.setenv("MEDIAHUB_AGENT_DEV_MODE", "true")
    config = Config(_env_file=None, runtime_mode="embedded", dev_mode=True, data_dir=tmp_path / "data")
    with TestClient(create_app(config)) as client:
        services = client.app.state.services
        assert services.agent.local_app is not None
        status = client.portal.call(services.agent.request, "GET", "/v1/health")
        assert isinstance(status, dict)
        assert client.get("/v1/health").status_code != 200
