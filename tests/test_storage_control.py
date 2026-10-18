import json
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from mediahub.storage_control import NasInput, body_values, prepare_storage

from scripts.storage_host import CONTAINER, StorageError, StorageHost, private_ip, save


@pytest.fixture
def controller(tmp_path):
    root = tmp_path / "hub"
    root.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    save(
        root / "storage-policy.json",
        {
            "lan": "192.168.1.15",
            "locations": [
                {
                    "id": "movies",
                    "label": "Movies",
                    "source": str(media),
                    "mountSource": "media-pool",
                    "mountTarget": str(media),
                }
            ],
        },
    )
    host = StorageHost(root)
    host.userspace_mounts = lambda: False
    host.mount_info = lambda path: {"source": "media-pool", "target": str(media), "fstype": "ext4"}
    host.smb_running = lambda: False
    yield host
    for child in host.mounts.iterdir():
        if child.is_dir():
            child.chmod(0o700)


def test_inventory_is_read_only_and_missing_mount_never_becomes_ready(controller):
    host = controller
    assert host.inventory()["locations"][0]["ready"]
    assert not host.file.exists()
    host.mount_info = lambda path: {"source": "system-disk", "target": "/", "fstype": "ext4"}
    assert not host.inventory()["locations"][0]["ready"]
    with pytest.raises(StorageError):
        host.location("movies")
    with pytest.raises(StorageError):
        host.location("/etc")


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "8.8.8.8", "169.254.169.254", "::1", "nas.local", "192.168.1.5;id"]
)
def test_nas_credentials_only_go_to_explicit_private_ips(address):
    with pytest.raises(StorageError):
        private_ip(address)


def test_nas_mount_credentials_are_private_and_survive_failed_mount(controller):
    host = controller
    calls = []
    host.packages = lambda: None

    def run(args, **kwargs):
        calls.append((args, kwargs))
        raise StorageError("Synthetic mount rejection")

    host.run = run
    body = {
        "label": "NAS",
        "server": "192.168.1.60",
        "share": "Media",
        "username": "test-user",
        "password": "synthetic-password",
        "readOnly": False,
    }
    with pytest.raises(StorageError, match="LXC"):
        host.add_nas(body)
    row = host.state()["nas"][0]
    credential = host.folder / (row["id"] + ".credentials")
    assert stat.S_IMODE(credential.stat().st_mode) == 0o600
    assert body["password"] in credential.read_text()
    assert body["password"] not in json.dumps(calls)
    assert body["password"] not in host.file.read_text()
    assert stat.S_IMODE((host.mounts / row["id"]).stat().st_mode) == 0
    assert not host.inventory()["nas"][0]["ready"]
    assert "password" not in host.inventory()["nas"][0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("server", "8.8.8.8"),
        ("share", "../etc"),
        ("password", "a\nusername=root"),
        ("username", "user\ndomain=root"),
        ("readOnly", "false"),
    ],
)
def test_invalid_nas_configuration_never_runs_commands(controller, field, value):
    host = controller
    host.run = lambda *args, **kwargs: pytest.fail("Invalid input reached host command")
    body = {
        "label": "NAS",
        "server": "192.168.1.60",
        "share": "Media",
        "username": "user",
        "password": "synthetic",
    }
    body[field] = value
    with pytest.raises(StorageError):
        host.add_nas(body)
    assert not host.file.exists()


def test_disconnect_rejects_attached_windows_share_and_preserves_credentials(controller):
    host = controller
    row = {
        "id": "a" * 24,
        "server": "192.168.1.60",
        "share": "Media",
        "label": "NAS",
        "username": "user",
        "readOnly": True,
        "enabled": True,
    }
    save(
        host.file,
        {
            "nas": [row],
            "shares": [{"name": "Media", "storageId": row["id"]}],
            "passwordConfigured": True,
        },
    )
    host.run = lambda *args, **kwargs: pytest.fail("Attached storage was touched")
    with pytest.raises(StorageError, match="Windows shares"):
        host.nas_action(row["id"], "remove")
    assert host.state()["nas"] == [row]


def test_saved_disabled_nas_never_reconnects_on_restart(controller):
    host = controller
    save(
        host.file,
        {"nas": [{"id": "a" * 24, "enabled": False}], "shares": [], "passwordConfigured": False},
    )
    host.mount_nas = lambda row: pytest.fail("Disabled NAS reconnected")
    host.reconcile()


@pytest.mark.parametrize("share", ["global", "homes", "../etc", "a\n[global]", "a,b"])
def test_share_names_cannot_inject_samba_configuration(controller, share):
    with pytest.raises(StorageError):
        controller.add_share(
            {"name": share, "storageId": "movies", "password": "synthetic-password"}
        )


