import asyncio
import base64
import configparser
import hashlib
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mediahub.apps.seedbox_daily import AddTorrent, TorrentAction
from pydantic import ValidationError

from agent.seedbox_torrents import TorrentService
from agent.torrent_input import magnet_hash, torrent_hash
from agent.vpn_locations import LocationService, ProtonLocations


def test_location_failure_keeps_client_stopped(tmp_path):
    async def run():
        lifecycle = SimpleNamespace(
            lock=asyncio.Lock(), state={"desiredRunning": True}, persist=Mock()
        )
        driver = SimpleNamespace(
            stop_torrent=AsyncMock(),
            storage_guard=AsyncMock(side_effect=ValueError("Unavailable")),
            start_torrent=AsyncMock(),
        )
        control = SimpleNamespace(lifecycle=lifecycle, driver=driver)
        service = LocationService(control)
        service.context = lambda: (tmp_path, None, None)
        await service.apply({"country": "Denmark", "id": "test-provider-server"})
        assert lifecycle.state["desiredRunning"] is False
        assert driver.stop_torrent.await_count == 2
        driver.start_torrent.assert_not_awaited()
        assert control.operation["state"] == "failed"

    asyncio.run(run())


def encode(value):
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(encode(v) for v in value) + b"e"
    return b"d" + b"".join(encode(k) + encode(v) for k, v in sorted(value.items())) + b"e"


def test_automatic_location_retry_bounded_and_stops_on_success():
    async def run():
        service = LocationService(SimpleNamespace())
        service.apply = AsyncMock(side_effect=[False, True])
        await service.apply_candidates([{"id": "one"}, {"id": "two"}, {"id": "three"}])
        assert service.apply.await_count == 2
        assert service.apply.call_args_list[0].kwargs == {"final_attempt": False}
        service.apply = AsyncMock(return_value=False)
        await service.apply_candidates([{"id": "selected"}])
        service.apply.assert_awaited_once_with({"id": "selected"}, final_attempt=True)

    asyncio.run(run())


def metainfo(name=b"test.txt"):
    info = {
        b"name": name,
        b"length": 4,
        b"piece length": 16384,
        b"pieces": hashlib.sha1(b"test").digest(),
    }
    return encode({b"info": info}), hashlib.sha1(encode(info)).hexdigest()


def test_private_inputs_excluded_from_serialization():
    body = AddTorrent(
        magnet="magnet:?xt=urn:btih:"
        + "a" * 40
        + "&tr=https%3A%2F%2Ftracker.example%2FPRIVATE_TOKEN",
        storageId="downloads",
    )
    assert "PRIVATE_TOKEN" not in body.model_dump_json()
    assert "PRIVATE_TOKEN" not in repr(body)
    assert "PRIVATE_TOKEN" in body.private_payload()["magnet"]
    assert "downloadLocationId" not in body.private_payload()

    selected = body.model_copy(update={"downloadLocationId": "folder-" + "b" * 64})
    assert selected.private_payload()["downloadLocationId"] == "folder-" + "b" * 64


@pytest.mark.parametrize(
    "value",
    [
        "https://example.org/file.torrent",
        "magnet:?dn=test",
        "magnet:?xt=urn:btih:bad",
        "magnet:?xt=urn:btih:" + "a" * 40 + "&xs=file:///etc/passwd",
        "magnet:?xt=urn:btih:" + "a" * 40 + "&tr=file:///etc/passwd",
        "magnet:?xt=urn:btih:" + "a" * 40 + "\n",
    ],
)
def test_invalid_magnets_rejected(value):
    with pytest.raises(ValueError):
        magnet_hash(value)


def test_magnet_hex_base32_and_v2():
    raw = bytes(range(20))
    identity = raw.hex()
    assert magnet_hash("magnet:?xt=urn:btih:" + identity) == identity
    assert magnet_hash("magnet:?xt=urn:btih:" + base64.b32encode(raw).decode()) == identity
    assert magnet_hash("magnet:?xt=urn:btmh:1220" + "a" * 64) == "a" * 64


