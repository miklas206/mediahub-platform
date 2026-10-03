import asyncio
import base64
import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from mediahub.agent_client import AgentClient
from mediahub.apps.plex_media import MAX_ARTWORK_BYTES, MAX_RECENT_MEDIA
from mediahub.apps.remote_adapter import RemoteAppAdapter, RemoteAppDefinition
from mediahub.errors import DomainError

from agent.main import AgentConfig, create_agent
from agent.plex_control import PlexControl
from agent.plex_media import PlexMedia

JPEG = b"\xff\xd8\xff\xe0test-preview"


@pytest.fixture
def media():
    policy = SimpleNamespace(
        installationId="plex-test", apiUrl="http://127.0.0.1:32400", apiNetwork=None, imageId="a"
    )
    control = SimpleNamespace(
        policy=lambda: policy,
        inspect=AsyncMock(return_value={"State": {"Running": True}}),
        plex_get=AsyncMock(),
        plex_connection=AsyncMock(return_value=(policy.apiUrl, "private-plex-token")),
    )
    return PlexMedia(control)


def mock_plex(logged_in, payload=None, error=None, package="org.mediahub.plex"):
    calls = []

    class Client:
        async def request(self, method, path):
            calls.append((method, path))
            if error:
                raise error
            return payload

    def client(host):
        assert host == "bound-plex-host"
        return Client()

    adapter = RemoteAppAdapter(
        RemoteAppDefinition(package, "plex_installation", "/v1/plex", view_id="plex"),
        "bound-plex-host",
        client,
        None,
        None,
        "plex-test",
    )
    logged_in.app.state.services.apps.adapter = lambda _: adapter
    return calls


def test_core_media_and_artwork_require_login(client):
    assert client.get("/api/v1/apps/test/plex/recent-media").status_code == 401
    assert client.get("/api/v1/apps/test/plex/artwork/12").status_code == 401


def test_core_returns_only_local_cover_urls_on_bound_host(logged_in):
    calls = mock_plex(
        logged_in,
        {
            "supported": True,
            "items": [
                {
                    "id": "12",
                    "title": "Example film",
                    "type": "movie",
                    "year": 2026,
                    "hasArtwork": True,
                }
            ],
        },
    )
    response = logged_in.get("/api/v1/apps/plex-test/plex/recent-media")
    assert response.status_code == 200
    assert response.json()["data"]["items"][0] == {
        "id": "12",
        "title": "Example film",
        "type": "movie",
        "year": 2026,
        "thumbnailUrl": "/api/v1/apps/plex-test/plex/artwork/12",
    }
    assert calls == [("GET", "/v1/plex/recent-media")]


@pytest.mark.parametrize("status", [404, 405, 501])
def test_older_agent_is_gracefully_unsupported(logged_in, status):
    mock_plex(logged_in, error=DomainError("agent_error", "Agent operation failed", status))
    response = logged_in.get("/api/v1/apps/plex-test/plex/recent-media")
    assert response.status_code == 200
    assert response.json()["data"] == {"supported": False, "items": []}


def test_unavailable_agent_does_not_claim_unsupported(logged_in):
    mock_plex(logged_in, error=DomainError("agent_unavailable", "Agent unavailable", 503))
    assert logged_in.get("/api/v1/apps/plex-test/plex/recent-media").status_code == 503


def test_core_rejects_other_app_and_unvalidated_agent_fields(logged_in):
    calls = mock_plex(logged_in, package="org.mediahub.seedbox")
    assert logged_in.get("/api/v1/apps/plex-test/plex/recent-media").status_code == 404
    assert not calls
    mock_plex(logged_in, {"supported": True, "items": [], "token": "secret-that-must-not-leak"})
    response = logged_in.get("/api/v1/apps/plex-test/plex/recent-media")
    assert response.status_code == 502
    assert "secret-that-must-not-leak" not in response.text


