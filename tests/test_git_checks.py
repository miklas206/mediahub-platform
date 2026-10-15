import asyncio
import base64
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mediahub.errors import DomainError
from mediahub.git_checks import GitHubGitChecks, GitHubHTTPSSource
from mediahub.managed_apps import ManagedAdapter
from mediahub.platform_source import GitHubSourceProvider
from mediahub.update_monitor import UpdateMonitor


def test_https_git_uses_only_approved_credentials_and_verified_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "999")
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "true")
    monkeypatch.setenv("GIT_ASKPASS", "untrusted-helper")
    monkeypatch.setenv("GIT_TRACE_CURL", "true")
    source = GitHubHTTPSSource("owner/private", tmp_path, "synthetic-secret")
    _, env = source._environment()
    assert all(key not in env for key in ["GIT_SSL_NO_VERIFY", "GIT_ASKPASS", "GIT_TRACE_CURL"])
    settings = {
        env[f"GIT_CONFIG_KEY_{n}"]: env[f"GIT_CONFIG_VALUE_{n}"]
        for n in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert settings["credential.helper"] == ""
    assert settings["http.sslVerify"] == "true"
    assert settings["http.followRedirects"] == "false"
    assert settings["protocol.allow"] == "never"
    assert settings["protocol.https.allow"] == "always"
    assert settings["http.https://github.com/.extraHeader"].endswith(
        base64.b64encode(b"x-access-token:synthetic-secret").decode()
    )
    assert source._remote() == "https://github.com/owner/private.git"
    assert "synthetic-secret" not in source._remote()


@pytest.mark.parametrize("existing", [False, True])
def test_fresh_and_existing_configuration_check_core_and_apps_without_rest(
    tmp_path, monkeypatch, existing
):
    credentials = ["stored-token" if existing else None]
    svc = SimpleNamespace(
        config=SimpleNamespace(data_dir=tmp_path),
        release_credentials=SimpleNamespace(token=lambda: credentials[0]),
        settings=SimpleNamespace(get=lambda: SimpleNamespace(release_repository="owner/core")),
        platform_update=SimpleNamespace(installed_source=lambda: {}),
    )
    svc.updates = UpdateMonitor(svc)
    calls = []

    def operate(self, repository, action, **kwargs):
        calls.append((repository, action))
        assert self.token == credentials[0]
        return "a" * 40, b'[project]\nversion="9.0.0"'

    monkeypatch.setattr(GitHubHTTPSSource, "_operate", operate)
    monkeypatch.setattr(
        httpx.AsyncClient, "get", AsyncMock(side_effect=AssertionError("No REST call allowed"))
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
    apps = [ManagedAdapter(manager, "org.mediahub." + kind) for kind in ["mediaseed", "mediavpn"]]

    async def run():
        for _ in range(10):
            results = await asyncio.gather(
                svc.updates.check_platform(), *(app.updateCheck() for app in apps)
            )
            assert all(result["latestVersion"] == "9.0.0" for result in results)
            assert all(result["sourceAccessMethod"] == "git" for result in results)
            assert all(result["privateAccessConfigured"] is existing for result in results)
        assert await svc.updates.main_watch.check("owner/core", credentials[0]) == "a" * 40
        assert len(calls) == 3
        assert credentials[0] not in repr(svc.updates.git_checks.cache) if existing else True

    asyncio.run(run())


def test_cache_is_scoped_to_credentials_repository_and_expiry(tmp_path, monkeypatch):
    now, token, calls = [1000], [None], []
    cache = GitHubGitChecks(tmp_path, lambda: token[0], lambda: now[0])

    def operate(self, repository, action, **kwargs):
        calls.append((repository, action))
        return "a" * 40, b'[project]\nversion="1.0.0"'

    monkeypatch.setattr(GitHubHTTPSSource, "_operate", operate)

    async def run():
        await cache.metadata("owner/core")
        assert await cache.head("owner/core") == "a" * 40
        await cache.metadata("owner/app")
        assert len(calls) == 2
        token[0] = "changed-secret"
        await cache.metadata("owner/core")
        assert len(calls) == 3
        now[0] += 300
        await cache.metadata("owner/core")
        assert len(calls) == 4
        assert "changed-secret" not in repr(cache.cache)

    asyncio.run(run())


def test_git_failure_is_redacted_reused_briefly_and_never_claims_latest(tmp_path, monkeypatch):
    calls = []

    def fail(self, *args, **kwargs):
        calls.append(args)
        raise ValueError("secret-token /private/path")

    monkeypatch.setattr(GitHubHTTPSSource, "_run", fail)
    cache = GitHubGitChecks(tmp_path, lambda: "secret-token")

    async def run():
        for _ in range(2):
            with pytest.raises(DomainError) as error:
                await GitHubSourceProvider("1.0.0", source_access=cache).check("owner/private")
            assert "secret-token" not in error.value.message
            assert "/private/path" not in error.value.message
            assert "read access" in error.value.message
        assert len(calls) == 1

    asyncio.run(run())


def test_real_git_metadata_is_pinned_and_cache_refreshes_after_main_moves(tmp_path, monkeypatch):
    git = shutil.which("git")
    if not git:
        pytest.skip("Git required for local transport fixture")
    repo = tmp_path / "upstream"
    repo.mkdir()

    def run(*args):
        return subprocess.check_output([git, "-C", str(repo), *args], stderr=subprocess.DEVNULL)

    run("init", "-b", "main")
    run("config", "user.name", "Fixture")
    run("config", "user.email", "fixture@example.invalid")
    (repo / "pyproject.toml").write_text('[project]\nversion="1.0.0"')
    run("add", ".")
    run("commit", "-m", "first")
    first = run("rev-parse", "HEAD").decode().strip()
    real_run = GitHubHTTPSSource._run

    def transport(self, args, *other, **kwargs):
        args = [str(repo) if arg == "https://github.com/owner/app.git" else arg for arg in args]
        return real_run(self, ["-c", "protocol.file.allow=always", *args], *other, **kwargs)

    monkeypatch.setattr(GitHubHTTPSSource, "_run", transport)
    now = [1000]
    checks = GitHubGitChecks(tmp_path / "data", lambda: None, lambda: now[0])

    async def scenario():
        assert await checks.metadata("owner/app") == (first, b'[project]\nversion="1.0.0"')
        (repo / "pyproject.toml").write_text('[project]\nversion="2.0.0"')
        run("add", ".")
        run("commit", "-m", "second")
        assert (await checks.metadata("owner/app"))[0] == first
        now[0] += 300
        second, project = await checks.metadata("owner/app")
        assert second != first and b"2.0.0" in project
        assert list((tmp_path / "data/source-git-cache").iterdir()) == []

    asyncio.run(scenario())


def test_git_requirement_is_in_core_image_for_fresh_and_upgraded_installs():
    from pathlib import Path

    dockerfile = (Path(__file__).parents[1] / "docker/Dockerfile").read_text()
    assert "apt-get install -y --no-install-recommends git openssh-client" in dockerfile
    assert "ca-certificates" in dockerfile


def test_missing_git_reports_prerequisite_without_attempting_rest(tmp_path, monkeypatch):
    monkeypatch.setattr("mediahub.git_checks.shutil.which", lambda _: None)
    source = GitHubHTTPSSource("owner/app", tmp_path)
    with pytest.raises(DomainError, match="require Git in the Core image"):
        source._environment()