@pytest.mark.parametrize(
    "name", [b"..", b"/etc/passwd", b"foo/bar", b"foo\\bar", b"C:drive", b"bad\x00name"]
)
def test_metainfo_unsafe_paths(name):
    with pytest.raises(ValueError):
        torrent_hash(metainfo(name)[0])


def test_metainfo_valid_and_truncated():
    raw, identity = metainfo()
    assert torrent_hash(raw) == identity
    for value in [
        raw[:-1],
        raw + b"junk",
        b"not a torrent",
        b"d4:infodee",
        b"i999999999999999999999999e",
    ]:
        with pytest.raises((ValueError, TypeError)):
            torrent_hash(value)


def test_no_file_deletion_or_paths_in_action_contract():
    with pytest.raises(ValidationError):
        TorrentAction(hash="a" * 40, action="remove", deleteFiles=True)
    with pytest.raises(ValidationError):
        AddTorrent(magnet="test", storageId="downloads", savePath="/etc")
    with pytest.raises(ValidationError):
        TorrentAction(hash="all", action="remove")


def test_download_locations_are_opaque_bounded_directories(tmp_path):
    (tmp_path / "Movies").mkdir()
    (tmp_path / "TV").mkdir()
    (tmp_path / ".incomplete").mkdir()
    (tmp_path / "file.txt").write_text("not a folder")
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    try:
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pass

    policy = SimpleNamespace(paths=SimpleNamespace(downloads=str(tmp_path), extraStorage=[]))
    spec = SimpleNamespace(downloadsStorageId="downloads")
    locations = TorrentService.download_locations(policy, spec)
    assert [
        (item["storageLabel"], item["label"], item["savePath"]) for item in locations
    ] == [
        ("Downloads", "Top folder", "/downloads"),
        ("Downloads", "Movies", "/downloads/Movies"),
        ("Downloads", "TV", "/downloads/TV"),
    ]
    assert all("/" not in item["id"] for item in locations)
    assert all(str(tmp_path) not in item["id"] for item in locations)


def test_download_location_must_still_exist_and_match_opaque_id(tmp_path):
    folder = tmp_path / "Movies"
    folder.mkdir()
    policy = SimpleNamespace(paths=SimpleNamespace(downloads=str(tmp_path), extraStorage=[]))
    spec = SimpleNamespace(downloadsStorageId="downloads")
    location = TorrentService.download_locations(policy, spec)[1]
    assert (
        TorrentService.resolve_download_location(policy, spec, location["id"])
        == "/downloads/Movies"
    )
    folder.rename(tmp_path / "Renamed")
    with pytest.raises(Exception) as denied:
        TorrentService.resolve_download_location(policy, spec, location["id"])
    assert getattr(denied.value, "code", "") == "download_location_denied"


def test_explicit_writable_logical_storage_is_a_destination(tmp_path):
    downloads = tmp_path / "downloads"
    movies = tmp_path / "movies"
    downloads.mkdir()
    movies.mkdir()
    (movies / "Completed").mkdir()
    mapping = SimpleNamespace(
        logicalId="movies",
        displayName="Movies",
        source=str(movies),
        target="/media/movies",
        readOnly=False,
        allowTorrentDownload=True,
    )
    policy = SimpleNamespace(
        paths=SimpleNamespace(downloads=str(downloads), extraStorage=[mapping])
    )
    spec = SimpleNamespace(downloadsStorageId="downloads")

    locations = TorrentService.download_locations(policy, spec)
    assert [(item["storageLabel"], item["savePath"]) for item in locations] == [
        ("Downloads", "/downloads"),
        ("Movies", "/media/movies"),
        ("Movies", "/media/movies/Completed"),
    ]
    assert locations[1]["id"].startswith("location-")
    assert TorrentService.allowed_save_roots(policy, spec) == [
        PurePosixPath("/downloads"),
        PurePosixPath("/media/movies"),
    ]


