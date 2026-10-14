"""Synthetic API/runtime tests: no public DNS, real VPN or installed browser."""

import asyncio
import base64
import copy
import hashlib
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from mediahub.app_settings import saved_address
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError
from mediahub.vpn_gateway import VPNGateway

BASE = "/api/v1/vpn-gateway"
ACCOUNT = "a" * 32
ZONE = "b" * 32
PROFILE = "c" * 24
TOKEN = "synthetic-private-cloudflare-token"
BODY = {
    "enabled": True,
    "profileId": PROFILE,
    "routes": [{"packageId": "mediahub", "zoneId": ZONE, "label": "hub"}],
}
FOREIGN = {
    "id": "unrelated-rule",
    "ref": "operator-rule",
    "expression": 'http.host eq "other.example.com"',
    "action": "route",
    "action_parameters": {"origin": {"port": 8443}},
    "enabled": True,
}


@pytest.fixture
def gateway(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    svc.config.base_url = "http://192.168.1.50:18765"
    service = svc.vpn_gateway
    service.store.put("api_token", TOKEN.encode())
    state = service.state()
    state["accountId"] = ACCOUNT
    service.save(state)
    monkeypatch.setattr(service, "schedule", Mock())
    monkeypatch.setattr(
        svc.shared_vpn,
        "vpn",
        AsyncMock(
            return_value={
                "profiles": [{"id": PROFILE, "name": "Synthetic Proton", "healthy": True}]
            }
        ),
    )
    remote = {
        "calls": [],
        "records": [],
        "ruleset": {"id": "ruleset-id", "rules": [copy.deepcopy(FOREIGN)]},
        "ssl": "strict",
        "ip": "8.8.8.8",
        "port": 54321,
        "certificates": True,
        "provider": True,
        "age": 0,
        "machine": None,
        "machineCalls": [],
    }

    async def cf(method, path, body=None, *, params=None, token=None, missing=False):
        remote["calls"].append((method, path, copy.deepcopy(body)))
        if path == "/zones":
            return [{"id": ZONE, "name": "example.com", "account": {"id": ACCOUNT}}]
        if path == "/zones/" + ZONE:
            return {"id": ZONE, "name": "example.com", "account": {"id": ACCOUNT}}
        if path.endswith("/settings/ssl"):
            assert method == "GET", "Never change zone-wide SSL mode"
            return {"value": remote["ssl"]}
        if "/dns_records" in path:
            prefix = "/zones/" + ZONE + "/dns_records"
            if path == prefix:
                if method == "GET":
                    return copy.deepcopy(
                        [row for row in remote["records"] if row["name"] == params["name"]]
                    )
                assert method == "POST"
                row = {"id": "record-" + str(len(remote["records"])), **body}
                remote["records"].append(row)
                return copy.deepcopy(row)
            row = next((row for row in remote["records"] if path.endswith("/" + row["id"])), None)
            if method == "DELETE":
                if row:
                    remote["records"].remove(row)
                return {}
            assert method == "PATCH" and row
            row.update(body)
            return copy.deepcopy(row)
        if path.endswith("/entrypoint"):
            return copy.deepcopy(remote["ruleset"])
        if path.endswith("/rulesets"):
            assert method == "POST" and remote["ruleset"] is None
            remote["ruleset"] = {"id": "created-ruleset", **copy.deepcopy(body)}
            for index, rule in enumerate(remote["ruleset"]["rules"]):
                rule["id"] = "owned-" + str(index)
            return copy.deepcopy(remote["ruleset"])
        if "/rules/" in path:
            rule = next(
                rule for rule in remote["ruleset"]["rules"] if path.endswith("/" + rule["id"])
            )
            if method == "DELETE":
                remote["ruleset"]["rules"].remove(rule)
                return {}
            assert method == "PATCH"
            rule.update(body)
            return copy.deepcopy(remote["ruleset"])
        if path.endswith("/rules"):
            assert method == "POST"
            remote["ruleset"]["rules"].append({"id": "owned-rule", **body})
            return copy.deepcopy(remote["ruleset"])
        raise AssertionError((method, path))

    async def vpn(method="GET", body=None):
        remote["machineCalls"].append((method, copy.deepcopy(body)))
        if method == "PUT":
            remote["machine"] = copy.deepcopy(body)
        machine = remote["machine"] or {"enabled": False, "profileId": None, "routes": []}
        return {
            "enabled": machine["enabled"],
            "profileId": machine["profileId"],
            "ready": remote["provider"] and remote["certificates"],
            "providerReady": remote["provider"],
            "phase": "ready",
            "publicIp": remote["ip"],
            "publicPort": remote["port"],
            "checkedAt": time.time() - remote["age"],
            "prerequisites": remote.get("prerequisites", []),
            "architecture": "amd64",
            "routes": [
                {key: row[key] for key in ("id", "hostname", "upstream")}
                | {
                    "certificateReady": remote["certificates"],
                    "tlsServerName": row.get("tlsServerName"),
                    "caFingerprint": hashlib.sha256(
                        row["caPem"].replace("\r\n", "\n").strip().encode()
                    ).hexdigest()
                    if row.get("caPem")
                    else None,
                }
                for row in machine["routes"]
            ],
        }

    monkeypatch.setattr(service, "cf", cf)
    monkeypatch.setattr(service, "vpn", vpn)
    monkeypatch.setattr(service, "probe", AsyncMock(return_value={"reachable": True}))
    return service, remote


def configure(client, service, body=None):
    response = client.put(BASE + "/config", json=body or BODY)
    assert response.status_code == 202, response.text
    return client.portal.call(service.reconcile, True)


def mutations(remote):
    return [call for call in remote["calls"] if call[0] != "GET"]


@pytest.mark.parametrize("all_offline", [False, True])
def test_app_restart_keeps_dns_selections_and_recovers_without_readding(logged_in, gateway, monkeypatch, all_offline):
    service, remote = gateway
    origin = AsyncMock(return_value={"upstream": "http://192.168.1.50:18765"})
    monkeypatch.setattr(service, "upstream", origin)
    body = {**BODY, "routes": [*BODY["routes"], {"packageId": "org.mediahub.mediavpn", "zoneId": ZONE, "label": "vpn"}]}
    configured = configure(logged_in, service, body)
    ids = [row["id"] for row in configured["routes"]]
    records = copy.deepcopy(remote["records"])
    rules = copy.deepcopy(remote["ruleset"])
    before_calls = len(remote["calls"])
    before_machine = len(remote["machineCalls"])

    async def offline(package):
        if all_offline or package == "org.mediahub.mediavpn":
            raise DomainError("app_unavailable", "Synthetic app restarting", 409)
        return {"upstream": "http://192.168.1.50:18765"}

    origin.side_effect = offline
    status = logged_in.portal.call(service.reconcile, True)
    assert [row["id"] for row in status["routes"]] == ids
    assert status["routes"][1]["status"] == "blocked"
    assert remote["records"] == records
    assert remote["ruleset"] == rules
    assert not any(method == "DELETE" for method, _, _ in remote["calls"][before_calls:])
    if all_offline:
        assert not any(method == "PUT" for method, _ in remote["machineCalls"][before_machine:])
    origin.side_effect = None
    recovered = logged_in.portal.call(service.reconcile, True)
    assert [row["id"] for row in recovered["routes"]] == ids
    assert all(row["status"] == "healthy" for row in recovered["routes"])
    assert remote["records"] == records


def test_gateway_provisions_owned_a_and_individual_origin_rule_and_verifies_https(
    logged_in, gateway
):
    service, remote = gateway
    status = configure(logged_in, service)
    assert status["routes"][0]["status"] == "healthy"
    assert status["routes"][0]["httpsVerified"] is True
    assert remote["records"][0]["type"] == "A" and remote["records"][0]["proxied"] is True
    assert remote["records"][0]["content"] == remote["ip"]
    assert remote["ruleset"]["rules"][0] == FOREIGN
    owned = remote["ruleset"]["rules"][1]
    assert owned["action_parameters"] == {"origin": {"port": remote["port"]}}
    assert owned["expression"] == 'http.host in {"hub.example.com"}'
    assert remote["machine"]["cloudflareToken"] == TOKEN
    assert remote["machine"]["routes"][0]["upstream"] == "http://192.168.1.50:18765"
    assert TOKEN not in str(status) and TOKEN not in str(service.state())
    assert "records" not in status and "rules" not in status
    assert all("cfd_tunnel" not in path for _, path, _ in remote["calls"])
    count = len(mutations(remote))
    logged_in.portal.call(service.reconcile, True)
    assert len(mutations(remote)) == count


def test_endpoint_rotation_updates_only_owned_rule_and_record(logged_in, gateway):
    service, remote = gateway
    configure(logged_in, service)
    remote.update(ip="1.1.1.1", port=45678)
    status = logged_in.portal.call(service.reconcile, True)
    assert status["routes"][0]["status"] == "healthy"
    assert len(remote["records"]) == 1
    assert remote["records"][0]["content"] == "1.1.1.1"
    assert remote["ruleset"]["rules"][0] == FOREIGN
    assert remote["ruleset"]["rules"][1]["action_parameters"]["origin"]["port"] == 45678


@pytest.mark.parametrize("lost", ["dns-create", "rule-create", "dns-update", "rule-update"])
def test_lost_cloudflare_response_recovers_pending_payload_without_duplicate_ownership(
    logged_in, gateway, monkeypatch, lost
):
    service, remote = gateway
    if lost.endswith("update"):
        configure(logged_in, service)
        remote.update(ip="1.1.1.1", port=45678)
    original = service.cf
    failed = False

    async def fail_once(method, path, *args, **kwargs):
        nonlocal failed
        value = await original(method, path, *args, **kwargs)
        selected = ("dns_records" in path) == lost.startswith("dns")
        if not failed and selected and method == ("PATCH" if lost.endswith("update") else "POST"):
            failed = True
            raise DomainError("cloudflare_unavailable", "Synthetic response loss", 502)
        return value

    monkeypatch.setattr(service, "cf", fail_once)
    if lost.endswith("create"):
        configure(logged_in, service)
    else:
        logged_in.portal.call(service.reconcile, True)
    assert failed
    status = logged_in.portal.call(service.reconcile, True)
    assert status["routes"][0]["status"] == "healthy"
    assert len(remote["records"]) == 1
    assert len(remote["ruleset"]["rules"]) == 2
    assert remote["ruleset"]["rules"][0] == FOREIGN


def test_missing_phase_ruleset_creation_recovers_after_restart(logged_in, gateway, monkeypatch):
    service, remote = gateway
    remote["ruleset"] = None
    original = service.cf

    async def lose(method, path, *args, **kwargs):
        value = await original(method, path, *args, **kwargs)
        if method == "POST" and path.endswith("/rulesets"):
            raise DomainError("cloudflare_unavailable", "Synthetic response loss", 502)
        return value

    monkeypatch.setattr(service, "cf", lose)
    configure(logged_in, service)
    restored = VPNGateway(service.svc)
    monkeypatch.setattr(restored, "cf", original)
    monkeypatch.setattr(restored, "vpn", service.vpn)
    monkeypatch.setattr(restored, "probe", service.probe)
    status = logged_in.portal.call(restored.reconcile, True)
    assert status["routes"][0]["status"] == "healthy"
    assert len(remote["ruleset"]["rules"]) == 1
    assert len([call for call in mutations(remote) if call[1].endswith("/rulesets")]) == 1


@pytest.mark.parametrize(
    "kind", ["foreign-dns", "edited-dns", "edited-rule", "removed-dns", "removed-rule"]
)
def test_external_records_and_rule_edits_are_never_overwritten(logged_in, gateway, kind):
    service, remote = gateway
    if kind == "foreign-dns":
        remote["records"] = [
            {
                "id": "foreign",
                "name": "hub.example.com",
                "type": "CNAME",
                "content": "old-tunnel.cfargotunnel.com",
                "proxied": True,
            }
        ]
    else:
        configure(logged_in, service)
        if kind == "edited-dns":
            remote["records"][0]["content"] = "9.9.9.9"
        if kind == "edited-rule":
            remote["ruleset"]["rules"][1]["action_parameters"]["origin"]["port"] = 12345
        if kind == "removed-dns":
            remote["records"] = []
        if kind == "removed-rule":
            remote["ruleset"]["rules"].pop()
    before = len(mutations(remote))
    status = (
        configure(logged_in, service)
        if kind == "foreign-dns"
        else logged_in.portal.call(service.reconcile, True)
    )
    assert status["routes"][0]["status"] == "conflict"
    assert len(mutations(remote)) == before
    assert remote["ruleset"]["rules"][0] == FOREIGN


@pytest.mark.parametrize("value", ["flexible", "full", "off"])
def test_ssl_full_strict_is_guidance_not_a_global_mutation(logged_in, gateway, value):
    service, remote = gateway
    remote["ssl"] = value
    status = configure(logged_in, service)
    assert status["routes"][0]["status"] == "blocked"
    assert status["issues"][0]["code"] == "cloudflare_ssl_required"
    assert not mutations(remote)


@pytest.mark.parametrize(
    "changes",
    [{"age": 180}, {"provider": False}, {"ip": "192.168.1.2"}, {"port": 0}, {"port": True}],
)
def test_unverified_or_stale_provider_never_publishes_dns(logged_in, gateway, changes):
    service, remote = gateway
    remote.update(changes)
    status = configure(logged_in, service)
    assert status["routes"][0]["status"] == "pending-port"
    assert not mutations(remote)


def test_pending_certificate_and_public_probe_are_separate_states(logged_in, gateway):
    service, remote = gateway
    remote["certificates"] = False
    status = configure(logged_in, service)
    assert status["routes"][0]["status"] == "pending-certificate"
    service.probe.assert_not_awaited()
    remote["certificates"] = True
    service.probe.return_value = {"reachable": False}
    status = logged_in.portal.call(service.reconcile, True)
    assert status["routes"][0]["status"] == "configured"
    assert status["routes"][0]["httpsVerified"] is False


def test_disable_does_not_need_online_app_and_only_deletes_owned_resources(
    logged_in, gateway, monkeypatch
):
    service, remote = gateway
    configured = configure(logged_in, service)
    monkeypatch.setattr(
        service,
        "upstream",
        AsyncMock(side_effect=DomainError("offline", "Synthetic app offline", 409)),
    )
    response = logged_in.put(BASE + "/config", json={"enabled": False})
    assert response.status_code == 202
    status = logged_in.portal.call(service.reconcile, True)
    assert status["routes"][0]["id"] == configured["routes"][0]["id"]
    assert status["routes"][0]["status"] == "disabled"
    assert remote["machine"]["enabled"] is False
    assert not remote["records"]
    assert remote["ruleset"]["rules"] == [FOREIGN]
    assert not service.state()["records"] and not service.state()["rules"]


def test_cleanup_preserves_external_edits_and_can_retry_lost_delete(
    logged_in, gateway, monkeypatch
):
    service, remote = gateway
    configure(logged_in, service)
    original = service.cf
    lost = False

    async def lose_delete(method, path, *args, **kwargs):
        nonlocal lost
        value = await original(method, path, *args, **kwargs)
        if method == "DELETE" and "dns_records" in path and not lost:
            lost = True
            raise DomainError("cloudflare_unavailable", "Synthetic lost delete", 502)
        return value

    monkeypatch.setattr(service, "cf", lose_delete)
    logged_in.put(BASE + "/config", json={"enabled": False})
    logged_in.portal.call(service.reconcile, True)
    assert service.state()["records"]
    logged_in.portal.call(service.reconcile, True)
    assert not service.state()["records"]
    assert remote["ruleset"]["rules"] == [FOREIGN]


def test_uninstalled_and_arbitrary_app_targets_are_rejected_before_machine_write(
    logged_in, gateway
):
    _, remote = gateway
    for package in ("org.mediahub.jellyfin", "org.other.app"):
        response = logged_in.put(
            BASE + "/config", json={**BODY, "routes": [{**BODY["routes"][0], "packageId": package}]}
        )
        assert response.status_code in {409, 422}
    assert not remote["machineCalls"] and not mutations(remote)
    response = logged_in.put(
        BASE + "/config",
        json={**BODY, "routes": [{**BODY["routes"][0], "upstream": "http://127.0.0.1"}]},
    )
    assert response.status_code == 422


def test_credentials_are_encrypted_redacted_and_cannot_rotate_during_enabled_gateway(
    logged_in, gateway
):
    service, _ = gateway
    response = logged_in.put(
        BASE + "/credentials", json={"accountId": ACCOUNT, "token": TOKEN + "-rotated"}
    )
    assert response.status_code == 200
    assert TOKEN not in response.text
    assert (TOKEN + "-rotated").encode() not in (
        service.store.directory / "api_token.sealed"
    ).read_bytes()
    configure(logged_in, service)
    response = logged_in.put(BASE + "/credentials", json={"accountId": ACCOUNT, "token": TOKEN})
    assert response.status_code == 409
    assert service.store.get("api_token").decode() == TOKEN + "-rotated"


def test_public_status_does_not_mutate_cloudflare_and_discovery_is_cached(logged_in, gateway):
    service, remote = gateway
    first = logged_in.get(BASE)
    assert first.status_code == 200
    assert first.json()["data"]["zones"] == [{"id": ZONE, "name": "example.com"}]
    assert first.json()["data"]["profiles"][0]["id"] == PROFILE
    count = len(remote["calls"])
    logged_in.get(BASE)
    assert len(remote["calls"]) == count
    assert not mutations(remote)


def test_machine_integration_uses_management_identity_and_never_returns_raw_error(
    logged_in, gateway, monkeypatch, tmp_path
):
    service, _ = gateway
    key = tmp_path / "management.token"
    key.write_text("synthetic-management-key")
    service.svc.managed_apps.policy = {
        "org.mediahub.mediavpn": SimpleNamespace(
            managementTokenFile=key, integrationUrl="http://192.168.1.50:18802"
        )
    }
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-MediaHub-Key"] == "synthetic-management-key"
        assert "X-MediaSeed-Key" not in request.headers
        return httpx.Response(403, text=TOKEN)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "mediahub.vpn_gateway.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(DomainError) as error:
        logged_in.portal.call(VPNGateway.vpn, service)
    assert TOKEN not in error.value.message
    assert calls[0].url.path == "/api/integration/web-gateway"


def test_current_machine_routes_are_verified_before_dns_and_drift_is_reapplied(logged_in, gateway):
    service, remote = gateway
    configure(logged_in, service)
    before = len([call for call in remote["machineCalls"] if call[0] == "PUT"])
    remote["machine"]["routes"][0]["upstream"] = "http://192.168.1.99:9999"
    status = logged_in.portal.call(service.reconcile, True)
    assert status["routes"][0]["status"] == "healthy"
    assert remote["machine"]["routes"][0]["upstream"] == "http://192.168.1.50:18765"
    assert len([call for call in remote["machineCalls"] if call[0] == "PUT"]) == before + 1


def test_unconfirmed_machine_configuration_does_not_publish_dns(logged_in, gateway, monkeypatch):
    service, remote = gateway
    original = service.vpn

    async def mismatch(*args, **kwargs):
        value = await original(*args, **kwargs)
        if value["routes"]:
            value["routes"][0]["hostname"] = "other.example.com"
        return value

    monkeypatch.setattr(service, "vpn", mismatch)
    status = configure(logged_in, service)
    assert status["routes"][0]["status"] == "blocked"
    assert not mutations(remote)


def test_disabling_must_finish_before_credential_rotation(logged_in, gateway):
    service, _ = gateway
    configure(logged_in, service)
    assert logged_in.put(BASE + "/config", json={"enabled": False}).status_code == 202
    assert (
        logged_in.put(
            BASE + "/credentials", json={"accountId": ACCOUNT, "token": TOKEN + "-new"}
        ).status_code
        == 409
    )
    logged_in.portal.call(service.reconcile, True)
    assert (
        logged_in.put(
            BASE + "/credentials", json={"accountId": ACCOUNT, "token": TOKEN + "-new"}
        ).status_code
        == 200
    )


def test_app_address_is_set_after_dns_and_restored_without_overwriting_user_changes(
    logged_in, gateway
):
    service, remote = gateway
    package = "org.mediahub.mediaseed"
    with service.svc.sessions.begin() as db:
        db.add(
            InstalledApp(
                package_id=package,
                name="MediaSeed",
                version="0.1.0",
                state="running",
                is_mock=False,
            )
        )
        db.add(
            Setting(
                key="app_address:" + package, value={"externalUrl": "https://previous.example.com"}
            )
        )
    service.svc.config.operator_app_urls[package] = "http://192.168.1.60:18800"
    body = {**BODY, "routes": [{"packageId": package, "zoneId": ZONE, "label": "seed"}]}
    configure(logged_in, service, body)
    assert saved_address(service.svc, package) == "https://seed.example.com"
    route_id = service.state()["routes"][0]["id"]
    renamed = {**body, "routes": [{**body["routes"][0], "id": route_id, "label": "seed-new"}]}
    configure(logged_in, service, renamed)
    assert saved_address(service.svc, package) == "https://seed-new.example.com"
    assert [row["name"] for row in remote["records"]] == ["seed-new.example.com"]
    logged_in.put(BASE + "/config", json={"enabled": False})
    logged_in.portal.call(service.reconcile, True)
    assert saved_address(service.svc, package) == "https://previous.example.com"
    configure(logged_in, service, body)
    with service.svc.sessions.begin() as db:
        row = db.query(Setting).filter(Setting.key == "app_address:" + package).one()
        row.value = {"externalUrl": "https://manually-changed.example.com"}
        db.query(InstalledApp).filter(
            InstalledApp.package_id == package
        ).one().state = "uninstalled"
    status = logged_in.portal.call(service.reconcile, True)
    assert not status["routes"][0]["httpsVerified"]
    assert remote["machine"]["enabled"] is False
    assert not remote["records"]
    assert saved_address(service.svc, package) == "https://manually-changed.example.com"


def test_https_targets_receive_only_valid_public_ca_and_no_unverified_tls(
    logged_in, gateway, tmp_path
):
    service, remote = gateway
    service.svc.config.base_url = "https://192.168.1.50:18765"
    service.svc.config.allowed_origins.append("https://127.0.0.1:18765")
    logged_in.base_url = "https://127.0.0.1:18765"
    ca = tmp_path / "ca.pem"
    service.svc.config.agent_ca_file = ca
    assert logged_in.put(BASE + "/config", json=BODY).status_code == 409
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic MediaHub CA")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, None)
    )
    ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    configure(logged_in, service)
    route = remote["machine"]["routes"][0]
    assert route["tlsServerName"] == "192.168.1.50"
    assert route["caPem"] == ca.read_text()
    assert "caPem" not in str(service.snapshot())
    assert "insecure" not in str(route).lower()


