import json
import time

import httpx
from sqlalchemy import select

from mediahub.db import Setting
from test_sso import configure


def test_overview_uses_short_lived_scoped_grant_and_cleans_it_up(logged_in, monkeypatch):
    configure(logged_in)
    svc = logged_in.app.state.services
    observed = []

    async def handler(request):
        assert str(request.url) == "https://seed.example/api/hub/overview"
        with svc.sessions() as db:
            grants = db.scalars(select(Setting).where(Setting.key.like("sso:session:%"))).all()
            assert len(grants) == 1
            assert grants[0].value["scope"] == "overview"
            assert grants[0].value["expires"] <= time.time() + 30
        observed.append(request.headers["authorization"])
        return httpx.Response(200, json={"checkedAt": time.time(), "ready": True, "torrents": []})

    original = httpx.AsyncClient
    monkeypatch.setattr("mediahub.mediaseed_api.httpx.AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}))
    response = logged_in.get("/api/v1/app-overview")
    assert response.status_code == 200
    assert response.json()["data"]["mediaseed"]["status"] == "ok"
    assert response.json()["data"]["mediavpn"]["status"] == "not_configured"
    assert len(observed) == 1
    assert observed[0] not in json.dumps(response.json())
    with svc.sessions() as db:
        assert not db.scalars(select(Setting).where(Setting.key.like("sso:session:%"))).all()


def test_denied_app_never_requested(logged_in, monkeypatch):
    configure(logged_in)
    svc = logged_in.app.state.services
    own = logged_in.get("/api/auth/me").json()["data"]["id"]
    logged_in.put(f"/api/users/{own}", json={"username": "tester", "appRoles": {"org.mediahub.mediaseed": "denied"}}).raise_for_status()
    def no_client(**kwargs):
        raise AssertionError("Denied app must not receive a request")
    monkeypatch.setattr("mediahub.mediaseed_api.httpx.AsyncClient", no_client)
    assert logged_in.get("/api/v1/app-overview").json()["data"]["mediaseed"]["status"] == "denied"


def test_overview_needs_hub_login(client):
    assert client.get("/api/v1/app-overview").status_code == 401


def test_failed_app_does_not_keep_grants_or_claim_healthy(logged_in, monkeypatch):
    configure(logged_in)
    async def failed(request):
        raise httpx.ConnectError("Synthetic offline app")
    original = httpx.AsyncClient
    monkeypatch.setattr("mediahub.mediaseed_api.httpx.AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(failed)}))
    response = logged_in.get("/api/v1/app-overview").json()["data"]
    assert response["mediaseed"] == {"status": "unavailable"}
    with logged_in.app.state.services.sessions() as db:
        assert not db.scalars(select(Setting).where(Setting.key.like("sso:session:%"))).all()
