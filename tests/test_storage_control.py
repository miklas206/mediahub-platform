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
    (source / "scripts/app_storage_host.py").write_bytes(
        script.with_name("app_storage_host.py").read_bytes()
    )
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
    (source / "scripts/app_storage_host.py").write_text("# reviewed app storage helper\n")
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
        return "obscured-password" if args[1] == "obscure" else ""

    host.run = run
    host.mount_userspace(row, host.mounts / row["id"])
    assert calls[0][1]["content"] == "synthetic-secret"
    assert all("synthetic-secret" not in " ".join(args) for args, _ in calls)
    config = host.folder / (row["id"] + ".rclone.conf")
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert "synthetic-secret" not in config.read_text()
    assert "idle_timeout = 5s" in config.read_text()
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


@pytest.mark.parametrize("existing", [False, True])
def test_verified_smb_client_prepares_on_install_and_upgrade(controller, monkeypatch, existing):
    import hashlib
    import io
    import zipfile

    import scripts.storage_host as module

    host = controller
    if existing:
        save(host.folder / "existing.credentials", "private synthetic credential")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("rclone-v1.75.2-linux-amd64/rclone", b"synthetic executable")
    content = archive.getvalue()
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setitem(
        module.RCLONE_ARCHIVES, "x86_64", ("amd64", hashlib.sha256(content).hexdigest())
    )
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(content)
    )
    host.prepare_rclone()
    assert host.rclone_binary().read_bytes() == b"synthetic executable"
    assert stat.S_IMODE(host.rclone_binary().stat().st_mode) == 0o700
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("Downloaded a prepared client again"),
    )
    host.prepare_rclone()
    if existing:
        assert (host.folder / "existing.credentials").read_text() == "private synthetic credential"


def test_smb_client_rejects_wrong_checksum(controller, monkeypatch):
    import io

    import scripts.storage_host as module

    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"untrusted archive")
    )
    with pytest.raises(StorageError, match="preparation failed"):
        controller.prepare_rclone()
    assert not controller.rclone_binary().exists()


@pytest.mark.parametrize(
    "usage", [{"total": 1100226719744, "free": 1054719385600}, {"total": -1, "free": 42}, {}]
)
def test_nas_capacity_uses_corrected_smb_query_and_keeps_connection(controller, usage):
    host = controller
    identifier = "d" * 24
    save(
        host.file,
        {
            "nas": [
                {
                    "id": identifier,
                    "server": "192.168.1.60",
                    "share": "Media",
                    "label": "NAS",
                    "readOnly": False,
                    "enabled": True,
                }
            ],
            "shares": [],
            "passwordConfigured": False,
        },
    )
    host.mount_info = lambda path: {
        "target": str(host.mounts / identifier),
        "source": "mediahub-nas-" + identifier,
        "fstype": "fuse.rclone",
    }
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[1] == "about":
            return json.dumps(usage)
        raise StorageError("The obsolete filesystem report must not be used")

    host.run = run
    row = next(row for row in host.inventory()["locations"] if row["id"] == identifier)
    assert row["ready"] is True
    assert row["totalBytes"] == (usage.get("total") if usage.get("total", -1) >= 0 else None)
    assert row["freeBytes"] == (usage.get("free") if usage.get("total", -1) >= 0 else None)
    assert any(args[1] == "about" for args in calls)


def test_app_storage_transport_validates_admin_csrf_and_selection(logged_in, monkeypatch):
    client = logged_in
    mock = AsyncMock(return_value={"saved": True})
    monkeypatch.setattr("mediahub.storage_control.host_request", mock)
    monkeypatch.setattr(client.app.state.services.setup, "require_complete", lambda: None)
    path = "/api/v1/storage-control/apps/plex/" + "a" * 24
    assert client.post(path, headers={"X-MediaHub-CSRF": "wrong"}).status_code == 403
    assert (
        client.post(
            "/api/v1/storage-control/apps/recover", headers={"X-MediaHub-CSRF": "wrong"}
        ).status_code
        == 403
    )
    assert mock.await_count == 0
    assert client.post(path).status_code == 200
    assert mock.call_args.args[1:] == ("POST", "/apps/plex/" + "a" * 24)
    assert client.delete(path).status_code == 200
    assert mock.call_args.args[1:] == ("DELETE", "/apps/plex/" + "a" * 24)
    assert client.post("/api/v1/storage-control/apps/unsupported/" + "a" * 24).status_code == 422
    assert client.post("/api/v1/storage-control/apps/recover").status_code == 200
    from mediahub.db import User
    from sqlalchemy import select

    with client.app.state.services.sessions.begin() as db:
        db.scalar(select(User).where(User.username == "tester")).role = "user"
    count = mock.await_count
    assert client.post(path).status_code == 403
    assert client.delete(path).status_code == 403
    assert client.post("/api/v1/storage-control/apps/recover").status_code == 403
    assert mock.await_count == count


