"""Owned Docker resource telemetry and guarded, reversible live limit updates."""

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path
from uuid import uuid4

from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from pydantic import Field

from agent.install_files import read_json, save_json

MIB = 1024**2


class ResourceLimits(StrictModel):
    memoryBytes: int | None = Field(ge=256 * MIB, le=4 * 1024**4, strict=True)
    cpuCores: float | None = Field(ge=0.25, le=1024, allow_inf_nan=False, strict=True)


class ResourceChange(ResourceLimits):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def limits_of(row):
    host = row.get("HostConfig", {})
    cpu = max(0, host.get("NanoCpus", 0)) / 1e9
    if not cpu and host.get("CpuQuota", 0) > 0:
        cpu = host["CpuQuota"] / (host.get("CpuPeriod") or 100000)
    return {
        "memoryBytes": host.get("Memory") if host.get("Memory", 0) > 0 else None,
        "cpuCores": cpu or None,
    }


def resource_revision(binding):
    values = sorted(
        [
            (
                r["id"],
                r["component"],
                limits_of(r["inspect"]),
                {
                    key: r["inspect"].get("HostConfig", {}).get(key)
                    for key in ["MemorySwap", "MemoryReservation", "CpusetCpus"]
                },
            )
            for r in binding["targets"]
        ]
    )
    return hashlib.sha256(
        json.dumps([binding["installationId"], values], sort_keys=True).encode()
    ).hexdigest()


def metrics_of(stats):
    memory = stats.get("memory_stats", {})
    raw = memory.get("usage")
    detail = memory.get("stats", {})
    # Proxmox discounts file cache, including active mmap cache used by torrents.
    cache = detail.get(
        "file",
        detail.get(
            "total_cache",
            detail.get("cache", detail.get("inactive_file", detail.get("total_inactive_file", 0))),
        ),
    )
    cpu, previous = stats.get("cpu_stats", {}), stats.get("precpu_stats", {})
    delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - previous.get("cpu_usage", {}).get(
        "total_usage", 0
    )
    system_delta = cpu.get("system_cpu_usage", 0) - previous.get("system_cpu_usage", 0)
    count = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", []))
    cores = delta / system_delta * count if system_delta > 0 and count and delta >= 0 else None
    return {
        "memoryBytes": max(0, raw - cache) if isinstance(raw, int) else None,
        "chargedBytes": raw,
        "cacheBytes": cache,
        "memoryAccounting": "excluding-file-cache-v2",
        "cpuCores": cores,
    }


def split_limits(limits, components):
    weights = {"app": 3 if "client" in components else 4, "client": 9, "proxy": 1}
    total = sum(weights.get(key, 1) for key in components)
    result = {}
    for key in components:
        ratio = weights.get(key, 1) / total
        result[key] = {
            "memoryBytes": int(limits["memoryBytes"] * ratio) if limits["memoryBytes"] else None,
            "cpuCores": round(limits["cpuCores"] * ratio, 6) if limits["cpuCores"] else None,
        }
    return result


def update_body(limits, old):
    # Docker ignores zero-valued resource updates. -1 explicitly removes RAM/CFS limits.
    previous = old.get("HostConfig", {})
    memory = limits["memoryBytes"] or -1
    swap = previous.get("MemorySwap", 0)
    if memory < 0:
        swap = -1
    elif swap > 0:
        swap = memory + max(0, swap - max(0, previous.get("Memory", 0)))
    elif swap == 0:
        swap = memory
    body = {"Memory": memory, "MemorySwap": swap}
    cpu = limits["cpuCores"]
    if previous.get("NanoCpus", 0) > 0:
        if cpu is None:
            raise DomainError(
                "resources_recreate_required",
                "Removing this CPU limit requires container recreation. Choose a finite CPU limit here.",
                409,
            )
        body["NanoCpus"] = int(cpu * 1e9)
    else:
        period = previous.get("CpuPeriod") or 100000
        body.update(CpuPeriod=period, CpuQuota=int(cpu * period) if cpu else -1)
    return body


