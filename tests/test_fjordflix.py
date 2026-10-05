import asyncio

import httpx
import pytest
from mediahub.db import ExternalIntegration
from mediahub.integrations.fjordflix import fetch_poster, poster_id
from mediahub.integrations.fjordhub import FjordHubClient, ProviderFailure

ORIGIN = "https://192.168.50.20:8443"
TOKEN = "test-private-access-token-123456"
PATH = "/api/integrations/v1/app-data/fjordflix/posters/"


def client(body=None, handler=None):
    return FjordHubClient(
        ORIGIN,
        TOKEN,
        transport=httpx.MockTransport(handler or (lambda _: httpx.Response(200, json=body))),
    )


def resource(app=None, ok=True):
    value = {"ok": ok, "hub": {"cpu_capacity_percent": 25}, "capacity": {}, "apps": []}
    if app is not None:
        value["app_data"] = {"fjordflix": app}
    return value


def app():
    return {
        "ok": True,
        "generated_at": "2026-10-05T20:00:00Z",
        "library_count": 12,
        "items": [
            {"id": str(i), "title": f"Æøå {i}", "poster_url": ORIGIN + PATH + str(i)}
            for i in range(12)
        ],
        "streams": [
            {
                "id": "s",
                "title": "Æøå",
                "position": 120,
                "duration": 7200,
                "height": 1080,
                "mbps": 8,
            }
        ],
    }


def test_order_optional_metadata_and_units():
    snapshot = asyncio.run(client(resource(app())).sync())
    assert snapshot.metrics["cpuPercent"] == 25
    data = snapshot.fjordflix
    assert [item["title"] for item in data["items"]] == [f"Æøå {i}" for i in range(10)]
    assert data["items"][0]["poster_id"] == "0"
    assert "poster_url" not in str(data)
    assert data["streams"][0]["position"] == 120
    assert data["streams"][0]["height"] == 1080
    assert data["streams"][0]["mbps"] == 8


@pytest.mark.parametrize("status", [401, 403, 404, 503])
def test_app_error_does_not_hide_resources_or_reflect_errors(status):
    snapshot = asyncio.run(client(resource({"ok": False, "status": status, "error": TOKEN})).sync())
    assert snapshot.status == "online"
    assert snapshot.metrics["cpuPercent"] == 25
    assert snapshot.fjordflix["status"] == status
    assert TOKEN not in str(snapshot)


def test_old_contract_empty_and_app_independent_from_resource_ok():
    assert asyncio.run(client(resource()).sync()).fjordflix is None
    empty = {"ok": True, "items": [], "streams": [], "library_count": 0}
    assert asyncio.run(client(resource(empty)).sync()).fjordflix["items"] == []
    snapshot = asyncio.run(client(resource(empty, ok=False)).sync())
    assert snapshot.status == "invalid_response" and snapshot.fjordflix["ok"] is True


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example" + PATH + "a",
        ORIGIN + PATH + "../a",
        ORIGIN + PATH + "%2e%2e/a",
        ORIGIN + PATH + "%252e%252e",
        ORIGIN + PATH + "a?token=x",
        ORIGIN + PATH + "a#x",
        "//evil.example" + PATH + "a",
        ORIGIN + PATH + "a\\b",
        ORIGIN + PATH + "a/b",
        "https://user@192.168.50.20:8443" + PATH + "a",
        ORIGIN + PATH + "a\n",
    ],
)
def test_poster_origin_path_encoding_policy(url):
    assert poster_id(url, ORIGIN) is None


@pytest.mark.parametrize("code", [301, 302, 307, 401, 403, 404, 503])
def test_poster_never_follows_redirect_or_exposes_errors(code):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer " + TOKEN
        return httpx.Response(code, headers={"location": "https://evil.example"}, text=TOKEN)

    with pytest.raises(ProviderFailure):
        asyncio.run(fetch_poster(client(handler=handler), "a"))
    assert calls == [ORIGIN + PATH + "a"]


@pytest.mark.parametrize(
    "content,kind",
    [
        (b"<script>x</script>", "image/jpeg"),
        (b"a" * (5 * 1024 * 1024 + 1), "image/png"),
        (b"x", "text/html"),
    ],
    ids=["invalid-signature", "oversized", "wrong-type"],
)
def test_poster_bounded_and_checks_content(content, kind):
    with pytest.raises(ProviderFailure):
        asyncio.run(
            fetch_poster(
                client(
                    handler=lambda _: httpx.Response(
                        200, content=content, headers={"content-type": kind}
                    )
                ),
                "a",
            )
        )


