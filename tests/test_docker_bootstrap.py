import base64
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

SPEC = importlib.util.spec_from_file_location(
    "docker_bootstrap", Path(__file__).resolve().parents[1] / "scripts/docker_bootstrap.py"
)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell required")
@pytest.mark.parametrize("scenario", ["update", "cancel", "missing-volume"])
def test_desktop_update_preserves_existing_installation(scenario):
    script = Path(__file__).resolve().parents[1] / "scripts/install-docker.ps1"
    command = r"""
$ErrorActionPreference = 'Stop'
$scriptPath = '__SCRIPT__'
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count) { throw 'Invalid PowerShell syntax' }
$global:desktopUpdateCalls = @()
function docker {
    $global:desktopUpdateCalls += ($args -join ' ')
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info') { return 'linux' }
    if ('__SCENARIO__' -eq 'missing-volume' -and $args[0] -eq 'volume') { $global:LASTEXITCODE = 1 }
}
function Test-Path { param($LiteralPath) return $true }
function Get-Content { param($LiteralPath, [switch]$Raw) return '{"name":"mediahub-guided","services":{"core":{"image":"mediahub-guided-core:local"},"agent":{"image":"mediahub-guided-agent:local"}}}' }
function Read-Host { if ('__SCENARIO__' -eq 'cancel') { return 'NO' }; return 'UPDATE' }
function New-Item { param($ItemType, $Path) }
function Invoke-WebRequest { param([switch]$UseBasicParsing, $Uri, $OutFile) }
function Expand-Archive { param($LiteralPath, $DestinationPath) }
$failed = $false
try { & $scriptPath -InstallDirectory 'C:\MediaHub-Test' -Update } catch { $failed = $true; $failureMessage = $_.Exception.Message }
[pscustomobject]@{ calls = $global:desktopUpdateCalls; failed = $failed; message = $failureMessage } | ConvertTo-Json -Compress
""".replace("__SCRIPT__", str(script).replace("'", "''")).replace("__SCENARIO__", scenario)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
         base64.b64encode(command.encode("utf-16le")).decode()],
        capture_output=True, text=True, timeout=20, check=True,
    )
    outcome = json.loads(result.stdout.splitlines()[-1])
    calls = outcome["calls"]
    assert not any("volume create" in call or " run " in call for call in calls)
    assert not any("prune" in call or "down" in call for call in calls)
    assert outcome["failed"] is (scenario == "missing-volume"), outcome
    builds = [call for call in calls if call.startswith("build ")]
    assert len(builds) == (2 if scenario == "update" else 0)
    if scenario == "update":
        assert "--force-recreate --wait --wait-timeout 180 core agent" in calls[-1]


def empty_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap.os, "chown", lambda *args: None, raising=False)
    root = tmp_path / "volumes"
    for name in bootstrap.VOLUMES:
        (root / name).mkdir(parents=True)
    output = tmp_path / "output"
    output.mkdir()
    return root, output


def test_compose_limits_private_access():
    config = bootstrap.compose_config("mediahub-guided", "127.0.0.1")
    core = config["services"]["core"]
    agent = config["services"]["agent"]
    assert core["ports"] == ["127.0.0.1:18765:18765"]
    assert "ports" not in agent
    assert not any("state:" in mount or "authority:" in mount for mount in core["volumes"])
    assert not any(
        "docker.sock" in mount for service in (core, agent) for mount in service["volumes"]
    )
    assert all(volume["external"] for volume in config["volumes"].values())
    assert config["networks"]["control"]["internal"] is True


@pytest.mark.parametrize("address", ["8.8.8.8", "0.0.0.0", "169.254.1.2", "localhost", "::1"])
def test_rejects_invalid_address(address):
    with pytest.raises(ValueError):
        bootstrap.compose_config("mediahub-guided", address)


def test_initialize_preserves_existing_data(tmp_path, monkeypatch):
    root, output = empty_installation(tmp_path, monkeypatch)
    existing = root / "storage" / "my-film.mkv"
    existing.write_bytes(b"irreplaceable")
    with pytest.raises(ValueError, match="not empty"):
        bootstrap.initialize("127.0.0.1", root, output)
    assert existing.read_bytes() == b"irreplaceable"
    assert not any(output.iterdir())
    assert not any((root / "authority").iterdir())