@pytest.mark.parametrize("existing_name", [None, "existing-operator-group"])
def test_media_group_is_prepared_once_without_changing_existing_accounts(
    monkeypatch, existing_name
):
    import scripts.storage_host as module

    groups = {1000: existing_name} if existing_name else {}
    calls = []

    def by_gid(gid):
        if gid not in groups:
            raise KeyError(gid)
        return SimpleNamespace(gr_name=groups[gid], gr_gid=gid)

    def by_name(name):
        raise KeyError(name)

    def command(args):
        calls.append(args)
        assert args == ["groupadd", "--gid", "1000", "mediahub-media"]
        groups[1000] = "mediahub-media"

    monkeypatch.setattr(module, "grp", SimpleNamespace(getgrgid=by_gid, getgrnam=by_name))
    monkeypatch.setattr(module, "command", command)
    assert module.ensure_media_group() == (existing_name or "mediahub-media")
    assert module.ensure_media_group() == (existing_name or "mediahub-media")
    assert len(calls) == (0 if existing_name else 1)


def test_media_group_name_collision_is_not_modified(monkeypatch):
    import scripts.storage_host as module

    def missing(gid):
        raise KeyError(gid)

    monkeypatch.setattr(
        module,
        "grp",
        SimpleNamespace(getgrgid=missing, getgrnam=lambda _: SimpleNamespace(gr_gid=1234)),
    )
    from unittest.mock import Mock

    command = Mock()
    monkeypatch.setattr(module, "command", command)
    with pytest.raises(StorageError, match="already in use"):
        module.ensure_media_group()
    command.assert_not_called()


@pytest.mark.parametrize("upgrading", [False, True])
def test_storage_service_install_prepares_group_before_start_on_new_and_older_hosts(
    tmp_path, monkeypatch, upgrading
):
    import scripts.storage_host as module

    root = tmp_path / "hub"
    root.mkdir()
    for name in ["storage_host.py", "storage-policy.json"]:
        (root / name).write_text("reviewed")
    events = []
    real_lstat = Path.lstat

    def lstat(path):
        details = real_lstat(path)
        return SimpleNamespace(st_uid=0, st_mode=details.st_mode)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(module, "ensure_media_group", lambda: events.append("group-ready"))
    monkeypatch.setattr(module, "save", lambda path, content: events.append((path, content)))
    monkeypatch.setattr(module, "command", lambda args: events.append(args))
    # Redirect only the unit location, keeping actual approved root validation.
    real_path = Path
    unit = tmp_path / "mediahub-storage.service"
    if upgrading:
        unit.write_text(
            "Description=MediaHub private storage controller\nExecStart=/usr/bin/python3 "
            + str(root / "storage_host.py")
            + " --root "
            + str(root)
            + "\nGroup=1000\n"
        )
    monkeypatch.setattr(
        module,
        "Path",
        lambda value: (
            unit
            if str(value) == "/etc/systemd/system/mediahub-storage.service"
            else real_path(value)
        ),
    )
    module.install(root)
    assert events[0] == "group-ready"
    assert "Group=1000" in events[1][1]
    assert events[-1] == ["systemctl", "restart", "mediahub-storage.service"]


@pytest.mark.parametrize("concurrent_creation", [False, True])
def test_media_group_creation_failure_is_clear_or_reuses_a_concurrent_installer(
    monkeypatch, concurrent_creation
):
    import scripts.storage_host as module

    groups = {}

    def by_gid(gid):
        if gid not in groups:
            raise KeyError(gid)
        return SimpleNamespace(gr_name=groups[gid])

    def by_name(name):
        raise KeyError(name)

    def command(args):
        if concurrent_creation:
            groups[1000] = "operator-media"
        raise StorageError("groupadd failed")

    monkeypatch.setattr(module, "grp", SimpleNamespace(getgrgid=by_gid, getgrnam=by_name))
    monkeypatch.setattr(module, "command", command)
    if concurrent_creation:
        assert module.ensure_media_group() == "operator-media"
    else:
        with pytest.raises(StorageError, match="could not be prepared"):
            module.ensure_media_group()


def test_nfs_input_does_not_require_or_expose_smb_credentials():
    from pydantic import ValidationError

    value = NasInput(
        protocol="nfs", label="Test NAS", server="192.168.1.60", share="/volume1/Media"
    )
    assert body_values(value)["password"] is None
    with pytest.raises(ValidationError):
        NasInput(
            protocol="nfs", label="NAS", server="192.168.1.60", share="/Media", username="wrong"
        )
    with pytest.raises(ValidationError):
        NasInput(label="NAS", server="192.168.1.60", share="Media")


