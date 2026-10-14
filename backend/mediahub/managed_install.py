"""Install only host-approved immutable app recipes; never accept Docker specs over HTTP."""

import asyncio
import hashlib
import json
import re
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from agent.install_files import read_json, save_json
from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.db import InstalledApp
from mediahub.errors import DomainError
from mediahub.managed_apps import PACKAGES

router = APIRouter(prefix="/managed-install", dependencies=[Depends(administrator)])


class ConfirmInstall(StrictModel):
    planDigest: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/prerequisites")
def prerequisites(request: Request):
    return result(services(request).app_dependencies.public())


@router.post("/prerequisites/retry", status_code=202)
async def retry_prerequisites(request: Request):
    service = services(request).app_dependencies
    if not service.task or service.task.done():
        service.start()
    return result(service.public())


class ManagedInstaller:
    def __init__(self, svc):
        self.svc = svc
        self.manager = svc.managed_apps

    def journal(self, package):
        return self.svc.config.data_dir / (
            "managed-install-" + package.rsplit(".", 1)[-1] + ".json"
        )

    def recipe(self, package):
        if package not in PACKAGES:
            raise DomainError("not_found", "App is not supported", 404)
        policy = self.manager.policy.get(package)
        if not policy or not policy.installFile:
            raise DomainError(
                "install_host_required", "This host has not prepared the app installer", 409
            )
        value = read_json(policy.installFile)
        if (
            value.get("installationId") != policy.installationId
            or value.get("packageId") != package
            or not 1 <= len(value.get("containers", [])) <= 8
        ):
            raise DomainError("install_policy_changed", "App installation policy is invalid", 409)
        names = set()
        for item in value["containers"]:
            spec = item["spec"]
            if (
                not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,100}", item["name"])
                or item["name"] in names
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", spec.get("Image", ""))
                or spec.get("Labels", {}).get("com.docker.compose.project") != policy.project
            ):
                raise DomainError(
                    "install_policy_changed", "App installation ownership is invalid", 409
                )
            names.add(item["name"])
        if not self.svc.config.sso_app_urls.get(package):
            raise DomainError(
                "install_sso_required", "Register the app HTTPS address before installation", 409
            )
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        return value, digest

    def status(self, package):
        path = self.journal(package)
        return read_json(path) if path.exists() else {"state": "idle"}

    async def plan(self, package):
        removal = self.manager.saved(package) if package in self.manager.policy else None
        if removal and removal.get("state") != "succeeded":
            raise DomainError("removal_incomplete", "Complete app removal and configuration reset before reinstalling", 409)
        dependencies = getattr(self.svc, "app_dependencies", None)
        if dependencies:
            dependencies.require_ready()
        recipe, digest = self.recipe(package)
        for item in recipe["containers"]:
            await self.manager.docker("GET", "/images/" + item["spec"]["Image"] + "/json")
            for volume in item.get("volumes", []):
                # A missing data volume must not silently become an empty library.
                await self.manager.docker("GET", "/volumes/" + quote(volume, safe=""))
            for network in item.get("networks", []):
                await self.manager.docker("GET", "/networks/" + quote(network, safe=""))
        rows = await self.manager.containers(package)
        return {
            "planDigest": digest,
            "name": PACKAGES[package],
            "alreadyRunning": bool(rows) and all(row["State"].get("Running") for row in rows),
            "dataPreserved": True,
            "operation": self.status(package),
        }

    async def install(self, package, digest):
        async with self.manager.lock:
            active = self.manager.tasks.get(package)
            if active and not active.done():
                raise DomainError("operation_busy", "Another app operation is running", 409)
            plan = await self.plan(package)
            if digest != plan["planDigest"]:
                raise DomainError("install_plan_changed", "Review the app installation again", 409)
            job = {
                "state": "accepted",
                "operationId": uuid4().hex,
                "progress": 0,
                "phase": "preparing",
                "message": "App installation accepted",
                "planDigest": digest,
                "dataPreserved": True,
            }
            save_json(self.journal(package), job)
            self.manager.tasks[package] = asyncio.create_task(self.run(package))
            return job

    async def initialize(self):
        for package in self.manager.policy:
            if self.status(package).get("state") in {"accepted", "running"}:
                active = self.manager.tasks.get(package)
                if not active or active.done():
                    self.manager.tasks[package] = asyncio.create_task(self.run(package))

    async def run(self, package):
        previous = self.status(package)
        approved = previous.get("planDigest")
        job = {
            "state": "running",
            "operationId": previous.get("operationId"),
            "progress": 5,
            "phase": "preparing",
            "message": "Preparing installation",
            "dataPreserved": True,
            "planDigest": approved,
        }
        save_json(self.journal(package), job)
        try:
            async with self.manager.lock:
                recipe, current = self.recipe(package)
                if approved and approved != current:
                    raise DomainError(
                        "install_plan_changed", "Review the app installation again", 409
                    )
                policy = self.manager.policy[package]
                job.update(phase="containers", progress=10, message="Starting app containers")
                save_json(self.journal(package), job)
                for index, item in enumerate(recipe["containers"]):
                    name = quote(item["name"], safe="")
                    container = await self.manager.docker(
                        "GET", "/containers/" + name + "/json", missing=True
                    )
                    if container:
                        expected = item["spec"]
                        actual = container.get("Config", {})
                        same_config = all(
                            actual.get(key) == expected.get(key)
                            for key in ("User", "Cmd", "Entrypoint", "WorkingDir")
                        )
                        same_config = same_config and sorted(actual.get("Env") or []) == sorted(
                            expected.get("Env") or []
                        )
                        same_mounts = all(
                            container.get("HostConfig", {}).get(key)
                            == expected.get("HostConfig", {}).get(key)
                            for key in (
                                "Binds",
                                "Mounts",
                                "Privileged",
                                "NetworkMode",
                                "PortBindings",
                                "ReadonlyRootfs",
                                "Devices",
                            )
                        )
                        if (
                            container.get("Config", {})
                            .get("Labels", {})
                            .get("com.docker.compose.project")
                            != policy.project
                            or container.get("Image") != item["spec"]["Image"]
                            or not same_config
                            or not same_mounts
                            or any(
                                actual.get("Labels", {}).get(key) != value
                                for key, value in expected["Labels"].items()
                            )
                        ):
                            raise DomainError(
                                "installation_changed",
                                "Existing app container ownership or image differs",
                                409,
                            )
                    else:
                        await self.manager.docker(
                            "POST", "/containers/create?name=" + name, body=item["spec"]
                        )
                    if not container or not container["State"].get("Running"):
                        await self.manager.docker("POST", "/containers/" + name + "/start")
                    job.update(progress=10 + round(60 * (index + 1) / len(recipe["containers"])))
                    save_json(self.journal(package), job)
                job.update(phase="health", progress=75, message="Checking app health")
                save_json(self.journal(package), job)
                for _ in range(45):
                    rows = await self.manager.containers(package)
                    if len(rows) >= len(recipe["containers"]) and all(
                        r["State"].get("Running")
                        and r["State"].get("Health", {}).get("Status", "healthy") == "healthy"
                        for r in rows
                    ):
                        break
                    if any(r["State"].get("Health", {}).get("Status") == "unhealthy" for r in rows):
                        raise DomainError(
                            "install_health_failed",
                            "App health check failed; app data was preserved",
                            409,
                        )
                    await asyncio.sleep(2)
                else:
                    raise DomainError(
                        "install_health_timeout",
                        "App did not become healthy; app data was preserved",
                        409,
                    )
                job.update(
                    phase="registering", progress=95, message="Registering app and hub login"
                )
                save_json(self.journal(package), job)
                self.manager.journal(package).unlink(missing_ok=True)
                with self.svc.sessions.begin() as db:
                    app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package))
                    if app is None:
                        app = InstalledApp(
                            package_id=package,
                            name=PACKAGES[package],
                            version="managed",
                            is_mock=False,
                        )
                        db.add(app)
                    app.state = "running"
                await self.manager.initialize()
                job.update(
                    state="succeeded",
                    phase="complete",
                    progress=100,
                    message="App installed and running",
                )
                self.svc.events.record(
                    "app.installed", package, "Managed app installed; persistent data preserved"
                )
        except DomainError as error:
            job.update(state="failed", message=error.message)
        except asyncio.CancelledError:
            raise
        except Exception:
            job.update(state="failed", message="App installation failed; app data was preserved")
        save_json(self.journal(package), job)


@router.get("/{package}")
async def plan(package: str, request: Request):
    return result(await services(request).managed_installer.plan(package))


@router.post("/{package}", status_code=202)
async def install(package: str, body: ConfirmInstall, request: Request):
    if request.url.scheme != "https":
        raise DomainError("https_required", "Use HTTPS to install apps", 403)
    return result(await services(request).managed_installer.install(package, body.planDigest))
