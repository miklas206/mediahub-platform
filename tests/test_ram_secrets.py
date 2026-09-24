import json

import pytest
from mediahub.secret_store import SecretStore

from agent import ram_secrets


def test_generic_store_opaque_records(tmp_path):
    store = SecretStore(tmp_path / "vault")
    secret = b"not-a-real-test-access-token-123456"
    assert store.put("integration-test", secret) == {"configured": True}
    assert store.get("integration-test") == secret
    assert secret not in (tmp_path / "vault/integration-test.sealed").read_bytes()


def test_real_disk_refused_without_writes(tmp_path):
    (tmp_path / "secrets").mkdir(mode=0o700)
    with pytest.raises(ValueError):
        ram_secrets.RuntimeSecrets(tmp_path).materialize()
    assert list((tmp_path / "secrets").iterdir()) == []


def test_materialize_clear_and_reconstruct(tmp_path, monkeypatch):
    # Filesystem simulation only; deployment test separately verifies actual tmpfs.
    monkeypatch.setattr(ram_secrets, "verify_ram_directory", lambda _: None)
    (tmp_path / "secrets").mkdir(mode=0o700)
    runtime = ram_secrets.RuntimeSecrets(tmp_path)
    payload = {
        "vpnConfig": "test-only-profile",
        "webUsername": "operator",
        "webPassword": "test-only-password-long-enough",
    }
    runtime.store.put("seedbox-runtime", json.dumps(payload).encode())
    runtime.materialize()
    config = tmp_path / "secrets/vpn.conf"
    inode = config.stat().st_ino
    assert config.read_text() == payload["vpnConfig"]
    runtime.clear()
    assert all(p.stat().st_size == 0 for p in (tmp_path / "secrets").iterdir())
    runtime.materialize()
    assert config.stat().st_ino == inode
    assert config.read_text() == payload["vpnConfig"]


def test_corrupt_ciphertext_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ram_secrets, "verify_ram_directory", lambda _: None)
    (tmp_path / "secrets").mkdir(mode=0o700)
    runtime = ram_secrets.RuntimeSecrets(tmp_path)
    runtime.store.put("seedbox-runtime", b"not-valid-json")
    with pytest.raises(ValueError):
        runtime.materialize()
    assert list((tmp_path / "secrets").iterdir()) == []


def test_symlink_secret_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ram_secrets, "verify_ram_directory", lambda _: None)
    (tmp_path / "secrets").mkdir(mode=0o700)
    target = tmp_path / "untouched"
    target.write_text("unchanged")
    try:
        (tmp_path / "secrets/vpn.conf").symlink_to(target)
    except OSError:
        pytest.skip("OS does not permit unprivileged symlinks")
    with pytest.raises((OSError, ValueError)):
        ram_secrets.RuntimeSecrets(tmp_path)._write("vpn.conf", b"changed")
    assert target.read_text() == "unchanged"
