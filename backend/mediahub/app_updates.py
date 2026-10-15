"""Independent first-party source updates using the approved host preparation path."""

import asyncio
import json
import tarfile
import time
import tomllib
from pathlib import PurePosixPath
from uuid import uuid4

import httpx
from packaging.version import Version

from agent.install_files import save_json
from mediahub.errors import DomainError
from mediahub.platform_source import SHA, GitHubSourceProvider, download_source

REPOSITORIES = {"mediaseed": "miklas206/mediaseed", "mediavpn": "miklas206/mediavpn"}


def extract_app(archive, destination, kind, expected_version):
    """Only regular, bounded application build inputs; never archive links/paths."""
    allowed = {
        kind,
        "Dockerfile",
        "pyproject.toml",
        ".dockerignore",
        "compose.yaml",
        "compose.hub.yaml",
        "compose.runtime.yaml",
        "compose.vpn.yaml",
        "hub-proxy.yaml",
    }
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    total, seen = 0, set()
    with tarfile.open(archive, "r:gz") as source:
        for index, member in enumerate(source):
            path = PurePosixPath(member.name)
            if (
                index > 20000
                or "\\" in member.name
                or path.is_absolute()
                or ".." in path.parts
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsafe app archive")
            relative = PurePosixPath(*path.parts[1:])
            if not relative.parts or relative.parts[0] not in allowed or member.isdir():
                continue
            total += member.size
            if (
                not member.isfile()
                or member.size > 32 * 1024**2
                or total > 256 * 1024**2
                or relative in seen
            ):
                raise ValueError("Invalid app archive")
            seen.add(relative)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, target.open("xb") as output:
                output.write(incoming.read())
            target.chmod(0o644)
    metadata = tomllib.loads((destination / "pyproject.toml").read_text())["project"]
    if (
        metadata["name"] != kind
        or metadata["version"] != expected_version
        or not (destination / "Dockerfile").is_file()
    ):
        raise ValueError("App source identity changed")


class AppUpdates:
    def __init__(self, manager):
        self.manager = manager
        self.tasks = {}
        self.start_lock = asyncio.Lock()

    def path(self, kind):
        if kind not in REPOSITORIES:
            raise ValueError("Unsupported app")
        return self.manager.svc.config.data_dir / "app-updates" / kind / "operation.json"

    def operation(self, kind):
        path = self.path(kind)
        return json.loads(path.read_text()) if path.is_file() else {"state": "idle", "progress": 0}

    async def check(self, adapter):
        kind = adapter.package.rsplit(".", 1)[-1]
        local = await adapter.installed_version()
        rows = await self.manager.containers(adapter.package)
        apps = [
            row
            for row in rows
            if row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "app"
        ]
        labels = apps[0]["Config"]["Labels"] if len(apps) == 1 else {}
        installed = local["installedVersion"]
        valid_installed = installed if installed and installed != "managed" else None
        try:
            result = await GitHubSourceProvider(
                valid_installed or "0.0.0",
                labels.get("org.mediahub.app.commit"),
                metadata_cache=getattr(
                    getattr(self.manager.svc, "updates", None), "github_metadata", None
                ),
            ).check(REPOSITORIES[kind], self.manager.svc.release_credentials.token())
        except DomainError as error:
            return {
                **local,
                "repository": REPOSITORIES[kind],
                "supported": True,
                "latestVersion": None,
                "updateAvailable": False,
                "installReady": False,
                "checkStatus": "deferred" if getattr(error, "retry_at", None) else "failed",
                "errorCode": error.code,
                "message": error.message,
                **({"retryAt": error.retry_at} if getattr(error, "retry_at", None) else {}),
            }
        local = await adapter.installed_version()
        installed = local["installedVersion"]
        valid_installed = installed if installed and installed != "managed" else None
        latest = result.get("latestVersion")
        available = bool(
            latest
            and (
                not valid_installed
                or Version(latest) > Version(valid_installed)
                or (
                    Version(latest) == Version(valid_installed)
                    and labels.get("org.mediahub.app.commit")
                    and result["updateAvailable"]
                )
            )
        )
        return {
            **result,
            **local,
            "supported": True,
            "checkStatus": "checked",
            "updateAvailable": available,
            "installReady": available and local.get("preparationState", "ready") == "ready",
            "message": "This app updates independently from MediaHub Core.",
        }

    async def start(self, adapter, checked):
        async with self.start_lock:
            return await self._start(adapter, checked)

    async def _start(self, adapter, checked):
        kind = adapter.package.rsplit(".", 1)[-1]
        if kind in self.tasks and not self.tasks[kind].done():
            raise DomainError("app_update_busy", "This app already has an active update", 409)
        previous = await self.status(adapter)
        if previous.get("state") == "running":
            raise DomainError("app_update_busy", "This app already has an active update", 409)
        self.manager.svc.app_dependencies.require_ready()
        if (
            not checked.get("updateAvailable")
            or checked.get("repository") != REPOSITORIES[kind]
            or not SHA.fullmatch(checked.get("latestCommit") or "")
        ):
            raise DomainError(
                "app_update_unverified", "Check this app's own repository before updating", 409
            )
        job = {
            "operationId": uuid4().hex,
            "state": "running",
            "progress": 5,
            "message": "Downloading the selected app's pinned source",
            "repository": checked["repository"],
            "commit": checked["latestCommit"],
            "toVersion": checked["latestVersion"],
            "startedAt": time.time(),
        }
        self.path(kind).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        save_json(self.path(kind), job)
        self.tasks[kind] = asyncio.create_task(self.run(adapter, job))
        return job

    async def status(self, adapter):
        kind = adapter.package.rsplit(".", 1)[-1]
        job = self.operation(kind)
        if job.get("state") not in {"running", "interrupted"} or (
            kind in self.tasks and not self.tasks[kind].done()
        ):
            return job
        helper = await self.manager.docker(
            "GET", "/containers/mediahub-app-dependencies/json", missing=True
        )
        owned_helper = helper and helper.get("Config", {}).get("Labels", {}).get(
            "org.mediahub.app-update"
        ) == job.get("operationId")
        if owned_helper and helper.get("State", {}).get("Running"):
            return {**job, "state": "running"}
        rows = await self.manager.containers(adapter.package)
        matching = [
            row
            for row in rows
            if row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "app"
            and row["Config"]["Labels"].get("org.mediahub.app.commit") == job.get("commit")
        ]
        if (
            len(matching) == 1
            and matching[0]["Config"]["Labels"].get("org.mediahub.app.version")
            == job.get("toVersion")
            and (not owned_helper or helper.get("State", {}).get("ExitCode") == 0)
        ):
            job.update(
                state="succeeded",
                progress=100,
                message="Selected app update verified after Core restart",
            )
        else:
            job.update(
                state="interrupted",
                message="App update was interrupted; inspect its runtime before retrying",
            )
        save_json(self.path(kind), job)
        return job

    async def run(self, adapter, job):
        kind = adapter.package.rsplit(".", 1)[-1]
        path = self.path(kind)
        try:
            async with self.manager.lock:
                stage = path.parent / job["operationId"]
                stage.mkdir(mode=0o700)
                archive = stage / "source.tar.gz"
                async with httpx.AsyncClient(
                    timeout=45, follow_redirects=False, trust_env=False
                ) as client:
                    await download_source(
                        client,
                        job["repository"],
                        job["commit"],
                        archive,
                        self.manager.svc.release_credentials.token(),
                    )
                source = stage / "source"
                await asyncio.to_thread(extract_app, archive, source, kind, job["toVersion"])
                job.update(
                    progress=30, message="Building only the selected app; existing data retained"
                )
                save_json(path, job)
                dependencies = self.manager.svc.app_dependencies
                await dependencies._run(
                    update={
                        "kind": kind,
                        "source": source.relative_to(self.manager.svc.config.data_dir).as_posix(),
                        "commit": job["commit"],
                        "repository": job["repository"],
                        "operationId": job["operationId"],
                    }
                )
                if dependencies.message:
                    raise DomainError("app_update_failed", dependencies.message, 409)
                rows = await self.manager.containers(adapter.package)
                apps = [
                    r
                    for r in rows
                    if r.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
                    == "app"
                ]
                if (
                    len(apps) != 1
                    or apps[0]["Config"]["Labels"].get("org.mediahub.app.version")
                    != job["toVersion"]
                    or apps[0]["Config"]["Labels"].get("org.mediahub.app.commit") != job["commit"]
                ):
                    raise DomainError(
                        "app_update_version_unverified",
                        "The selected app version could not be verified",
                        409,
                    )
                job.update(
                    state="succeeded",
                    progress=100,
                    message="Selected app updated; MediaHub Core and the other app retained",
                )
        except (
            DomainError,
            OSError,
            ValueError,
            KeyError,
            tarfile.TarError,
            httpx.HTTPError,
        ) as error:
            job.update(
                errorCode=error.code if isinstance(error, DomainError) else type(error).__name__,
                state="failed",
                message="App update failed. Existing data retained; check app runtime before retrying.",
            )
        except asyncio.CancelledError:
            job.update(
                state="interrupted",
                message="Core stopped during app update; inspect the retained helper before retrying",
            )
            raise
        finally:
            save_json(path, job)