def test_readonly_or_unapproved_extra_storage_is_not_a_destination(tmp_path):
    downloads = tmp_path / "downloads"
    extra = tmp_path / "extra"
    downloads.mkdir()
    extra.mkdir()
    mappings = [
        SimpleNamespace(
            logicalId="readonly",
            displayName="Read only",
            source=str(extra),
            target="/media/readonly",
            readOnly=True,
            allowTorrentDownload=False,
        ),
        SimpleNamespace(
            logicalId="unapproved",
            displayName="Unapproved",
            source=str(extra),
            target="/media/unapproved",
            readOnly=False,
            allowTorrentDownload=False,
        ),
    ]
    policy = SimpleNamespace(
        paths=SimpleNamespace(downloads=str(downloads), extraStorage=mappings)
    )
    spec = SimpleNamespace(downloadsStorageId="downloads")
    assert [item["storageLabel"] for item in TorrentService.download_locations(policy, spec)] == [
        "Downloads"
    ]


def test_duplicate_writable_logical_storage_ids_fail_closed(tmp_path):
    downloads = tmp_path / "downloads"
    first = tmp_path / "first"
    second = tmp_path / "second"
    for path in (downloads, first, second):
        path.mkdir()
    mappings = [
        SimpleNamespace(
            logicalId="movies",
            displayName="Movies one",
            source=str(first),
            target="/media/movies-one",
            readOnly=False,
            allowTorrentDownload=True,
        ),
        SimpleNamespace(
            logicalId="movies",
            displayName="Movies two",
            source=str(second),
            target="/media/movies-two",
            readOnly=False,
            allowTorrentDownload=True,
        ),
    ]
    policy = SimpleNamespace(
        paths=SimpleNamespace(downloads=str(downloads), extraStorage=mappings)
    )
    spec = SimpleNamespace(downloadsStorageId="downloads")
    with pytest.raises(ValueError, match="unique"):
        TorrentService.download_locations(policy, spec)


def test_download_location_contract_rejects_paths():
    with pytest.raises(ValidationError):
        AddTorrent(
            magnet="magnet:?xt=urn:btih:" + "a" * 40,
            storageId="downloads",
            downloadLocationId="../../etc",
        )


def test_download_location_contract_accepts_agent_opaque_logical_location():
    body = AddTorrent(
        magnet="magnet:?xt=urn:btih:" + "a" * 40,
        storageId="downloads",
        downloadLocationId="location-" + "b" * 64,
    )
    assert body.downloadLocationId == "location-" + "b" * 64


def test_proton_profile_only_changes_public_peer():
    private = base64.b64encode(b"x" * 32).decode()
    old = base64.b64encode(b"y" * 32).decode()
    new = base64.b64encode(b"z" * 32).decode()
    profile = f"[Interface]\nPrivateKey={private}\nAddress=10.2.0.2/32\nDNS=10.2.0.1\n[Peer]\nPublicKey={old}\nEndpoint=1.1.1.1:51820\nAllowedIPs=0.0.0.0/0\n"
    output = ProtonLocations().profile(profile, {"publicKey": new, "ips": ["9.9.9.9"]})
    parsed = configparser.ConfigParser()
    parsed.read_string(output)
    assert parsed["Interface"]["PrivateKey"] == private
    assert parsed["Interface"]["Address"] == "10.2.0.2/32"
    assert parsed["Peer"]["Endpoint"] == "9.9.9.9:51820" and parsed["Peer"]["PublicKey"] == new


def test_proton_catalog_excludes_nonp2p_securecore_private_ips():
    import json

    valid = {
        "vpn": "wireguard",
        "port_forward": True,
        "wgpubkey": base64.b64encode(b"x" * 32).decode(),
        "ips": ["1.1.1.1"],
        "hostname": "one.protonvpn.net",
        "country": "Denmark",
    }
    rows = [
        valid,
        dict(valid, port_forward=False),
        dict(valid, secure_core=True),
        dict(valid, ips=["192.168.1.1"]),
        dict(valid, vpn="openvpn"),
    ]
    driver = SimpleNamespace(
        container=AsyncMock(return_value={}), execute=AsyncMock(return_value=json.dumps(rows))
    )
    result = asyncio.run(ProtonLocations().servers(driver))
    assert len(result) == 1 and result[0]["country"] == "Denmark"