def apply_saved_resources(spec, state_dir, package, component="app"):
    """Apply before creation, only to an ownership-validated runtime specification."""
    path = Path(state_dir) / "app-resource-limits.json"
    if path.is_file():
        saved = read_json(path).get(package, {})
        entry = (
            saved.get("components", {}).get(component)
            if saved.get("installationId")
            == spec.get("Labels", {}).get("org.mediahub.installation")
            else None
        )
        if entry:
            spec.setdefault("HostConfig", {}).update(update_body(entry, spec))
    return spec


class DockerResources:
    def __init__(self, request, resolve, persist, state_dir=None):
        self.request, self.resolve, self.persist = request, resolve, persist
        self.lock = asyncio.Lock()
        self.directory = Path(state_dir) / "resource-operations" if state_dir else None
        self.active = None

    def journal(self, package, value=None):
        if not self.directory:
            return {}
        # Package has already been resolved through the approved installation map.
        if "/" in package or "\\" in package or len(package) > 100:
            raise ValueError("Invalid resource journal key")
        path = self.directory / (package + ".json")
        if value is not None:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            save_json(path, value)
        return read_json(path) if path.is_file() else {}

    async def observe(self, package):
        binding = await self.resolve(package)
        info = await self.request("GET", "/info")
        components = {}
        measured = []
        for target in binding["targets"]:
            key = target["component"]
            row = target["inspect"]
            if key not in components or row["State"].get("Running"):
                components[key] = limits_of(row)
            if target.get("measure", True) and row["State"].get("Running"):
                stats = await self.request(
                    "GET", "/containers/" + target["id"] + "/stats?stream=false"
                )
                measured.append(metrics_of(stats))

        def total(key):
            return (
                sum(x[key] for x in components.values())
                if components and all(x[key] is not None for x in components.values())
                else None
            )

        running_components = {
            target["component"]
            for target in binding["targets"]
            if target.get("measure", True) and target["inspect"]["State"].get("Running")
        }
        valid = (
            bool(measured)
            and running_components == set(components)
            and all(x["memoryBytes"] is not None and x["cpuCores"] is not None for x in measured)
        )
        operation = self.journal(package)
        if operation.get("state") == "running" and self.active != package:
            expected = operation.get("parts", {})
            complete = operation.get("installationId") == binding["installationId"] and all(
                limits_of(row["inspect"]) == expected.get(row["component"])
                for row in binding["targets"]
            )
            operation.update(
                state="succeeded" if complete else "interrupted",
                message="Resource limits verified after restart."
                if complete
                else "Resource change was interrupted. Review and save limits manually before other changes.",
            )
            self.journal(package, operation)
        editable = (
            binding.get("editable", True)
            and info.get("MemoryLimit") is True
            and info.get("CpuCfsQuota") is True
        )
        return {
            "available": bool(binding["targets"]),
            "operation": {key: operation.get(key) for key in ["state", "message", "operationId"]}
            if operation
            else None,
            "editable": editable,
            "canRemoveCpuLimit": all(
                row["inspect"].get("HostConfig", {}).get("NanoCpus", 0) <= 0
                for row in binding["targets"]
            ),
            "reason": binding.get("reason")
            or (None if editable else "The host must support Docker memory and CPU quotas."),
            "installationId": binding["installationId"],
            "revision": resource_revision(binding),
            "sampledAt": time.time(),
            "memoryAccounting": "excluding-file-cache-v2",
            "running": bool(measured),
            "validSample": valid,
            "memoryBytes": sum(x["memoryBytes"] for x in measured)
            if measured and all(x["memoryBytes"] is not None for x in measured)
            else None,
            "cpuCores": sum(x["cpuCores"] or 0 for x in measured) if valid else None,
            "limits": {key: total(key) for key in ["memoryBytes", "cpuCores"]},
            "components": [{"name": key, "limits": value} for key, value in components.items()],
            "host": {
                "id": info.get("ID"),
                "memoryBytes": info.get("MemTotal"),
                "cpuCores": info.get("NCPU"),
            },
            "sharedExcluded": binding.get("sharedExcluded", False),
        }

    async def check_budget(self, binding, proposed, parts):
        if any(
            part["memoryBytes"] is not None and part["memoryBytes"] < 64 * MIB
            for part in parts.values()
        ):
            raise DomainError(
                "resources_components",
                "The selected RAM limit is too small for this app's components. Increase the total RAM limit.",
                409,
            )
        info = await self.request("GET", "/info")
        if info.get("MemoryLimit") is not True or info.get("CpuCfsQuota") is not True:
            raise DomainError(
                "resources_unsupported",
                "Docker memory and CPU quotas are not supported by this host.",
                409,
            )
        if (
            proposed["memoryBytes"] and proposed["memoryBytes"] > info.get("MemTotal", 0) * 0.9
        ) or (proposed["cpuCores"] and proposed["cpuCores"] > info.get("NCPU", 0)):
            raise DomainError(
                "resources_capacity",
                "Requested limits exceed the host capacity; leave memory for the host and other apps.",
                409,
            )
        own = {r["id"] for r in binding["targets"]}
        other_memory, other_cpu = 0, 0
        rows = await self.request("GET", "/containers/json?all=false")
        if len(rows) > 256:
            raise DomainError(
                "resources_capacity",
                "Host capacity could not be verified for this many containers.",
                409,
            )
        for summary in rows:
            if summary["Id"] in own:
                continue
            row = await self.request("GET", "/containers/" + summary["Id"] + "/json")
            existing = limits_of(row)
            if existing["memoryBytes"] is None:
                stats = await self.request(
                    "GET", "/containers/" + summary["Id"] + "/stats?stream=false"
                )
                memory = metrics_of(stats)["memoryBytes"]
                if memory is None:
                    raise DomainError(
                        "resources_capacity",
                        "Current host memory usage could not be verified.",
                        409,
                    )
                other_memory += memory * 1.25
            else:
                other_memory += existing["memoryBytes"]
            other_cpu += existing["cpuCores"] or 0
        current = {}
        for target in binding["targets"]:
            current[target["component"]] = limits_of(target["inspect"])
        old_mem = sum(x["memoryBytes"] or 0 for x in current.values())
        old_cpu = sum(x["cpuCores"] or 0 for x in current.values())
        if (
            proposed["memoryBytes"]
            and proposed["memoryBytes"] > old_mem
            and proposed["memoryBytes"] + other_memory > info.get("MemTotal", 0) * 0.9
        ):
            raise DomainError(
                "resources_capacity",
                "There is not enough uncommitted host memory for this increase.",
                409,
            )
        if (
            proposed["cpuCores"]
            and proposed["cpuCores"] > old_cpu
            and proposed["cpuCores"] + other_cpu > info.get("NCPU", 0)
        ):
            raise DomainError(
                "resources_capacity",
                "The CPU limits already assigned to other apps leave insufficient capacity.",
                409,
            )
        for target in binding["targets"]:
            row, part = target["inspect"], parts[target["component"]]
            cpuset = row.get("HostConfig", {}).get("CpusetCpus", "")
            if cpuset and part["cpuCores"]:
                count = 0
                for segment in cpuset.split(","):
                    ends = [int(x) for x in segment.split("-")]
                    count += ends[-1] - ends[0] + 1
                if part["cpuCores"] > count:
                    raise DomainError(
                        "resources_affinity",
                        "The app CPU affinity is smaller than the requested limit.",
                        409,
                    )
            if part["memoryBytes"] and part["memoryBytes"] < row.get("HostConfig", {}).get(
                "MemoryReservation", 0
            ):
                raise DomainError(
                    "resources_reservation",
                    "The requested memory limit is below an existing memory reservation.",
                    409,
                )
            if (
                part["memoryBytes"]
                and part["memoryBytes"] != row.get("HostConfig", {}).get("Memory", 0)
                and row["State"].get("Running")
            ):
                stats = await self.request(
                    "GET", "/containers/" + target["id"] + "/stats?stream=false"
                )
                charged = metrics_of(stats)["memoryBytes"]
                if charged is None or part["memoryBytes"] < max(64 * MIB, math.ceil(charged * 1.2)):
                    raise DomainError(
                        "resources_memory_busy",
                        "The proposed memory limit is too close to current usage. Keep at least 20% headroom.",
                        409,
                    )

    async def change(self, package, change):
        async with self.lock:
            binding = await self.resolve(package)
            if not binding.get("editable", True):
                raise DomainError(
                    "resources_unsupported",
                    binding.get("reason") or "Resource limits cannot be changed for this runtime.",
                    409,
                )
            if resource_revision(binding) != change.revision:
                raise DomainError(
                    "resources_stale",
                    "App containers or resource limits changed. Refresh before applying.",
                    409,
                )
            proposed = change.model_dump(include={"memoryBytes", "cpuCores"})
            components = sorted({row["component"] for row in binding["targets"]})
            parts = split_limits(proposed, components)
            await self.check_budget(binding, proposed, parts)
            for target in binding["targets"]:
                update_body(parts[target["component"]], target["inspect"])
            old_parts = {r["component"]: limits_of(r["inspect"]) for r in binding["targets"]}
            changed = []
            job = {
                "operationId": uuid4().hex,
                "state": "running",
                "installationId": binding["installationId"],
                "parts": parts,
                "previous": old_parts,
                "startedAt": time.time(),
                "message": "Saving resource limits.",
            }
            self.journal(package, job)
            self.active = package
            persisted = False
            try:
                persisted = True
                await self.persist(package, parts)
                # Persist first so concurrent future recreations inherit the requested limits.
                fresh = await self.resolve(package)
                if resource_revision(fresh) != change.revision:
                    raise DomainError(
                        "resources_stale",
                        "The app changed during resource preparation. Refresh and retry.",
                        409,
                    )
                for target in fresh["targets"]:
                    # Include uncertain acknowledgements: Docker may apply before the connection fails.
                    changed.append(target)
                    await self.request(
                        "POST",
                        "/containers/" + target["id"] + "/update",
                        body=update_body(parts[target["component"]], target["inspect"]),
                    )
                verified = await self.resolve(package)
                for target in verified["targets"]:
                    actual, expected = limits_of(target["inspect"]), parts[target["component"]]
                    if (
                        actual["memoryBytes"] != expected["memoryBytes"]
                        or abs((actual["cpuCores"] or 0) - (expected["cpuCores"] or 0)) > 0.00001
                    ):
                        raise DomainError(
                            "resources_unverified",
                            "Docker did not confirm the requested resource limits.",
                            409,
                        )
                job.update(state="succeeded", message="Resource limits saved and verified.")
            except BaseException:
                failed = False
                if persisted:
                    try:
                        await self.persist(package, old_parts)
                    except (DomainError, OSError, ValueError, KeyError):
                        failed = True
                for target in changed:
                    try:
                        current = await self.request("GET", "/containers/" + target["id"] + "/json")
                        # Never restore a name that was taken over by a different container.
                        if current.get("Id") != target["id"]:
                            raise ValueError("Resource ownership changed during recovery")
                        old_limits = limits_of(target["inspect"])
                        await self.request(
                            "POST",
                            "/containers/" + target["id"] + "/update",
                            body=update_body(old_limits, current),
                        )
                        restored = await self.request(
                            "GET", "/containers/" + target["id"] + "/json"
                        )
                        if limits_of(restored) != old_limits:
                            raise ValueError("Resource recovery could not be verified")
                    except (DomainError, OSError, ValueError, KeyError):
                        failed = True
                job.update(
                    state="recovery_failed" if failed else "rolled_back",
                    message="Resource change needs manual recovery. Review and save the app limits before other changes."
                    if failed
                    else "Resource change failed; previous limits restored.",
                )
                if failed:
                    raise DomainError("resources_recovery_failed", job["message"], 503) from None
                raise
            finally:
                self.journal(package, job)
                self.active = None
            return await self.observe(package)
