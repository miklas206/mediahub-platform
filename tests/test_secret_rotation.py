import os

import pytest
from mediahub.secret_store import SecretStore


def test_atomic_rotation_leaves_only_encrypted_values(tmp_path):
    store = SecretStore(tmp_path / "vault")
    store.put("example", b"OLD-PRIVATE-VALUE")
    assert store.replace("example", b"NEW-PRIVATE-VALUE") == {"configured": True}
    assert store.get("example") == b"NEW-PRIVATE-VALUE"
    for item in store.directory.iterdir():
        assert b"PRIVATE-VALUE" not in item.read_bytes()
    assert sorted(p.name for p in store.directory.iterdir()) == ["example.sealed", "master.key"]
    if os.name != "nt":
        assert (store.directory / "example.sealed").stat().st_mode & 0o077 == 0


def test_failed_atomic_replace_preserves_previous_record(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "vault")
    store.put("example", b"OLD-PRIVATE-VALUE")

    def fail(*args):
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.replace("example", b"NEW-PRIVATE-VALUE")
    assert store.get("example") == b"OLD-PRIVATE-VALUE"
    assert not list(store.directory.glob(".rotation-*"))


def test_rotation_does_not_create_missing_record(tmp_path):
    store = SecretStore(tmp_path / "vault")
    store.put("existing", b"existing")
    with pytest.raises(OSError):
        store.replace("missing", b"new-private-value")
    assert not (store.directory / "missing.sealed").exists()
