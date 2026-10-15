import json
import sys
import time
from pathlib import Path

import pytest
from mediahub.host_metrics import HostSampler, read_host_metrics
from mediahub.resource_history import allocation_key

from agent.resource_control import metrics_of

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts.prepare_local_apps import prepare_host_metrics


def fixture_host(tmp_path):
    host = tmp_path / "host"
    host.mkdir()
    (host / "meminfo").write_text(
        "MemTotal: 16777216 kB\nMemAvailable: 15000000 kB\nCached: 1000000 kB\n"
    )
    (host / "stat").write_text(
        "cpu 100 0 0 200 0 0 0 0\n" + "".join(f"cpu{i} 1 0 0 2\n" for i in range(16))
    )
    group = host / "cgroup"
    group.mkdir()
    for name, value in {
        "memory.current": "15000000000",
        "memory.max": "max",
        "memory.stat": "anon 1000000000\nfile 13500000000\n",
        "cpu.max": "max 100000",
        "cpu.stat": "usage_usec 1000000\n",
        "cpuset.cpus.effective": "0-2,5-6,10-11,15",
    }.items():
        (group / name).write_text(value)
    return host


def test_lxc_total_uses_parent_memory_and_cpuset_not_core_limit(tmp_path, monkeypatch):
    host = fixture_host(tmp_path)
    sampler = HostSampler(host)
    clock = iter([10, 13])
    monkeypatch.setattr("mediahub.host_metrics.time.monotonic", lambda: next(clock))
    first = sampler.sample()
    assert first["ram"]["usedBytes"] == 1500000000
    assert first["ram"]["totalBytes"] is None  # resolved from the Docker daemon in Core
    assert first["cpu"]["cores"] == 8
    assert first["cpu"]["percent"] is None
    (host / "cgroup/cpu.stat").write_text("usage_usec 4000000\n")
    assert sampler.sample()["cpu"]["percent"] == 12.5


def test_native_linux_falls_back_to_proc_and_lxc_limits_are_respected(tmp_path, monkeypatch):
    monkeypatch.setattr("mediahub.host_metrics.os.sysconf", lambda name: 100, raising=False)
    host = fixture_host(tmp_path)
    (host / "cgroup/memory.max").write_text(str(2 * 1024**3))
    (host / "cgroup/cpu.max").write_text("200000 100000")
    row = HostSampler(host).sample()
    assert row["ram"]["totalBytes"] == 2 * 1024**3
    assert row["cpu"]["cores"] == 2
    for p in (host / "cgroup").iterdir():
        p.unlink()
    row = HostSampler(host).sample()
    assert row["ram"]["usedBytes"] == (16777216 - 15000000) * 1024
    assert row["cpu"]["cores"] == 16


def test_stale_or_missing_snapshot_does_not_become_core_usage(tmp_path):
    assert read_host_metrics(tmp_path) is None
    path = tmp_path / "host-metrics/host-metrics.json"
    path.parent.mkdir()
    for age, expected in [(1, True), (20, False), (-20, False)]:
        path.write_text(
            json.dumps(
                {"sampledAt": time.time() - age, "scope": "docker-host", "ram": {"usedBytes": 1024}}
            )
        )
        assert (read_host_metrics(tmp_path, {"memoryBytes": 16 * 1024**3}) is not None) == expected


@pytest.mark.parametrize("legacy", [False, True])
def test_lxcfs_reader_limit_is_not_used_as_host_capacity(tmp_path, legacy):
    host = fixture_host(tmp_path)
    (host / "meminfo").write_text("MemTotal: 65536 kB\nMemAvailable: 54000 kB\nCached: 1024 kB\n")
    snapshot = HostSampler(host).sample()
    if legacy:
        snapshot["ram"].update(totalBytes=64 * 1024**2, availableBytes=0, percent=3999)
        snapshot["ram"].pop("parentLimitBytes", None)
    path = tmp_path / "host-metrics/host-metrics.json"
    path.parent.mkdir()
    path.write_text(json.dumps(snapshot))
    assert read_host_metrics(tmp_path) is None
    corrected = read_host_metrics(tmp_path, {"memoryBytes": 16 * 1024**3})
    assert corrected["ram"]["totalBytes"] == 16 * 1024**3
    assert corrected["ram"]["usedBytes"] == 1500000000
    assert 0 < corrected["ram"]["percent"] < 100


