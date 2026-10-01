import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mediahub import fjordhub_uninstall_remote as remote
from mediahub.errors import DomainError
from mediahub.fjordhub_deploy import DeployConfig
from mediahub.fjordhub_uninstall import UninstallDeployment, uninstall_deployment

CFG = DeployConfig(ctid="103").model_dump()
RAW = "\n".join(
    [
        "hostname: fjordhub",
        "rootfs: local-lvm:vm-103-disk-0,size=24G",
        "mp0: local-lvm:vm-103-disk-1,mp=/srv/mediahub/appdata/fjordhub,size=32G",
        "mp1: /mnt/mediahub-3tb,mp=/media,ro=1",
    ]
)


def test_external_media_is_not_a_disk_to_delete():
    deleted, kept = remote.storage_plan(RAW, CFG)
    assert [d["slot"] for d in deleted] == ["rootfs", "mp0"]
    assert kept == [{"slot": "mp1", "source": "/mnt/mediahub-3tb", "path": "/media"}]


@pytest.mark.parametrize(
    "value", ["proc:rw sys:rw", "proc sys cgroup", "proc:mixed sys:ro cgroup:rw:force"]
)
def test_kernel_automounts_are_not_mistaken_for_media_disks(value):
    assert remote.storage_plan(RAW + "\nlxc.mount.auto: " + value, CFG) == remote.storage_plan(
        RAW, CFG
    )


@pytest.mark.parametrize(
    "entry",
    [
        "unused0: local-lvm:vm-103-disk-2",
        "lxc.mount.entry: /srv/media movies none bind 0 0",
        "lxc.mount.auto: proc sys /srv/media",
        "lxc.mount.fstab: /etc/custom-fstab",
        "lxc.rootfs.path: /srv/other",
    ],
)
def test_blocked_preview_identifies_entry_and_lxc_without_exposing_values(entry):
    with pytest.raises(ValueError) as error:
        remote.storage_plan(RAW + "\n" + entry, CFG)
    assert entry.split(": ")[0] in str(error.value)
    assert "pct config 103" in str(error.value)
    assert "Nothing has been deleted" in str(error.value)
    assert entry.split(": ", 1)[1] not in str(error.value)


@pytest.mark.parametrize(
    "raw",
    [
        RAW + "\nmp2: local-lvm:vm-103-disk-2,mp=/movies",
        RAW + "\nmp2: /dev/sdb,mp=/movies",
        RAW + "\nunused0: local-lvm:vm-103-disk-2",
        RAW + "\n[snapshot]",
        RAW + "\n[PENDING]",
        RAW + "\nlxc.mount.entry: /srv/media movies none bind 0 0",
        RAW.replace("vm-103-disk-0", "vm-104-disk-0"),
        RAW.replace("vm-103-disk-0", "104/vm-103-disk-0.raw"),
        RAW.replace("hostname: fjordhub", "hostname: other"),
        RAW.replace("mp=/srv/mediahub/appdata/fjordhub", "mp=/movies"),
        RAW + "\nprotection: 1",
    ],
)
def test_ambiguous_or_changed_storage_blocks_removal(raw):
    with pytest.raises(ValueError):
        remote.storage_plan(raw, CFG)


def simulated_host(monkeypatch, tmp_path, *, local_media=False, leftover=False):
    # Map remote absolute paths into a disposable local sandbox. No real CLI calls.
    def sandbox(path):
        return tmp_path / str(path).lstrip("/")

    conf = sandbox("/etc/pve/lxc/103.conf")
    conf.parent.mkdir(parents=True)
    conf.write_text(RAW)
    external = sandbox("/mnt/mediahub-3tb/movie.mkv")
    external.parent.mkdir(parents=True)
    external.write_bytes(b"media must survive")
    deleted, _ = remote.storage_plan(RAW, CFG)
    calls = []
    stopped = False
    account = "mediahub-fjordhub-103-abcdef01@pve"

    def run(args, timeout=60):
        nonlocal stopped
        calls.append(args)
        if args[:2] == ["pct", "config"]:
            return conf.read_text()
        if args[:2] == ["pct", "status"]:
            return "status: stopped" if stopped else "status: running"
        if args[:2] == ["pct", "exec"]:
            return json.dumps(
                {
                    "containers": ["fjordhub", "fjordflix"],
                    "account": account,
                    "media": [
                        {
                            "path": "/internal/movies" if local_media else "/media/movies",
                            "nonempty": True,
                        }
                    ],
                }
            )
        if args[:3] == ["pveum", "user", "list"]:
            return json.dumps(
                [{"userid": account, "comment": "FjordHub inventory for LXC 103 (MediaHub)"}]
            )
        if args[:2] == ["pvesh", "get"]:
            return json.dumps(
                [{"volid": d["source"]} for d in deleted] if conf.exists() or leftover else []
            )
        if args[:2] == ["pct", "shutdown"]:
            stopped = True
            return ""
        if args[:2] == ["pct", "destroy"]:
            conf.unlink()
            return ""
        if args[:3] == ["pveum", "user", "delete"]:
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(remote, "Path", sandbox)
    monkeypatch.setattr(remote, "run", run)
    return calls, conf, external


