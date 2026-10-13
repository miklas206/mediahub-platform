"""Bounded, disposable GPU encoding tests. Never attach media or modify app containers."""

import asyncio
import contextlib
import copy
import hashlib
import json
import secrets
from datetime import datetime, timezone

import httpx
from mediahub.errors import DomainError

from agent.gpu import apply_gpu, available, verify_gpu
from agent.install_images import pull_latest


def fingerprint(grant):
    return hashlib.sha256(json.dumps(grant.model_dump(), sort_keys=True).encode()).hexdigest()


def encode_arguments(grant):
    args = ["-hide_banner", "-loglevel", "info"]
    if grant.vendor == "nvidia":
        encoder = "h264_nvenc"
    elif grant.vendor == "intel":
        args += [
            "-init_hw_device",
            "qsv=hw,child_device=" + grant.devices[0],
            "-filter_hw_device",
            "hw",
        ]
        encoder = "h264_qsv"
    else:
        args += ["-vaapi_device", grant.devices[0]]
        encoder = "h264_vaapi"
    args += ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10"]
    if grant.vendor != "nvidia":
        args += ["-vf", "format=nv12,hwupload=extra_hw_frames=16"]
    return args + ["-c:v", encoder, "-frames:v", "10", "-an", "-f", "null", "-"]


def isolated_filesystem(row, spec):
    host = row.get("HostConfig", {})
    temporary = spec["HostConfig"]["Tmpfs"]
    return (
        host.get("Tmpfs") == temporary
        and not host.get("Binds")
        and all(
            mount.get("Type") == "tmpfs" and mount.get("Destination") in temporary
            for mount in row.get("Mounts") or []
        )
    )


