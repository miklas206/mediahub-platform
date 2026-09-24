"""Scoped Seedbox preparation. Never starts containers or creates download directories."""

import hashlib
import json
import os
import time
from pathlib import Path

from mediahub.apps.seedbox import SeedboxInstallation, SeedboxRuntimePaths, compose_plan
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from pydantic import Field


class SeedboxPolicy(StrictModel):
    hostId: str
    downloadsStorageId: str
    workRoot: str
    paths: SeedboxRuntimePaths
    nfsSource: str
    storageMarker: str
    hostMountSnapshot: str | None = None


def host_mount_verified(snapshot, path, source, read_only=False):
    """Reject stale host observations; a container can retain an old unmounted bind."""
    try:
        file = Path(snapshot)
        if file.stat().st_size > 1024 * 1024:
            return False
        data = json.loads(file.read_text())
        if (
            data.get("scope") != "host-mount-namespace"
            or data.get("available") is not True
            or not 0 <= time.time() - data["observedAt"] <= 30
        ):
            return False
        rows = [m for m in data["mounts"] if m["path"] == path]
        return (
            len(rows) == 1
            and rows[0]["filesystem"] == "nfs4"
            and rows[0]["source"] == source
            and rows[0]["readOnly"] is read_only
        )
    except (OSError, ValueError, TypeError, KeyError):
        return False


def policy_host_mounts_verified(policy):
    return bool(policy.hostMountSnapshot) and all(
        host_mount_verified(policy.hostMountSnapshot, path, source, readonly)
        for path, source, readonly in [
            (policy.paths.downloads, policy.nfsSource, False),
            *[(m.source, m.nfsSource, m.readOnly) for m in policy.paths.extraStorage],
        ]
    )


def policy_mounts_verified(policy):
    return all(
        mount_verified(path, source, marker)
        for path, source, marker in [
            (policy.paths.downloads, policy.nfsSource, policy.storageMarker),
            *[(m.source, m.nfsSource, m.storageMarker) for m in policy.paths.extraStorage],
        ]
    )


class PrepareSeedbox(StrictModel):
    installation: SeedboxInstallation
    reviewedPlanDigest: str = Field(pattern=r"^[a-f0-9]{64}$")


def mount_verified(path, source, marker, mountinfo=Path("/proc/self/mountinfo")):
    """Validate this namespace's explicit mount and NFS source, never mere directory existence."""
    try:
        rows = []
        for line in mountinfo.read_text().splitlines():
            left, right = line.split(" - ", 1)
            fields, filesystem = left.split(), right.split()
            mount = fields[4].replace("\\040", " ").replace("\\134", "\\")
            if mount == path:
                rows.append((fields, filesystem))
        if len(rows) != 1:
            return False
        _, filesystem = rows[0]
        if filesystem[0] != "nfs4" or filesystem[1] != source:
            return False
        return (Path(path) / ".mediahub-storage-id").read_text().strip() == marker
    except (OSError, ValueError, IndexError):
        return False


class SeedboxInstaller:
    def __init__(self, policy_file, verify_mount=mount_verified):
        self.policy_file = policy_file
        self.verify_mount = verify_mount

    def policy(self):
        if self.policy_file is None:
            raise DomainError(
                "seedbox_disabled", "Seedbox installation is not enabled on this Agent", 503
            )
        try:
            return SeedboxPolicy.model_validate_json(self.policy_file.read_text())
        except (OSError, ValueError):
            raise DomainError(
                "seedbox_policy_invalid", "Seedbox host policy unavailable", 503
            ) from None

    def plan(self, spec):
        policy = self.policy()
        if spec.hostId != policy.hostId or spec.downloadsStorageId != policy.downloadsStorageId:
            raise DomainError(
                "seedbox_target_denied", "Host or logical storage is not authorized", 403
            )
        work = Path(policy.workRoot)
        if not work.is_absolute() or work.resolve() != work or not work.is_dir():
            raise DomainError("seedbox_policy_invalid", "Seedbox work root unavailable", 503)
        # New runtime files must stay inside explicitly delegated work root.
        for field in ("appdata", "vpnState", "vpnConfig", "dnsConfig"):
            path = Path(getattr(policy.paths, field))
            if path.resolve() != path or not path.is_relative_to(work):
                raise DomainError(
                    "seedbox_policy_invalid", "Runtime path outside delegated root", 503
                )
        if Path(policy.paths.downloads).is_relative_to(work):
            raise DomainError(
                "seedbox_policy_invalid", "Downloads must be separate mounted storage", 503
            )
        verified = self.verify_mount(policy.paths.downloads, policy.nfsSource, policy.storageMarker)
        verified = verified and all(
            self.verify_mount(m.source, m.nfsSource, m.storageMarker)
            for m in policy.paths.extraStorage
        )
        if policy.hostMountSnapshot:
            verified = verified and policy_host_mounts_verified(policy)
        plan = {
            "targetHost": spec.hostId,
            "installationId": spec.installationId,
            "storage": {
                "logicalId": spec.downloadsStorageId,
                "hostPath": policy.paths.downloads,
                "mountedAndVerified": verified,
                "source": policy.nfsSource,
            },
            "compose": compose_plan(spec, policy.paths),
            "requirements": {
                "secretReference": spec.credentialRef,
                "protocol": spec.protocol,
                "provider": spec.provider,
                "configPresent": Path(policy.paths.vpnConfig).is_file(),
            },
            "healthChecks": [
                "required-devices",
                "nfs-source-and-marker",
                "app-write-access",
                "vpn-interface-route-external-ip",
                "qbittorrent-api",
            ],
            "executionStage": "prepare-only",
            "containersStarted": False,
            "blockers": [] if verified else ["Verified NFS downloads storage is required"],
        }
        digest_data = {"spec": spec.model_dump(), "policy": policy.model_dump(), "plan": plan}
        plan["digest"] = hashlib.sha256(
            json.dumps(digest_data, sort_keys=True).encode()
        ).hexdigest()
        return plan

    def prepare(self, request):
        # Revalidate at execution. Missing mount cannot be bypassed by an old review.
        plan = self.plan(request.installation)
        if plan["blockers"]:
            raise DomainError(
                "storage_unavailable", "Verified NFS storage required; no local fallback", 409
            )
        if plan["digest"] != request.reviewedPlanDigest:
            raise DomainError("plan_changed", "Installation plan changed; review it again", 409)
        root = Path(self.policy().workRoot)
        destination = root / "installation.json"
        # Exclusive claim: no overwrite/replacement of existing state or partial install.
        try:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                saved = json.loads(destination.read_text())
                if (
                    saved.get("review", {}).get("digest") == plan["digest"]
                    and saved.get("state") == "prepared"
                ):
                    return {
                        "state": "prepared",
                        "installationId": request.installation.installationId,
                        "digest": plan["digest"],
                        "containersStarted": False,
                        "alreadyPrepared": True,
                    }
            except (OSError, ValueError):
                pass
            raise DomainError(
                "already_prepared", "An installation already exists; inspect before continuing", 409
            ) from None
        with os.fdopen(fd, "w") as file:
            json.dump(
                {
                    "installation": request.installation.model_dump(),
                    "review": plan,
                    "state": "prepared",
                    "vpnVerified": False,
                },
                file,
            )
            file.flush()
            os.fsync(file.fileno())
        return {
            "state": "prepared",
            "installationId": request.installation.installationId,
            "digest": plan["digest"],
            "containersStarted": False,
        }