def test_core_artwork_validates_id_and_serves_private_raster(logged_in):
    calls = mock_plex(
        logged_in,
        {
            "contentType": "image/jpeg",
            "content": base64.b64encode(JPEG).decode(),
        },
    )
    assert logged_in.get("/api/v1/apps/plex-test/plex/artwork/not-numeric").status_code == 422
    assert not calls
    response = logged_in.get("/api/v1/apps/plex-test/plex/artwork/12")
    assert response.status_code == 200 and response.content == JPEG
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert calls == [("GET", "/v1/plex/artwork/12")]


@pytest.mark.parametrize(
    "content_type,content",
    [
        ("image/svg+xml", b"<svg/>"),
        ("image/jpeg", b"<html>secret</html>"),
        ("image/png", JPEG),
        ("image/jpeg", JPEG + b"x" * MAX_ARTWORK_BYTES),
    ],
    ids=["svg", "html", "wrong-signature", "oversized"],
)
def test_core_rejects_unsafe_or_oversized_artwork(logged_in, content_type, content):
    mock_plex(
        logged_in, {"contentType": content_type, "content": base64.b64encode(content).decode()}
    )
    response = logged_in.get("/api/v1/apps/plex-test/plex/artwork/12")
    assert response.status_code == 502
    assert "<html>" not in response.text


def test_recent_metadata_is_bounded_cached_and_credentials_are_omitted(media):
    media.control.plex_get.return_value = ET.fromstring(
        '<MediaContainer token="SECRET">'
        + "".join(
            f'<Video ratingKey="{i}" title="Film {i}" type="movie" year="2026" '
            f'thumb="/library/metadata/{i}/thumb/1" key="https://secret.invalid/?token=SECRET"/>'
            for i in range(20)
        )
        + "</MediaContainer>"
    )

    async def run():
        result = await media.recent()
        assert result == await media.recent()
        return result

    result = asyncio.run(run())
    assert len(result["items"]) == MAX_RECENT_MEDIA
    assert "SECRET" not in json.dumps(result)
    media.control.plex_get.assert_awaited_once_with(
        media.control.policy(),
        "/library/recentlyAdded",
        params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": MAX_RECENT_MEDIA},
    )


def test_recent_skips_invalid_ids_and_external_thumbnail_urls(media):
    media.control.plex_get.return_value = ET.fromstring(
        '<MediaContainer><Video ratingKey="../12" title="Invalid" type="movie"/>'
        '<Video ratingKey="12" title="Valid" type="movie" thumb="https://example.com/a.jpg"/>'
        "</MediaContainer>"
    )
    result = asyncio.run(media.recent())
    assert result["items"] == [
        {"id": "12", "title": "Valid", "type": "movie", "year": None, "hasArtwork": False}
    ]


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/image",
        "//example.com/image",
        "/library/metadata/12/thumb?token=x",
        "/library/metadata/12/../thumb",
        "/:/prefs",
        "/library/metadata/12/art/1",
    ],
)
def test_agent_never_proxies_arbitrary_thumbnail_paths(media, path):
    media.control.plex_get.return_value = ET.fromstring(
        f'<MediaContainer><Video ratingKey="12" thumb="{path}"/></MediaContainer>'
    )
    media.fetch_artwork = AsyncMock()
    with pytest.raises(DomainError) as error:
        asyncio.run(media.artwork("12"))
    assert error.value.code == "plex_artwork_missing"
    media.fetch_artwork.assert_not_awaited()


def test_artwork_is_cached_but_ownership_is_checked_on_every_request(media):
    media.control.plex_get.return_value = ET.fromstring(
        '<MediaContainer><Video ratingKey="12" thumb="/library/metadata/12/thumb/1"/></MediaContainer>'
    )
    media.fetch_artwork = AsyncMock(return_value={"contentType": "image/jpeg", "content": "image"})

    async def run():
        assert await media.artwork("12") == await media.artwork("12")
        media.control.inspect.side_effect = DomainError("ownership_mismatch", "Denied", 409)
        with pytest.raises(DomainError):
            await media.artwork("12")

    asyncio.run(run())
    media.fetch_artwork.assert_awaited_once()
    assert media.control.inspect.await_count == 3


