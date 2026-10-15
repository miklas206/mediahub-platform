import asyncio
import copy
import time

import pytest
from mediahub.errors import DomainError
from mediahub.resource_history import ResourceHistory, recommendations
from pydantic import ValidationError

from agent.resource_control import (
    DockerResources,
    ResourceChange,
    apply_saved_resources,
    limits_of,
    metrics_of,
    resource_revision,
)

GIB = 1024**3


def snapshot(now=None):
    return {
        "available": True,
        "editable": True,
        "running": True,
        "validSample": True,
        "sampledAt": now or time.time(),
        "installationId": "owned-installation",
        "revision": "a" * 64,
        "memoryBytes": int(3.8 * GIB),
        "cpuCores": 0.25,
        "limits": {"memoryBytes": 4 * GIB, "cpuCores": 2},
        "host": {"id": "host", "memoryBytes": 16 * GIB, "cpuCores": 8},
    }


def sample(used=0.5):
    return {
        "memory_stats": {"usage": int(used * GIB), "stats": {"inactive_file": 0}},
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200},
            "system_cpu_usage": 1000,
            "online_cpus": 8,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 0},
    }


class DockerFixture:
    def __init__(self, tmp_path, count=1, limited=True):
        self.rows = {}
        for index in range(count):
            key = "owned-" + str(index)
            self.rows[key] = {
                "Id": key,
                "HostConfig": {
                    "Memory": 4 * GIB if limited else 0,
                    "MemorySwap": 4 * GIB if limited else 0,
                    "NanoCpus": 0,
                    "CpuPeriod": 100000 if limited else 0,
                    "CpuQuota": 200000 if limited else 0,
                },
                "State": {"Running": True},
            }
        self.calls = []
        self.saved = []
        self.usage = 0.5
        self.other_memory = 0
        self.fail = None
        self.info = {
            "MemoryLimit": True,
            "CpuCfsQuota": True,
            "MemTotal": 16 * GIB,
            "NCPU": 8,
            "ID": "host",
        }
        self.engine = DockerResources(self.request, self.resolve, self.persist, tmp_path)

    async def resolve(self, package):
        if package != "plex":
            raise DomainError("not_found", "No approved app", 404)
        return {
            "installationId": "owned",
            "targets": [
                {
                    "id": key,
                    "component": "app" if n == 0 else "client",
                    "inspect": copy.deepcopy(row),
                }
                for n, (key, row) in enumerate(self.rows.items())
            ],
        }

    async def persist(self, package, parts):
        self.saved.append(copy.deepcopy(parts))

    async def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == "/info":
            return self.info
        if path == "/containers/json?all=false":
            return [{"Id": "other"}] if self.other_memory else []
        if path == "/containers/other/json":
            return {"HostConfig": {"Memory": self.other_memory}, "State": {"Running": True}}
        if "/stats?" in path:
            return sample(self.usage)
        key = path.split("/")[2]
        if path.endswith("/json"):
            return copy.deepcopy(self.rows[key])
        if method == "POST" and path.endswith("/update"):
            if self.fail == key:
                self.fail = None
                raise DomainError("synthetic_failure", "Synthetic update failure", 503)
            host = self.rows[key]["HostConfig"]
            if body.get("NanoCpus", 0) > 0 and (
                host.get("CpuQuota", 0) > 0 or host.get("CpuPeriod", 0) > 0
            ):
                raise DomainError("conflict", "Nano CPUs conflict with existing CFS quotas", 409)
            # Real Docker semantics: zero does not clear an existing field.
            for name, value in body.items():
                if value != 0:
                    host[name] = value
            return {"Warnings": []}
        raise AssertionError((method, path))

    async def change(self, memory=6 * GIB, cpu=3):
        binding = await self.resolve("plex")
        return await self.engine.change(
            "plex",
            ResourceChange(memoryBytes=memory, cpuCores=cpu, revision=resource_revision(binding)),
        )


