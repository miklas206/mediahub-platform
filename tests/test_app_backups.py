import pytest
from cryptography.exceptions import InvalidTag
from mediahub.app_backups import create_archive, restore_new_directory, verify_archive

PASSWORD = "isolated-app-backup-password"


def test_encrypted_app_backup_restore_and_preserve(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.ini").write_bytes(b"SECRET_MARKER_TEST")
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"MEDIA_NOT_INCLUDED")
    archive = create_archive("plex", {"configuration": config}, PASSWORD)
    assert b"SECRET_MARKER_TEST" not in archive
    assert b"MEDIA_NOT_INCLUDED" not in archive
    assert verify_archive(archive, PASSWORD)["files"] == 1
    with pytest.raises(InvalidTag):
        verify_archive(archive, "wrong")
    restored = tmp_path / "offline"
    restore_new_directory(archive, PASSWORD, restored)
    assert (restored / "configuration/settings.ini").read_bytes() == b"SECRET_MARKER_TEST"
    with pytest.raises(ValueError):
        restore_new_directory(archive, PASSWORD, restored)
    assert media.read_bytes() == b"MEDIA_NOT_INCLUDED"


def test_reject_changed_archive(tmp_path):
    source = tmp_path / "config"
    source.write_text("value")
    archive = create_archive("seedbox", {"settings": source}, PASSWORD)
    with pytest.raises(InvalidTag):
        verify_archive(archive[:-1] + bytes([archive[-1] ^ 1]), PASSWORD)


@pytest.mark.parametrize("label", ["../escape", "/absolute", "a/../b", "a\\b", "C:bad"])
def test_unsafe_archive_paths_rejected(tmp_path, label):
    source = tmp_path / "config"
    source.write_text("value")
    with pytest.raises(ValueError):
        create_archive("plex", {label: source}, PASSWORD)


def test_oversized_config_refused(tmp_path, monkeypatch):
    from mediahub import app_backups

    source = tmp_path / "config"
    source.write_bytes(b"large")
    monkeypatch.setattr(app_backups, "LIMIT", 4)
    with pytest.raises(ValueError):
        create_archive("seedbox", {"settings": source}, PASSWORD)
