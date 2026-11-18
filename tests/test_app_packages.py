import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from mediahub import app_packages as packages
from mediahub.errors import DomainError

from scripts import app_package_fetch as fetch


def request(root):
    updater = SimpleNamespace(
        root=root,
        available=True,
        _host_capability=lambda key: True,
        status=lambda: {"state": "idle"},
    )
    svc = SimpleNamespace(
        platform_update=updater, setup=SimpleNamespace(require_complete=lambda: None)
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=svc)))


def test_retry_preserves_existing_job_and_shows_its_state(tmp_path):
    req = request(tmp_path)
    answer = packages.queue("mediaupload", packages.Selection(location="movies"), req)["data"]
    assert packages.details("mediaupload", req)["data"]["operationId"] == answer["operationId"]
    with pytest.raises(DomainError):
        packages.queue("video-downloader", packages.Selection(location="videos"), req)
    job = json.loads((tmp_path / "request.json").read_text())
    assert job["app"] == "mediaupload" and job["location"] == "movies"


def test_credentials_are_separate_and_read_once(tmp_path):
    req = request(tmp_path)
    (tmp_path / "first-login-mediaupload.json").write_text(
        json.dumps({"username": "fixture", "password": "synthetic"})
    )
    assert packages.details("mediaupload", req)["data"]["firstLogin"] is True
    response = packages.first_login("mediaupload", req)
    assert (
        json.loads(response.body)["data"]["username"] == "fixture"
        and response.headers["cache-control"] == "no-store"
    )
    with pytest.raises(DomainError):
        packages.first_login("mediaupload", req)


def test_host_catalog_and_checksum_failure_before_staging(tmp_path, monkeypatch):
    releases = json.loads(
        (Path(__file__).resolve().parents[1] / "scripts/app-package-releases.json").read_text()
    )
    assert set(releases) == set(fetch.APPS)
    monkeypatch.setattr(fetch, "fetch", lambda url, limit: b"incomplete-download")
    for app, approved in releases.items():
        monkeypatch.setattr(
            fetch, "signed_index", lambda app: {**releases[app], "minimumHub": "0.6.96"}
        )
        with pytest.raises(ValueError, match="checksum"):
            fetch.retrieve(app, tmp_path, approved, "0.6.96")
    assert list(tmp_path.iterdir()) == []


def test_signed_channel_rejects_a_changed_index(tmp_path, monkeypatch):
    # A correctly sized but unrelated signature must fail before any package is fetched.
    import base64

    invalid = {
        "app": "mediaupload",
        "version": "9.0.0",
        "signature": base64.b64encode(bytes(64)).decode(),
    }
    monkeypatch.setattr(fetch, "fetch", lambda url, limit: json.dumps(invalid).encode())
    with pytest.raises(ValueError, match="signature verification"):
        fetch.retrieve("mediaupload", tmp_path)