def test_snapshot_expires_previous_https_success(logged_in, gateway):
    service, _ = gateway
    configure(logged_in, service)
    state = service.state()
    state["routes"][0]["checkedAt"] = time.time() - 180
    service.save(state)
    row = service.snapshot()["routes"][0]
    assert row["httpsVerified"] is False
    assert row["status"] == "configured"


@pytest.mark.parametrize(
    "marker,code,expected",
    [
        ("owned-route", 200, True),
        ("owned-route", 401, True),
        ("owned-route", 400, False),
        ("owned-route", 404, False),
        ("other-route", 200, False),
        (None, 403, False),
        ("owned-route", 502, False),
    ],
)
def test_public_https_probe_requires_tls_and_exact_gateway_route_marker(
    logged_in, gateway, monkeypatch, marker, code, expected
):
    service, _ = gateway
    writer = Mock()
    writer.drain = AsyncMock()
    header = (
        f"HTTP/1.1 {code} Synthetic\r\n"
        + (f"X-MediaVPN-Route: {marker}\r\n" if marker else "")
        + "\r\n"
    )
    reader = SimpleNamespace(readuntil=AsyncMock(return_value=header.encode()))
    connection = AsyncMock(return_value=(reader, writer))
    monkeypatch.setattr("mediahub.vpn_gateway.asyncio.open_connection", connection)

    async def run():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(
            loop,
            "getaddrinfo",
            AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))]),
        )
        return await VPNGateway.probe(service, "hub.example.com", "owned-route")

    result = logged_in.portal.call(run)
    assert result["reachable"] is expected
    kwargs = connection.await_args.kwargs
    assert kwargs["ssl"].check_hostname and kwargs["server_hostname"] == "hub.example.com"
    assert connection.await_args.args == ("1.1.1.1", 443)