class GPUSetup:
    def __init__(self, apps):
        self.apps = apps
        self.task = None
        self.report = {"state": "idle", "verified": False, "details": []}

    def grant(self, gpu_id):
        grant = next((g for g in self.apps.policy().gpus if g.id == gpu_id), None)
        if not grant or not available(grant):
            raise DomainError(
                "gpu_unavailable",
                "Choose a GPU shared with this MediaHub host and check its device permissions",
                409,
            )
        return grant

    async def status(self):
        try:
            options = await self.apps.options("jellyfin")
        except DomainError as error:
            if error.code != "container_install_disabled":
                raise
            return {"gpus": [], "preparationRequired": True, "test": copy.deepcopy(self.report)}
        report = copy.deepcopy(self.report)
        if report.get("verified"):
            try:
                report["verified"] = (
                    fingerprint(self.grant(report["gpuId"])) == report["fingerprint"]
                )
            except DomainError:
                report["verified"] = False
        return {
            "hostId": options["hostId"],
            "gpus": options["gpus"],
            "preparationRequired": not any(g["available"] for g in options["gpus"]),
            "test": report,
        }

    async def start(self, gpu_id):
        if self.task and not self.task.done():
            raise DomainError("operation_busy", "A GPU test is already running on this host", 409)
        grant = self.grant(gpu_id)
        if grant.vendor == "nvidia":
            info = await self.apps.request("GET", "/info")
            if "nvidia" not in info.get("Runtimes", {}):
                raise DomainError(
                    "gpu_runtime_missing",
                    "Prepare NVIDIA Container Toolkit on the MediaHub host first",
                    409,
                )
        # Check again after awaited preflight; simultaneous submissions must not
        # create two GPU workloads when Docker /info yields control.
        if self.task and not self.task.done():
            raise DomainError("operation_busy", "A GPU test is already running on this host", 409)
        self.report = {
            "state": "running",
            "phase": "preflight",
            "progress": 5,
            "gpuId": gpu_id,
            "verified": False,
            "fingerprint": fingerprint(grant),
            "details": [],
            "message": "Checking GPU access",
        }
        self.task = asyncio.create_task(self.run(grant))
        return copy.deepcopy(self.report)

    def phase(self, phase, progress, message, indeterminate=False):
        self.report.update(
            phase=phase, progress=progress, message=message, indeterminate=indeterminate
        )

    def validate_grant(self, original):
        if fingerprint(self.grant(original.id)) != fingerprint(original):
            raise DomainError(
                "gpu_changed", "GPU approval changed during the test; run the test again", 409
            )

    async def logs(self, name):
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(self.apps.socket)),
                base_url="http://docker",
                timeout=10,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET", f"/containers/{name}/logs?stdout=true&stderr=true&tail=60"
                ) as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536:
                            raise ValueError("GPU test output exceeded its limit")
            # Docker's non-TTY log stream has an eight-byte header per frame.
            output, offset = bytearray(), 0
            while offset + 8 <= len(content):
                header = content[offset : offset + 8]
                size = int.from_bytes(header[4:8], "big")
                if (
                    header[0] not in {1, 2}
                    or header[1:4] != b"\0\0\0"
                    or offset + 8 + size > len(content)
                ):
                    raise ValueError("Invalid GPU test output frame")
                output.extend(content[offset + 8 : offset + 8 + size])
                offset += 8 + size
            if offset != len(content):
                raise ValueError("Incomplete GPU test output")
            return output.decode("utf-8", errors="replace")[-12000:].splitlines()[-32:]
        except (httpx.HTTPError, ValueError):
            return ["GPU test log could not be read; inspect the test result and host driver."]

    async def run(self, grant):
        token = secrets.token_hex(12)
        name = "mediahub-gpu-test-" + token
        created = False
        passed = False
        try:
            self.phase("download", 10, "Downloading the official Jellyfin GPU test image", True)
            image = await pull_latest(self.apps.socket, "jellyfin/jellyfin")
            self.validate_grant(grant)
            policy = self.apps.policy()
            spec = {
                "Image": image["Id"],
                "User": f"{policy.uid}:{policy.gid}",
                "Entrypoint": ["/usr/lib/jellyfin-ffmpeg/ffmpeg"],
                "Cmd": encode_arguments(grant),
                "Env": [],
                "Labels": {"org.mediahub.gpu.test": token},
                "HostConfig": {
                    "NetworkMode": "none",
                    "Mounts": [],
                    "Privileged": False,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "ReadonlyRootfs": True,
                    "RestartPolicy": {"Name": "no"},
                    "Memory": 1024**3,
                    "MemorySwap": 1024**3,
                    "PidsLimit": 256,
                    "Tmpfs": {
                        path: f"rw,nosuid,nodev,noexec,size=64m,uid={policy.uid},gid={policy.gid}"
                        for path in ("/tmp", "/config", "/cache")
                    },
                    "LogConfig": {
                        "Type": "json-file",
                        "Config": {"max-size": "1m", "max-file": "1"},
                    },
                },
            }
            apply_gpu(spec, grant)
            self.phase("container", 55, "Creating an isolated GPU test container")
            if await self.apps.request("GET", f"/containers/{name}/json", missing=True) is not None:
                raise DomainError(
                    "gpu_test_conflict", "GPU test container name is already in use", 409
                )
            created = True
            await self.apps.request("POST", "/containers/create?name=" + name, spec)
            row = await self.apps.request("GET", f"/containers/{name}/json")
            if (
                row.get("Config", {}).get("Labels", {}).get("org.mediahub.gpu.test") != token
                or row.get("Image") != image["Id"]
                or not verify_gpu(row, spec)
                or row.get("HostConfig", {}).get("Privileged") is not False
                or row.get("HostConfig", {}).get("NetworkMode") != "none"
                or not isolated_filesystem(row, spec)
            ):
                raise DomainError(
                    "gpu_test_ownership",
                    "GPU test container no longer matches its approved plan",
                    409,
                )
            self.validate_grant(grant)
            self.phase("encode", 75, "Encoding ten synthetic frames with the selected GPU", True)
            await self.apps.request("POST", f"/containers/{name}/start")
            result = await asyncio.wait_for(
                self.apps.request("POST", f"/containers/{name}/wait?condition=not-running"),
                timeout=120,
            )
            self.report["details"] = await self.logs(name)
            if (
                not isinstance(result, dict)
                or type(result.get("StatusCode")) is not int
                or result["StatusCode"] != 0
                or result.get("Error")
            ):
                raise DomainError(
                    "gpu_encode_failed",
                    "GPU encoding failed. Check the test log and host driver; no CPU fallback was used",
                    409,
                )
            self.validate_grant(grant)
            passed = True
        except asyncio.CancelledError:
            self.report.update(state="failed", message="GPU test interrupted; run the test again")
            raise
        except (
            DomainError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            asyncio.TimeoutError,
        ) as error:
            self.report.update(
                state="failed",
                message=str(error)
                if isinstance(error, DomainError)
                else "GPU test failed or timed out; check the host and run it again",
            )
        finally:
            if created:
                previous_phase = self.report.get("phase")
                previous_message = self.report.get("message")
                previous_progress = self.report.get("progress", 0)
                self.phase("cleanup", 95, "Removing the owned GPU test container")
                try:
                    row = await self.apps.request("GET", f"/containers/{name}/json", missing=True)
                    if row is not None:
                        if (
                            row.get("Config", {}).get("Labels", {}).get("org.mediahub.gpu.test")
                            != token
                        ):
                            raise ValueError("GPU test ownership changed")
                        await self.apps.request("DELETE", f"/containers/{name}?force=true&v=false")
                    if not passed:
                        self.report["message"] = previous_message
                except (DomainError, OSError, ValueError, TypeError, KeyError, AttributeError):
                    passed = False
                    self.report.update(
                        state="failed",
                        message="GPU test cleanup failed; inspect the owned test container before retrying",
                    )
                if not passed:
                    self.report["phase"] = previous_phase
                    self.report["progress"] = previous_progress
            if passed:
                self.report.update(
                    state="succeeded",
                    phase="complete",
                    progress=100,
                    verified=True,
                    message="GPU encoding passed and the test container was removed",
                    testedAt=datetime.now(timezone.utc).isoformat(),
                )
            self.report["indeterminate"] = False

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
