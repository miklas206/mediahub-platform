"""Exercise the actual embedded installer programs without a live Proxmox host."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mediahub.fjordhub_deploy import TEMPLATES, DeployConfig, commands

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = TEMPLATES["proxmox"]
PREFLIGHT, WRITE_ENV = re.findall(r"python3 -c '\n(.*?)\n'", SCRIPT, re.S)
CHECK = SCRIPT.split("<<'MEDIAHUB_CHECK'\n")[1].split("\nMEDIAHUB_CHECK")[0]
TOKEN = {"full-tokenid": "mediahub-fjordhub-210-test@pve!inventory", "value": "test-secret"}


@pytest.mark.parametrize("address", ["192.168.1.126", "fd00::126", ""])
def test_node_discovery_uses_native_resolver_and_propagates_failure(tmp_path, address):
    # Proxmox modules are host-only. Exercise the real shell/Perl invocation
    # against their contract, without requiring a node entry in .members.
    modules = tmp_path / "PVE"
    modules.mkdir()
    (modules / "Cluster.pm").write_text(
        "package PVE::Cluster;\n"
        "my $updated = 0;\n"
        "sub cfs_update { $updated = 1; }\n"
        "sub remote_node_ip {\n"
        "  die 'Cluster state not loaded' unless $updated;\n"
        "  die 'Wrong node' unless shift eq 'node2';\n"
        "  return $ENV{TEST_NODE_IP};\n"
        "}\n1;\n"
    )
    discovery = SCRIPT.split("API_IP=", 1)[1].split("# Refuse", 1)[0]
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "/bin/bash"
    result = subprocess.run(
        [bash, "-s"],
        input="set -e\nNODE=node2\nAPI_IP=" + discovery + '\nprintf "%s" "$API_URL"\n',
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env={**os.environ, "PERL5LIB": ".", "TEST_NODE_IP": address},
    )
    if address:
        assert result.returncode == 0, result.stderr
        host = f"[{address}]" if ":" in address else address
        assert result.stdout == f"https://{host}:8006"
    else:
        assert result.returncode != 0
        assert "Cannot resolve Proxmox node IP" in result.stderr
        assert result.stdout == ""


def write_env(folder, token=TOKEN):
    return subprocess.run(
        [sys.executable, "-c", WRITE_ENV, str(folder), "https://192.168.1.2:8006", "node2", "210"],
        input=json.dumps(token),
        text=True,
        capture_output=True,
    )


def test_shared_script_and_rendering():
    assert SCRIPT == (ROOT / "scripts/configure-fjordhub-proxmox.sh").read_text()
    lxc = commands(DeployConfig(ctid="210"))
    assert 'bash -s -- "$CTID"' in lxc
    assert SCRIPT in lxc
    assert "pveum user add" not in commands(DeployConfig(target="linux"))
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "/bin/bash"
    subprocess.run([bash, "-n"], input=SCRIPT, text=True, check=True)
    assert "--privsep 1" in SCRIPT
    assert '--tokens "$ACCOUNT!inventory" --roles PVEAuditor' in SCRIPT
    assert 'pveum user delete "$ACCOUNT"' in SCRIPT


def test_env_writer_preserves_settings_and_uses_actual_node_and_ctid(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=unchanged\nDATA_DIR=/srv/appdata\nPROXMOX_NODE=pve\n")
    result = write_env(tmp_path)
    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in env.read_text().splitlines())
    assert values["SECRET_KEY"] == "unchanged"
    assert values["DATA_DIR"] == "/srv/appdata"
    assert values["PROXMOX_NODE"] == "node2"
    assert values["PROXMOX_VMID"] == "210"
    assert values["PROXMOX_API_URL"] == "https://192.168.1.2:8006"
    assert values["PROXMOX_TOKEN_SECRET"] == TOKEN["value"]
    assert TOKEN["value"] not in result.stdout + result.stderr
    assert not (tmp_path / ".env.mediahub-proxmox").exists()


@pytest.mark.parametrize("value", ["test\nINJECTED=yes", "$(id)", "${SECRET_KEY}"])
def test_invalid_api_value_does_not_change_env(tmp_path, value):
    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=unchanged\n")
    result = write_env(tmp_path, {**TOKEN, "value": value})
    assert result.returncode != 0
    assert env.read_text() == "SECRET_KEY=unchanged\n"
    assert value not in result.stdout + result.stderr


def test_repair_refuses_existing_credentials(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PROXMOX_TOKEN_SECRET=existing-secret\n")
    result = subprocess.run(
        [sys.executable, "-c", PREFLIGHT, str(tmp_path)],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "already configured" in result.stderr
    assert "existing-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["", "token", "acl", "write", "start", "check"])
def test_account_cleanup_and_failure_status(failure):
    # Only replace host discovery/preflight. Exercise the actual shell control flow
    # with mocked Proxmox commands, including pipe/exit/trap handling.
    script = SCRIPT.replace("[ -d /etc/pve ]", "true")
    script = re.sub(r"^NODE=.*$", "NODE=node2", script, flags=re.M)
    script = re.sub(r"^API_IP=.*$", "API_IP=192.168.1.2", script, flags=re.M)
    script = re.sub(r"^ACCOUNT=.*$", "ACCOUNT=mediahub-test@pve", script, flags=re.M)
    mocks = r"""
