import pytest
from mediahub.apps.plex import PlexInstallation
from mediahub.errors import DomainError

from agent.plex_install import PlexInstallPolicy, PlexVPNInstallPolicy, installation_plan


@pytest.fixture
def install_policy(tmp_path):
    return PlexInstallPolicy(
        hostId="local",
        bindAddress="192.0.2.10",
        image="lscr.io/linuxserver/plex@sha256:" + "a" * 64,
        initImage="sha256:" + "b" * 64,
        storage={
            kind: {"label": kind, "kind": kind, "path": str(tmp_path / kind)}
            for kind in ("movies", "tv", "other", "appdata")
        },
        hostMountSnapshot=str(tmp_path / "snapshot"),
        requiredFilesystemUuids={str(tmp_path): "verified-media"},
        storageMarkers={str(tmp_path / "marker"): "verified-media"},
    )


def spec(**kwargs):
    return PlexInstallation(
        moviesStorageIds=["movies"], tvStorageIds=["tv"], appdataStorageId="appdata", **kwargs
    )


def test_plan_has_readonly_media_and_ram_account_preferences(install_policy):
    plan = installation_plan(install_policy, spec())
    mounts = plan["container"]["HostConfig"]["Mounts"]
    assert all(m["ReadOnly"] for m in mounts if m["Target"].startswith("/media/"))
    assert all(not m["Target"].endswith("Preferences.xml") for m in mounts)
    assert plan["runtimeVolume"]["DriverOpts"]["type"] == "tmpfs"
    assert "noswap" in plan["runtimeVolume"]["DriverOpts"]["o"]
    assert plan["container"]["HostConfig"]["RestartPolicy"]["Name"] == "no"
    assert plan["planDigest"] == installation_plan(install_policy, spec())["planDigest"]


def test_mapping_cannot_read_appdata_as_media(install_policy):
    body = spec()
    body.moviesStorageIds = ["appdata"]
    with pytest.raises(DomainError):
        installation_plan(install_policy, body)


def test_host_and_storage_guards_required(install_policy):
    with pytest.raises(DomainError):
        installation_plan(install_policy, spec(hostId="another-host"))
    install_policy.requiredFilesystemUuids = {}
    with pytest.raises(DomainError):
        installation_plan(install_policy, spec())


def test_verified_pooled_mount_is_a_valid_storage_guard(install_policy, tmp_path):
    install_policy.requiredFilesystemUuids = {}
    install_policy.requiredMounts = {str(tmp_path): "mediahub-main"}

    plan = installation_plan(install_policy, spec())

    assert plan["installation"]["moviesStorageIds"] == ["movies"]


def test_appdata_cannot_overlap_existing_media(install_policy):
    install_policy.storage["appdata"].path = install_policy.storage["movies"].path
    with pytest.raises(DomainError):
        installation_plan(install_policy, spec())


def test_vpn_plan_moves_host_port_to_owned_gateway(install_policy):
    install_policy.vpn = PlexVPNInstallPolicy(
        image="qmcgaw/gluetun@sha256:" + "c" * 64,
        lanSubnet="192.168.1.0/24",
    )

    plan = installation_plan(install_policy, spec())

    assert plan["container"]["HostConfig"]["NetworkMode"] == ("container:mediahub-plex-main-vpn")
    assert "PortBindings" not in plan["container"]["HostConfig"]
    assert "ExposedPorts" not in plan["container"]
    assert "NetworkingConfig" not in plan["container"]
    assert plan["vpn"]["expectedCountryCode"] == "DK"
