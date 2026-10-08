import json
import subprocess
import tarfile

import pytest

from scripts.source_release import package


def source_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    for name in ("backend", "agent", "apps", "frontend", "docker"):
        directory = repo / name
        directory.mkdir()
        (directory / "tracked.txt").write_text("tracked source")
    for name in ("requirements.lock", "README.md", "LICENSE", "alembic.ini", ".dockerignore"):
        (repo / name).write_text("example")
    (repo / "pyproject.toml").write_text('[project]\nversion="0.5.0"\n')
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Source test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "source fixture",
        ],
        check=True,
    )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    (repo / "frontend" / "private-untracked.env").write_text("not for packaging")
    (repo / ".env").write_text("not for packaging")
    return repo, revision


def test_source_package_uses_exact_commit_and_excludes_untracked_files(tmp_path, monkeypatch):
    repo, revision = source_repo(tmp_path, monkeypatch)
    # Local tracked edits are excluded too; the published commit is authoritative.
    (repo / "pyproject.toml").write_text('[project]\nversion="9.9.9"\n')
    output = tmp_path / "release"
    manifest = package("example/mediahub", revision, output, "v0.5.0")
    assert manifest["source"]["commit"] == revision
    assert manifest["version"] == "0.5.0"
    with tarfile.open(output / "mediahub-source.tar.gz") as archive:
        names = archive.getnames()
        assert not any(".env" in name or "private-untracked" in name for name in names)
        assert (
            archive.extractfile("mediahub-source/pyproject.toml").read().replace(b"\r\n", b"\n")
            == b'[project]\nversion="0.5.0"\n'
        )
    assert json.loads((output / "mediahub-source-release.json").read_text()) == manifest


def test_source_package_rejects_mismatching_release_tag(tmp_path, monkeypatch):
    _, revision = source_repo(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="tag must match"):
        package("example/mediahub", revision, tmp_path / "release", "v0.6.0")
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize(
    "repository,revision", [("https://github.com/owner/repo", "a" * 40), ("owner/repo", "main")]
)
def test_source_package_rejects_unbounded_identity(tmp_path, repository, revision):
    with pytest.raises(ValueError):
        package(repository, revision, tmp_path / "release")
