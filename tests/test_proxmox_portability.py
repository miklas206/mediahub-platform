import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1] / "scripts/install-proxmox.sh").read_text()


def shell(code, stdin="", **values):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    executable = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash is needed to validate the Proxmox installer")
    result = subprocess.run([executable, "-c", "set -Eeuo pipefail\n" + code], input=stdin.encode(),
                            capture_output=True, env={**os.environ, **values}, timeout=10)
    result.stdout, result.stderr = result.stdout.decode(), result.stderr.decode()
    return result


@pytest.mark.parametrize("arch,accepted", [("amd64", True), ("arm64", True), ("armhf", False)])
def test_bootstrap_accepts_native_64bit_architecture(arch, accepted):
    code = SCRIPT.split("MEDIAHUB_ARCH=$(", 1)[1].split("read -r -p 'New container", 1)[0]
    result = shell('dpkg() { printf "%s" "$CASE_ARCH"; }\nMEDIAHUB_ARCH=$(' + code, CASE_ARCH=arch)
    assert (result.returncode == 0) == accepted


@pytest.mark.parametrize("arch", ["amd64", "arm64"])
def test_template_selection_never_downloads_the_other_architecture(arch):
    code = next(line for line in SCRIPT.splitlines() if line.startswith("TEMPLATE=$(pveam"))
    result = shell('pveam() { printf "%s\\n" "$CASE_TEMPLATES"; }\nMEDIAHUB_ARCH=$CASE_ARCH\n' + code + '\nprintf "%s" "$TEMPLATE"',
        CASE_ARCH=arch, CASE_TEMPLATES="system debian-13-standard_13.0-1_amd64.tar.zst\nsystem debian-13-standard_13.0-2_arm64.tar.zst\nsystem debian-13-standard_13.0-3_amd64.tar.zst")
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("_" + arch + ".tar.zst")


@pytest.mark.parametrize("cpus,memory,expected", [("1", "3072", "1 2048"), ("32", "64000", "4 8192"), ("2", "8192", "2 4096")])
def test_defaults_fit_small_and_large_nodes(cpus, memory, expected):
    code = "HOST_CPUS=$(" + SCRIPT.split("HOST_CPUS=$(", 1)[1].split("read -r -p 'Container hostname", 1)[0]
    result = shell('nproc() { printf "%s" "$CASE_CPUS"; }\nawk() { printf "%s" "$CASE_MEMORY"; }\n' + code + '\nprintf "%s %s" "$CT_CORES" "$CT_MEMORY"',
                   stdin="\n\n", CASE_CPUS=cpus, CASE_MEMORY=memory)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


def test_invalid_resource_override_stops_before_guest_creation():
    code = "HOST_CPUS=$(" + SCRIPT.split("HOST_CPUS=$(", 1)[1].split("read -r -p 'Container hostname", 1)[0]
    result = shell('nproc() { echo 2; }\nawk() { echo 4096; }\n' + code, stdin="8\n16384\n")
    assert result.returncode != 0
    assert "available CPU cores" in result.stderr