def test_invalid_capacity_or_inconsistent_usage_is_not_displayed(tmp_path):
    path = tmp_path / "host-metrics/host-metrics.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({"scope": "docker-host", "sampledAt": time.time(), "ram": {"usedBytes": 2000}})
    )
    for value in [0, -1, True, None, "16GB", 1000]:
        assert read_host_metrics(tmp_path, {"memoryBytes": value}) is None


def test_daemon_capacity_is_refreshed_and_failures_invalidate_it(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from mediahub.system import SystemService

    service = SystemService(SimpleNamespace(data_dir=tmp_path))
    clock = [0]
    calls = []
    monkeypatch.setattr("mediahub.system.time.monotonic", lambda: clock[0])

    async def docker(method, path):
        calls.append((method, path))
        if clock[0] >= 30:
            raise OSError("synthetic unavailable")
        return {"MemTotal": (16 if clock[0] < 15 else 32) * 1024**3}

    async def check():
        await service.refresh_host_capacity(docker)
        assert service.host_capacity["memoryBytes"] == 16 * 1024**3
        clock[0] = 5
        await service.refresh_host_capacity(docker)
        assert len(calls) == 1
        clock[0] = 15
        await service.refresh_host_capacity(docker)
        assert service.host_capacity["memoryBytes"] == 32 * 1024**3
        clock[0] = 30
        await service.refresh_host_capacity(docker)
        assert service.host_capacity is None

    asyncio.run(check())


def test_history_separates_old_cache_inflated_measurements():
    old = {"limits": {"memoryBytes": 1024**3, "cpuCores": 1}}
    updated = {**old, "memoryAccounting": "excluding-file-cache-v2"}
    assert allocation_key(old) != allocation_key(updated)
    assert allocation_key(updated) == allocation_key(dict(updated))


def test_system_disk_uses_host_os_file_not_download_or_core_volume(tmp_path, monkeypatch):
    from types import SimpleNamespace

    host = fixture_host(tmp_path)
    paths = []

    def usage(path):
        paths.append(path)
        return SimpleNamespace(total=32 * 1024**3, used=23 * 1024**3, free=9 * 1024**3)

    monkeypatch.setattr("mediahub.host_metrics.shutil.disk_usage", usage)
    snapshot = HostSampler(host).sample()
    assert paths == [host / "os-release"]
    assert snapshot["systemDisk"]["totalBytes"] == 32 * 1024**3
    assert snapshot["systemDisk"]["freeBytes"] == 9 * 1024**3
    assert snapshot["systemDisk"]["scope"] == "host-system-filesystem"


@pytest.mark.parametrize("key", ["file", "total_cache", "cache"])
def test_torrent_active_file_cache_is_not_reported_as_app_ram(key):
    row = metrics_of(
        {
            "memory_stats": {
                "usage": 6 * 1024**3,
                "stats": {key: 5 * 1024**3, "inactive_file": 1024**3},
            }
        }
    )
    assert row["memoryBytes"] == 1024**3
    assert row["chargedBytes"] == 6 * 1024**3


@pytest.mark.parametrize("existing", [False, True])
def test_fresh_and_older_install_prepare_sampler_without_restarting_apps(
    tmp_path, monkeypatch, existing
):
    host = tmp_path / "native"
    for name in ["proc/meminfo", "proc/stat", "sys/fs/cgroup"]:
        p = host / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.mkdir() if name.endswith("cgroup") else p.write_text("fixture")
    root = tmp_path / "install"
    (root / "data").mkdir(parents=True)
    (root / "data/config.json").write_text("preserved")
    monkeypatch.setattr("scripts.prepare_local_apps.os.chown", lambda *args: None, raising=False)
    compose = {"services": {"core": {"image": "owned-core:1"}}}
    calls = []
    if existing:
        prepare_host_metrics(root, compose, host, command=lambda *args: calls.append(args))
    prepare_host_metrics(root, compose, host, command=lambda *args: calls.append(args))
    cfg = json.loads((root / "host-metrics/compose.json").read_text())
    assert set(cfg["services"]) == {"sampler"}
    sampler = cfg["services"]["sampler"]
    assert sampler["network_mode"] == "none"
    assert sampler["read_only"] is True
    assert sampler["cap_drop"] == ["ALL"]
    assert all(v.endswith(":ro") for v in sampler["volumes"][:3])
    assert sampler["volumes"][3] == {
        "type": "bind",
        "source": "/etc/os-release",
        "target": "/host/os-release",
        "read_only": True,
        "bind": {"create_host_path": False},
    }
    assert (root / "data/config.json").read_text() == "preserved"
    assert all("never" in call and "--no-build" in call for call in calls)
