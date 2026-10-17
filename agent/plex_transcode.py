"""Provision a dedicated transcode mount and migrate owned older runtimes."""

import asyncio
import contextlib
import copy
import hashlib
import json
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from mediahub.apps.plex import PlexInstallation
from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.plex_control import PlexMount, PlexPolicy
from agent.plex_install import transcode_mount


def preferences(content, mounted):
    root = ET.fromstring(content)
    if mounted:
        current = root.get("TranscoderTempDirectory", "")
        if not current or current in {"/run/plex-temp", "/tmp", "/transcode"}:
            root.set("TranscoderTempDirectory", "/transcode")
        root.set("TranscoderPersistSessionDirs", "0")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


async def prepare(runtime, plan, *, clean=False):
    policy = runtime.policy()
    spec = PlexInstallation.model_validate(plan["installation"])
    mount = transcode_mount(policy, spec)
    if mount not in plan["container"]["HostConfig"]["Mounts"]:
        raise DomainError(
            "plex_temp_mapping_changed", "Plex temporary mount requires migration", 409
        )
    if not await runtime.control.storage_verified(policy):
        raise DomainError(
            "storage_unavailable", "Verified storage required for Plex temporary files", 409
        )
    if clean:
        current = await runtime.control.inspect(runtime.control.policy())
        if current["State"].get("Running"):
            raise DomainError("plex_temp_busy", "Plex must be stopped before orphan cleanup", 409)
    source = Path(mount["Source"])
    # Mount the approved parent, allowing only Temp/<installation> creation.
    # The helper never receives writable media mounts or namespace privileges.
    parent = source.parent.parent.parent
    guarded = [Path(p) for p in (*policy.requiredMounts, *policy.requiredFilesystemUuids)]
    if not any(parent == root or root in parent.parents for root in guarded):
        parent = source.parent.parent
    code = Path(__file__).with_name("plex_transcode_worker.py").read_text()
    code += "\nprint(json.dumps(prepare('/approved', " + repr(
        str(source.parent.relative_to(parent))
    )
    code += ", " + repr(spec.installationId) + ", clean=" + repr(clean) + ")))\n"
    name = "mediahub-plex-temp-" + uuid.uuid4().hex[:12]
    helper = None
    try:
        helper = (
            await runtime.request(
                "POST",
                "/containers/create?name=" + name,
                body={
                    "Image": policy.initImage,
                    "User": f"{policy.uid}:{policy.gid}",
                    "Entrypoint": ["python", "-c", code],
                    "Labels": {
                        "org.mediahub.package": "org.mediahub.plex",
                        "org.mediahub.installation": spec.installationId,
                        "org.mediahub.plex.role": "transcode-preparation",
                    },
                    "HostConfig": {
                        "NetworkMode": "none",
                        "ReadonlyRootfs": True,
                        "CapDrop": ["ALL"],
                        "SecurityOpt": ["no-new-privileges:true"],
                        "Memory": 64 * 1024**2,
                        "MemorySwap": 64 * 1024**2,
                        "PidsLimit": 16,
                        "LogConfig": {"Type": "none", "Config": {}},
                        "Mounts": [
                            {
                                "Type": "bind",
                                "Source": str(parent),
                                "Target": "/approved",
                                "ReadOnly": False,
                            }
                        ],
                    },
                },
            )
        )["Id"]
        await runtime.request("POST", f"/containers/{helper}/start")
        result = await runtime.request("POST", f"/containers/{helper}/wait")
        if result.get("StatusCode") != 0:
            raise DomainError(
                "plex_temp_unwritable",
                "Plex temporary storage cannot allocate files. Check permissions, free space and pooled-drive placement; at least 1 GiB free is required.",
                409,
            )
        runtime.transcode_status = {
            "state": "ready",
            "path": str(source),
            "message": "Temporary storage is writable; Plex cleans finished sessions and MediaHub clears orphan sessions before restart.",
        }
    finally:
        if helper:
            await runtime.remove_helper(helper)


async def reconcile(runtime, policy):
    if time.monotonic() - getattr(runtime, "temp_checked_at", 0) < 60:
        return
    plan = read_json(runtime.state_dir / "plex-plan.json")
    current = await runtime.control.inspect(policy)
    if current["State"].get("Running"):
        prefs = await runtime.control.plex_get(policy, "/:/prefs")
        custom = next(
            (row.get("value", "") for row in prefs if row.get("id") == "TranscoderTempDirectory"),
            "",
        )
        if custom and custom not in {"/run/plex-temp", "/tmp", "/transcode"}:
            runtime.transcode_status = {
                "state": "custom",
                "path": custom,
                "message": "Your existing custom transcoding directory is preserved; MediaHub does not clean it.",
            }
            runtime.temp_checked_at = time.monotonic()
            return
    if any(m.get("Target") == "/transcode" for m in plan["container"]["HostConfig"]["Mounts"]):
        await prepare(runtime, plan)
        runtime.temp_checked_at = time.monotonic()
        return
    sessions = (
        await runtime.control.plex_get(policy, "/status/sessions")
        if current["State"].get("Running")
        else ET.Element("MediaContainer", size="0")
    )
    if int(sessions.get("size", "0")) or list(sessions):
        runtime.transcode_status = {
            "state": "pending",
            "message": "Temporary storage will be prepared automatically when active playback finishes.",
        }
        return
    await migrate(runtime, policy, plan)