def test_public_probe_rejects_private_dns_answers_without_connecting(
    logged_in, gateway, monkeypatch
):
    service, _ = gateway
    connection = AsyncMock()
    monkeypatch.setattr("mediahub.vpn_gateway.asyncio.open_connection", connection)

    async def run():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(
            loop,
            "getaddrinfo",
            AsyncMock(
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
            ),
        )
        return await VPNGateway.probe(service, "hub.example.com", "owned-route")

    assert logged_in.portal.call(run)["reachable"] is False
    connection.assert_not_awaited()


def test_gateway_requires_authenticated_admin_https_and_csrf(logged_in, gateway):
    service, remote = gateway
    service.svc.config.dev_mode = False
    assert logged_in.put(BASE + "/config", json=BODY).status_code == 403
    service.svc.config.dev_mode = True
    csrf = logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.put(BASE + "/config", json=BODY).status_code == 403
    logged_in.headers["X-MediaHub-CSRF"] = csrf
    service.svc.auth.save_user("limited", "synthetic-user-password", role="user")
    response = logged_in.post(
        "/api/auth/login", json={"username": "limited", "password": "synthetic-user-password"}
    )
    logged_in.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    assert logged_in.get(BASE).status_code == 403
    assert logged_in.put(BASE + "/config", json=BODY).status_code == 403
    assert not remote["machineCalls"] and not mutations(remote)