def test_working_set_and_cpu_cores_are_real_not_host_percentages():
    values = sample(2)
    values["memory_stats"]["stats"]["inactive_file"] = GIB
    result = metrics_of(values)
    assert result["memoryBytes"] == GIB and result["cpuCores"] == 0.8
    assert metrics_of({"memory_stats": {}})["memoryBytes"] is None
    assert metrics_of({"cpu_stats": {}})["cpuCores"] is None


@pytest.mark.parametrize(
    "cpu,memory",
    [(-1, GIB), (True, GIB), (float("nan"), GIB), (1, True), (1, -1), (1, 128 * 1024**2)],
)
def test_resource_request_rejects_invalid_and_non_numeric_limits(cpu, memory):
    with pytest.raises(ValidationError):
        ResourceChange(cpuCores=cpu, memoryBytes=memory, revision="a" * 64)


def test_revision_is_stable_across_discovery_order_and_tracks_replacement(tmp_path):
    fake = DockerFixture(tmp_path, 2)
    binding = asyncio.run(fake.resolve("plex"))
    old = resource_revision(binding)
    binding["targets"].reverse()
    assert resource_revision(binding) == old
    binding["targets"][0]["id"] = "replacement"
    assert resource_revision(binding) != old


def test_live_change_verifies_only_owned_containers_and_retains_journal(tmp_path):
    fake = DockerFixture(tmp_path)
    result = asyncio.run(fake.change())
    assert result["limits"] == {"memoryBytes": 6 * GIB, "cpuCores": 3}
    assert result["operation"]["state"] == "succeeded"
    assert fake.rows["owned-0"]["HostConfig"]["CpuQuota"] == 300000
    assert all("restart" not in path and "create" not in path for _, path, _ in fake.calls)
    assert fake.engine.journal("plex")["parts"] == fake.saved[0]


def test_multi_container_failure_restores_previous_unlimited_resources(tmp_path):
    fake = DockerFixture(tmp_path, 2, limited=False)
    fake.fail = "owned-1"
    with pytest.raises(DomainError, match="Synthetic update failure"):
        asyncio.run(fake.change(4 * GIB, 2))
    assert all(
        limits_of(row) == {"memoryBytes": None, "cpuCores": None} for row in fake.rows.values()
    )
    assert fake.engine.journal("plex")["state"] == "rolled_back"
    assert len(fake.saved) == 2


def test_busy_ram_and_host_overcommit_are_rejected_before_persisting(tmp_path):
    fake = DockerFixture(tmp_path)
    fake.usage = 3.8
    with pytest.raises(DomainError, match="20% headroom"):
        asyncio.run(fake.change(3 * GIB, 2))
    assert not fake.saved
    fake.usage = 0.5
    fake.other_memory = 10 * GIB
    with pytest.raises(DomainError, match="uncommitted host memory"):
        asyncio.run(fake.change())
    assert not fake.saved


def test_cpu_edit_does_not_require_changing_an_unchanged_nearly_full_ram_limit(tmp_path):
    fake = DockerFixture(tmp_path)
    fake.usage = 3.8
    result = asyncio.run(fake.change(4 * GIB, 3))
    assert result["limits"]["cpuCores"] == 3


def test_memory_limit_can_be_cleared_without_claiming_zero_did_it(tmp_path):
    fake = DockerFixture(tmp_path)
    result = asyncio.run(fake.change(None, None))
    assert result["limits"] == {"memoryBytes": None, "cpuCores": None}
    assert fake.rows["owned-0"]["HostConfig"]["Memory"] == -1
    assert fake.rows["owned-0"]["HostConfig"]["CpuQuota"] == -1


def test_existing_nano_cpu_limit_requires_recreation_to_remove(tmp_path):
    fake = DockerFixture(tmp_path)
    fake.rows["owned-0"]["HostConfig"].update(NanoCpus=2000000000, CpuQuota=0, CpuPeriod=0)
    with pytest.raises(DomainError, match="requires container recreation"):
        asyncio.run(fake.change(6 * GIB, None))
    assert not fake.saved
    assert asyncio.run(fake.change())["limits"]["cpuCores"] == 3


