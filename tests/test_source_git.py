import asyncio
import os
import shutil
import subprocess
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.config import Config
from mediahub.errors import DomainError
from mediahub.main_branch_watch import MainBranchWatch
from mediahub.platform_source import GitHubSourceProvider, download_source, normalize_source
from mediahub.source_git import GitHubSSHSource, source_access
from pydantic import ValidationError

REPOSITORY = "owner/private-repo"
COMMIT = "a" * 40


@pytest.fixture
def access(tmp_path):
    keydir = tmp_path / "ssh"
    keydir.mkdir()
    (keydir / "id_ed25519").write_text("fixture-not-a-real-key")
    (keydir / "id_ed25519").chmod(0o600)
    (keydir / "known_hosts").write_text("github.com fixture-not-a-host-key")
    return GitHubSSHSource(REPOSITORY, keydir, tmp_path / "data")


def test_optional_access_configuration_is_paired_and_repository_bound(tmp_path):
    assert source_access(SimpleNamespace()) is None
    for values in (
        {"source_git_repository": REPOSITORY},
        {"source_git_ssh_dir": tmp_path},
        {"source_git_repository": "git@github.com:owner/repo", "source_git_ssh_dir": tmp_path},
        {"source_git_repository": REPOSITORY, "source_git_ssh_dir": "relative/path"},
    ):
        with pytest.raises(ValidationError):
            Config(_env_file=None, **values)
    config = Config(
        _env_file=None,
        data_dir=tmp_path / "data",
        source_git_repository=REPOSITORY,
        source_git_ssh_dir=tmp_path,
    )
    assert source_access(config).repository == REPOSITORY


def test_other_repository_rejected_before_any_git_or_ssh(access, monkeypatch, tmp_path):
    def forbidden():
        pytest.fail("Mismatched repository must not load credentials or run Git")

    monkeypatch.setattr(access, "_environment", forbidden)
    with pytest.raises(DomainError, match="different GitHub repository"):
        asyncio.run(GitHubSourceProvider("0.4.29", source_access=access).check("owner/other"))
    with pytest.raises(DomainError, match="different GitHub repository"):
        asyncio.run(
            download_source(
                None, "owner/other", COMMIT, tmp_path / "out", None, source_access=access
            )
        )


def test_deploy_identity_ignores_inherited_agents_config_and_strictly_verifies_host(
    access, monkeypatch
):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_SSH_COMMAND", "untrusted-command")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/unrelated-personal-agent")
    _, environment = access._environment()
    assert "GIT_CONFIG_COUNT" not in environment
    assert "SSH_AUTH_SOCK" not in environment
    assert "untrusted-command" not in environment["GIT_SSH_COMMAND"]
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    command = environment["GIT_SSH_COMMAND"]
    for required in (
        "StrictHostKeyChecking=yes",
        "IdentityAgent=none",
        "IdentitiesOnly=yes",
        "BatchMode=yes",
        "known_hosts",
        "id_ed25519",
        "PasswordAuthentication=no",
    ):
        assert required in command


def test_git_failure_details_are_redacted_and_cache_is_removed(access, monkeypatch):
    def failure(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git", stderr="PRIVATE-KEY /secret/path")

    monkeypatch.setattr(access, "_run", failure)
    with pytest.raises(DomainError) as error:
        asyncio.run(access.metadata(REPOSITORY))
    assert error.value.code == "source_git_unavailable"
    assert "PRIVATE-KEY" not in str(error.value)
    assert "/secret/path" not in str(error.value)
    assert list(access.cache.iterdir()) == []


def test_overlarge_cache_is_refused_before_running_git(access, monkeypatch):
    access.cache.mkdir(parents=True)
    (access.cache / "old-pack").write_bytes(b"oversize")
    monkeypatch.setattr("mediahub.source_git.MAX_CACHE", 4)
    monkeypatch.setattr(
        access, "_run", lambda *args, **kwargs: pytest.fail("Cache must be bounded")
    )
    with pytest.raises(DomainError):
        asyncio.run(access.head(REPOSITORY))


def test_main_watch_uses_throttled_ssh_head_checks_without_personal_token():
    now = [1000]
    access = SimpleNamespace(head=AsyncMock(return_value=COMMIT))
    watch = MainBranchWatch(clock=lambda: now[0], source_access=access)
    assert asyncio.run(watch.check(REPOSITORY, None)) == COMMIT
    now[0] += 60
    assert asyncio.run(watch.check(REPOSITORY, None)) is None
    access.head.assert_awaited_once_with(REPOSITORY)
    now[0] += 900
    access.head.side_effect = DomainError("source_git_unavailable", "unavailable", 503)
    assert asyncio.run(watch.check(REPOSITORY, None)) is None


def test_real_git_archive_stays_on_checked_commit_when_main_advances(access, monkeypatch, tmp_path):
    """Only transport is replaced; real fetch/show/archive and source normalization run."""
    git = shutil.which("git")
    if not git:
        pytest.skip("Git is required for the source fixture")
    repo = tmp_path / "upstream"
    repo.mkdir()

    def run(*args):
        return subprocess.check_output([git, "-C", str(repo), *args], stderr=subprocess.DEVNULL)

    run("init", "-b", "main")
    run("config", "user.name", "Fixture")
    run("config", "user.email", "fixture@example.invalid")
    (repo / "pyproject.toml").write_text('[project]\nversion="0.4.29"\n')
    (repo / "backend").mkdir()
    (repo / "backend" / "example.py").write_text("CHECKED_COMMIT = True\n")
    (repo / "private-note").write_text("must-not-enter-normalized-source")
    run("add", ".")
    run("commit", "-m", "checked")
    first = run("rev-parse", "HEAD").decode().strip()
    actual_run = access._run
    requests = []

    def local_transport(args, *arguments, **keywords):
        requests.append(list(args))
        rewritten = [
            str(repo) if arg == f"git@github.com:{REPOSITORY}.git" else arg for arg in args
        ]
        # Test-only override. Production transport explicitly disables local paths.
        return actual_run(["-c", "protocol.file.allow=always", *rewritten], *arguments, **keywords)

    monkeypatch.setattr(access, "_run", local_transport)
    checked = asyncio.run(GitHubSourceProvider("0.4.29", source_access=access).check(REPOSITORY))
    assert checked["latestCommit"] == first
    assert checked["privateAccessConfigured"] is True
    (repo / "backend" / "example.py").write_text("WRONG_NEW_COMMIT = True\n")
    run("add", ".")
    run("commit", "-m", "main moved")
    assert run("rev-parse", "HEAD").decode().strip() != first
    downloaded, normalized = tmp_path / "download.tar.gz", tmp_path / "source.tar.gz"
    asyncio.run(download_source(None, REPOSITORY, first, downloaded, None, source_access=access))
    digest = normalize_source(downloaded, normalized)
    assert len(digest) == 64
    with tarfile.open(normalized, "r:gz") as archive:
        assert (
            archive.extractfile("mediahub-source/backend/example.py").read()
            == b"CHECKED_COMMIT = True\n"
        )
        assert all("private-note" not in name for name in archive.getnames())
    fetches = [args for args in requests if args[0] == "fetch"]
    assert len(fetches) == 2 and all(args[-1] == first for args in fetches)
    assert list(access.cache.iterdir()) == []


def test_invalid_commit_ref_is_rejected_before_loading_credentials(access, monkeypatch, tmp_path):
    monkeypatch.setattr(access, "_environment", lambda: pytest.fail("Commit must be a full SHA"))
    with pytest.raises(DomainError):
        asyncio.run(access.archive(REPOSITORY, "main", tmp_path / "archive"))