def test_cloudflare_api_backoff_and_permission_errors_are_sanitized(
    logged_in, gateway, monkeypatch
):
    service, _ = gateway
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"}, text=TOKEN)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "mediahub.vpn_gateway.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    for _ in range(2):
        with pytest.raises(DomainError) as error:
            logged_in.portal.call(VPNGateway.cf, service, "GET", "/zones")
        assert error.value.code == "cloudflare_backoff"
        assert TOKEN not in error.value.message
    assert len(requests) == 1


@pytest.mark.parametrize(
    "app,port", [("prowlarr", 9696), ("radarr", 7878), ("sonarr", 8989), ("autobrr", 7474)]
)
def test_known_retired_container_apps_are_candidates_only_while_installed(
    logged_in, gateway, monkeypatch, app, port
):
    service, remote = gateway
    package = "org.mediahub." + app
    assert package not in {row["packageId"] for row in service.snapshot()["apps"]}
    with service.svc.sessions.begin() as db:
        db.add(
            InstalledApp(
                package_id=package, name=app, version="1.0.0", state="running", is_mock=False
            )
        )
        db.add(Setting(key="container_installation_" + app, value={"hostId": "paired-host"}))
    request = AsyncMock(
        return_value={"state": "running", "url": "http://192.168.1.70:" + str(port)}
    )
    monkeypatch.setattr(
        service.svc.hosts,
        "client",
        Mock(return_value=SimpleNamespace(request=request, trusted_transport=True)),
    )
    assert package in {row["packageId"] for row in service.snapshot()["apps"]}
    body = {**BODY, "routes": [{"packageId": package, "zoneId": ZONE, "label": app}]}
    configure(logged_in, service, body)
    request.assert_awaited_with("GET", "/v1/container-apps/" + app + "/status")
    assert remote["machine"]["routes"][0]["upstream"] == "http://192.168.1.70:" + str(port)
    with service.svc.sessions.begin() as db:
        db.query(InstalledApp).filter(
            InstalledApp.package_id == package
        ).one().state = "uninstalled"
    assert package not in {row["packageId"] for row in service.snapshot()["apps"]}
    assert logged_in.put(BASE + "/config", json=body).status_code == 409


