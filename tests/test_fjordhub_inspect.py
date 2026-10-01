import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mediahub.errors import DomainError
from mediahub.fjordhub_inspect import InspectDeployment, inspect_deployment


def setup(monkeypatch, resources=None, error=False):
    job = {
        "id": "test-job",
        "state": "succeeded",
        "host": "192.168.1.126",
        "config": {"ctid": "103"},
        "logs": [],
    }
    service = SimpleNamespace(
        latest=lambda: job, save=MagicMock(), inspection_lock=threading.Lock()
    )
    client = MagicMock()
    if error:
        client.connect.side_effect = OSError("private password detail")
    stdout = MagicMock()
    stdout.read.return_value = json.dumps(resources or []).encode()
    client.exec_command.return_value = (None, stdout, None)
    monkeypatch.setattr("mediahub.fjordhub_inspect.paramiko.SSHClient", lambda: client)
    body = InspectDeployment(
        host=job["host"], jobId=job["id"], password="secret", fingerprint="SHA256:" + "A" * 43
    )
    return service, body, client


def test_deleted_lxc_is_not_still_installed(monkeypatch):
    service, body, client = setup(monkeypatch)
    result = inspect_deployment(service, body)
    assert result["state"] == "removed"
    assert all("pct exec" not in c.args[0] for c in client.exec_command.call_args_list)
    assert service.latest()["state"] == "succeeded"  # history is preserved
    assert service.latest()["verification"]["state"] == "removed"


def test_ssh_failure_is_unknown_not_removed(monkeypatch):
    service, body, _ = setup(monkeypatch, error=True)
    result = inspect_deployment(service, body)
    assert result["state"] == "unknown" and "private password" not in str(result)


def test_reused_lxc_id_fails_closed(monkeypatch):
    service, body, client = setup(
        monkeypatch, [{"type": "lxc", "vmid": 103, "name": "someone-else", "status": "running"}]
    )
    assert inspect_deployment(service, body)["state"] == "unknown"
    assert len(client.exec_command.call_args_list) == 1


def test_removal_requires_exact_confirmation(monkeypatch):
    service, body, client = setup(monkeypatch)
    body.remove = True
    with pytest.raises(DomainError):
        inspect_deployment(service, body)
    client.connect.assert_not_called()


@pytest.mark.parametrize(
    "remove,origin,expected",
    [
        (False, "https://github.com/qlerup/fjordhub.git", "installed"),
        (True, "https://github.com/qlerup/fjordhub.git", "removed"),
        (True, "https://github.com/other/project.git", "unknown"),
    ],
)
def test_guest_inspection_and_bounded_container_removal(
    tmp_path, monkeypatch, capsys, remove, origin, expected
):
    import subprocess
    import sys

    from mediahub.fjordhub_inspect import GUEST

    root = tmp_path / "fjordhub"
    root.mkdir()
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        output = ""
        if args[0] == "git":
            output = origin
        elif args[1] == "ps":
            output = "owned-id"
        elif args[1] == "inspect":
            output = json.dumps(
                [
                    {
                        "Id": "owned-id",
                        "State": {"Running": True},
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project.working_dir": str(root),
                                "com.docker.compose.service": "fjordhub",
                            }
                        },
                    }
                ]
            )
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        sys, "argv", ["script", json.dumps({"installPath": str(root), "remove": remove})]
    )
    with pytest.raises(SystemExit):
        exec(compile(GUEST, "guest_check", "exec"), {})
    assert json.loads(capsys.readouterr().out)["state"] == expected
    destructive = [c for c in calls if c[:2] == ["docker", "rm"]]
    assert destructive == ([["docker", "rm", "owned-id"]] if expected == "removed" else [])
    assert root.is_dir()
