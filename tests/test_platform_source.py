import asyncio
import base64
import io
import tarfile

import httpx
import pytest
from mediahub.errors import DomainError
from mediahub.platform_source import GitHubSourceProvider, download_source, normalize_source

COMMIT = "a" * 40


@pytest.mark.parametrize("installed,available", [("b" * 40, True), (COMMIT, False), (None, True)])
def test_main_updates_do_not_require_version_change_or_release(installed, available):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": COMMIT})
        assert request.url.params["ref"] == COMMIT
        return httpx.Response(
            200,
            json={
                "encoding": "base64",
                "content": base64.b64encode(b'[project]\nversion="0.4.29"').decode(),
            },
        )

    result = asyncio.run(
        GitHubSourceProvider("0.4.29", installed, httpx.MockTransport(handle)).check("owner/repo")
    )
    assert result["updateAvailable"] is available
    assert result["latestCommit"] == COMMIT
    assert result["latestVersion"] == "0.4.29"
    assert len(calls) == 2 and all("releases" not in call for call in calls)


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_failed_checks_never_report_up_to_date(status):
    with pytest.raises(DomainError):
        asyncio.run(
            GitHubSourceProvider(
                "0.4.29", transport=httpx.MockTransport(lambda r: httpx.Response(status))
            ).check("owner/repo")
        )


def test_private_token_stays_on_api_host(tmp_path):
    def handle(request):
        if request.url.host == "api.github.com":
            assert request.url.path.endswith(COMMIT)
            assert request.headers["Authorization"] == "Bearer secret"
            return httpx.Response(
                302,
                headers={
                    "Location": f"https://codeload.github.com/owner/repo/legacy.tar.gz/{COMMIT}?token=temporary"
                },
            )
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=b"archive")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            await download_source(client, "owner/repo", COMMIT, tmp_path / "source", "secret")

    asyncio.run(run())
    assert (tmp_path / "source").read_bytes() == b"archive"


@pytest.mark.parametrize(
    "url",
    [
        "http://codeload.github.com/owner/repo/legacy.tar.gz/" + COMMIT,
        "https://evil.example/archive",
        "https://codeload.github.com/other/repo/legacy.tar.gz/" + COMMIT,
        "https://codeload.github.com/owner/repo/legacy.tar.gz/main",
    ],
)
def test_archive_redirect_must_keep_pinned_repository_and_commit(tmp_path, url):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={"Location": url}))
        ) as client:
            await download_source(client, "owner/repo", COMMIT, tmp_path / "source", "secret")

    with pytest.raises(DomainError):
        asyncio.run(run())


def make_archive(path, unsafe=None):
    with tarfile.open(path, "w:gz") as archive:
        for name in [
            "repo-123/backend/main.py",
            "repo-123/.github/workflows/ci.yml",
            "repo-123/scripts/install.py",
        ]:
            member = tarfile.TarInfo(name)
            member.size = 4
            archive.addfile(member, io.BytesIO(b"test"))
        if unsafe:
            member = tarfile.TarInfo(unsafe)
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            archive.addfile(member)


def test_archive_only_retains_build_inputs_and_normalizes_root(tmp_path):
    source = tmp_path / "raw.tar.gz"
    output = tmp_path / "source.tar.gz"
    make_archive(source)
    assert len(normalize_source(source, output)) == 64
    with tarfile.open(output) as archive:
        assert archive.getnames() == ["mediahub-source/backend/main.py"]


@pytest.mark.parametrize("path", ["repo-123/backend/link", "repo-123/../escape", "/absolute"])
def test_unsafe_archive_entries_rejected(tmp_path, path):
    make_archive(tmp_path / "raw", path)
    with pytest.raises(ValueError):
        normalize_source(tmp_path / "raw", tmp_path / "out")
