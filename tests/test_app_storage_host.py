import copy
import json
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.nas_storage import plex_nas_ready
from scripts.storage_host import StorageError, StorageHost, save

NAS = "a" * 24


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "hub"
    root.mkdir()
    (root / "updates").mkdir()
    (root / "agent").mkdir()
    (root / "data").mkdir()
    host = StorageHost(root)
    host.userspace_mounts = lambda: False
    save(root / "storage-policy.json", {"lan": "192.168.1.50", "locations": []})
    save(
        host.file,
        {
            "nas": [
                {
                    "id": NAS,
                    "label": "Synthetic NAS",
                    "server": "192.168.1.50",
                    "share": "Media",
                    "readOnly": False,
                    "enabled": True,
                }
            ],
            "shares": [],
            "passwordConfigured": False,
        },
    )
    host.nas_ready = lambda row: True
    host.mount_info = lambda path: {
        "target": str(path),
        "source": "//192.168.1.50/Media",
        "fstype": "cifs",
    }
    host.apps.view = lambda *args, **kwargs: host.apps.views / NAS
    host.apps.write_status = lambda: None
    monkeypatch.setattr("scripts.app_storage_host.os.chown", lambda *args: None)
    containers = {}
    original_mount = {
        "Type": "bind",
        "Source": "/approved/local",
        "Target": "/downloads/local",
        "ReadOnly": False,
    }
    for kind, services in [
        ("mediaseed", ["app", "qbittorrent"]),
        ("mediavpn", ["app", "sso-proxy"]),
    ]:
        project = "mediahub-" + kind
        cfg = {"name": project, "services": {}}
        for service in services:
            name = project + "-" + service
            cfg["services"][service] = {
                "environment": {},
                "volumes": [
                    {"type": "bind", "source": "/approved/local", "target": "/downloads/local"}
                ],
            }
            containers[name] = {
                "Id": name,
                "Name": "/" + name,
                "Image": "sha256:reviewed-image",
                "State": {"Running": False, "Restarting": False},
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": project,
                        "com.docker.compose.service": service,
                        "org.mediahub.mediavpn.nas-storage": "rslave-v1",
                    },
                    "Env": ["SECRET=synthetic-private-setting"],
                },
                "HostConfig": {
                    "Mounts": [copy.deepcopy(original_mount)],
                    "Memory": 512 * 1024**2,
                    "NetworkMode": "container:verified-vpn",
                    "SecurityOpt": ["no-new-privileges:true"],
                },
                "Mounts": [
                    {"Source": "/approved/local", "Destination": "/downloads/local", "RW": True}
                ],
                "NetworkSettings": {"Networks": {}},
            }
        folder = root / "local-apps" / kind
        folder.mkdir(parents=True)
        save(folder / "compose.json", cfg)
    save(
        root / "data/managed-apps.json",
        {
            "org.mediahub." + kind: {"project": "mediahub-" + kind}
            for kind in ["mediaseed", "mediavpn"]
        },
    )
    calls = []
    fail = {"creation": None}

    def docker(method, path, body=None):
        from urllib.parse import parse_qs, unquote, urlsplit

        calls.append((method, path, copy.deepcopy(body)))
        if method == "GET" and path.startswith("/containers/json"):
            query = parse_qs(urlsplit(path).query)
            labels = json.loads(unquote(query.get("filters", ["{}"])[0])).get("label", [])
            return [
                {
                    "Id": key,
                    "Names": [row["Name"]],
                    "State": "running" if row["State"]["Running"] else "exited",
                }
                for key, row in containers.items()
                if all(
                    row["Config"]["Labels"].get(k) == v
                    for k, v in (label.split("=", 1) for label in labels)
                )
            ]
        if method == "POST" and path.startswith("/containers/create"):
            name = parse_qs(urlsplit(path).query)["name"][0]
            if fail["creation"] == name:
                raise StorageError("Synthetic container failure")
            key = name + "-replacement-" + str(len(calls))
            containers[key] = {
                "Id": key,
                "Name": "/" + name,
                "Image": body["Image"],
                "State": {"Running": False},
                "Config": {
                    k: v for k, v in body.items() if k not in {"HostConfig", "NetworkingConfig"}
                },
                "HostConfig": copy.deepcopy(body["HostConfig"]),
                "NetworkSettings": {"Networks": {}},
            }
            return {"Id": key}
        key = path.split("/")[2]
        if method == "GET":
            row = containers.get(key) or next(
                r for r in containers.values() if r["Name"] == "/" + key
            )
            return copy.deepcopy(row)
        if method == "DELETE":
            assert not containers[key]["State"]["Running"]
            del containers[key]
            return {}
        if method == "POST" and "/rename?" in path:
            containers[key]["Name"] = "/" + parse_qs(urlsplit(path).query)["name"][0]
            return {}
        raise AssertionError((method, path))

    host.apps.docker = docker
    return host, containers, calls, fail