async def migrate(runtime, policy, plan):
    receipt = runtime.state_dir / "plex-transcode-migration.json"
    if receipt.exists():
        saved = read_json(receipt)
        if saved.get("state") != "complete":
            raise DomainError(
                "plex_temp_recovery_required",
                "Temporary storage migration needs recovery; original runtime and media were preserved",
                409,
            )
    before = await runtime.control.inspect(policy)
    new_plan = copy.deepcopy(plan)
    new_plan["container"]["HostConfig"]["Mounts"].append(
        transcode_mount(runtime.policy(), PlexInstallation.model_validate(plan["installation"]))
    )
    reference = before.get("Config", {}).get("Image", "")
    new_plan["container"]["Image"] = (
        reference if reference.startswith("lscr.io/linuxserver/plex@sha256:") else before["Image"]
    )
    nonce = uuid.uuid4().hex
    new_plan["container"]["Labels"]["org.mediahub.plex.temp-migration"] = nonce
    new_plan["container"]["Env"] = [
        v for v in new_plan["container"].get("Env", []) if not v.startswith("TMPDIR=")
    ] + ["TMPDIR=/transcode"]
    new_plan["planDigest"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in new_plan.items() if k != "planDigest"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    await prepare(runtime, new_plan)
    if before["State"].get("Running"):
        sessions = await runtime.control.plex_get(policy, "/status/sessions")
        if int(sessions.get("size", "0")) or list(sessions):
            runtime.transcode_status = {
                "state": "pending",
                "message": "Temporary storage will be prepared automatically when active playback finishes.",
            }
            return
    old_policy = policy.model_dump()
    desired = runtime.control.intent(policy)
    old_name = policy.container + "-temp-rollback"
    saved = {
        "state": "prepared",
        "oldPlan": plan,
        "newPlan": new_plan,
        "oldPolicy": old_policy,
        "oldContainer": old_name,
        "oldId": before["Id"],
        "nonce": nonce,
        "desiredRunning": desired,
    }
    save_json(receipt, saved)
    try:
        runtime.control.save_intent(policy, False)
        await runtime.stop(policy)
        await runtime.request("POST", f"/containers/{policy.container}/rename?name={old_name}")
        await runtime.request(
            "POST", "/containers/create?name=" + policy.container, body=new_plan["container"]
        )
        inspected = await runtime.request("GET", f"/containers/{policy.container}/json")
        policy.mounts = [
            PlexMount(source=m["Source"], target=m["Destination"], readOnly=not m["RW"])
            for m in inspected["Mounts"]
        ]
        save_json(Path(runtime.control.policy_file), policy.model_dump())
        save_json(runtime.state_dir / "plex-plan.json", new_plan)
        if desired:
            await runtime.start(policy)
            for _ in range(20):
                try:
                    await runtime.control.plex_get(policy, "/identity")
                    break
                except DomainError:
                    await asyncio.sleep(1)
            else:
                raise DomainError(
                    "plex_temp_start_failed",
                    "Plex did not become ready with temporary storage",
                    503,
                )
        runtime.control.save_intent(policy, desired)
        save_json(receipt, {"state": "complete"})
        with contextlib.suppress(DomainError):
            await runtime.request("DELETE", f"/containers/{before['Id']}?v=false")
        runtime.control.record("temporary_storage_migrated")
    except Exception:
        await restore(runtime, saved)
        raise


async def restore(runtime, saved):
    old = PlexPolicy.model_validate(saved["oldPolicy"])
    listing = await runtime.request("GET", "/containers/json?all=1")
    rows = [row for row in listing if row["Id"] == saved["oldId"]]
    if len(rows) != 1:
        raise DomainError(
            "plex_temp_recovery_required",
            "Original Plex runtime is missing; recovery stopped without deleting data",
            409,
        )
    current = [row for row in listing if "/" + old.container in row.get("Names", [])]
    original = await runtime.request("GET", f"/containers/{saved['oldId']}/json")
    if (
        original.get("Image") != old.imageId
        or original.get("Config", {}).get("Labels", {}).get("org.mediahub.installation")
        != old.installationId
    ):
        raise DomainError("plex_ownership_mismatch", "Original Plex runtime ownership changed", 409)
    for row in current:
        if row["Id"] == saved["oldId"]:
            continue
        item = await runtime.request("GET", f"/containers/{row['Id']}/json")
        labels = item.get("Config", {}).get("Labels", {})
        if (
            labels.get("org.mediahub.plex.temp-migration") != saved["nonce"]
            or item.get("Image") != old.imageId
        ):
            raise DomainError(
                "plex_ownership_mismatch", "Temporary-storage replacement ownership changed", 409
            )
        if item["State"].get("Running"):
            await runtime.request("POST", f"/containers/{row['Id']}/stop?t=30")
        await runtime.request("DELETE", f"/containers/{row['Id']}?v=false")
    if original.get("Name") != "/" + old.container:
        await runtime.request("POST", f"/containers/{saved['oldId']}/rename?name={old.container}")
    save_json(Path(runtime.control.policy_file), old.model_dump())
    save_json(runtime.state_dir / "plex-plan.json", saved["oldPlan"])
    runtime.control.save_intent(old, saved["desiredRunning"])
    if saved["desiredRunning"] and not original["State"].get("Running"):
        await runtime.start(old)
    save_json(
        runtime.state_dir / "plex-transcode-migration.json",
        {**saved, "state": "failed", "originalRestored": True},
    )
    runtime.transcode_status = {
        "state": "blocked",
        "message": "Temporary storage migration failed; the original Plex runtime was restored. Check writable temporary storage before retrying.",
    }


async def recover(runtime):
    receipt = runtime.state_dir / "plex-transcode-migration.json"
    if receipt.exists():
        saved = read_json(receipt)
        if saved.get("state") == "prepared":
            await restore(runtime, saved)
