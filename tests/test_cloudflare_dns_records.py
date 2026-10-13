import pytest

# ruff: noqa: F811
# Import the shared pytest fixture while keeping its registered fixture name.
from test_cloudflare_management import BASE, ZONE, managed  # noqa: F401


@pytest.mark.parametrize(
    "kind,content",
    [("A", "192.168.1.50"), ("AAAA", "2001:db8::1"), ("CNAME", "target.example.com")],
)
def test_supported_record_types(logged_in, managed, kind, content):
    response = logged_in.post(
        BASE + "/dns",
        json={"zoneId": ZONE, "hostname": "new.example.com", "type": kind, "content": content},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["dnsRecords"][0]["type"] == kind


def test_dns_conflicts_never_overwrite_existing_records(logged_in, managed):
    _, _, remote = managed
    remote["records"].append({"type": "A", "content": "192.168.1.99", "proxied": False})
    response = logged_in.post(
        BASE + "/dns",
        json={
            "zoneId": ZONE,
            "hostname": "new.example.com",
            "type": "A",
            "content": "192.168.1.50",
        },
    )
    assert response.status_code == 409
    assert not any(
        method in {"PUT", "PATCH", "DELETE"} and "/dns_records" in path
        for method, path, _ in remote["calls"]
    )


@pytest.mark.parametrize(
    "kind,content", [("A", "2001:db8::1"), ("AAAA", "192.168.1.50"), ("CNAME", "new.example.com")]
)
def test_bad_dns_targets_are_rejected(logged_in, managed, kind, content):
    response = logged_in.post(
        BASE + "/dns",
        json={"zoneId": ZONE, "hostname": "new.example.com", "type": kind, "content": content},
    )
    assert response.status_code == 422