def test_sharing_only_uses_approved_paths_and_password_uses_stdin(controller):
    host = controller
    calls = []
    host.smb_image = lambda: "owned-image"
    host.owned_smb = lambda: None
    host.smb_running = lambda: True
    host.run = lambda args, **kwargs: calls.append((args, kwargs)) or ""
    host.add_share(
        {"name": "Media", "storageId": "movies", "password": "synthetic-password", "readOnly": True}
    )
    command = next(args for args, _ in calls if args[:2] == ["docker", "run"])
    assert "192.168.1.15:445:445/tcp" in command
    assert "--privileged" not in command and "--network=host" not in command
    assert any("dst=/shares/Media,readonly" in item for item in command)
    assert all("synthetic-password" not in str(args) for args, _ in calls)
    assert any(
        kwargs.get("content") == "synthetic-password\nsynthetic-password\n" for _, kwargs in calls
    )
    assert "synthetic-password" not in host.file.read_text()
    assert "server min protocol = SMB3_00" in (host.folder / "samba/smb.conf").read_text()
    assert host.state()["shares"][0]["readOnly"]


def test_windows_share_cannot_escalate_read_only_nas(controller):
    host = controller
    host.smb_image = lambda: "owned-image"
    host.location = lambda _: {"source": "/approved", "readOnly": True}
    with pytest.raises(StorageError, match="read-only NAS"):
        host.configure_smb([{"name": "Media", "storageId": "a" * 24, "readOnly": False}])


def test_failed_replacement_restores_previous_windows_service(controller):
    host = controller
    host.smb_image = lambda: "owned-image"
    folder = host.folder / "samba"
    folder.mkdir()
    save(folder / "smb.conf", "previous-reviewed-config")
    observed = iter([{"State": {"Running": True}}, None])
    host.owned_smb = lambda: next(observed)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "inspect"]:
            raise StorageError("Not found")
        if args[:2] == ["docker", "run"]:
            raise StorageError("Synthetic port collision")
        return ""

    host.run = run
    with pytest.raises(StorageError, match="collision"):
        host.configure_smb([{"name": "Media", "storageId": "movies", "readOnly": True}])
    assert ["docker", "rename", CONTAINER + "-previous", CONTAINER] in calls
    assert ["docker", "start", CONTAINER] in calls
    assert (folder / "smb.conf").read_text() == "previous-reviewed-config"


def test_preparation_never_overwrites_pending_update(tmp_path):
    spool = tmp_path
    (spool / "request.json").write_text('{"action":"existing-update"}')
    updater = SimpleNamespace(available=True, root=spool, _host_capability=lambda _: True)
    with pytest.raises(DomainError) as error:
        prepare_storage(SimpleNamespace(platform_update=updater))
    assert error.value.code == "host_busy"
    assert json.loads((spool / "request.json").read_text())["action"] == "existing-update"
    assert list(spool.iterdir()) == [spool / "request.json"]


def test_api_secrets_are_hidden_in_models_but_forwarded_to_private_controller():
    model = NasInput(
        label="NAS",
        server="192.168.1.60",
        share="Media",
        username="test",
        password="synthetic-secret",
    )
    assert "synthetic-secret" not in repr(model)
    assert body_values(model)["password"] == "synthetic-secret"


def test_storage_api_requires_login_and_csrf(logged_in, monkeypatch):
    client = logged_in
    response = client.post("/api/v1/storage-control/prepare", headers={"X-MediaHub-CSRF": "wrong"})
    assert response.status_code == 403
    response = client.post(
        "/api/v1/storage-control/nas/" + "a" * 24 + "/credentials",
        headers={"X-MediaHub-CSRF": "wrong"},
        json={"username": "test", "password": "synthetic-secret"},
    )
    assert response.status_code == 403
    mock = AsyncMock(return_value={"available": True, "nas": [], "shares": [], "locations": []})
    monkeypatch.setattr("mediahub.storage_control.host_request", mock)
    assert client.get("/api/v1/storage-control").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/v1/storage-control").status_code == 401
    assert mock.await_count == 1