def test_replacement_or_other_app_is_never_an_update_target(tmp_path):
    fake = DockerFixture(tmp_path)
    with pytest.raises(DomainError, match="Refresh before applying"):
        asyncio.run(
            fake.engine.change(
                "plex", ResourceChange(memoryBytes=6 * GIB, cpuCores=3, revision="0" * 64)
            )
        )
    with pytest.raises(DomainError, match="No approved app"):
        asyncio.run(
            fake.engine.change(
                "foreign", ResourceChange(memoryBytes=6 * GIB, cpuCores=3, revision="0" * 64)
            )
        )
    assert not fake.saved


def test_restart_exposes_interrupted_journal_without_repeating_updates(tmp_path):
    fake = DockerFixture(tmp_path)
    fake.engine.journal(
        "plex",
        {
            "state": "running",
            "installationId": "owned",
            "parts": {"app": {"memoryBytes": 6 * GIB, "cpuCores": 3}},
        },
    )
    result = asyncio.run(fake.engine.observe("plex"))
    assert result["operation"]["state"] == "interrupted"
    assert not any(method == "POST" for method, _, _ in fake.calls)


def test_repeated_ram_pressure_proposes_four_to_six_gib_but_single_peak_does_not():
    now = 10 * 86400
    rows = [
        {
            "time": now - 3600 + i * 300,
            "memoryBytes": int((3.8 if i < 3 else 1) * GIB),
            "cpuCores": 0.1,
        }
        for i in range(12)
    ]
    advice = recommendations(rows, {"memoryBytes": 4 * GIB, "cpuCores": 2}, now)
    assert len(advice) == 1 and advice[0]["proposed"] == 6 * GIB
    rows[0]["memoryBytes"] = GIB
    rows[1]["memoryBytes"] = GIB
    assert recommendations(rows, {"memoryBytes": 4 * GIB, "cpuCores": 2}, now) == []


def test_reduction_requires_a_week_and_keeps_rare_bursts():
    now = 10 * 86400
    rows = [
        {"time": now - 7 * 86400 + i * 300, "memoryBytes": 100 * 1024**2, "cpuCores": 0.05}
        for i in range(1, 2017)
    ]
    limits = {"memoryBytes": 4 * GIB, "cpuCores": 2}
    assert {item["direction"] for item in recommendations(rows, limits, now)} == {"decrease"}
    assert recommendations(rows[-24:], limits, now) == []
    assert recommendations(rows[::3], limits, now) == []
    rows[50]["memoryBytes"] = 3 * GIB
    rows[50]["cpuCores"] = 1
    assert recommendations(rows, limits, now) == []
    assert recommendations(rows, {"memoryBytes": None, "cpuCores": None}, now) == []


def test_history_and_opt_out_survive_restart_and_allocations_do_not_mix(tmp_path):
    now = [10 * 86400]
    history = ResourceHistory(tmp_path, lambda: now[0])
    observed = snapshot(now[0])
    history.record("plex", observed)
    assert history.decorate("plex", observed)["history"]["samples"] == 1
    bad = {**observed, "validSample": False}
    history.record("plex", bad)
    history.preference("plex", False)
    restarted = ResourceHistory(tmp_path, lambda: now[0])
    assert restarted.enabled("plex") is False
    assert restarted.decorate("plex", observed)["recommendations"] == []
    assert (
        restarted.decorate("plex", {**observed, "limits": {"memoryBytes": 6 * GIB, "cpuCores": 2}})[
            "history"
        ]["samples"]
        == 0
    )
    assert (
        restarted.decorate("plex", {**observed, "installationId": "new-install"})["history"][
            "samples"
        ]
        == 0
    )
    assert restarted.decorate("plex", observed)["history"]["samples"] == 1