def test_agent_invalid_identifier_never_reaches_policy_or_plex(media):
    with pytest.raises(DomainError):
        asyncio.run(media.artwork("12?url=https://example.com"))
    media.control.inspect.assert_not_awaited()
    media.control.plex_get.assert_not_awaited()


def install_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    calls = []

    def client(**kwargs):
        calls.append(kwargs)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("agent.plex_media.httpx.AsyncClient", client)
    return calls


def test_image_fetch_uses_private_header_and_fixed_transcode(monkeypatch, media):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=JPEG)

    clients = install_transport(monkeypatch, handler)
    result = asyncio.run(
        media.fetch_artwork(media.control.policy(), "/library/metadata/12/thumb/1")
    )
    assert base64.b64decode(result["content"]) == JPEG
    request = requests[0]
    assert request.headers["X-Plex-Token"] == "private-plex-token"
    assert request.url.path == "/photo/:/transcode"
    assert request.url.params["url"] == "/library/metadata/12/thumb/1"
    assert request.url.params["width"] == "240"
    assert "private-plex-token" not in str(request.url) + json.dumps(result)
    assert clients[0] == {"timeout": 8, "trust_env": False, "follow_redirects": False}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://outside.invalid/"}),
        httpx.Response(200, headers={"content-type": "image/svg+xml"}, content=b"<svg/>"),
        httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"<html/>"),
        httpx.Response(
            200,
            headers={"content-type": "image/jpeg", "content-length": str(MAX_ARTWORK_BYTES + 1)},
            content=JPEG,
        ),
        httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=JPEG + b"x" * MAX_ARTWORK_BYTES
        ),
    ],
)
def test_image_fetch_rejects_redirects_nonimages_and_oversized_bodies(monkeypatch, media, response):
    install_transport(monkeypatch, lambda _: response)
    with pytest.raises(DomainError) as error:
        asyncio.run(media.fetch_artwork(media.control.policy(), "/library/metadata/12/thumb"))
    assert error.value.code == "plex_artwork_unavailable"
    assert "private-plex-token" not in str(error.value)


