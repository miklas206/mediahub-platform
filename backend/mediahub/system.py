import platform
import shutil
import time
from pathlib import Path

import psutil

from mediahub import __version__
from mediahub.db import now


class SystemService:
    def __init__(self, config):
        self.config = config
        self.started = time.monotonic()
        self.previous_network = None
        self.previous_time = None
        self.previous_cgroup_cpu = None
        self.previous_cgroup_time = None
        psutil.cpu_percent(None)  # first sample is intentionally discarded

    def status(self):
        memory = psutil.virtual_memory()
        disk = shutil.disk_usage(self.config.data_dir.resolve())
        network = psutil.net_io_counters()
        sample_time = time.monotonic()
        rates = {"uploadBytesPerSecond": None, "downloadBytesPerSecond": None}
        if self.previous_network is not None:
            delta = max(sample_time - self.previous_time, 0.001)
            rates = {
                "uploadBytesPerSecond": max(
                    0, (network.bytes_sent - self.previous_network.bytes_sent) / delta
                ),
                "downloadBytesPerSecond": max(
                    0, (network.bytes_recv - self.previous_network.bytes_recv) / delta
                ),
            }
        self.previous_network, self.previous_time = network, sample_time
        ram = {
            "totalBytes": memory.total,
            "availableBytes": memory.available,
            "usedBytes": memory.total - memory.available,
            "percent": memory.percent,
            "cacheBytes": getattr(memory, "cached", None),
            "scope": "operating-system",
        }
        cpu = {
            "percent": psutil.cpu_percent(None),
            "cores": psutil.cpu_count(),
            "scope": "operating-system",
        }
        # cgroup v2-aware reporting when limited in Docker/LXC. Never call these PVE host metrics.
        group = Path("/sys/fs/cgroup")
        try:
            limit = (group / "memory.max").read_text().strip()
            if limit != "max" and int(limit) < memory.total:
                current = int((group / "memory.current").read_text())
                stats = dict(
                    line.split() for line in (group / "memory.stat").read_text().splitlines()
                )
                ram = {
                    "totalBytes": int(limit),
                    "availableBytes": max(0, int(limit) - current),
                    "usedBytes": current,
                    "percent": current / int(limit) * 100,
                    "cacheBytes": int(stats.get("file", 0)),
                    "scope": "cgroup-v2",
                }
            quota, period = (group / "cpu.max").read_text().split()
            if quota != "max":
                cores = int(quota) / int(period)
                ticks = int(
                    dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())[
                        "usage_usec"
                    ]
                )
                percent = None
                if self.previous_cgroup_cpu is not None:
                    percent = min(
                        100,
                        max(
                            0,
                            (ticks - self.previous_cgroup_cpu)
                            / 1e6
                            / (sample_time - self.previous_cgroup_time)
                            / cores
                            * 100,
                        ),
                    )
                cpu = {"percent": percent, "cores": cores, "scope": "cgroup-v2"}
                self.previous_cgroup_cpu, self.previous_cgroup_time = ticks, sample_time
        except (OSError, ValueError, KeyError):
            pass
        return {
            "hostname": platform.node(),
            "version": __version__,
            "timestamp": now(),
            "uptimeSeconds": time.time() - psutil.boot_time(),
            "coreUptimeSeconds": sample_time - self.started,
            "cpu": cpu,
            "ram": ram,
            "disk": {
                "totalBytes": disk.total,
                "freeBytes": disk.free,
                "usedBytes": disk.used,
                "percent": disk.used / disk.total * 100,
                "scope": "Core data filesystem",
            },
            "network": rates,
            "environment": platform.system(),
        }
