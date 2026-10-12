from mediahub.mediaseed_api import app_origin


def test_mediaseed_status_requires_login(client):
    assert client.get("/api/v1/mediaseed/status").status_code == 401
    assert client.get("/api/v1/mediavpn/status").status_code == 401


def test_mediavpn_configured_app_health(logged_in, monkeypatch):
    assert logged_in.get("/api/v1/mediavpn/status").json()["data"]["configured"] is False
    async def probe(origin):
        assert origin == "http://192.168.1.111:18802"
        return True
    monkeypatch.setattr("mediahub.mediaseed_api.available", probe)
    logged_in.app.state.services.config.operator_app_urls["org.mediahub.mediavpn"] = "http://192.168.1.111:18802"
    response = logged_in.get("/api/v1/mediavpn/status")
    assert response.json()["data"] == {"configured": True, "available": True, "url": "http://192.168.1.111:18802", "preview": True}


def test_mediaseed_unconfigured(logged_in):
    response = logged_in.get("/api/v1/mediaseed/status")
    assert response.status_code == 200
    assert response.json()["data"] == {"configured": False, "available": False, "url": None}


def test_mediaseed_configured_link_and_health(logged_in, monkeypatch):
    async def probe(origin):
        assert origin == "http://192.168.1.111:18800"
        return True
    monkeypatch.setattr("mediahub.mediaseed_api.available", probe)
    logged_in.app.state.services.config.operator_app_urls["org.mediahub.mediaseed"] = "http://192.168.1.111:18800"
    response = logged_in.get("/api/v1/mediaseed/status")
    assert response.status_code == 200
    assert response.json()["data"] == {"configured": True, "available": True, "url": "http://192.168.1.111:18800", "preview": True}


def test_only_private_operator_origins_are_probed():
    assert app_origin("http://192.168.1.111:18800/") == "http://192.168.1.111:18800"
    for value in [None, "https://public.example", "http://169.254.169.254", "http://0.0.0.0", "http://192.168.1.111/path", "javascript:alert(1)", "http://user:pass@192.168.1.111", "http://192.168.1.111?secret=test"]:
        assert app_origin(value) is None