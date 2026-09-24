import base64
import secrets

import pytest
from mediahub.apps.seedbox_credentials import (
    QBitInitialSettings,
    SeedboxCredentials,
    VPNProfileRegistry,
    WireGuardProfileAdapter,
)
from mediahub.errors import DomainError
from pydantic import SecretStr, ValidationError


@pytest.fixture
def profile():
    private = base64.b64encode(secrets.token_bytes(32)).decode()
    public = base64.b64encode(secrets.token_bytes(32)).decode()
    return f"[Interface]\nPrivateKey = {private}\nAddress = 10.2.0.2/32\nDNS = 10.2.0.1\n[Peer]\nPublicKey = {public}\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = 1.1.1.1:51820\nPersistentKeepalive = 25\n"


def test_credentials_never_serialize_secrets(profile):
    password = secrets.token_urlsafe(24)
    credentials = SeedboxCredentials(
        vpnConfig=profile, webUsername="operator", webPassword=password
    )
    assert credentials.model_dump() == {"webUsername": "operator"}
    assert profile not in repr(credentials) and password not in repr(credentials)
    assert password not in credentials.model_dump_json()
    assert credentials.public() == {
        "vpn": {"configured": True},
        "qBittorrent": {"configured": True},
    }


def test_profile_validation_is_secret_safe(profile):
    result = WireGuardProfileAdapter().validate(SecretStr(profile))
    assert isinstance(result, SecretStr)
    assert "PrivateKey" in result.get_secret_value()
    assert result.get_secret_value() not in repr(result)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.replace("DNS =", "PostUp ="),
        lambda p: p.replace("10.2.0.2/32", "127.0.0.1/32"),
        lambda p: p.replace("0.0.0.0/0, ::/0", "10.0.0.0/8"),
        lambda p: p.replace("1.1.1.1:51820", "127.0.0.1:51820"),
        lambda p: p.replace("1.1.1.1:51820", "server.local:51820"),
        lambda p: p.replace("1.1.1.1:51820", "server.example:99999"),
        lambda p: p.replace("[Peer]", "[Peer]\nPostUp = sh attacker"),
        lambda p: p + "\n[Peer]\nEndpoint = other.example:443\n",
        lambda p: p + "\n[DEFAULT]\nPostUp = sh attacker\n",
        lambda p: p.replace("PrivateKey =", "PrivateKey = bad\nOtherKey ="),
        lambda p: p + "\x00",
        lambda p: "x" * 65537,
    ],
)
def test_unsafe_profiles_rejected_without_echo(profile, change):
    submitted = change(profile)
    with pytest.raises(DomainError) as error:
        WireGuardProfileAdapter().validate(SecretStr(submitted))
    assert error.value.code == "invalid_vpn_profile"
    assert submitted not in str(error.value)


def test_validation_errors_do_not_print_password(profile):
    with pytest.raises(ValidationError) as error:
        SeedboxCredentials(vpnConfig=profile, webUsername="operator", webPassword="bad-secret")
    assert "bad-secret" not in str(error.value)


def test_qbit_settings_cannot_enable_wan_or_arbitrary_paths():
    assert QBitInitialSettings().networkInterface == "tun0"
    for extra in [
        {"networkInterface": "eth0"},
        {"downloadPath": "/etc"},
        {"maxConnections": 100000},
    ]:
        with pytest.raises(ValidationError):
            QBitInitialSettings(**extra)


def test_unimplemented_protocol_is_not_silently_accepted():
    registry = VPNProfileRegistry()
    assert registry.schemas()[0]["protocol"] == "wireguard"
    with pytest.raises(DomainError):
        registry.get("openvpn")