def test_saved_limits_apply_before_recreation_only_to_same_installation(tmp_path):
    from agent.install_files import save_json

    save_json(
        tmp_path / "app-resource-limits.json",
        {
            "org.mediahub.plex": {
                "installationId": "owned",
                "components": {"app": {"memoryBytes": 4 * GIB, "cpuCores": 2}},
            }
        },
    )
    spec = {
        "Labels": {"org.mediahub.installation": "owned"},
        "HostConfig": {"Mounts": [{"preserve": "media"}]},
    }
    apply_saved_resources(spec, tmp_path, "org.mediahub.plex")
    assert spec["HostConfig"]["Memory"] == 4 * GIB and spec["HostConfig"]["CpuQuota"] == 200000
    assert spec["HostConfig"]["Mounts"] == [{"preserve": "media"}]
    other = {"Labels": {"org.mediahub.installation": "new"}, "HostConfig": {}}
    apply_saved_resources(other, tmp_path, "org.mediahub.plex")
    assert not other["HostConfig"]


def test_resource_api_requires_login_csrf_and_admin_and_retains_preferences(
    logged_in, client, monkeypatch
):
    svc = logged_in.app.state.services
    app = svc.apps.list()[0]
    id = app["id"]
    assert logged_in.get("/api/resources").status_code == 200
    token = logged_in.headers.pop("X-MediaHub-CSRF")
    assert (
        logged_in.put(f"/api/resources/{id}/recommendations", json={"enabled": False}).status_code
        == 403
    )
    logged_in.headers["X-MediaHub-CSRF"] = token
    response = logged_in.put(f"/api/resources/{id}/recommendations", json={"enabled": False})
    assert (
        response.status_code == 200 and response.json()["data"]["recommendationsEnabled"] is False
    )
    assert ResourceHistory(svc.config.data_dir).enabled(app["packageId"]) is False
    assert (
        logged_in.put(
            f"/api/resources/{id}",
            json={
                "memoryBytes": 4 * GIB,
                "cpuCores": 2,
                "revision": "a" * 64,
                "container": "foreign",
            },
        ).status_code
        == 422
    )
    with svc.sessions.begin() as db:
        from mediahub.db import User

        user = db.query(User).first()
        user.role = "viewer"
    assert logged_in.get("/api/resources").status_code == 403


def test_uncertain_docker_acknowledgement_restores_the_affected_container(tmp_path):
    fake = DockerFixture(tmp_path)
    original = fake.request
    fail_once = [True]

    async def uncertain(method, path, body=None):
        result = await original(method, path, body)
        if method == "POST" and fail_once[0]:
            fail_once[0] = False
            raise OSError("Connection dropped after Docker applied the update")
        return result

    fake.engine.request = uncertain
    with pytest.raises(OSError):
        asyncio.run(fake.change())
    assert limits_of(fake.rows["owned-0"]) == {"memoryBytes": 4 * GIB, "cpuCores": 2}
    assert fake.engine.journal("plex")["state"] == "rolled_back"


def test_resource_api_rejects_anonymous_access(client):
    assert client.get("/api/resources").status_code == 401