def test_nfs_mount_reconnect_and_native_identity(controller):
    host, calls = controller, []
    host.packages = lambda: None
    mounted = False

    def info(path):
        if mounted:
            return {"source": "192.168.1.60:/volume1/Media", "target": str(path), "fstype": "nfs4"}
        return {}

    def run(args, **kwargs):
        nonlocal mounted
        calls.append(args)
        assert args[:3] == ["mount", "-t", "nfs"]
        mounted = True
        return ""

    host.mount_info, host.run = info, run
    host.add_nas(
        {
            "protocol": "nfs",
            "label": "NAS",
            "server": "192.168.1.60",
            "share": "/volume1/Media",
            "readOnly": False,
        }
    )
    row = host.state()["nas"][0]
    assert host.nas_ready(row)
    assert not (host.folder / (row["id"] + ".credentials")).exists()
    assert "hard" in calls[0][-1].split(",")
    assert "rw" in calls[0][-1].split(",")
    assert "vers=4.1" in calls[0][-1]
    assert "credentials" not in str(calls)
    host.nas_action(row["id"], "connect")
    assert len(calls) == 1
    host.mount_info = lambda path: {
        "target": str(path),
        "source": "mediahub-nas-" + row["id"],
        "fstype": "fuse.rclone",
    }
    assert not host.nas_ready(row)
    with pytest.raises(StorageError, match="NFS uses export permissions"):
        host.nas_credentials(row["id"], {"username": "wrong", "password": "synthetic"})


@pytest.mark.parametrize(
    "export",
    [
        "Media",
        "/",
        "/Media/../secret",
        "/Media//sub",
        "/Media/",
        "/Media\nother",
        "/Media,soft",
        "//Media",
    ],
)
def test_nfs_rejects_ambiguous_paths_before_saving(controller, export):
    with pytest.raises(StorageError):
        controller.add_nas(
            {"protocol": "nfs", "label": "NAS", "server": "192.168.1.60", "share": export}
        )
    assert not controller.file.exists()


def test_lxc_nfs_prerequisite_preserves_saved_connection_and_smb(controller):
    host = controller
    host.packages = lambda: None
    host.userspace_mounts = lambda: True
    host.run = lambda *a, **k: pytest.fail("Must not attempt a forbidden kernel mount")
    with pytest.raises(StorageError, match="unprivileged LXC"):
        host.add_nas(
            {"protocol": "nfs", "label": "NAS", "server": "192.168.1.60", "share": "/volume1/Media"}
        )
    row = host.state()["nas"][0]
    assert row["protocol"] == "nfs" and row["enabled"]
    assert "unprivileged LXC" in row["error"]
    assert not list(host.folder.glob("*.credentials"))


@pytest.mark.parametrize("upgrade", [False, True])
def test_nfs_client_prepared_on_fresh_install_and_upgrade(controller, monkeypatch, upgrade):
    import scripts.storage_host as module

    host, calls = controller, []
    if upgrade:
        save(host.file, {"nas": [], "shares": [], "passwordConfigured": False})
        save(host.folder / "kept.credentials", "synthetic existing secret")
    installed = {"mount.cifs"}
    monkeypatch.setattr(
        module.shutil, "which", lambda executable: executable if executable in installed else None
    )

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["apt-get", "install"]:
            installed.add("mount.nfs")
        return ""

    host.run = run
    host.packages()
    assert calls[-1][-1] == "nfs-common"
    host.packages()
    assert len(calls) == 2
    if upgrade:
        assert (host.folder / "kept.credentials").read_text() == "synthetic existing secret"


def test_legacy_smb_connection_still_has_the_same_identity(controller):
    host = controller
    row = {
        "id": "a" * 24,
        "label": "Legacy",
        "server": "192.168.1.60",
        "share": "Media",
        "username": "existing",
        "readOnly": True,
        "enabled": True,
    }
    state = {"nas": [row], "shares": [], "passwordConfigured": False}
    save(host.file, state)
    save(host.folder / (row["id"] + ".credentials"), "synthetic untouched credential")
    original = host.file.read_bytes()
    host.mount_info = lambda path: {
        "target": str(path),
        "source": "//192.168.1.60/Media",
        "fstype": "cifs",
    }
    assert host.nas_ready(row)
    host.packages = lambda: None
    host.nas_action(row["id"], "connect")
    assert host.file.read_bytes() == original
    assert (
        host.folder / (row["id"] + ".credentials")
    ).read_text() == "synthetic untouched credential"


def test_nfs_mount_failure_is_saved_for_retry_without_credentials(controller):
    host = controller
    host.packages = lambda: None
    host.run = lambda *a, **kw: (_ for _ in ()).throw(StorageError("Synthetic inaccessible export"))
    with pytest.raises(StorageError, match="Enable NFSv4.1"):
        host.add_nas(
            {"protocol": "nfs", "label": "NAS", "server": "192.168.1.60", "share": "/Media"}
        )
    row = host.state()["nas"][0]
    assert row["enabled"] and "Enable NFSv4.1" in row["error"]
    assert stat.S_IMODE((host.mounts / row["id"]).stat().st_mode) == 0
    assert not list(host.folder.glob("*.credentials"))