def test_output_conflict_has_no_volume_writes(tmp_path, monkeypatch):
    root, output = empty_installation(tmp_path, monkeypatch)
    (output / "ca.pem").write_bytes(b"existing certificate")
    with pytest.raises(ValueError, match="already exists"):
        bootstrap.initialize("127.0.0.1", root, output)
    assert all(not any((root / name).iterdir()) for name in bootstrap.VOLUMES)
    assert (output / "ca.pem").read_bytes() == b"existing certificate"


def test_creates_https_identity_and_rejects_second_install(tmp_path, monkeypatch):
    root, output = empty_installation(tmp_path, monkeypatch)
    bootstrap.initialize("127.0.0.1", root, output)
    config = json.loads((output / "compose.json").read_text())
    assert config == bootstrap.compose_config("mediahub-guided", "127.0.0.1")
    assert set(path.name for path in output.iterdir()) == {"compose.json", "ca.pem"}
    ca = x509.load_pem_x509_certificate((output / "ca.pem").read_bytes())
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    for role in ("core", "agent"):
        cert = x509.load_pem_x509_certificate((root / f"{role}-tls" / "server.pem").read_bytes())
        cert.verify_directly_issued_by(ca)
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert role in names.get_values_for_type(x509.DNSName)
        key = serialization.load_pem_private_key(
            (root / f"{role}-tls" / "server.key").read_bytes(), password=None
        )
        assert key.public_key().public_numbers() == cert.public_key().public_numbers()
    token = (root / "credentials" / "token").read_bytes()
    with pytest.raises(ValueError, match="not empty"):
        bootstrap.initialize("127.0.0.1", root, output)
    assert (root / "credentials" / "token").read_bytes() == token


@pytest.mark.skipif(os.environ.get("MEDIAHUB_DOCKER_SMOKE") != "1", reason="Opt-in Docker test")
def test_real_docker_https_installation(tmp_path):
    project = "mediahub-qa-guided-" + uuid4().hex[:8]
    source = Path(__file__).resolve().parents[1]

    def docker(*args):
        return subprocess.run(
            ["docker", *map(str, args)], check=True, capture_output=True, text=True
        ).stdout

    mounts = []
    for name in bootstrap.VOLUMES:
        docker("volume", "create", "--label", "mediahub.qa=true", f"{project}-{name}")
        mounts.extend(["--mount", f"type=volume,src={project}-{name},dst=/bootstrap/{name}"])
    docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "0",
        "--entrypoint",
        "python",
        *mounts,
        "--mount",
        f"type=bind,src={source / 'scripts/docker_bootstrap.py'},dst=/bootstrap.py,readonly",
        "--mount",
        f"type=bind,src={tmp_path},dst=/output",
        "mediahub-guided-agent:local",
        "/bootstrap.py",
    )
    compose_path = tmp_path / "compose.json"
    config = json.loads(compose_path.read_text())
    config["name"] = project
    for name in bootstrap.VOLUMES:
        config["volumes"][name]["name"] = f"{project}-{name}"
    config["services"]["core"]["ports"] = ["127.0.0.1::18765"]
    compose_path.write_text(json.dumps(config))
    docker("compose", "-f", compose_path, "config", "--quiet")
    try:
        docker("compose", "-f", compose_path, "up", "-d", "--wait", "--wait-timeout", "180")
        response = docker(
            "compose",
            "-f",
            compose_path,
            "exec",
            "-T",
            "core",
            "python",
            "-c",
            "import ssl,urllib.request;print(urllib.request.urlopen('https://127.0.0.1:18765/api/health',context=ssl.create_default_context(cafile='/trust/ca.pem')).status)",
        )
        assert response.strip() == "200"
        assert "healthy" in docker("compose", "-f", compose_path, "ps")
    finally:
        docker("compose", "-f", compose_path, "stop")
