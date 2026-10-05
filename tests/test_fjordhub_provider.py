import asyncio

import httpx
import pytest
from mediahub.integrations.fjordhub import FjordHubClient, validate_url


def fixture_response(request):
    assert request.method == "GET"
    assert request.headers["authorization"] == "Bearer test-private-key"
    if request.url.path == "/api/integrations/v1/resources":
        return httpx.Response(404)
    data = {
        "/api/integrations/v1/apps": {
            "items": [
                {
                    "id": "future-app",
                    "name": "Unreleased App",
                    "status": "running",
                    "secret": "never expose",
                    "description": "test-private-key",
                }
            ]
        },
    }
    return httpx.Response(200, json=data[request.url.path])


def provider(handler=fixture_response):
    return FjordHubClient(
        "https://192.168.50.20:8443", "test-private-key", transport=httpx.MockTransport(handler)
    )


def test_dynamic_catalog_and_redaction_without_invented_status():
    snapshot = asyncio.run(provider().sync())
    assert snapshot.status == "online"
    assert snapshot.apps[0]["name"] == "Unreleased App"
    assert snapshot.apps[0]["description"] == "[redacted]"
    assert "secret" not in snapshot.apps[0]
    assert "status" not in snapshot.apps[0]
    assert snapshot.storage == [] and snapshot.metrics == {} and snapshot.events == []
    assert snapshot.version is None and snapshot.scopes == []
    assert snapshot.capabilities == ["app_catalog.read"]


@pytest.mark.parametrize(
    "code,status",
    [
        (401, "authentication_failed"),
        (403, "lan_access_denied"),
        (404, "api_incompatible"),
        (500, "offline"),
        (302, "offline"),
        (429, "rate_limited"),
    ],
)
def test_failures_and_no_redirects(code, status):
    snapshot = asyncio.run(
        provider(
            lambda _: httpx.Response(
                code, headers={"Retry-After": "120", "Location": "https://attacker.example"}
            )
        ).sync()
    )
    assert snapshot.status == status
    if code == 429:
        assert snapshot.retry_after == 120


def test_connection_only_calls_real_catalog_route_and_includes_apps():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return fixture_response(request)

    snapshot = asyncio.run(provider(handler).test())
    assert snapshot.status == "online"
    assert len(snapshot.apps) == 1
    assert paths == ["/api/integrations/v1/resources", "/api/integrations/v1/apps"]


def test_current_resource_contract_and_allowlisted_fields():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "capacity": {"cpu_count": 4},
                "hub": {
                    "cpu_capacity_percent": 25,
                    "memory_usage": 1024,
                    "net_rx": 99,
                    "secret": "do-not-return",
                },
                "apps": [
                    {
                        "id": "app",
                        "name": "test-private-key",
                        "running_count": 1,
                        "container_count": 1,
                        "secret": "do-not-return",
                    }
                ],
            },
        )

    snapshot = asyncio.run(provider(handler).sync())
    assert paths == ["/api/integrations/v1/resources"]
    assert snapshot.status == "online"
    assert snapshot.capabilities == ["docker.resources.read"]
    assert snapshot.metrics["cpuPercent"] == 25
    assert snapshot.metrics["networkReceivedBytes"] == 99
    assert snapshot.apps[0]["name"] == "[redacted]"
    assert "secret" not in snapshot.apps[0]
    assert snapshot.storage == [] and snapshot.events == []


def test_unrelated_success_response_is_not_connection_success():
    snapshot = asyncio.run(
        provider(lambda _: httpx.Response(200, json={"api_version": "2"})).test()
    )
    assert snapshot.status == "invalid_response"


def test_timeout_is_isolated():
    def handler(request):
        raise httpx.ReadTimeout("Do not expose exception data", request=request)

    assert asyncio.run(provider(handler).test()).status == "timeout"


def test_private_address_policy():
    for url in [
        "http://192.168.50.20",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://example.com",
        "https://192.168.50.20/path",
        "https://user:pass@192.168.50.20",
    ]:
        with pytest.raises(ValueError):
            validate_url(url)
    assert validate_url("http://192.168.50.20", allow_http=True) == "http://192.168.50.20"


@pytest.mark.parametrize("field", ["url", "local_url", "external_url"])
def test_explicit_installed_app_addresses_keep_nondefault_ports(field):
    body = {
        "ok": True,
        "capacity": {},
        "hub": {},
        "apps": [
            None,
            {
                "id": "fjordflix",
                "name": "FjordFlix",
                "container_count": 1,
                field: "https://192.168.50.20:9234/library",
            },
        ],
    }
    snapshot = provider().resource_snapshot(body)
    assert snapshot.apps[0][field] == "https://192.168.50.20:9234/library"


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example:9234/",
        "http://192.168.50.20:9234/",
        "https://user:pass@192.168.50.20:9234/",
        "https://192.168.50.20:9234/?token=x",
        "https://192.168.50.20:9234/#token=x",
        "javascript:alert(1)",
        "https://192.168.50.20:8443/",
        "https://192.168.50.20:0/",
        "https://192.168.50.20:9234/test-private-key",
    ],
)
def test_untrusted_installed_app_addresses_are_not_projected(value):
    snapshot = provider().resource_snapshot(
        {
            "ok": True,
            "capacity": {},
            "hub": {},
            "apps": [{"id": "fjordflix", "name": "FjordFlix", "container_count": 1, "url": value}],
        }
    )
    assert "url" not in snapshot.apps[0]


def test_verified_upstream_metrics_only_contract_has_no_invented_app_addresses():
    snapshot = provider().resource_snapshot(
        {
            "ok": True,
            "capacity": {},
            "hub": {},
            "hub_url": "http://192.168.50.20:8091/",
            "apps": [
                {
                    "id": "fjordflix",
                    "name": "FjordFlix",
                    "container_count": 1,
                    "running_count": 1,
                    "default_port": 8093,
                    "port": 9234,
                }
            ],
        }
    )
    assert snapshot.apps == [
        {"id": "fjordflix", "name": "FjordFlix", "container_count": 1, "running_count": 1}
    ]
