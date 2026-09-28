import json

import pytest
from mediahub.apps.seedbox import SeedboxInstallation, SeedboxRuntimePaths, compose_plan, start_gate
from pydantic import ValidationError


def spec(**kwargs):
    return SeedboxInstallation(
        installationId="seedbox-test",
        hostId="remote-test",
        downloadsStorageId="test-only",
        credentialRef="vpn_test",
        **kwargs,
    )


def paths(**kwargs):
    return SeedboxRuntimePaths(
        **(
            {
                "downloads": "/data/downloads",
                "appdata": "/opt/seedbox/qbit",
                "vpnState": "/opt/seedbox/vpn",
                "vpnConfig": "/opt/seedbox/secrets/vpn.conf",
                "dnsConfig": "/opt/seedbox/dns.conf",
                "vpnImage": "qmcgaw/gluetun@sha256:" + "a" * 64,
                "torrentImage": "lscr.io/linuxserver/qbittorrent@sha256:" + "b" * 64,
            }
            | kwargs
        )
    )


def test_no_independent_torrent_network_or_mount_creation():
    plan = compose_plan(spec(), paths())
    vpn, torrent = plan["services"]["vpn"], plan["services"]["torrent"]
    assert torrent["network_mode"] == "service:vpn"
    assert "ports" not in torrent and "networks" not in torrent
    assert vpn["ports"] == ["127.0.0.1:18080:18080/tcp"]
    assert torrent["environment"]["WEBUI_PORT"] == "18080"
    assert vpn["environment"]["FIREWALL_INPUT_PORTS"] == "18080"
    assert vpn["environment"]["LOG_LEVEL"] == "warn"
    for service in plan["services"].values():
        assert service["restart"] == "no"
        assert all(v["bind"]["create_host_path"] is False for v in service["volumes"])
    serialized = json.dumps(plan)
    assert "movies" not in serialized and "tv" not in serialized
    assert "PRIVATE_KEY" not in serialized and "vpn_test" not in serialized


def test_openvpn_provider_independent_design():
    vpn = compose_plan(spec(protocol="openvpn", provider="example-provider"), paths())["services"][
        "vpn"
    ]
    assert vpn["environment"]["VPN_TYPE"] == "openvpn"
    assert vpn["environment"]["VPN_SERVICE_PROVIDER"] == "custom"


def test_runtime_paths_fail_closed():
    with pytest.raises(ValidationError):
        paths(vpnImage="qmcgaw/gluetun:latest")
    with pytest.raises(ValidationError):
        paths(downloads="/")
    with pytest.raises(ValidationError):
        paths(appdata="/data/downloads/config")


def test_start_gate():
    safe = dict(
        mount_verified=True,
        device_health="healthy",
        tunnel_verified=True,
        requested_service="torrent",
    )
    assert start_gate(**safe)
    for field, value in (
        ("mount_verified", False),
        ("device_health", "critical"),
        ("device_health", "unknown"),
        ("tunnel_verified", False),
    ):
        assert not start_gate(**(safe | {field: value}))
    assert start_gate(**(safe | {"requested_service": "vpn", "tunnel_verified": False}))


def extra(**changes):
    return (
        dict(
            logicalId="legacy-seed",
            source="/data/legacy-seed",
            target="/legacy/seed",
            nfsSource="host:/legacy-seed",
            storageMarker="legacy-test-marker",
            readOnly=True,
        )
        | changes
    )


def test_legacy_seed_mapping_is_scoped_readonly_and_never_created():
    plan = compose_plan(spec(), paths(extraStorage=[extra()]))
    mount = plan["services"]["torrent"]["volumes"][-1]
    assert mount == {
        "type": "bind",
        "source": "/data/legacy-seed",
        "target": "/legacy/seed",
        "read_only": True,
        "bind": {"create_host_path": False},
    }
    assert len(plan["services"]["vpn"]["volumes"]) == 2


def test_explicit_torrent_destination_requires_write_access():
    with pytest.raises(ValidationError):
        paths(extraStorage=[extra(allowTorrentDownload=True)])

    runtime = paths(
        extraStorage=[
            extra(
                logicalId="movies",
                displayName="Movies",
                source="/data/movies",
                target="/media/movies",
                nfsSource="host:/movies",
                storageMarker="movies-marker",
                readOnly=False,
                allowTorrentDownload=True,
            )
        ]
    )
    mapping = runtime.extraStorage[0]
    assert mapping.displayName == "Movies"
    assert mapping.allowTorrentDownload is True
    mount = compose_plan(spec(), runtime)["services"]["torrent"]["volumes"][-1]
    assert mount["target"] == "/media/movies" and mount["read_only"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"source": "/"},
        {"source": "/data/downloads/sub"},
        {"source": "/opt/seedbox"},
        {"target": "/downloads/legacy"},
        {"target": "/config/legacy"},
        {"target": "/proc/test"},
        {"target": "/etc/test"},
        {"target": "/legacy/../seed"},
    ],
)
def test_legacy_mapping_cannot_shadow_system_or_existing_storage(change):
    with pytest.raises(ValidationError):
        paths(extraStorage=[extra(**change)])


def test_duplicate_legacy_mount_rejected():
    with pytest.raises(ValidationError):
        paths(extraStorage=[extra(), extra()])
