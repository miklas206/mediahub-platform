"""Read-only Docker-host telemetry, including an LXC's virtualized proc files."""

import json
import os
import shutil
import time
from pathlib import Path


class HostSampler:
    def __init__(self, root=Path("/host")):
        self.root = root
        self.previous = None

    def sample(self):
        root = self.root
        mem = {
            k: int(v.split()[0]) * 1024
            for k, v in (line.split(":", 1) for line in (root / "meminfo").read_text().splitlines())
        }
        group = root / "cgroup"
        total = mem["MemTotal"]
        used = total - mem["MemAvailable"]
        cache = mem.get("Cached", 0) + mem.get("Buffers", 0)
        parent_limit = None
        if (group / "memory.current").is_file():
            current = int((group / "memory.current").read_text())
            stat = dict(line.split() for line in (group / "memory.stat").read_text().splitlines())
            limit = (group / "memory.max").read_text().strip()
            if limit != "max":
                parent_limit = int(limit)
            # LXCFS virtualizes meminfo for the reading process, even via a bind.
            # Only the parent cgroup or the Docker daemon can establish capacity.
            total = parent_limit
            cache = int(stat.get("file", 0))
            used = max(0, current - cache)
        lines = (root / "stat").read_text().splitlines()
        cores = sum(line.startswith("cpu") and line[3:4].isdigit() for line in lines)
        cpuset = group / "cpuset.cpus.effective"
        if cpuset.is_file() and cpuset.read_text().strip():
            allowed = set()
            for part in cpuset.read_text().strip().split(","):
                bounds = list(map(int, part.split("-")))
                allowed.update(range(bounds[0], bounds[-1] + 1))
            cores = min(cores, len(allowed))
        quota = group / "cpu.max"
        if quota.is_file():
            value, period = quota.read_text().split()
            if value != "max":
                cores = min(cores, int(value) / int(period))
        cores = max(cores, 0.01)
        clock = time.monotonic()
        cpu_stat = group / "cpu.stat"
        stats = (
            dict(line.split() for line in cpu_stat.read_text().splitlines())
            if cpu_stat.is_file()
            else {}
        )
        if "usage_usec" in stats:
            counter = int(stats["usage_usec"]) / 1e6
            mode = "cgroup"
        else:
            ticks = list(map(int, lines[0].split()[1:9]))
            counter = (sum(ticks) - ticks[3] - ticks[4]) / os.sysconf("SC_CLK_TCK")
            mode = "proc"
        percent = None
        if self.previous and self.previous[2] == mode and clock > self.previous[0]:
            percent = min(
                100, max(0, (counter - self.previous[1]) / (clock - self.previous[0]) / cores * 100)
            )
        self.previous = (clock, counter, mode)
        system_disk = None
        try:
            disk = shutil.disk_usage(root / "os-release")
            system_disk = {
                "totalBytes": disk.total,
                "usedBytes": disk.used,
                "freeBytes": disk.free,
                "percent": disk.used / disk.total * 100,
                "scope": "host-system-filesystem",
            }
        except (OSError, ZeroDivisionError):
            pass
        return {
            "sampledAt": time.time(),
            "scope": "docker-host",
            "systemDisk": system_disk,
            "cpu": {"percent": percent, "cores": cores, "scope": "docker-host"},
            "ram": {
                "totalBytes": total,
                "usedBytes": used,
                "availableBytes": max(0, total - used) if total else None,
                "cacheBytes": cache,
                "percent": used / total * 100 if total else None,
                "scope": "docker-host",
                "parentLimitBytes": parent_limit,
            },
        }


def read_host_metrics(data_dir, capacity=None):
    try:
        result = json.loads((data_dir / "host-metrics/host-metrics.json").read_text())
        if result["scope"] != "docker-host" or not 0 <= time.time() - result["sampledAt"] <= 15:
            return None
        if (
            not capacity
            or type(capacity.get("memoryBytes")) is not int
            or capacity["memoryBytes"] <= 0
        ):
            return None
        ram = result["ram"]
        total = capacity["memoryBytes"]
        parent = ram.get("parentLimitBytes")
        if type(parent) is int and parent > 0:
            total = min(total, parent)
        used = ram["usedBytes"]
        if type(used) is not int or not 0 <= used <= total:
            return None
        ram.update(
            totalBytes=total,
            availableBytes=total - used,
            percent=used / total * 100,
            capacitySource="docker-daemon",
        )
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main():
    sampler = HostSampler()
    output = Path("/output/host-metrics.json")
    while True:
        try:
            result = sampler.sample()
            temporary = output.with_suffix(".tmp")
            temporary.write_text(json.dumps(result))
            temporary.replace(output)
        except (OSError, ValueError, KeyError):
            # The last snapshot expires; a failed probe never becomes zero usage.
            pass
        time.sleep(3)


if __name__ == "__main__":
    main()
