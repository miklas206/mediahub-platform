"""Generated scripts are parsed, never run against a network share in these tests."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from mediahub.windows_share_scripts import (
    generate_connect_script,
    generate_diagnostics_script,
    utf8_bom_script,
)

GENERATORS = (generate_connect_script, generate_diagnostics_script)
POWERSHELL = shutil.which("powershell.exe") if os.name == "nt" else None


@pytest.mark.parametrize("generate", GENERATORS)
def test_unicode_and_dollar_share_are_literal_and_download_is_ps51_utf8_bom(generate):
    script = generate("192.168.1.148", "Medier ÆØÅ$", "M", "HJEM\\søren")
    assert "$SharePath = '\\\\192.168.1.148\\Medier ÆØÅ$'" in script
    assert "$SuggestedUsername = 'HJEM\\søren'" in script
    payload = utf8_bom_script(script)
    assert payload.startswith(b"\xef\xbb\xbf")
    assert payload.decode("utf-8-sig").replace("\r\n", "\n") == script
    assert b"\r\n" in payload
    assert utf8_bom_script(payload.decode("utf-8-sig")) == payload


@pytest.mark.parametrize("generate", GENERATORS)
@pytest.mark.parametrize(
    "overrides",
    [
        {"host": "127.0.0.1"}, {"host": "8.8.8.8"}, {"host": "169.254.1.1"},
        {"host": "100.64.0.1"}, {"host": "server.local"}, {"host": "::1"},
        {"host": "192.168.1.2'; Stop-Computer #"}, {"host": 3232235778},
        {"share": "../medier"}, {"share": "medier\\film"}, {"share": "medier\nexit"},
        {"share": "media'; exit; '"}, {"share": "$(Stop-Computer)"},
        {"share": "."}, {"share": ".."}, {"share": "media."}, {"share": " media"},
        {"share": ""}, {"share": "x" * 81}, {"drive": "C"},
        {"drive": "M:"}, {"drive": "M;exit"}, {"username": "user\nexit"},
        {"username": "user'"}, {"username": "a`nb"}, {"username": " user"},
        {"username": "x" * 129}, {"username": "user:password"}, {"username": 0},
    ],
)
def test_rejects_unsafe_or_out_of_scope_connection_metadata(generate, overrides):
    values = {"host": "192.168.1.148", "share": "MediaHub", "drive": "M", "username": ""}
    values.update(overrides)
    with pytest.raises(ValueError):
        generate(**values)


@pytest.mark.parametrize("host", ["10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.255.254"])
def test_accepts_each_rfc1918_network_and_optional_username(host):
    assert "$SuggestedUsername = ''" in generate_connect_script(host, "Media", "Z")


def test_accepts_same_leading_dot_share_and_lowercase_drive_as_configuration_api():
    script = generate_connect_script("192.168.1.148", ".hidden", "m")
    assert "$SharePath = '\\\\192.168.1.148\\.hidden'" in script
    assert "$DriveName = 'M'" in script


def test_connect_requires_confirmation_and_preserves_existing_mapping():
    script = generate_connect_script("192.168.1.148", "MediaHub", "M")
    assert "SupportsShouldProcess=$true, ConfirmImpact='High'" in script
    assert "$PSCmdlet.ShouldProcess" in script
    assert script.index("$PSCmdlet.ShouldProcess") < script.index("$Credential = Get-Credential")
    assert script.index("$Recheck = Get-LocalInventory") < script.index("New-PSDrive -Name")
    assert "-Credential $Credential -Persist -Scope Global" in script
    assert "$State.RememberedPath" in script
    assert "Drevbogstavet er optaget" in script
    assert "$Credential = $null" in script


def test_diagnostics_bound_access_and_capacity_and_explain_failures():
    script = generate_diagnostics_script("192.168.1.148", "MediaHub", "M")
    assert "$Process.WaitForExit($TimeoutSeconds * 1000)" in script
    assert "$Process.Kill()" in script
    assert "$Process.Dispose()" in script
    assert "$Process.StartInfo.CreateNoWindow = $true" in script
    assert "$Space = Invoke-BoundedRead" in script
    assert "$Access = Invoke-BoundedRead" in script
    assert "Test-Path -LiteralPath $SharePath -PathType Container" in script
    assert "Mapping changed during diagnostics" in script
    for guidance in ("Fejl 53:", "Fejl 67:", "Fejl 5:", "Fejl 1219:", "Samba dfree", "Kvoter", "Windows-VPN", "DNS:"):
        assert guidance in script
    for forbidden in ("New-PSDrive", "Get-Credential", "Remove-PSDrive", "Set-ExecutionPolicy", "cmdkey", "net use", "Set-Smb", "Set-NetFirewall", "WriteAllText"):
        assert forbidden not in script


def _powershell(command: str, timeout: int = 15) -> str:
    import base64

    assert POWERSHELL
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, timeout=timeout, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout.decode("utf-8-sig").strip()


def _parse_file(path: Path) -> str:
    literal = "'" + str(path).replace("'", "''") + "'"
    return (
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
        "$Tokens = $null; $Errors = $null; "
        "$Ast = [System.Management.Automation.Language.Parser]::ParseFile("
        + literal + ", [ref]$Tokens, [ref]$Errors); "
        "if ($Errors.Count -gt 0) { $Errors | Out-String | Write-Error; exit 1 }; "
    )


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell parser requires Windows")
@pytest.mark.parametrize("generate", GENERATORS)
def test_real_ps51_parser_accepts_scripts_and_mutation_surface_is_limited(generate, tmp_path):
    path = tmp_path / "download.ps1"
    path.write_bytes(utf8_bom_script(generate("192.168.1.148", "Medier ÆØÅ$", "M", "HJEM\\søren")))
    output = _powershell(_parse_file(path) + """
    @($Ast.FindAll({ param($Node)
        $Node -is [System.Management.Automation.Language.CommandAst]
    }, $true) | ForEach-Object { $_.GetCommandName() } | Where-Object { $_ }) | ConvertTo-Json -Compress
    """)
    commands = json.loads(output)
    assert "Remove-PSDrive" not in commands
    assert not any(command.startswith(("Set-", "Remove-", "Clear-", "Enable-", "Disable-")) for command in commands)
    assert ("New-PSDrive" in commands) == (generate is generate_connect_script)
    assert ("Get-Credential" in commands) == (generate is generate_connect_script)


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell worker requires Windows")
def test_bounded_worker_transports_unicode_and_kills_only_its_own_timed_out_process(tmp_path):
    # Execute only the extracted generic worker function with synthetic operations.
    # Neither script main, inventory, TCP checks nor share access are ever executed.
    path = tmp_path / "download.ps1"
    path.write_bytes(utf8_bom_script(generate_diagnostics_script("192.168.1.148", "MediaHub", "M")))
    command = _parse_file(path) + """
    $Function = $Ast.Find({ param($Node)
        $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $Node.Name -eq 'Invoke-BoundedRead'
    }, $true)
    . ([scriptblock]::Create($Function.Extent.Text))
    $Success = Invoke-BoundedRead -Values @('Søren ÆØÅ $test') -Operation {
        param($Text) [pscustomobject]@{ Text = $Text }
    }
    $Timeout = Invoke-BoundedRead -TimeoutSeconds 1 -Operation { Start-Sleep -Seconds 30 }
    @{ Success = $Success; Timeout = $Timeout } | ConvertTo-Json -Depth 5 -Compress
    """
    started = time.monotonic()
    result = json.loads(_powershell(command))
    assert time.monotonic() - started < 12
    assert result["Success"] == {"Ok": True, "Value": {"Text": "Søren ÆØÅ $test"}}
    assert result["Timeout"]["Ok"] is False
    assert result["Timeout"]["TimedOut"] is True


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell worker requires Windows")
def test_bounded_worker_drains_large_stdout_and_stderr_without_false_timeout(tmp_path):
    # Exercise only the generic worker with synthetic strings larger than the
    # Windows pipe buffers, never network access or the generated script's main.
    path = tmp_path / "download.ps1"
    path.write_bytes(utf8_bom_script(generate_diagnostics_script("192.168.1.148", "MediaHub", "M")))
    command = _parse_file(path) + """
    $Function = $Ast.Find({ param($Node)
        $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $Node.Name -eq 'Invoke-BoundedRead'
    }, $true)
    . ([scriptblock]::Create($Function.Extent.Text))
    $Result = Invoke-BoundedRead -TimeoutSeconds 4 -Operation {
        [Console]::Error.Write([string]::new([char]101, 12000))
        [string]::new([char]120, 12000)
    }
    @{ Ok = $Result.Ok; Length = $Result.Value.Length; Value = $Result.Value } |
        ConvertTo-Json -Compress
    """
    result = json.loads(_powershell(command))
    assert result == {"Ok": True, "Length": 12000, "Value": "x" * 12000}


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell worker requires Windows")
def test_access_operation_checks_browsing_without_returning_names(tmp_path):
    # Run only the generated bounded access operation against temporary local
    # folders. No script main, SMB share, network request or drive mapping runs.
    empty = tmp_path / "empty"
    empty.mkdir()
    populated = tmp_path / "populated"
    populated.mkdir()
    (populated / "private-entry-name.txt").write_text("not read", encoding="utf-8")
    absent = tmp_path / "does-not-exist"
    path = tmp_path / "download.ps1"
    path.write_bytes(utf8_bom_script(generate_diagnostics_script("192.168.1.148", "MediaHub", "M")))
    paths = ", ".join("'" + str(value).replace("'", "''") + "'" for value in (empty, populated, absent))
    command = _parse_file(path) + """
    $Function = $Ast.Find({ param($Node)
        $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $Node.Name -eq 'Invoke-BoundedRead'
    }, $true)
    . ([scriptblock]::Create($Function.Extent.Text))
    $AccessBlock = $Ast.Find({ param($Node)
        $Node -is [System.Management.Automation.Language.ScriptBlockExpressionAst] -and
        $Node.Extent.Text.Contains('EnumerateFileSystemEntries')
    }, $true).ScriptBlock.GetScriptBlock()
    $Results = foreach ($LocalFolder in @(""" + paths + """)) {
        Invoke-BoundedRead -Operation $AccessBlock -Values @($LocalFolder)
    }
    @($Results) | ConvertTo-Json -Depth 4 -Compress
    """
    output = _powershell(command)
    assert json.loads(output) == [
        {"Ok": True, "Value": True},
        {"Ok": True, "Value": True},
        {"Ok": True, "Value": False},
    ]
    assert "private-entry-name" not in output
