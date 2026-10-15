import asyncio
import base64

import httpx
import pytest
from mediahub.errors import DomainError
from mediahub.github_metadata import GitHubMetadata
from mediahub.main_branch_watch import MainBranchWatch
from mediahub.platform_source import GitHubSourceProvider


def test_cooldown_survives_restart_without_storing_credentials(tmp_path):
    async def run():
        now = [1000]
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(429, headers={"x-ratelimit-reset": "4600"})

        path = tmp_path / "github-cooldowns.json"
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle),
            headers={"Authorization": "Bearer synthetic-secret"},
        ) as client:
            for cache in [GitHubMetadata(lambda: now[0], state_file=path), None]:
                cache = cache or GitHubMetadata(lambda: now[0], state_file=path)
                with pytest.raises(DomainError) as error:
                    await cache.get(client, "/repos/owner/repo/commits/main")
                assert error.value.retry_at == 4600
            assert len(calls) == 1
            assert "synthetic-secret" not in path.read_text()
            now[0] = 4600
            restarted = GitHubMetadata(lambda: now[0], state_file=path)
            with pytest.raises(DomainError):
                await restarted.get(client, "/repos/owner/repo/commits/main")
            assert len(calls) == 2

    asyncio.run(run())


def test_core_agent_and_watcher_share_requests_then_refresh_after_ttl():
    async def run():
        now = [1000]
        calls = []

        def handle(request):
            calls.append(request)
            if request.url.path.endswith("/commits/main"):
                return httpx.Response(200, json={"sha": "a" * 40})
            return httpx.Response(
                200,
                json={
                    "encoding": "base64",
                    "content": base64.b64encode(b'[project]\nversion="0.5.7"').decode(),
                },
            )

        transport = httpx.MockTransport(handle)
        cache = GitHubMetadata(lambda: now[0])
        core = GitHubSourceProvider("0.5.7", "a" * 40, transport, metadata_cache=cache)
        agent = GitHubSourceProvider("0.5.6", "b" * 40, transport, metadata_cache=cache)
        watch = MainBranchWatch(transport, lambda: now[0], metadata_cache=cache)
        results = await asyncio.gather(
            core.check("owner/repo"), agent.check("owner/repo"), watch.check("owner/repo", None)
        )
        assert len(calls) == 2
        assert results[0]["updateAvailable"] is False
        assert results[1]["updateAvailable"] is True
        now[0] += 300
        await core.check("owner/repo")
        assert len(calls) == 3  # Refresh main; keep immutable commit's pyproject.
        await core.check("owner/repo", "new-token")
        assert len(calls) == 5

    asyncio.run(run())


def test_valid_cached_metadata_remains_available_during_provider_cooldown():
    async def run():
        calls = []

        def handle(request):
            calls.append(request.url.path)
            return (
                httpx.Response(200, json={"sha": "a" * 40})
                if len(calls) == 1
                else httpx.Response(429)
            )

        cache = GitHubMetadata(lambda: 1000)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            cached = await cache.get(client, "/repos/owner/hub/commits/main")
            with pytest.raises(DomainError):
                await cache.get(client, "/repos/owner/other/commits/main")
            assert await cache.get(client, "/repos/owner/hub/commits/main") is cached
            assert len(calls) == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "headers,deadline",
    [
        ({"retry-after": "1800", "x-ratelimit-reset": "4600"}, 4600),
        ({"retry-after": "Thu, 01 Jan 1970 01:00:00 GMT"}, 3600),
        ({}, 4600),
    ],
)
def test_rate_limit_blocks_all_metadata_paths_until_provider_deadline(headers, deadline):
    async def run():
        now = [1000]
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(429, headers=headers)

        transport = httpx.MockTransport(handle)
        cache = GitHubMetadata(lambda: now[0])
        source = GitHubSourceProvider("0.5.7", transport=transport, metadata_cache=cache)
        for repo in ["owner/repo", "owner/other"]:
            with pytest.raises(DomainError) as error:
                await source.check(repo)
            assert error.value.code == "github_rate_limited"
            assert error.value.retry_at == deadline
        watch = MainBranchWatch(transport, lambda: now[0], metadata_cache=cache)
        assert await watch.check("owner/repo", None) is None
        assert len(calls) == 1
        now[0] = deadline - 1
        with pytest.raises(DomainError):
            await source.check("owner/repo")
        assert len(calls) == 1
        now[0] = deadline
        with pytest.raises(DomainError):
            await source.check("owner/repo")
        assert len(calls) == 2
        await watch.check("owner/repo", "replacement-token")
        assert len(calls) == 3

    asyncio.run(run())


@pytest.mark.parametrize("limited", [False, True])
def test_first_party_checks_share_cache_and_provider_cooldown(monkeypatch, limited):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mediahub.managed_apps import ManagedAdapter

    async def run():
        now = [1000]
        calls = []

        def handle(request):
            calls.append(request.url.path)
            if limited:
                return httpx.Response(429, headers={"x-ratelimit-reset": "4600"})
            if request.url.path.endswith("/commits/main"):
                return httpx.Response(200, json={"sha": "a" * 40})
            return httpx.Response(
                200,
                json={
                    "encoding": "base64",
                    "content": base64.b64encode(b'[project]\nversion="9.0.0"').decode(),
                },
            )

        transport = httpx.MockTransport(handle)

        def provider(*args, **kwargs):
            assert kwargs["metadata_cache"] is cache
            return GitHubSourceProvider(*args, **kwargs, transport=transport)

        monkeypatch.setattr("mediahub.app_updates.GitHubSourceProvider", provider)
        cache = GitHubMetadata(lambda: now[0])
        svc = SimpleNamespace(
            updates=SimpleNamespace(github_metadata=cache),
            release_credentials=SimpleNamespace(token=lambda: None),
        )
        manager = SimpleNamespace(
            svc=svc,
            containers=AsyncMock(
                return_value=[
                    {
                        "Config": {
                            "Labels": {
                                "com.docker.compose.service": "app",
                                "org.mediahub.app.version": "1.0.0",
                            }
                        }
                    }
                ]
            ),
        )
        apps = [
            ManagedAdapter(manager, "org.mediahub." + kind) for kind in ["mediaseed", "mediavpn"]
        ]
        for _ in range(10):
            results = await asyncio.gather(*(app.updateCheck() for app in apps))
            if limited:
                assert all(
                    result["checkStatus"] == "deferred" and result["retryAt"] == 4600
                    for result in results
                )
                assert all(result["installedVersion"] == "1.0.0" for result in results)
            else:
                assert all(result["updateAvailable"] for result in results)
        assert len(calls) == (1 if limited else 4)
        now[0] += 300
        await apps[0].updateCheck()
        assert len(calls) == (1 if limited else 5)  # Refresh main, reuse pinned pyproject.

    asyncio.run(run())
