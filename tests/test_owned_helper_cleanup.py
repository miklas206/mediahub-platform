import copy
import json

import pytest

from scripts.platform_update_host import HostUpdater


def fixture(tmp_path):
    images, calls = {}, []
    ids = {name: "sha256:" + char * 64 for name, char in zip(
        ("current", "previous", "rollback", "live", "stopped", "obsolete", "unlabelled", "foreign", "mismatch", "relay", "current_relay", "rollback_helper"),
        "abcdef123456",
    )}
    for name, identifier in ids.items():
        source = identifier[7:]
        images[identifier] = {"Id": identifier, "RepoTags": ["mediahub-web-gateway:" + source[:16]],
                              "Config": {"Labels": {"org.mediahub.gateway.source": source}}}
    images[ids["unlabelled"]]["Config"]["Labels"] = {}
    images[ids["foreign"]]["RepoTags"].append("foreign-caddy:keep")
    images[ids["mismatch"]]["Config"]["Labels"]["org.mediahub.gateway.source"] = "9" * 64
    images[ids["relay"]].update(RepoTags=["mediahub-vpn-relay:1"], Config={"Labels": {
        "org.mediahub.vpn.relay-source": ids["relay"][7:], "org.mediahub.managed-component": "vpn-relay"}})
    containers = {"live-container": ids["live"], "stopped-container": ids["stopped"]}
    (tmp_path / "compose.json").write_text(json.dumps({"services": {"core": {"image": ids["current"]}}}))
    local = tmp_path / "local-apps"
    local.mkdir()
    registry = local / "vpn-helper-images.json"
    registry.write_text(json.dumps({"images": {"gateway": ids["current"], "relay": ids["current_relay"]}, "previousImages": [ids["previous"]]}))
    backup = tmp_path / "update-backups" / ("a" * 32)
    backup.mkdir(parents=True)
    (backup / "compose.json").write_text(json.dumps({"services": {"old-helper": {"image": ids["rollback"]}}}))
    (backup / "vpn-helper-images.json").write_text(json.dumps({"images": {"gateway": ids["rollback_helper"]}, "previousImages": []}))

    def command(*args):
        calls.append(args)
        if args[:3] == ("docker", "ps", "-aq"):
            return "\n".join(containers)
        if args[:2] == ("docker", "inspect"):
            return containers[args[-1]]
        if args[:3] == ("docker", "image", "inspect"):
            if "--format" in args:
                return args[-1]
            return json.dumps([copy.deepcopy(images[args[-1]])])
        if args[:3] == ("docker", "image", "ls"):
            return "\n".join(images)
        if args[:3] == ("docker", "image", "rm"):
            assert len(args) == 4 and args[-1].startswith("sha256:")
            images.pop(args[-1])
            return ""
        raise AssertionError(args)

    updater = HostUpdater(tmp_path)
    updater.command = command
    return updater, images, containers, calls, ids, registry


def test_preview_and_cleanup_preserve_all_references_foreign_tags_and_unknown_ownership(tmp_path):
    updater, images, _, calls, ids, _ = fixture(tmp_path)
    plan = updater.cleanup_preview()
    assert {row["id"] for row in plan} == {ids["obsolete"], ids["relay"]}
    assert not any(args[:3] == ("docker", "image", "rm") for args in calls)
    result = updater._cleanup_helper_images()
    assert set(result["removedImageIds"]) == {ids["obsolete"], ids["relay"]}
    assert len(images) == len(ids) - 2
    assert all("prune" not in args and "--force" not in args for args in calls)


def test_new_stopped_container_reference_after_preview_prevents_deletion(tmp_path):
    updater, images, containers, _, ids, _ = fixture(tmp_path)
    original = updater.cleanup_preview
    counter = 0

    def preview():
        nonlocal counter
        counter += 1
        if counter == 2:
            containers["new-stopped-container"] = ids["obsolete"]
        return original()

    updater.cleanup_preview = preview
    result = updater._cleanup_helper_images()
    assert ids["obsolete"] not in result["removedImageIds"]
    assert ids["obsolete"] in images


def test_new_recipe_and_changed_ownership_after_preview_prevent_deletion(tmp_path):
    updater, images, _, _, ids, registry = fixture(tmp_path)
    original = updater.cleanup_preview
    counter = 0

    def preview():
        nonlocal counter
        counter += 1
        if counter == 2:
            state = json.loads(registry.read_text())
            state["previousImages"].append(ids["obsolete"])
            registry.write_text(json.dumps(state))
            images[ids["relay"]]["Config"]["Labels"]["org.mediahub.managed-component"] = "foreign"
        return original()

    updater.cleanup_preview = preview
    assert updater._cleanup_helper_images()["removedImageIds"] == []


def test_unknown_current_recipe_preserves_legacy_helpers(tmp_path):
    updater, _, _, calls, _, registry = fixture(tmp_path)
    registry.unlink()
    assert updater.cleanup_preview() == []
    assert calls == []


def test_partial_failure_keeps_exact_completed_image_ids(tmp_path):
    updater, _, _, _, ids, _ = fixture(tmp_path)
    command = updater.command

    def fail_second(*args):
        if args[:3] == ("docker", "image", "rm") and args[-1] == ids["obsolete"]:
            raise ValueError("Synthetic Docker refusal")
        return command(*args)

    updater.command = fail_second
    progress = {}
    with pytest.raises(ValueError, match="Synthetic"):
        updater._cleanup_helper_images(progress)
    assert progress["removedImageIds"] == [ids["relay"]]
    assert {row["id"] for row in progress["planned"]} == {ids["relay"], ids["obsolete"]}


def test_rollback_snapshot_preserves_helper_recipe_ledger(tmp_path, monkeypatch):
    updater, _, _, _, _, registry = fixture(tmp_path)
    updater.operation = "b" * 32
    updater.installed_version.write_text("0.5.38")
    monkeypatch.setattr(updater, "_state_directories", lambda: ())
    target = updater.backups / updater.operation
    updater._copy_configuration(target)
    assert json.loads((target / "vpn-helper-images.json").read_text()) == json.loads(registry.read_text())