@pytest.mark.parametrize("network", ["container:verified-vpn", "bridge"])
def test_recreation_normalizes_only_shared_network_metadata(installation, network):
    host, containers, _, _ = installation
    row = copy.deepcopy(containers["mediahub-mediaseed-app"])
    row["HostConfig"]["NetworkMode"] = network
    row["Config"].update(Hostname="daemon-inherited", ExposedPorts={"32400/tcp": {}})
    before = copy.deepcopy(row)
    spec = host.apps.specification(row)
    assert row == before
    assert spec["Image"] == row["Image"]
    assert spec["HostConfig"] == row["HostConfig"]
    assert spec["Env"] == row["Config"]["Env"]
    if network.startswith("container:"):
        assert "Hostname" not in spec
        assert "ExposedPorts" not in spec
    else:
        assert spec["Hostname"] == "daemon-inherited"
        assert spec["ExposedPorts"] == {"32400/tcp": {}}


def test_existing_plex_vpn_container_can_attach_and_remove_nas(installation):
    host, containers, calls, _ = installation
    row = copy.deepcopy(containers["mediahub-mediaseed-app"])
    row.update(Id="plex", Name="/plex")
    row["Config"].update(
        Hostname="inherited-vpn-hostname",
        ExposedPorts={"32400/tcp": {}},
        Labels={
            "org.mediahub.package": "org.mediahub.plex",
            "org.mediahub.installation": "synthetic",
        },
    )
    containers["plex"] = row
    policy = {
        "container": "plex",
        "installationId": "synthetic",
        "imageId": row["Image"],
        "controlStatePath": "/state/plex-intent.json",
        "mounts": [{"source": "/approved/local", "target": "/downloads/local", "readOnly": False}],
    }
    save(host.root / "agent/plex-managed.json", policy)
    save(host.root / "agent/plex-intent.json", {"desiredRunning": False})
    save(
        host.root / "agent/plex-plan.json",
        {
            "installation": {"installationId": "synthetic"},
            "container": {"HostConfig": copy.deepcopy(row["HostConfig"])},
        },
    )
    original_docker = host.apps.docker

    def docker(method, path, body=None):
        if method == "POST" and path.startswith("/containers/create"):
            # Match the real Engine's validation, absent from the older fake.
            assert "Hostname" not in body
            assert "ExposedPorts" not in body
            assert body["HostConfig"]["NetworkMode"] == "container:verified-vpn"
        result = original_docker(method, path, body)
        if method == "POST" and path.startswith("/containers/create"):
            containers[result["Id"]]["Mounts"] = [
                {"Source": m["Source"], "Destination": m["Target"], "RW": not m["ReadOnly"]}
                for m in body["HostConfig"]["Mounts"]
            ]
        return result

    host.apps.docker = docker
    for attach in (True, False):
        assert host.apps.change("plex", NAS, attach)["saved"]
        current = next(r for r in containers.values() if r["Name"] == "/plex")
        assert not current["State"]["Running"]
        assert current["Image"] == row["Image"]
        assert current["Config"]["Env"] == row["Config"]["Env"]
        mounts = current["HostConfig"]["Mounts"]
        assert mounts[0] == row["HostConfig"]["Mounts"][0]
        if attach:
            assert mounts[1]["ReadOnly"] is True
            assert mounts[1]["Target"].endswith(NAS)
        else:
            assert len(mounts) == 1
    assert host.state()["appBindings"] == []
    assert not any(path.endswith("/start") for _, path, _ in calls)


