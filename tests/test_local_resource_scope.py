import asyncio
from types import SimpleNamespace

from mediahub.app_resources import AppResources
from mediahub.managed_apps import ManagedAdapter


def test_overview_excludes_external_monitors_and_remote_hosts():
    rows = [
        {"id": "seed", "packageId": "org.mediahub.mediaseed"},
        {"id": "plex", "packageId": "org.mediahub.plex"},
        {"id": "remote", "packageId": "org.mediahub.jellyfin"},
        {"id": "cloudflare", "packageId": "org.mediahub.cloudflared"},
        {"id": "web", "packageId": "org.mediahub.external"},
    ]
    adapters = {
        "seed": object.__new__(ManagedAdapter),
        "plex": SimpleNamespace(host_id="local", client_factory=lambda _: None),
        "remote": SimpleNamespace(host_id="other-host", client_factory=lambda _: None),
        "cloudflare": SimpleNamespace(monitor=True),
        "web": SimpleNamespace(),
    }
    resources = object.__new__(AppResources)
    resources.svc = SimpleNamespace(
        apps=SimpleNamespace(list=lambda: rows, adapter=lambda identifier: adapters[identifier])
    )
    resources.row = lambda app: app
    resources.shared = []
    resources.shared_at = 0
    result = resources.summary()
    assert [row["id"] for row in result["items"]] == ["seed", "plex"]
    assert result["scope"] == "local-host"


def test_local_infrastructure_groups_name_services_and_deduplicate_containers():
    def row(id, project=None, service=None, name=None, **labels):
        return {
            "Id": id,
            "Names": ["/" + (name or id)],
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                **labels,
            },
        }

    core = row("core", "mediahub-platform", "core")
    rows = [
        core,
        core,
        row("proxy", "mediahub-platform", "proxy"),
        row("sampler", "mediahub-host-metrics", "sampler"),
        row("web", name="mediavpn-web", **{"org.mediahub.mediavpn.owner": "mediavpn"}),
        row("relay", **{"org.mediahub.vpn.relay": "plex"}),
        row("vpnapp", "mediahub-mediavpn", "app", **{"org.mediahub.mediavpn.owner": "mediavpn"}),
        row(
            "torrent",
            **{
                "org.mediahub.mediavpn.seedbox": "mediaseed",
                "org.mediahub.mediavpn.owner": "mediavpn",
            },
        ),
        row("external", "cloudflared", "cloudflared"),
        {"Id": "foreign", "Labels": None, "Names": ["/unrelated"]},
    ]
    measured = []

    async def docker(method, path):
        if path == "/containers/json?all=false":
            return rows
        identifier = path.split("/")[2]
        measured.append(identifier)
        return {
            "memory_stats": {"usage": 1024, "stats": {"file": 0}},
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
                "online_cpus": 8,
            },
            "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
        }

    resources = object.__new__(AppResources)
    resources.svc = SimpleNamespace(
        managed_apps=SimpleNamespace(
            docker=docker,
            policy={"org.mediahub.mediavpn": SimpleNamespace(project="mediahub-mediavpn")},
        )
    )
    asyncio.run(resources.collect_shared())
    assert sorted(measured) == ["core", "proxy", "relay", "sampler", "web"]
    groups = {r["name"]: r for r in resources.shared}
    assert groups["MediaHub and support services"]["memoryBytes"] == 3 * 1024
    vpn = groups["Shared VPN infrastructure"]
    assert vpn["memoryBytes"] == 2 * 1024
    assert {r["name"] for r in vpn["components"]} == {"Web gateway", "VPN app routing"}