def test_full_removal_preserves_external_files_and_cleans_dedicated_account(monkeypatch, tmp_path):
    calls, conf, external = simulated_host(monkeypatch, tmp_path)
    plan = remote.inspect(CFG)
    result = remote.execute(CFG, plan["digest"])
    assert result["state"] == "removed" and not conf.exists()
    assert external.read_bytes() == b"media must survive"
    assert ["pct", "destroy", "103", "--purge", "1", "--destroy-unreferenced-disks", "0"] in calls
    assert ["pveum", "user", "delete", "mediahub-fjordhub-103-abcdef01@pve"] in calls
    # Recovery repeats only verification/account cleanup, never disk destruction.
    remote.execute(CFG, plan["digest"])
    assert sum(c[:2] == ["pct", "destroy"] for c in calls) == 1


def test_local_media_blocks_even_a_preview(monkeypatch, tmp_path):
    calls, conf, _ = simulated_host(monkeypatch, tmp_path, local_media=True)
    with pytest.raises(ValueError, match="Media exists on an internal disk"):
        remote.inspect(CFG)
    assert conf.exists() and not any(c[:2] == ["pct", "shutdown"] for c in calls)


def test_changed_plan_never_stops_guest(monkeypatch, tmp_path):
    calls, conf, _ = simulated_host(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="Installation changed"):
        remote.execute(CFG, "0" * 64)
    assert conf.exists() and not any(c[:2] == ["pct", "shutdown"] for c in calls)


def test_proxmox_partial_disk_removal_is_not_success(monkeypatch, tmp_path):
    calls, conf, external = simulated_host(monkeypatch, tmp_path, leftover=True)
    plan = remote.inspect(CFG)
    with pytest.raises(ValueError, match="application disk remains"):
        remote.execute(CFG, plan["digest"])
    assert not conf.exists() and external.exists()
    assert not any(c[:3] == ["pveum", "user", "delete"] for c in calls)


@pytest.mark.parametrize("change", ["shutdown_failure", "storage_changed"])
def test_shutdown_failure_or_storage_race_prevents_destroy(monkeypatch, tmp_path, change):
    calls, conf, external = simulated_host(monkeypatch, tmp_path)
    plan = remote.inspect(CFG)
    original_run = remote.run

    def run(args, timeout=60):
        if args[:2] == ["pct", "shutdown"]:
            if change == "shutdown_failure":
                raise ValueError("Shutdown failed")
            conf.write_text(RAW.replace("/mnt/mediahub-3tb", "/mnt/changed"))
        return original_run(args, timeout)

    monkeypatch.setattr(remote, "run", run)
    with pytest.raises(ValueError):
        remote.execute(CFG, plan["digest"])
    assert conf.exists() and external.exists()
    assert not any(c[:2] == ["pct", "destroy"] for c in calls)


def test_internal_media_under_external_parent_mount_is_still_blocked(monkeypatch, tmp_path):
    _, conf, _ = simulated_host(monkeypatch, tmp_path)
    conf.write_text(RAW.replace("mp=/media,ro=1", "mp=/srv,ro=1"))
    original_run = remote.run

    def run(args, timeout=60):
        output = original_run(args, timeout)
        if args[:2] == ["pct", "exec"]:
            guest = json.loads(output)
            guest["media"] = [{"path": CFG["dataPath"] + "/movies", "nonempty": True}]
            return json.dumps(guest)
        return output

    monkeypatch.setattr(remote, "run", run)
    with pytest.raises(ValueError, match="internal disk"):
        remote.inspect(CFG)