id() { echo 0; }
pveum() {
    if [[ "$*" == "user delete "* ]]; then echo ACCOUNT_REMOVED >&2; fi
    if [[ "$*" == "user token add "* ]]; then
        [ "$FAILURE" != token ] || return 1
        printf '%s\n' '{"value":"fake-secret","full-tokenid":"mediahub-test@pve!inventory"}'
    fi
    if [[ "$*" == *--tokens* ]] && [ "$FAILURE" = acl ]; then return 1; fi
    return 0
}
pct() {
    if [[ "$*" == *"token = json.load"* ]]; then
        cat >/dev/null
        [ "$FAILURE" != write ] || return 1
    elif [[ "$*" == *"docker compose up"* ]]; then
        [ "$FAILURE" != start ] || return 1
    elif [[ "$*" == *"docker compose exec"* ]]; then
        cat >/dev/null
        [ "$FAILURE" != check ] || return 1
        echo VERIFIED
    fi
    return 0
}
"""
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "/bin/bash"
    result = subprocess.run(
        [bash, "-s", "--", "210", "/opt/fjordhub"],
        input=mocks + script,
        text=True,
        capture_output=True,
        env={**os.environ, "FAILURE": failure},
    )
    assert (result.returncode == 0) == (not failure), result.stderr
    assert ("ACCOUNT_REMOVED" in result.stderr) == (failure in {"token", "acl", "write"})
    assert ("VERIFIED" in result.stdout) == (not failure)
    assert "fake-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", [None, "denied", "network", "invalid-json"])
def test_inventory_verification_fails_closed(monkeypatch, failure):
    for key, value in {
        "PROXMOX_API_URL": "https://192.168.1.2:8006",
        "PROXMOX_NODE": "node2",
        "PROXMOX_VMID": "210",
        "PROXMOX_TOKEN_ID": TOKEN["full-tokenid"],
        "PROXMOX_TOKEN_SECRET": TOKEN["value"],
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["headers"]["Authorization"].endswith("=" + TOKEN["value"])
        assert kwargs["timeout"] == 20
        if failure == "network":
            raise OSError("test network error")

        def status():
            if failure == "denied":
                raise ValueError("403")

        return SimpleNamespace(
            raise_for_status=status, json=lambda: {} if failure else {"data": []}
        )

    monkeypatch.setitem(
        sys.modules,
        "requests",
        SimpleNamespace(
            get=get,
            packages=SimpleNamespace(urllib3=SimpleNamespace(disable_warnings=lambda: None)),
        ),
    )
    if failure:
        with pytest.raises(SystemExit, match="Proxmox inventory check failed"):
            exec(CHECK, {})
    else:
        exec(CHECK, {})
        assert len(calls) == 5
        assert any("/nodes/node2/lxc/210/config" in url for url in calls)
