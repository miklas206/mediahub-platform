import secrets

import pytest
from mediahub.apps.seedbox_credentials import SeedboxCredentials
from mediahub.errors import DomainError

from agent.seedbox_secret_store import SeedboxSecretStore


def test_secret_store_encrypts_and_exposes_only_configured(tmp_path):
    store = SeedboxSecretStore(tmp_path / "vault")
    credentials = SeedboxCredentials(
        vpnConfig="private-profile-" + secrets.token_hex(20),
        webUsername="operator",
        webPassword=secrets.token_urlsafe(24),
    )
    assert store.stage("test-install", credentials) == {"configured": True}
    assert store.status("test-install") == {"configured": True}
    raw = (tmp_path / "vault/test-install.sealed").read_bytes()
    assert credentials.vpnConfig.get_secret_value().encode() not in raw
    assert credentials.webPassword.get_secret_value().encode() not in raw
    loaded = store.load("test-install")
    assert loaded.vpnConfig == credentials.vpnConfig
    assert loaded.webPassword == credentials.webPassword
    with pytest.raises(DomainError) as error:
        store.stage("test-install", credentials)
    assert error.value.code == "credentials_exist"


@pytest.mark.parametrize("reference", ["../../secret", "/tmp/file", "a/b", "", "a", "x?token=abc"])
def test_references_are_not_paths(tmp_path, reference):
    store = SeedboxSecretStore(tmp_path / "vault")
    with pytest.raises(DomainError):
        store.load(reference)
    assert not (tmp_path / "vault").exists()


def test_missing_status_does_not_create_files(tmp_path):
    store = SeedboxSecretStore(tmp_path / "vault")
    assert store.status("test-install") == {"configured": False}
    assert not (tmp_path / "vault").exists()


def test_corrupted_secret_is_not_reported_configured(tmp_path):
    store = SeedboxSecretStore(tmp_path / "vault")
    store.stage(
        "test-install",
        SeedboxCredentials(
            vpnConfig="example-private-profile",
            webUsername="operator",
            webPassword=secrets.token_urlsafe(24),
        ),
    )
    (tmp_path / "vault/test-install.sealed").write_bytes(b"corrupted")
    assert store.status("test-install") == {"configured": False}
    with pytest.raises(DomainError) as error:
        store.load("test-install")
    assert "corrupted" not in str(error.value)