def test_media_seed_attachment_is_additive_persistent_and_vpn_bound(installation):
    host, containers, calls, _ = installation
    assert host.apps.change("mediaseed", NAS, True)["saved"]
    bindings = host.state()["appBindings"]
    assert bindings == [{"app": "mediaseed", "storageId": NAS}]
    cfg = json.loads((host.root / "local-apps/mediaseed/compose.json").read_text())
    for service in ["app", "qbittorrent"]:
        volumes = cfg["services"][service]["volumes"]
        assert volumes[0]["source"] == "/approved/local"
        assert volumes[1]["bind"] == {"create_host_path": False, "propagation": "rslave"}
    roots = json.loads(cfg["services"]["app"]["environment"]["MEDIASEED_STORAGE_ROOTS"])
    assert roots[0]["path"].endswith("/nas-" + NAS + "/files")
    vpn = json.loads((host.root / "local-apps/mediavpn/compose.json").read_text())
    mapping = json.loads(vpn["services"]["app"]["environment"]["MEDIAVPN_MEDIASEED_STORAGE"])
    assert mapping[0]["source"] == str(host.apps.views / NAS)
    created = [
        body
        for method, path, body in calls
        if method == "POST" and path.startswith("/containers/create")
    ]
    assert len(created) == 3
    for body in created:
        assert body["HostConfig"]["Memory"] == 512 * 1024**2
        assert body["HostConfig"]["NetworkMode"] == "container:verified-vpn"
        assert body["HostConfig"]["SecurityOpt"] == ["no-new-privileges:true"]
        assert "SECRET=synthetic-private-setting" in body["Env"]
    count = len(calls)
    assert host.apps.change("mediaseed", NAS, True)["saved"]
    assert len(calls) == count  # Idempotent save, no restarts.
    assert all(not r["State"]["Running"] for r in containers.values())
    assert stat.S_IMODE((host.folder / "app-storage-operation.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("service", ["mediahub-mediaseed-app", "mediahub-mediavpn-app"])
def test_running_app_is_rejected_before_storage_or_container_changes(installation, service):
    host, containers, calls, _ = installation
    containers[service]["State"]["Running"] = True
    before = host.file.read_bytes()
    with pytest.raises(StorageError, match="Stop the app"):
        host.apps.change("mediaseed", NAS, True)
    assert host.file.read_bytes() == before
    assert not [c for c in calls if c[0] != "GET"]


def test_partial_container_failure_restores_previous_names_configs_and_bindings(installation):
    host, containers, calls, fail = installation
    before = {p: p.read_bytes() for p in (host.root / "local-apps").rglob("compose.json")}
    fail["creation"] = "mediahub-mediavpn-app"
    with pytest.raises(StorageError, match="Synthetic"):
        host.apps.change("mediaseed", NAS, True)
    assert all(p.read_bytes() == value for p, value in before.items())
    assert host.state().get("appBindings", []) == []
    assert all(r["Name"] == "/" + key for key, r in containers.items())
    assert (
        json.loads((host.folder / "app-storage-operation.json").read_text())["state"]
        == "rolled_back"
    )
    assert not any(
        path.endswith("/start") or "force=" in path or "v=1" in path for _, path, _ in calls
    )


def test_attachment_removal_preserves_local_storage_and_never_deletes_media(installation):
    host, _, calls, _ = installation
    host.apps.change("mediaseed", NAS, True)
    host.apps.change("mediaseed", NAS, False)
    assert host.state()["appBindings"] == []
    cfg = json.loads((host.root / "local-apps/mediaseed/compose.json").read_text())
    assert len(cfg["services"]["app"]["volumes"]) == 1
    assert json.loads(cfg["services"]["app"]["environment"]["MEDIASEED_STORAGE_ROOTS"]) == []
    assert all(not path.startswith("/volumes/") for _, path, _ in calls)


@pytest.mark.parametrize(
    "data",
    [
        None,
        {"observedAt": 0, "nas": {NAS: True}},
        {"observedAt": time.time(), "nas": {NAS: False}},
        {"observedAt": time.time(), "nas": {NAS: True}},
    ],
)
def test_plex_supervisor_requires_fresh_positive_nas_evidence(tmp_path, data):
    policy = SimpleNamespace(mounts=[SimpleNamespace(target="/media/nas/" + NAS)])
    if data:
        save(tmp_path / "nas-storage-status.json", data)
    assert plex_nas_ready(policy, tmp_path) is bool(
        data and data["observedAt"] > 0 and data["nas"][NAS]
    )
    assert plex_nas_ready(SimpleNamespace(mounts=[]), tmp_path)


@pytest.mark.parametrize(
    "stats",
    [
        None,
        {"uploadsQueued": 1, "uploadsInProgress": 0, "erroredFiles": 0},
        {"uploadsQueued": 0, "uploadsInProgress": 0, "erroredFiles": 0},
    ],
)
def test_disconnect_requires_confirmed_write_cache_uploads(installation, stats):
    host, _, _, _ = installation
    row = {**host.state()["nas"][0], "cacheLocationId": "movies"}
    host.run = lambda *args, **kwargs: json.dumps({"diskCache": stats})
    if stats and stats["uploadsQueued"] == 0:
        host.apps.require_flushed(row)
    else:
        with pytest.raises(StorageError, match="not confirmed uploaded"):
            host.apps.require_flushed(row)


def test_private_inventory_never_exposes_compose_credentials(installation):
    host, _, _, _ = installation
    host.apps.change("mediaseed", NAS, True)
    public = json.dumps(host.apps.public())
    assert "SECRET" not in public and "synthetic-private-setting" not in public
    assert "files" in public


def test_view_reconnect_inspects_mount_before_touching_dead_fuse_path(installation, monkeypatch):
    host, _, _, _ = installation
    apps = host.apps
    # Exercise the real method instead of the fixture's view substitute.
    from scripts.app_storage_host import AppStorage

    parent = apps.views / (NAS + "-ro")
    parent.mkdir(parents=True)
    target = parent / "files"
    target.mkdir()
    operations = []
    mounted = [True]
    apps.directory = lambda *args: None
    host.mount_info = lambda path: (
        {"target": str(path), "source": "//192.168.1.50/Media", "fstype": "cifs"}
        if path != target or mounted[0]
        else {}
    )
    original_stat = Path.stat
    original_symlink = Path.is_symlink

    def stat_path(path, *args, **kwargs):
        if path == target and mounted[0]:
            raise OSError(107, "Synthetic disconnected FUSE")
        return original_stat(path, *args, **kwargs)

    def symlink(path):
        if path == target and mounted[0]:
            pytest.fail("Dead FUSE must not be inspected before its mount is identified")
        return original_symlink(path)

    def run(args, **kwargs):
        operations.append(args)
        if args[:1] == ["umount"]:
            mounted[0] = False
        return ""

    monkeypatch.setattr(Path, "stat", stat_path)
    monkeypatch.setattr(Path, "is_symlink", symlink)
    host.run = run
    AppStorage.view(apps, NAS, read_only=True)
    assert ["umount", str(target)] in operations
    assert any(args[:4] == ["mount", "--bind", "-o", "ro"] for args in operations)


def test_interrupted_recreation_can_restore_stopped_apps_without_deleting_files(installation):
    host, containers, _, _ = installation
    original = host.apps.docker

    def crash(method, path, body=None):
        if method == "POST" and path.startswith(
            "/containers/create?name=mediahub-mediaseed-qbittorrent"
        ):
            raise KeyboardInterrupt("Synthetic process loss")
        return original(method, path, body)

    host.apps.docker = crash
    before = {p: p.read_bytes() for p in (host.root / "local-apps").rglob("compose.json")}
    with pytest.raises(KeyboardInterrupt):
        host.apps.change("mediaseed", NAS, True)
    assert host.apps.public()["interrupted"]
    host.apps.docker = original
    assert host.apps.recover()["saved"]
    assert not host.apps.public()["interrupted"]
    assert all(r["Name"] == "/" + key for key, r in containers.items())
    assert all(not r["State"]["Running"] for r in containers.values())
    assert all(p.read_bytes() == value for p, value in before.items())
    assert host.state()["appBindings"] == []


def test_write_cache_refuses_the_system_filesystem(installation, tmp_path, monkeypatch):
    host, _, _, _ = installation
    media = tmp_path / "approved-media"
    media.mkdir()
    host.location = lambda _: {"kind": "local", "source": str(media), "mountTarget": str(media)}
    import os

    original_stat = os.stat
    device = original_stat(media).st_dev

    def stat_path(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if str(path) == "/":
            fields = list(value)
            fields[2] = device
            return os.stat_result(fields)
        return value

    monkeypatch.setattr("scripts.app_storage_host.os.stat", stat_path)
    host.mount_info = lambda path: {"fstype": "ext4"}
    calls = []
    host.run = lambda args, **kwargs: calls.append(args)
    with pytest.raises(StorageError, match="not the system disk"):
        host.apps.cache_directory({"id": NAS, "cacheLocationId": "downloads"})
    assert not calls


def test_write_cache_selection_preserves_nas_identity_and_login(
    installation, tmp_path, monkeypatch
):
    host, _, _, _ = installation
    host.userspace_mounts = lambda: True
    host.locations = lambda: [
        {
            "id": "downloads",
            "source": str(tmp_path),
            "kind": "local",
            "mountTarget": "/mnt/media",
            "ready": True,
        }
    ]
    host.apps.cache_directory = lambda row: tmp_path / "cache"
    monkeypatch.setattr(
        "scripts.app_storage_host.os.statvfs",
        lambda _: SimpleNamespace(f_bavail=50, f_frsize=1024**3),
    )
    private = host.folder / (NAS + ".credentials")
    save(private, "username=synthetic\npassword=synthetic-private\n")
    before = private.read_bytes()
    calls = []
    host.run = lambda args, **kwargs: calls.append(args)
    mounted = []
    host.mount_nas = mounted.append
    host.apps.enable_writes(NAS)
    row = host.state()["nas"][0]
    assert row["cacheLocationId"] == "downloads"
    assert row["id"] == NAS and row["share"] == "Media"
    assert private.read_bytes() == before
    assert mounted[0] == row
    assert any(c[:2] == ["fusermount3", "-u"] for c in calls)


def test_install_recipe_is_updated_together_with_owned_media_seed_containers(installation):
    host, containers, _, _ = installation
    folder = host.root / "data/managed-install-recipes"
    folder.mkdir()
    for kind in ["mediaseed", "mediavpn"]:
        save(
            folder / (kind + ".json"),
            {
                "packageId": "org.mediahub." + kind,
                "containers": [
                    {"name": key, "spec": host.apps.specification(row)}
                    for key, row in containers.items()
                    if row["Config"]["Labels"]["com.docker.compose.project"] == "mediahub-" + kind
                ],
            },
        )
    host.apps.change("mediaseed", NAS, True)
    seed = json.loads((folder / "mediaseed.json").read_text())
    assert all(
        any(m["Target"].endswith(NAS) for m in entry["spec"]["HostConfig"]["Mounts"])
        for entry in seed["containers"]
    )
    vpn = json.loads((folder / "mediavpn.json").read_text())
    app = next(
        item
        for item in vpn["containers"]
        if item["spec"]["Labels"]["com.docker.compose.service"] == "app"
    )
    assert any(v.startswith("MEDIAVPN_MEDIASEED_STORAGE=") and NAS in v for v in app["spec"]["Env"])


def test_host_and_agent_cannot_change_app_storage_and_runtime_concurrently(installation):
    from mediahub.errors import DomainError

    from agent.nas_storage import app_storage_guard

    host, _, _, _ = installation
    with host.apps.runtime_guard():
        with pytest.raises(DomainError, match="Wait for the app storage change"):
            with app_storage_guard(host.root / "agent"):
                pytest.fail("Concurrent app operation acquired the NAS lock")
    with app_storage_guard(host.root / "agent"):
        with pytest.raises(StorageError, match="current app operation"):
            with host.apps.runtime_guard():
                pytest.fail("NAS change acquired an active app operation lock")


def test_app_can_browse_view_parent_but_cannot_write_missing_nas(installation):
    from scripts.app_storage_host import AppStorage

    host, _, _, _ = installation
    host.mount_info = lambda path: {}
    host.run = lambda args, **kwargs: ""
    parent = AppStorage.view(host.apps, NAS, files=False)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE((parent / "files").stat().st_mode) == 0o000


def test_older_vpn_requires_its_automatic_update_before_nas_attachment(installation):
    host, containers, calls, _ = installation
    containers["mediahub-mediavpn-app"]["Config"]["Labels"].pop("org.mediahub.mediavpn.nas-storage")
    before = host.file.read_bytes()
    with pytest.raises(StorageError, match="Update MediaVPN to 0.2.31"):
        host.apps.change("mediaseed", NAS, True)
    assert host.file.read_bytes() == before
    assert not [c for c in calls if c[0] != "GET"]