def test_image_route_requires_local_login(logged_in):
    svc = logged_in.app.state.services
    payload = {"baseUrl": ORIGIN, "accessToken": TOKEN}
    identifier = logged_in.post("/api/v1/integrations/fjordhub", json=payload).json()["data"]["id"]
    svc.integrations.provider_factory = lambda *args, **kw: client(
        handler=lambda _: httpx.Response(
            200, content=b"\xff\xd8\xfffixture", headers={"content-type": "image/jpeg"}
        )
    )
    url = f"/api/v1/integrations/{identifier}/fjordflix/posters/a"
    response = logged_in.get(url)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert TOKEN.encode() not in response.content
    logged_in.cookies.clear()
    assert logged_in.get(url).status_code in {401, 403}


def test_resources_and_app_preserve_last_good_independently(logged_in):
    svc = logged_in.app.state.services
    identifier = logged_in.post(
        "/api/v1/integrations/fjordhub", json={"baseUrl": ORIGIN, "accessToken": TOKEN}
    ).json()["data"]["id"]

    def refresh(value):
        with svc.sessions.begin() as db:
            db.get(ExternalIntegration, identifier).next_sync = 0
        svc.integrations.provider_factory = lambda *args, **kw: client(value)
        return logged_in.post(f"/api/v1/integrations/{identifier}/refresh", json={}).json()["data"][
            "snapshot"
        ]

    first = refresh(resource(app()))
    failed = refresh(resource({"ok": False, "status": 503}))
    assert failed["stale"] is False and failed["fjordflix"]["stale"] is True
    assert failed["fjordflix"]["items"] == first["fjordflix"]["items"]
    independent = refresh(resource({"ok": True, "items": [], "streams": []}, ok=False))
    assert independent["stale"] is True and independent["metrics"] == first["metrics"]
    assert independent["fjordflix"]["stale"] is False and independent["fjordflix"]["items"] == []
    recovered = refresh(resource(app()))
    assert recovered["stale"] is False and recovered["fjordflix"]["stale"] is False


@pytest.mark.parametrize("status", [[], {}, "503", True])
def test_malformed_app_error_still_preserves_metrics(status):
    snapshot = asyncio.run(client(resource({"ok": False, "status": status})).sync())
    assert snapshot.metrics["cpuPercent"] == 25
    assert snapshot.fjordflix["status"] == 503


def test_poster_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout(TOKEN, request=request)

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(fetch_poster(client(handler=handler), "a"))


def test_environment_config_is_backend_only_and_preserves_disconnect(logged_in):
    from mediahub.config import Config
    from mediahub.integrations.service import IntegrationService

    config = Config(
        FJORDHUB_BASE_URL=ORIGIN,
        FJORDHUB_ACCESS_TOKEN=TOKEN,
        _env_file=None,
        data_dir=logged_in.app.state.services.config.data_dir,
    )
    assert TOKEN not in repr(config)
    assert "fjordhub_access_token" not in config.model_dump()
    svc = logged_in.app.state.services
    integration = IntegrationService(config, svc.sessions, svc.events)
    rows = integration.list()
    assert len(rows) == 1 and rows[0]["tokenConfigured"]
    assert TOKEN not in str(rows)
    with svc.sessions.begin() as db:
        saved = db.get(ExternalIntegration, rows[0]["id"])
        saved.snapshot = {"status": "online", "metrics": {"cpuPercent": 25}}
    assert IntegrationService(config, svc.sessions, svc.events).list()[0]["snapshot"][
        "metrics"
    ] == {"cpuPercent": 25}
    integration.disconnect(rows[0]["id"])
    restarted = IntegrationService(config, svc.sessions, svc.events)
    assert restarted.list()[0]["enabled"] is False
    assert restarted.list()[0]["tokenConfigured"] is False


def test_invalid_environment_token_cannot_appear_in_validation_message():
    from mediahub.config import Config
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as failure:
        Config(FJORDHUB_ACCESS_TOKEN=TOKEN + "\n", _env_file=None)
    assert TOKEN not in str(failure.value)
