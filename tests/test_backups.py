import io
import json
import sqlite3
import zipfile

import pytest
from cryptography.exceptions import InvalidTag
from mediahub.backups import CoreBackup, decrypt_archive, restore_new_directory, verified_members
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore

PASSWORD = "isolated-backup-test-password-123"
ARCHIVE_PASSWORD = "isolated-backup-encryption-password"


def test_encrypted_backup_roundtrip_and_exclusions(client, tmp_path):
    svc = client.app.state.services
    svc.auth.create_admin("test", PASSWORD)
    token, profile = svc.auth.login("test", PASSWORD, "test")
    store = SecretStore(svc.config.data_dir.resolve() / "private-records")
    store.put("test-token", b"SECRET_TEST_MARKER")
    (svc.config.data_dir / "media").mkdir()
    (svc.config.data_dir / "media" / "dont-backup.mkv").write_bytes(b"EXCLUDED_MEDIA_TEST")
    content = CoreBackup(svc).create(ARCHIVE_PASSWORD)
    assert b"SECRET_TEST_MARKER" not in content
    assert b"EXCLUDED_MEDIA_TEST" not in content
    with pytest.raises(InvalidTag):
        decrypt_archive(content, "wrong-password")
    with zipfile.ZipFile(io.BytesIO(decrypt_archive(content, ARCHIVE_PASSWORD))) as archive:
        assert archive.testzip() is None
        assert "core/private-records/master.key" in archive.namelist()
        assert (
            archive.read("core/secrets.key") == (svc.config.data_dir / "secrets.key").read_bytes()
        )
        assert all("dont-backup" not in name for name in archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert not manifest["mediaIncluded"] and not manifest["appRuntimeDataIncluded"]
        db = sqlite3.connect(":memory:")
        db.deserialize(archive.read("core/mediahub.db"))
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        db.close()


def test_backup_endpoint_requires_auth_csrf_and_password(client):
    assert client.get("/api/v1/backups").status_code == 401
    client.app.state.services.auth.create_admin("test", PASSWORD)
    login = client.post("/api/v1/auth/login", json={"username": "test", "password": PASSWORD})
    body = {"password": PASSWORD, "backupPassword": ARCHIVE_PASSWORD}
    assert client.post("/api/v1/backups/export", json=body).status_code == 403
    client.headers["X-MediaHub-CSRF"] = login.json()["data"]["csrf"]
    assert (
        client.post("/api/v1/backups/export", json={**body, "password": "wrong"}).status_code == 401
    )
    response = client.post("/api/v1/backups/export", json=body)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "application/octet-stream"


def test_offline_restore_only_new_directory(client, tmp_path):
    svc = client.app.state.services
    svc.auth.create_admin("test", PASSWORD)
    content = CoreBackup(svc).create(ARCHIVE_PASSWORD)
    manifest, _ = verified_members(content, ARCHIVE_PASSWORD)
    assert manifest["scope"] == "core-configuration"
    target = tmp_path / "restored"
    restore_new_directory(content, ARCHIVE_PASSWORD, target)
    assert (target / "secrets.key").read_bytes() == (
        svc.config.data_dir / "secrets.key"
    ).read_bytes()
    assert (target / "mediahub.db").is_file()
    with pytest.raises(ValueError):
        restore_new_directory(content, ARCHIVE_PASSWORD, target)
    with pytest.raises(InvalidTag):
        restore_new_directory(content, "incorrect", tmp_path / "bad-password")
    assert not (tmp_path / "bad-password").exists()


def test_backup_does_not_follow_private_config_symlink(client, tmp_path):
    directory = client.app.state.services.config.data_dir.resolve() / "private-records"
    try:
        directory.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit creating test symlinks")
    with pytest.raises(DomainError) as error:
        CoreBackup(client.app.state.services).create(ARCHIVE_PASSWORD)
    assert error.value.code == "backup_path_unsafe"