@pytest.mark.parametrize("existing", [False, True])
def test_compose_resource_persistence_is_idempotent_and_preserves_upgrade_config(
    tmp_path, monkeypatch, existing
):
    import importlib.util
    import json
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "scripts/prepare_local_apps.py"
    monkeypatch.syspath_prepend(str(source.parent))
    spec = importlib.util.spec_from_file_location("resource_preparation", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path.resolve()
    (root / "data").mkdir()
    (root / "data/managed-apps.json").write_text(
        json.dumps({"org.mediahub.mediaseed": {"project": "mediahub-mediaseed"}})
    )
    folder = root / "local-apps/mediaseed"
    folder.mkdir(parents=True)
    config = {
        "name": "mediahub-mediaseed",
        "services": {
            name: {
                "environment": {"PRESERVED": "synthetic-config"},
                "volumes": ["kept:/data"],
                **({"mem_limit": GIB, "cpu_quota": 100000} if existing else {}),
            }
            for name in ["app", "qbittorrent"]
        },
        "volumes": {"kept": {"external": True}},
    }
    path = folder / "compose.json"
    path.write_text(json.dumps(config))
    rows = [
        {"Config": {"Labels": {"com.docker.compose.service": name}}, "HostConfig": {}}
        for name in config["services"]
    ]
    calls = []

    def run(*args):
        calls.append(args)
        return "app client" if args[1] == "ps" else json.dumps(rows)

    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module, "private", lambda path, content: path.write_text(content))
    parts = {
        "app": {"memoryBytes": GIB, "cpuCores": 0.5},
        "client": {"memoryBytes": 3 * GIB, "cpuCores": 1.5},
    }
    module.configure_resource_limits(root, "mediaseed", parts)
    first = path.read_text()
    module.configure_resource_limits(root, "mediaseed", parts)
    assert path.read_text() == first
    updated = json.loads(first)
    assert updated["services"]["qbittorrent"]["mem_limit"] == 3 * GIB
    assert updated["services"]["qbittorrent"]["cpu_quota"] == 150000
    assert updated["services"]["app"]["environment"] == config["services"]["app"]["environment"]
    assert (
        updated["services"]["app"]["volumes"] == ["kept:/data"]
        and updated["volumes"] == config["volumes"]
    )
    assert all(call[1] in {"ps", "inspect"} for call in calls)


def test_approval_rechecks_history_opt_out_and_exact_proposal(logged_in, monkeypatch):
    from unittest.mock import AsyncMock

    svc = logged_in.app.state.services
    app = svc.apps.list()[0]
    resources = svc.resources
    now = time.time()
    raw = snapshot(now)
    for index in range(12):
        resources.history.clock = lambda index=index: now - (11 - index) * 300
        resources.history.record(app["packageId"], {**raw, "sampledAt": now - (11 - index) * 300})
    resources.history.clock = lambda: now
    advice = resources.history.decorate(app["packageId"], raw)["recommendations"][0]
    monkeypatch.setattr(resources, "observe", AsyncMock(return_value=raw))
    local = type(
        "Engine",
        (),
        {
            "change": AsyncMock(
                return_value={**raw, "limits": {**raw["limits"], "memoryBytes": 6 * GIB}}
            )
        },
    )()
    monkeypatch.setattr(resources, "backend", lambda app: (local, None))
    body = ResourceChange(memoryBytes=6 * GIB, cpuCores=2, revision=raw["revision"])
    result = asyncio.run(resources.change(app, body, advice["id"]))
    assert result["limits"]["memoryBytes"] == 6 * GIB
    resources.preference(app, False)
    with pytest.raises(DomainError, match="disabled"):
        asyncio.run(resources.change(app, body, advice["id"]))
    assert local.change.await_count == 1
    # Opt-out suppresses proposals, not the manual control.
    asyncio.run(resources.change(app, body))
    assert local.change.await_count == 2


def test_shared_client_template_is_counted_once(tmp_path):
    fake = DockerFixture(tmp_path, count=2)
    fake.rows["owned-1"]["State"]["Running"] = False
    original = fake.resolve

    async def resolve(package):
        binding = await original(package)
        for target in binding["targets"]:
            target["component"] = "client"
        binding["sharedExcluded"] = True
        return binding

    fake.engine.resolve = resolve
    result = asyncio.run(fake.engine.observe("plex"))
    assert result["memoryBytes"] == int(0.5 * GIB)
    assert result["limits"]["memoryBytes"] == 4 * GIB
    assert result["sharedExcluded"] and len(result["components"]) == 1


def test_stopped_component_cannot_be_treated_as_long_term_idle_usage(tmp_path):
    fake = DockerFixture(tmp_path, count=2)
    fake.rows["owned-1"]["State"]["Running"] = False
    result = asyncio.run(fake.engine.observe("plex"))
    assert result["validSample"] is False
    history = ResourceHistory(tmp_path)
    history.record("plex", result)
    assert history.decorate("plex", result)["history"]["samples"] == 0