@pytest.mark.parametrize("existing", [False, True])
def test_storage_preparation_is_additive_on_fresh_and_older_installs(
    tmp_path, monkeypatch, existing
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import scripts.prepare_local_apps as module

    root, source = tmp_path / "hub", tmp_path / "source"
    (root / "updates").mkdir(parents=True)
    (source / "scripts").mkdir(parents=True)
    script = Path(__file__).resolve().parents[1] / "scripts/storage_host.py"
    (source / "scripts/storage_host.py").write_bytes(script.read_bytes())
    old = root / "storage-private/state.json"
    old.parent.mkdir()
    if existing:
        old.write_text('{"nas":[{"id":"old-private-state"}],"shares":[]}')
        (root / "updates/host-capabilities.json").write_text('{"sourceBuild":true}')
    monkeypatch.setattr(module.os, "chown", lambda *args: None)
    module.prepare_storage_host(root, "192.168.1.15", source, [])
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    module.prepare_storage_host(root, "192.168.1.15", source, [])
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    capabilities = json.loads((root / "updates/host-capabilities.json").read_text())
    assert capabilities["storageController"] is True
    assert len(capabilities["storageControllerRevision"]) == 64
    if existing:
        assert capabilities["sourceBuild"]
        assert "old-private-state" in old.read_text()
    assert not (root / "network-storage").exists()  # No mount before the host-side controller runs.


@pytest.mark.parametrize("existing", [False, True])
def test_storage_main_folder_is_prepared_once_and_checks_mount_identity(
    tmp_path, monkeypatch, existing
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import scripts.prepare_local_apps as module

    root, source, media = tmp_path / "hub", tmp_path / "source", tmp_path / "media"
    (root / "agent").mkdir(parents=True)
    (root / "updates").mkdir()
    (source / "scripts").mkdir(parents=True)
    (source / "scripts/storage_host.py").write_text("# reviewed test helper\n")
    (media / "movies").mkdir(parents=True)
    (media / "downloads").mkdir()
    marker = media / ".identity"
    marker.write_text("approved-pool")
    snapshot = tmp_path / "mounts.json"
    snapshot.write_text(json.dumps({"mounts": [{"path": str(media), "source": "pool"}]}))
    (root / "agent/container-apps.json").write_text(
        json.dumps(
            {
                "hostMountSnapshot": str(snapshot),
                "requiredMounts": {str(media): "pool"},
                "storageMarkers": {str(marker): "approved-pool"},
            }
        )
    )
    locations = [
        {"id": folder, "label": folder, "source": str(media / folder)}
        for folder in ("movies", "downloads")
    ]
    if existing:
        (root / "storage-private").mkdir()
        save(
            root / "storage-private/state.json",
            {"nas": [], "shares": [{"name": "Movies", "storageId": "movies", "readOnly": True}]},
        )
    monkeypatch.setattr(module.os, "chown", lambda *args: None)
    for _ in range(2):
        module.prepare_storage_host(root, "192.168.1.15", source, locations)
    policy = json.loads((root / "storage-policy.json").read_text())
    assert len(policy["locations"]) == 3
    main = policy["locations"][-1]
    assert main["source"] == str(media)
    host = StorageHost(root)
    host.mount_info = lambda path: {"source": "pool", "target": str(media)}
    assert host.location(main["id"])["ready"]
    marker.write_text("different-pool")
    with pytest.raises(StorageError):
        host.location(main["id"])
    if existing:
        assert host.state()["shares"][0]["storageId"] == "movies"


def test_host_storage_bootstrap_only_runs_the_reviewed_installer(tmp_path, monkeypatch):
    from scripts.platform_update_host import HostUpdater

    script = tmp_path / "storage_host.py"
    script.write_text("# synthetic reviewed source")
    script.chmod(0o700)
    updater = HostUpdater(tmp_path)
    updater.updates.mkdir()
    request = {"action": "storage_prepare", "operationId": "a" * 32}
    (updater.updates / "request.json").write_text(json.dumps(request))
    original_lstat = Path.lstat

    def lstat(path):
        info = original_lstat(path)
        return SimpleNamespace(st_uid=0, st_mode=info.st_mode) if path == script else info

    monkeypatch.setattr(Path, "lstat", lstat)
    calls = []
    updater.command = lambda *args: calls.append(args)
    updater._prepare_storage(request)
    assert calls == [
        (
            "systemd-run",
            "--quiet",
            "--wait",
            "--collect",
            "--unit=mediahub-storage-install",
            "/usr/bin/python3",
            str(script),
            "--root",
            str(tmp_path),
            "--install",
        )
    ]
    assert not (updater.updates / "request.json").exists()
    assert list(updater.updates.iterdir()) == []


def test_user_role_cannot_read_or_modify_storage_controller(logged_in, monkeypatch):
    from mediahub.db import User
    from sqlalchemy import select

    client = logged_in
    with client.app.state.services.sessions.begin() as db:
        user = db.scalar(select(User).where(User.username == "tester"))
        user.role = "user"
    mock = AsyncMock()
    monkeypatch.setattr("mediahub.storage_control.host_request", mock)
    assert client.get("/api/v1/storage-control").status_code == 403
    assert client.post("/api/v1/storage-control/prepare").status_code == 403
    assert client.post("/api/v1/storage-control/nas", json={}).status_code == 403
    assert mock.await_count == 0


def test_local_share_rejects_replaced_storage_identity(controller):
    host = controller
    policy = host.policy()
    marker = host.root / "identity"
    marker.write_text("expected-volume")
    policy["locations"][0]["markers"] = {str(marker): "expected-volume"}
    save(host.root / "storage-policy.json", policy)
    assert host.location("movies")["ready"]
    marker.write_text("another-volume")
    assert not host.inventory()["locations"][0]["ready"]
    with pytest.raises(StorageError):
        host.location("movies")
    assert "markers" not in host.inventory()["locations"][0]


def test_foreign_installations_smb_container_is_never_adopted(controller):
    from scripts.storage_host import OWNER

    controller.run = lambda *args, **kwargs: json.dumps(
        [{"Config": {"Labels": {OWNER: "smb", OWNER + ".installation": "another-installation"}}}]
    )
    with pytest.raises(StorageError, match="another service"):
        controller.owned_smb()


def test_userspace_nas_mount_uses_private_config_and_preserves_read_only(controller, monkeypatch):
    host = controller
    row = {"id": "a" * 24, "server": "192.168.1.60", "share": "Media", "readOnly": True}
    save(host.folder / (row["id"] + ".credentials"), "username=test\npassword=synthetic-secret\n")
    calls = []
    real_open = __import__("os").open
    monkeypatch.setattr(
        "scripts.storage_host.os.open",
        lambda path, flags, *args: real_open(
            "/dev/null" if str(path) == "/dev/fuse" else path, flags, *args
        ),
    )

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return "obscured-password" if args[:2] == ["rclone", "obscure"] else ""

    host.run = run
    host.mount_userspace(row, host.mounts / row["id"])
    assert calls[0][1]["content"] == "synthetic-secret"
    assert all("synthetic-secret" not in " ".join(args) for args, _ in calls)
    config = host.folder / (row["id"] + ".rclone.conf")
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert "synthetic-secret" not in config.read_text()
    mount = calls[-1][0]
    assert "--read-only" in mount
    assert "--property=Type=notify" in mount
    assert "nosuid,nodev,noexec" in mount
    host.mount_info = lambda path: {
        "target": str(host.mounts / row["id"]),
        "source": "mediahub-nas-" + row["id"],
        "fstype": "fuse.rclone",
    }
    assert host.nas_ready(row)
    assert not host.nas_ready({**row, "id": "b" * 24})


@pytest.mark.parametrize("existing", [False, True])
def test_proxmox_storage_preparation_preserves_other_devices(existing):
    from scripts.proxmox_storage import prepare

    calls = []

    def runner(*args):
        calls.append(args)
        if args[:2] == ("pct", "config"):
            return "unprivileged: 1\ndev0: path=/dev/net/tun\ndev1: path=/dev/nvidia0\n" + (
                "dev2: path=/dev/fuse,uid=0,gid=0,mode=0600\n" if existing else ""
            )
        return ""

    assert prepare("107", runner)["changed"] is not existing
    changes = [args for args in calls if args[:2] == ("pct", "set")]
    assert len(changes) == (0 if existing else 1)
    if changes:
        assert changes[0][3] == "--dev2"
        assert changes[0][4] == "path=/dev/fuse,uid=0,gid=0,mode=0600"
    assert not any("restart" in args or "reboot" in args for args in calls)


def test_correcting_saved_nas_login_keeps_id_and_retries(controller):
    host = controller
    row = {
        "id": "c" * 24,
        "server": "192.168.1.60",
        "share": "Media",
        "username": "old",
        "readOnly": False,
        "enabled": False,
        "error": "Old login rejected",
    }
    save(host.file, {"nas": [row], "shares": [], "passwordConfigured": False})
    host.packages = lambda: None
    attempts = []
    host.mount_nas = lambda value: attempts.append(value.copy())
    result = host.dispatch(
        "POST",
        "/nas/" + row["id"] + "/credentials",
        {"username": "updated", "password": "new-synthetic-secret"},
    )
    assert result == {"saved": True}
    saved = host.state()["nas"][0]
    assert saved["id"] == row["id"] and saved["enabled"] is True
    assert saved["username"] == "updated" and saved["readOnly"] is False
    assert "error" not in saved and len(attempts) == 1
    assert "new-synthetic-secret" not in host.file.read_text()
    assert "new-synthetic-secret" in (host.folder / (row["id"] + ".credentials")).read_text()
