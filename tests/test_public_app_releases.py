import asyncio
import hashlib

import httpx
import pytest
from mediahub.app_releases import REPOSITORIES, latest_release
from mediahub.errors import DomainError
from mediahub.github_metadata import GitHubMetadata


def test_all_public_apps_share_cached_checks_despite_persisted_rest_limit(tmp_path):
    async def run():
        now = [1000]
        state = tmp_path / "github-cooldowns.json"
        cache = GitHubMetadata(lambda: now[0], state_file=state)
        cache.cooldowns[hashlib.sha256(b"").digest()] = 4600
        cache.persist_cooldowns()
        cache = GitHubMetadata(lambda: now[0], state_file=state)
        calls = []

        def respond(request):
            calls.append(request)
            assert request.method == "HEAD" and request.url.host == "github.com"
            assert request.url.path.endswith("/releases/latest")
            repository = request.url.path.strip("/").removesuffix("/releases/latest")
            return httpx.Response(
                302,
                headers={"Location": "https://github.com/" + repository + "/releases/tag/v12.2"},
            )

        transport = httpx.MockTransport(respond)
        for _ in range(3):
            results = await asyncio.gather(
                *(latest_release(package, "1.0", cache, transport) for package in REPOSITORIES)
            )
            assert all(
                result["latestVersion"] == "12.2" and result["checkMethod"] == "public-release"
                for result in results
            )
        assert len(calls) == len(REPOSITORIES)
        now[0] += 301
        await latest_release("org.mediahub.jellyfin", "12.2", cache, transport)
        assert len(calls) == len(REPOSITORIES) + 1

    asyncio.run(run())


def test_public_check_never_forwards_credentials_or_follows_redirect():
    async def run():
        calls = []

        def respond(request):
            calls.append(request)
            assert "Authorization" not in request.headers and "Cookie" not in request.headers
            return httpx.Response(302, headers={"Location": "https://untrusted.example/private"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            headers={"Authorization": "Bearer synthetic-secret", "Cookie": "private=secret"},
            auth=("synthetic", "password"),
            follow_redirects=True,
        ) as client:
            await GitHubMetadata().latest_public_release(client, "jellyfin/jellyfin")
        assert len(calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "location",
    [
        "https://untrusted.example/jellyfin/jellyfin/releases/tag/v12.2",
        "http://github.com/jellyfin/jellyfin/releases/tag/v12.2",
        "https:/jellyfin/jellyfin/releases/tag/v12.2",
        "https://github.com/other/repo/releases/tag/v12.2",
        "https://github.com/jellyfin/jellyfin/releases/tag/v13.0-rc1",
        "https://github.com/jellyfin/jellyfin/releases/tag/v13.0.dev1",
        "https://github.com/jellyfin/jellyfin/releases/tag/v12.2?secret=1",
        "https://github.com/jellyfin/jellyfin/releases/tag/v12.2%2Fextra",
        "",
    ],
)
def test_unverified_locations_cannot_claim_an_update(location):
    async def run():
        with pytest.raises(DomainError) as error:
            await latest_release(
                "org.mediahub.jellyfin",
                "1.0",
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(302, headers={"Location": location})
                ),
            )
        assert error.value.code == "app_release_unavailable"

    asyncio.run(run())


def test_numeric_sonarr_preview_is_not_selected_from_tags_or_feeds():
    async def run():
        def respond(request):
            assert request.url.path == "/Sonarr/Sonarr/releases/latest"
            return httpx.Response(
                302, headers={"Location": "/Sonarr/Sonarr/releases/tag/v4.0.20.3014"}
            )

        result = await latest_release(
            "org.mediahub.sonarr", "4.0.19", transport=httpx.MockTransport(respond)
        )
        assert result["latestVersion"] == "4.0.20.3014" and result["updateAvailable"]

    asyncio.run(run())


def test_public_retry_after_is_persisted_and_cached_success_remains_available(tmp_path):
    async def run():
        now = [1000]
        calls = []
        state = tmp_path / "cooldowns.json"

        def respond(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(
                    302,
                    headers={"Location": "https://github.com/jellyfin/jellyfin/releases/tag/v12.2"},
                )
            return httpx.Response(429, headers={"Retry-After": "600"})

        transport = httpx.MockTransport(respond)
        cache = GitHubMetadata(lambda: now[0], state_file=state)
        await latest_release("org.mediahub.jellyfin", "1.0", cache, transport)
        with pytest.raises(DomainError) as error:
            await latest_release("org.mediahub.radarr", "1.0", cache, transport)
        assert error.value.retry_at == 1600
        await latest_release("org.mediahub.jellyfin", "1.0", cache, transport)
        restarted = GitHubMetadata(lambda: now[0], state_file=state)
        with pytest.raises(DomainError) as error:
            await latest_release("org.mediahub.autobrr", "1.0", restarted, transport)
        assert error.value.retry_at == 1600 and len(calls) == 2
        now[0] = 1600
        with pytest.raises(DomainError):
            await latest_release("org.mediahub.autobrr", "1.0", restarted, transport)
        assert len(calls) == 3

    asyncio.run(run())