def wrapper(monkeypatch):
    job = {
        "id": "job",
        "host": "192.168.1.126",
        "state": "failed",
        "config": CFG,
        "logs": [],
        "uninstall": {"state": "ready", "digest": "a" * 64, "checkedAt": time.time()},
    }
    service = SimpleNamespace(
        latest=lambda: job, save=MagicMock(), inspection_lock=threading.Lock()
    )
    services = SimpleNamespace(fjordhub_deploy=service)
    client = MagicMock()
    monkeypatch.setattr("mediahub.fjordhub_uninstall.paramiko.SSHClient", lambda: client)
    body = UninstallDeployment(
        host=job["host"],
        jobId="job",
        password="secret",
        fingerprint="SHA256:" + "A" * 43,
        remove=True,
        confirmedJobId="job",
        externalMediaConfirmed=True,
        planDigest="a" * 64,
    )
    return job, services, client, body


@pytest.mark.parametrize(
    "change", ["confirmation", "external", "digest", "expired", "host", "job", "running", "linux"]
)
def test_exact_fresh_confirmation_is_required_before_ssh(monkeypatch, change):
    job, services, client, body = wrapper(monkeypatch)
    if change == "confirmation":
        body.confirmedJobId = "other"
    if change == "external":
        body.externalMediaConfirmed = False
    if change == "digest":
        body.planDigest = "b" * 64
    if change == "expired":
        job["uninstall"]["checkedAt"] -= 601
    if change == "host":
        body.host = "192.168.1.100"
    if change == "job":
        body.jobId = "other"
    if change == "running":
        job["state"] = "running"
    if change == "linux":
        job["config"] = {**CFG, "target": "linux"}
    with pytest.raises(DomainError):
        uninstall_deployment(services, body)
    client.connect.assert_not_called()
    assert not services.fjordhub_deploy.inspection_lock.locked()


def test_remote_failure_remains_incomplete_and_does_not_leak_password(monkeypatch):
    job, services, client, body = wrapper(monkeypatch)
    client.exec_command.side_effect = OSError("secret")
    with pytest.raises(DomainError) as failure:
        uninstall_deployment(services, body)
    assert job["uninstall"]["state"] == "incomplete"
    assert "secret" not in failure.value.message
    client.close.assert_called_once()


def test_success_removes_only_matching_connection_and_keeps_history(monkeypatch, logged_in):
    from mediahub.db import ExternalIntegration

    job, services, client, body = wrapper(monkeypatch)
    real = logged_in.app.state.services
    services.sessions, services.integrations = real.sessions, real.integrations
    job["logs"] = ["MEDIAHUB_FJORDHUB_URL=http://192.168.1.112:8888"]
    with real.sessions.begin() as db:
        matching = ExternalIntegration(
            provider="fjordhub", name="This guest", base_url="http://192.168.1.112:8888"
        )
        other = ExternalIntegration(
            provider="fjordhub", name="Other guest", base_url="http://192.168.1.113:8888"
        )
        db.add_all([matching, other])
        db.flush()
        matching_id, other_id = matching.id, other.id
    stdin, stdout = MagicMock(), MagicMock()
    stdout.channel.recv_exit_status.return_value = 0
    stdout.read.return_value = json.dumps(
        {"ok": True, "result": {"state": "removed", "message": "Removed"}}
    ).encode()
    client.exec_command.return_value = stdin, stdout, MagicMock()
    assert uninstall_deployment(services, body)["state"] == "removed"
    with real.sessions() as db:
        assert db.get(ExternalIntegration, matching_id) is None
        assert db.get(ExternalIntegration, other_id) is not None
    assert job["state"] == "failed"  # original installation history remains truthful
    assert job["verification"]["state"] == "removed"


def test_uninstall_endpoint_requires_auth_and_csrf(client, logged_in, monkeypatch):
    called = MagicMock(return_value={"state": "ready"})
    monkeypatch.setattr("mediahub.fjordhub_api.uninstall_deployment", called)
    payload = {
        "host": "192.168.1.126",
        "jobId": "job",
        "password": "secret",
        "fingerprint": "SHA256:" + "A" * 43,
    }
    assert logged_in.post("/api/v1/fjordhub/deployment/uninstall", json=payload).status_code == 200
    called.reset_mock()
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.post("/api/v1/fjordhub/deployment/uninstall", json=payload).status_code == 403
    client.cookies.clear()
    assert client.post("/api/v1/fjordhub/deployment/uninstall", json=payload).status_code in (
        401,
        403,
    )
    called.assert_not_called()