def test_blocked_runtime_prerequisites_are_visible_and_prevent_activation(logged_in, gateway):
    service, remote = gateway
    remote["prerequisites"] = [
        {"id": "tun", "state": "blocked", "message": "TUN access is required"}
    ]
    state = configure(logged_in, service)
    assert state["gateway"]["architecture"] == "amd64"
    assert state["checks"][0] == {
        "id": "runtime-tun",
        "state": "blocked",
        "message": "TUN access is required",
    }
    assert not [call for call in remote["machineCalls"] if call[0] == "PUT"]
    assert not mutations(remote)


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_actual_mediavpn_machine_api_contract_matches_hub_including_tls_trust(
    tmp_path, monkeypatch, scheme
):
    # Develop against the independent app; CI uses the exact bundled delivery.
    root = Path(__file__).resolve().parents[1]
    standalone = root.parent.parent / "mediavpn"
    source = (
        standalone
        if (standalone / "mediavpn/web_gateway.py").is_file()
        else root / "docker/bundled/mediavpn"
    )
    monkeypatch.syspath_prepend(str(source))
    from mediavpn.app import create_app

    monkeypatch.setenv("MEDIAVPN_SHARED_ADDRESS", "192.168.1.50")
    runtime = SimpleNamespace(
        enabled=True,
        docker=lambda: SimpleNamespace(containers=SimpleNamespace(list=lambda **_: [])),
        status=lambda _: {"healthy": False},
    )
    app = create_app(tmp_path / "vpn", "http://testserver", runtime=runtime)
    monkeypatch.setattr(
        app.state.web_gateway,
        "prerequisites",
        lambda **_: {"ready": True, "checks": [], "architecture": "amd64"},
    )
    client = TestClient(app)
    credentials = {"username": "synthetic", "password": "synthetic-test-password"}
    assert client.post("/api/auth/setup", json=credentials).status_code == 200
    login = client.post("/api/auth/login", json=credentials)
    client.headers["X-MediaVPN-CSRF"] = login.json()["csrf"]
    key = base64.b64encode(bytes(range(32))).decode()
    wireguard = f"[Interface]\nPrivateKey={key}\nAddress=10.2.0.2/32\nDNS=10.2.0.1\n[Peer]\nPublicKey={key}\nAllowedIPs=0.0.0.0/0\nEndpoint=1.1.1.1:51820\n"
    profile = client.post(
        "/api/profiles",
        json={"name": "Synthetic", "configuration": wireguard, "port_forwarding": True},
    ).json()["id"]
    route = {
        "id": "a" * 32,
        "hostname": "app.example.com",
        "upstream": scheme + "://192.168.1.50:8080",
    }
    if scheme == "https":
        private_key = ed25519.Ed25519PrivateKey.generate()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic CA")])
        ca = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(private_key, None)
        )
        route.update(
            tlsServerName="192.168.1.50", caPem=ca.public_bytes(serialization.Encoding.PEM).decode()
        )
    payload = {"enabled": True, "profileId": profile, "routes": [route], "cloudflareToken": TOKEN}
    headers = {"X-MediaHub-Key": (tmp_path / "vpn/integrations/mediahub.token").read_text()}
    accepted = client.put("/api/integration/web-gateway", json=payload, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["phase"] == "applying"
    assert VPNGateway.machine_matches(accepted.json(), payload)
    assert accepted.json()["providerReady"] is False
    assert TOKEN not in accepted.text and "caPem" not in accepted.text
    actual = client.get("/api/integration/web-gateway", headers=headers).json()
    assert VPNGateway.machine_matches(actual, payload)
    for field in (
        "hostname",
        "upstream",
        *(("tlsServerName", "caFingerprint") if scheme == "https" else ()),
    ):
        changed = copy.deepcopy(actual)
        changed["routes"][0][field] = "wrong"
        assert not VPNGateway.machine_matches(changed, payload)
    client.close()


def test_dedicated_legacy_plex_vpn_blocks_second_managed_provider(logged_in, gateway, monkeypatch):
    service, remote = gateway
    client = SimpleNamespace(request=AsyncMock(return_value={"vpn": {"enabled": True}}))
    monkeypatch.setattr(service.svc.shared_vpn, "bindings", lambda: [{"id": "plex"}])
    monkeypatch.setattr(service.svc.shared_vpn, "target", lambda _: ({"id": "plex"}, client))
    response = logged_in.put(BASE + "/config", json=BODY)
    assert response.status_code == 409
    assert not remote["machineCalls"] and not mutations(remote)
    client.request.assert_awaited_once_with("GET", "/v1/plex/status")


def test_plex_domain_edit_preserves_other_app_routes(logged_in, gateway, monkeypatch):
    service, remote = gateway
    configure(logged_in, service)
    before = copy.deepcopy(service.state()["routes"][0])
    monkeypatch.setattr(service.svc.apps, "get", Mock(return_value={"packageId":"org.mediahub.plex","isMock":False,"state":"running"}))
    monkeypatch.setattr(service,"upstream",AsyncMock(return_value={"upstream":"http://192.168.1.50:32400"}))
    response = logged_in.put(BASE+"/apps/installation-specific-id/domain",json={"zoneId":ZONE,"label":"plex"})
    assert response.status_code == 200, response.text
    routes = service.state()["routes"]
    assert routes[0]["id"] == before["id"]
    assert routes[0]["hostname"] == before["hostname"]
    assert routes[1]["hostname"] == "plex.example.com"
    assert routes[1]["packageId"] == "org.mediahub.plex"
    response = logged_in.put(BASE+"/apps/installation-specific-id/domain",json={"zoneId":ZONE,"label":"movies"})
    assert response.status_code == 200
    assert service.state()["routes"][0]["id"] == before["id"]
    assert service.state()["routes"][1]["hostname"] == "movies.example.com"


def test_domain_editor_rejects_concurrent_gateway_change(logged_in, gateway):
    service, _ = gateway
    configure(logged_in, service)
    before = service.state()
    response = logged_in.put(BASE+"/config",json={**BODY,"expectedRevision":before.get("revision",0)-1})
    assert response.status_code == 409
    assert service.state() == before


def test_plex_runtime_open_url_uses_saved_domain_and_local_server(logged_in, monkeypatch):
    svc=logged_in.app.state.services
    monkeypatch.setattr(svc.apps,"adapter",Mock(return_value=SimpleNamespace(
        definition=SimpleNamespace(package_id="org.mediahub.plex",view_id="plex"),
        status=AsyncMock(return_value={"url":"http://192.168.1.50:32400","available":True}))))
    svc.config.operator_app_urls["org.mediahub.plex"]="https://app.plex.tv/desktop/#!/settings/web/general"
    assert logged_in.get("/api/v1/apps/install-id/runtime").json()["data"]["operatorUrl"] == "http://192.168.1.50:32400/web/index.html"
    with svc.sessions.begin() as db:
        db.add(Setting(key="app_address:org.mediahub.plex",value={"externalUrl":"https://plex.example.com"}))
    assert logged_in.get("/api/v1/apps/install-id/runtime").json()["data"]["operatorUrl"] == "https://plex.example.com/web/index.html"