def test_agent_routes_require_paired_token(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("t" * 48)
    config = AgentConfig(state_dir=tmp_path, token_file=token_file, dev_mode=True, _env_file=None)
    monkeypatch.setattr(
        PlexMedia, "recent", AsyncMock(return_value={"supported": True, "items": []})
    )
    with TestClient(create_agent(config)) as client:
        assert client.get("/v1/plex/recent-media").status_code == 401
        assert client.get("/v1/plex/artwork/12").status_code == 401
        assert (
            client.get(
                "/v1/plex/recent-media", headers={"Authorization": "Bearer " + "t" * 48}
            ).status_code
            == 200
        )


@pytest.mark.parametrize("operation", ["recent", "artwork"])
def test_total_deadline_includes_policy_inspection(monkeypatch, media, operation):
    cancelled = []

    async def stalled_policy(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    media.control.inspect.side_effect = stalled_policy
    monkeypatch.setattr("agent.plex_media.RECENT_TIMEOUT", 0.01)
    monkeypatch.setattr("agent.plex_media.ARTWORK_TIMEOUT", 0.01)
    with pytest.raises(DomainError) as error:
        asyncio.run(media.recent() if operation == "recent" else media.artwork("12"))
    assert error.value.status == 503
    assert cancelled == [True]
    assert media.recent_cache is None and not media.artwork_cache


def test_artwork_queue_wait_is_time_bounded(monkeypatch, media):
    media.artwork_slots = asyncio.Semaphore(0)
    monkeypatch.setattr("agent.plex_media.ARTWORK_TIMEOUT", 0.01)
    with pytest.raises(DomainError) as error:
        asyncio.run(media.artwork("12"))
    assert error.value.code == "plex_artwork_unavailable"
    media.control.plex_get.assert_not_awaited()


def test_cover_cache_has_fixed_capacity_and_is_scoped_to_installation(media):
    async def metadata(_, endpoint):
        key = endpoint.rsplit("/", 1)[-1]
        return ET.fromstring(
            f'<MediaContainer><Video ratingKey="{key}" thumb="/library/metadata/{key}/thumb"/></MediaContainer>'
        )

    media.control.plex_get.side_effect = metadata
    media.fetch_artwork = AsyncMock(return_value={"contentType": "image/jpeg", "content": "cover"})

    async def run():
        for key in range(40):
            await media.artwork(str(key))
        assert len(media.artwork_cache) == 32
        assert {key[-1] for key in media.artwork_cache} == {str(key) for key in range(8, 40)}
        await media.artwork("39")
        assert media.fetch_artwork.await_count == 40
        media.control.policy().installationId = "different-installation"
        await media.artwork("39")
        assert media.fetch_artwork.await_count == 41

    asyncio.run(run())


class OversizedStream(httpx.AsyncByteStream):
    def __init__(self, limit):
        self.limit = limit
        self.closed = False
        self.read_past_limit = False

    async def __aiter__(self):
        yield b"x" * self.limit
        yield b"x"
        self.read_past_limit = True
        yield b"should-not-be-read"

    async def aclose(self):
        self.closed = True


def test_plex_xml_limit_stops_stream_before_buffering_rest(monkeypatch):
    stream = OversizedStream(2 * 1024 * 1024)
    install_transport(monkeypatch, lambda _: httpx.Response(200, stream=stream))
    control = PlexControl(None, None)
    control.plex_connection = AsyncMock(return_value=("http://127.0.0.1:32400", "private-token"))
    with pytest.raises(DomainError) as error:
        asyncio.run(control.plex_get(None, "/library/recentlyAdded"))
    assert error.value.code == "plex_api_unavailable"
    assert stream.closed and not stream.read_past_limit


def test_plex_xml_stream_preserves_empty_mutation_and_valid_xml(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, content=b"" if request.method == "PUT" else b'<MediaContainer size="8"/>'
        )

    install_transport(monkeypatch, handler)
    control = PlexControl(None, None)
    control.plex_connection = AsyncMock(return_value=("http://127.0.0.1:32400", "private-token"))

    async def run():
        assert (await control.plex_get(None, "/updater/check?download=0", "PUT")).tag == "Empty"
        assert (await control.plex_get(None, "/library/recentlyAdded")).get("size") == "8"

    asyncio.run(run())
    assert all(request.headers["X-Plex-Token"] == "private-token" for request in requests)


@pytest.mark.parametrize("path", ["/v1/plex/recent-media", "/v1/plex/artwork/12"])
def test_core_agent_media_transport_bounds_response_before_json_decode(monkeypatch, path):
    stream = OversizedStream(1024 * 1024)
    original = httpx.AsyncClient

    def client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
        return original(**kwargs)

    monkeypatch.setattr("mediahub.agent_client.httpx.AsyncClient", client)
    agent = AgentClient(
        SimpleNamespace(agent_url="http://agent", agent_socket=None), token="x" * 48
    )
    with pytest.raises(DomainError) as error:
        asyncio.run(agent.request("GET", path))
    assert error.value.code == "agent_unavailable"
    assert stream.closed and not stream.read_past_limit


@pytest.mark.parametrize("status", [200, 401, 404])
def test_media_transport_preserves_valid_json_and_agent_errors(monkeypatch, status):
    original = httpx.AsyncClient
    payload = (
        {"supported": True, "items": []}
        if status == 200
        else {"code": "agent_error", "message": "Diagnostic"}
    )

    def handler(request):
        assert request.headers["Authorization"] == "Bearer " + "x" * 48
        return httpx.Response(status, json=payload)

    def client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(**kwargs)

    monkeypatch.setattr("mediahub.agent_client.httpx.AsyncClient", client)
    agent = AgentClient(
        SimpleNamespace(agent_url="http://agent", agent_socket=None), token="x" * 48
    )
    if status == 200:
        assert asyncio.run(agent.request("GET", "/v1/plex/recent-media")) == payload
    else:
        with pytest.raises(DomainError) as error:
            asyncio.run(agent.request("GET", "/v1/plex/recent-media"))
        assert error.value.status == status
        assert error.value.code == ("agent_rejected" if status == 401 else "agent_error")
