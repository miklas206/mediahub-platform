import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("vpn_preparation", SCRIPTS / "prepare_local_apps.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_fresh_install_builds_helpers_and_pulls_provider_without_starting_anything(tmp_path, monkeypatch):
    source = tmp_path / "source"
    for folder, files in [("relay_image", ["Dockerfile", "runtime.py"]), ("gateway_image", ["Dockerfile", "config.py", "observer.py", "natpmp.py", "plex_port.py"])]:
        directory = source / "mediavpn" / folder
        directory.mkdir(parents=True)
        for name in files:
            (directory / name).write_text("synthetic " + name)
    images, calls = {}, []

    def run(*args):
        calls.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            if args[3] not in images:
                raise subprocess.CalledProcessError(1, args)
            return json.dumps([images[args[3]]])
        if args[:2] == ("docker", "build"):
            labels = dict(args[i+1].split("=", 1) for i, value in enumerate(args) if value == "--label")
            images[args[args.index("--tag")+1]] = {"Id": "sha256:" + str(len(images)+1)*64, "Config": {"Labels": labels}}
        if args[:2] == ("docker", "pull"):
            images[args[2]] = {"Id": "sha256:" + "a"*64, "RepoDigests": ["qmcgaw/gluetun@sha256:" + "b"*64]}
        return ""

    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module.os, "chown", lambda *args: None, raising=False)
    root = tmp_path / "hub"
    first = module.prepare_vpn_helpers(source, root)
    assert set(first) == {"relay", "gateway", "provider"}
    assert sum(call[:2] == ("docker", "build") for call in calls) == 2
    assert not any("run" in call or "start" in call for call in calls)
    calls.clear()
    second = module.prepare_vpn_helpers(source, root)
    assert second == first
    assert not any(call[:2] == ("docker", "build") for call in calls)
    ledger = json.loads((root / "local-apps/vpn-helper-images.json").read_text())
    assert set(ledger["previousImages"]) == set(first.values())


def test_helper_sources_are_part_of_reviewed_bundle():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/sync_bundled_apps.py").read_text()
    assert '"gateway_image" in p.relative_to(root).parts' in script
    assert (root / "docker/runtime-scripts/prepare_local_apps.py").read_bytes() == (root / "scripts/prepare_local_apps.py").read_bytes()


def test_upgrade_refreshes_reviewed_oneshot_helper_and_keeps_previous_source(tmp_path):
    root, source = tmp_path / "hub", tmp_path / "source"
    (root / "updates").mkdir(parents=True)
    (source / "scripts").mkdir(parents=True)
    old = root / "platform_update_host.py"
    old.write_text("old_version = True\n")
    old.chmod(0o700)
    reviewed = source / "scripts/platform_update_host.py"
    reviewed.write_text("new_version = True\n")
    caps = root / "updates/host-capabilities.json"
    caps.write_text('{"mainBranchUpdates":true}')
    module.refresh_host_updater(root, source)
    assert old.read_text() == reviewed.read_text()
    assert (root / "updates/platform_update_host.previous.py").read_text() == "old_version = True\n"
    assert json.loads(caps.read_text()) == {"mainBranchUpdates": True, "maintenance": True, "ownedHelperCleanup": True}
    # Idempotence preserves the useful previous helper instead of backing up itself.
    module.refresh_host_updater(root, source)
    assert (root / "updates/platform_update_host.previous.py").read_text() == "old_version = True\n"
