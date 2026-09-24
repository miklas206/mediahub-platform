"""Owned Plex runtime provisioning with encrypted preferences and RAM-only secrets.

The installer accepts logical choices only. Host paths, identities and image
digests come from local operator policy, never from an HTTP caller.
"""

import asyncio
import contextlib
import hashlib
import io
import json
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from mediahub.apps.plex import PlexInstallRequest
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore

from agent.install_files import read_json, save_json
from agent.plex_control import PlexMount, PlexPolicy
from agent.plex_install import PMS_ROOT, PlexInstallPolicy, installation_plan


class PlexRuntime:
    def __init__(self, control, install_policy_file, state_dir):
        self.control = control
        self.policy_file = install_policy_file
        self.state_dir = Path(state_dir)
        self.vault = SecretStore(self.state_dir / "plex-secrets")
        self.last_saved = None
        self.operation = {"state": "idle", "message": "No operation running"}
        self.update_task = None
        self.libraries_ready = False

    def policy(self):
        try:
            return PlexInstallPolicy.model_validate(read_json(Path(self.policy_file)))
        except (OSError, ValueError, TypeError):
            raise DomainError(
                "plex_install_disabled", "Plex installation is not configured", 409
            ) from None

    async def request(self, method, path, *, body=None, payload=None, binary=False):
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(self.control.socket)),
                base_url="http://docker",
                timeout=15 if method == "GET" else 60,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    json=body,
                    content=payload,
                    headers={"Content-Type": "application/x-tar"} if payload else None,
                )
                response.raise_for_status()
                if len(response.content) > 4 * 1024**2:
                    raise ValueError()
                return response.content if binary else response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise DomainError(
                "plex_provision_failed", "Plex runtime operation failed", 503
            ) from None

    async def options(self):
        policy = self.policy()
        return {
            "hostId": policy.hostId,
            "storage": [
                {"id": key, "label": item.label, "kind": item.kind}
                for key, item in policy.storage.items()
            ],
        }

    async def ensure_libraries(self, policy):
        if self.libraries_ready:
            return
        plan = read_json(self.state_dir / "plex-plan.json")
        sections = await self.control.plex_get(policy, "/library/sections")
        existing = {
            tuple(sorted(loc.get("path", "") for loc in section.findall("Location")))
            for section in sections.findall("Directory")
        }
        defaults = {
            "movies": ("Movies", "movie", "Plex Movie", "tv.plex.agents.movie"),
            "tv": ("TV Shows", "show", "Plex TV Series", "tv.plex.agents.series"),
            "other": ("Other Media", "movie", "Plex Video Files", "tv.plex.agents.none"),
        }
        for kind, paths in plan["libraries"].items():
            if not paths or tuple(sorted(paths)) in existing:
                continue
            name, media_type, scanner, agent = defaults[kind]
            params = [
                ("name", name),
                ("type", media_type),
                ("scanner", scanner),
                ("agent", agent),
                ("language", "en-US"),
                *(("location", path) for path in paths),
            ]
            await self.control.plex_get(policy, "/library/sections", "POST", params=params)
        self.libraries_ready = True
        self.control.record("libraries_ready")

    async def plan(self, spec):
        policy = self.policy()
        plan = installation_plan(policy, spec)
        # The detailed mount plan stays inside the Agent. No runtime config or
        # account material is returned to the browser.
        return {
            "planDigest": plan["planDigest"],
            "installation": spec.model_dump(),
            "mediaReadOnly": True,
            "preferencesEncrypted": True,
            "port": 32400,
        }

    async def archive_write(self, name, files, uid, gid):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for path, content in files.items():
                entry = tarfile.TarInfo(path)
                entry.size, entry.mode, entry.uid, entry.gid = len(content), 0o600, uid, gid
                archive.addfile(entry, io.BytesIO(content))
        await self.request(
            "PUT", f"/containers/{name}/archive?path=/config", payload=stream.getvalue()
        )

    async def preferences(self, policy):
        inspected = await self.request("GET", f"/containers/{policy.container}/json")
        if not inspected.get("State", {}).get("Running"):
            raise DomainError(
                "plex_stopped", "Plex is stopped; encrypted preferences retained", 409
            )
        # Docker's archive endpoint remounts every bind, which is prohibited for
        # read-only media binds inside an unprivileged LXC. Read the RAM file in
        # the owned container instead. No secret appears in argv or Docker logs.
        execution = await self.request(
            "POST",
            f"/containers/{policy.container}/exec",
            body={
                "AttachStdout": True,
                "AttachStderr": False,
                "Cmd": ["/bin/cat", PMS_ROOT + "/Preferences.xml"],
            },
        )
        data = await self.request(
            "POST",
            "/exec/" + execution["Id"] + "/start",
            body={"Detach": False, "Tty": False},
            binary=True,
        )
        status = await self.request("GET", "/exec/" + execution["Id"] + "/json")
        try:
            if status.get("ExitCode") != 0:
                raise ValueError()
            chunks = []
            while data:
                if len(data) < 8 or data[0] != 1:
                    raise ValueError()
                size = int.from_bytes(data[4:8], "big")
                if size > len(data) - 8:
                    raise ValueError()
                chunks.append(data[8 : 8 + size])
                data = data[8 + size :]
            content = b"".join(chunks)
            if len(content) > 131072:
                raise ValueError()
            root = ET.fromstring(content)
            if root.tag != "Preferences":
                raise ValueError()
            return content
        except (ValueError, ET.ParseError, tarfile.TarError, OSError):
            raise DomainError(
                "plex_preferences_invalid", "Plex preferences are unavailable", 503
            ) from None

    async def checkpoint(self, policy):
        content = await self.preferences(policy)
        fingerprint = hashlib.sha256(content).digest()
        if fingerprint != self.last_saved:
            key = policy.installationId
            if self.vault.status(key)["configured"]:
                self.vault.replace(key, content)
            else:
                self.vault.put(key, content)
            self.last_saved = fingerprint

    async def helper(self, policy, plan, initialize=False):
        name = plan["name"] + "-prepare"
        labels = plan["container"]["Labels"]
        # Never overwrite an unrelated container with the same name.
        listing = await self.request("GET", "/containers/json?all=1")
        if any("/" + name in row.get("Names", []) for row in listing):
            raise DomainError(
                "plex_prepare_exists", "Previous Plex preparation requires recovery", 409
            )
        code = (
            "import pathlib,os,time,json; "
            "assert pathlib.Path('/sys/fs/cgroup/memory.swap.max').read_text().strip()=='0', 'Swap must be disabled'; "
            "p=pathlib.Path('/config/Library/Application Support/Plex Media Server'); "
            "p.mkdir(parents=True,exist_ok=True); "
            f"os.chown('/config',{policy.uid},{policy.gid}); "
            f"os.chown(p,{policy.uid},{policy.gid}); "
        )
        mounts = [plan["container"]["HostConfig"]["Mounts"][0]]
        if initialize:
            appdata = policy.storage[plan["installation"]["appdataStorageId"]].path
            mounts.append(
                {"Type": "bind", "Source": appdata, "Target": "/appdata", "ReadOnly": False}
            )
            from agent.plex_install import PERSISTENT_DIRECTORIES

            # mkdir without exist_ok claims a new directory, preventing accidental
            # adoption/chown of existing application or media data.
            code += (
                f"r=pathlib.Path('/appdata')/{plan['installation']['installationId']!r}; "
                f"r.mkdir(mode=0o750); os.chown(r,{policy.uid},{policy.gid}); "
                f"[( (r/d).mkdir(mode=0o750),os.chown(r/d,{policy.uid},{policy.gid})) "
                f"for d in {PERSISTENT_DIRECTORIES!r}]; "
            )
        code += "pathlib.Path('/config/.prepared').touch(mode=0o600); time.sleep(180)"
        await self.request(
            "POST",
            "/containers/create?name=" + name,
            body={
                "Image": policy.initImage,
                "Labels": labels,
                "User": "0:0",
                "Entrypoint": ["python", "-c", code],
                "HostConfig": {
                    "Mounts": mounts,
                    "NetworkMode": "none",
                    "Memory": 128 * 1024**2,
                    "MemorySwap": 128 * 1024**2,
                    "PidsLimit": 32,
                    "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                    "LogConfig": {"Type": "none", "Config": {}},
                },
            },
        )
        try:
            await self.request("POST", f"/containers/{name}/start")
        except DomainError:
            await self.remove_helper(name)
            raise
        for _ in range(30):
            try:
                await self.request(
                    "GET", f"/containers/{name}/archive?path=/config/.prepared", binary=True
                )
                return name
            except DomainError:
                await asyncio.sleep(0.2)
        await self.remove_helper(name)
        raise DomainError(
            "plex_prepare_failed", "Plex configuration directory could not be prepared", 409
        )

    async def remove_helper(self, name):
        with contextlib.suppress(DomainError):
            await self.request("POST", f"/containers/{name}/stop?t=2")
            await self.request("DELETE", f"/containers/{name}")

    async def install(self, body: PlexInstallRequest):
        async with self.control.lock:
            policy = self.policy()
            plan = installation_plan(policy, body.installation)
            if plan["planDigest"] != body.reviewedPlanDigest:
                raise DomainError(
                    "plex_plan_changed", "Review the current installation plan first", 409
                )
            if Path(self.control.policy_file).exists():
                raise DomainError(
                    "plex_already_installed", "Managed Plex is already installed", 409
                )
            guard = PlexPolicy(
                hostId=policy.hostId,
                container=plan["name"],
                imageId="sha256:" + "0" * 64,
                installationId=body.installation.installationId,
                preferencesPath="",
                mounts=[],
                storageMarkers=policy.storageMarkers,
                hostMountSnapshot=policy.hostMountSnapshot,
                requiredMounts=policy.requiredMounts,
                requiredFilesystemUuids=policy.requiredFilesystemUuids,
            )
            if not await self.control.storage_verified(guard):
                raise DomainError(
                    "storage_unavailable",
                    "Media storage is not verified; installation blocked",
                    409,
                )
            # Image must have been pulled by the controlled operator/update path.
            image = await self.request("GET", "/images/" + policy.image + "/json")
            existing = await self.request("GET", "/volumes")
            if any(
                v["Name"] == plan["runtimeVolume"]["Name"] for v in existing.get("Volumes") or []
            ):
                raise DomainError(
                    "plex_volume_exists", "Existing runtime volume requires recovery", 409
                )
            await self.request("POST", "/volumes/create", body=plan["runtimeVolume"])
            helper = await self.helper(policy, plan, initialize=True)
            try:
                root = ET.Element(
                    "Preferences",
                    FriendlyName=body.installation.serverName,
                    PublishServerOnPlexOnlineKey="0",
                    ManualPortMappingMode="1",
                )
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                if policy.reuseEncryptedPreferences:
                    content = self.vault.get(body.installation.installationId)
                    if ET.fromstring(content).tag != "Preferences":
                        raise DomainError(
                            "plex_identity_invalid", "Encrypted Plex identity is invalid", 409
                        )
                else:
                    self.vault.put(body.installation.installationId, content)
                files = {
                    "Library/Application Support/Plex Media Server/Preferences.xml": content,
                    ".claim": body.claimToken.get_secret_value().encode()
                    if body.claimToken
                    else b"",
                }
                await self.archive_write(helper, files, policy.uid, policy.gid)
                await self.request(
                    "POST", "/containers/create?name=" + plan["name"], body=plan["container"]
                )
                guard.imageId = image["Id"]
                guard.apiUrl = f"http://{policy.bindAddress}:32400"
                guard.apiNetwork = policy.controlNetwork
                guard.controlStatePath = str(self.state_dir / "plex-intent.json")
                # Docker resolves named volumes to a host mountpoint. Capture the
                # exact actual mount set once, then enforce it for every action.
                inspected = await self.request("GET", f"/containers/{plan['name']}/json")
                guard.mounts = [
                    PlexMount(source=m["Source"], target=m["Destination"], readOnly=not m["RW"])
                    for m in inspected["Mounts"]
                ]
                save_json(self.state_dir / "plex-plan.json", plan)
                save_json(Path(self.control.policy_file), guard.model_dump())
                self.control.save_intent(guard, True)
                await self.request("POST", f"/containers/{plan['name']}/start")
                self.control.record("installed")
                return {
                    "state": "accepted",
                    "installationId": guard.installationId,
                    "message": "Plex started; account claim and library readiness are being checked",
                }
            finally:
                await self.remove_helper(helper)

    async def start(self, policy):
        """Restore encrypted preferences before the only container start path."""
        if not await self.control.storage_verified(policy):
            raise DomainError(
                "storage_unavailable", "Media storage is unavailable; Plex start blocked", 409
            )
        plan = read_json(self.state_dir / "plex-plan.json")
        install_policy = self.policy()
        helper = await self.helper(install_policy, plan)
        try:
            content = self.vault.get(policy.installationId)
            await self.archive_write(
                helper,
                {
                    "Library/Application Support/Plex Media Server/Preferences.xml": content,
                    ".claim": b"",
                },
                install_policy.uid,
                install_policy.gid,
            )
            await self.request("POST", f"/containers/{policy.container}/start")
        finally:
            await self.remove_helper(helper)

    async def stop(self, policy):
        # Keep the RAM volume alive through Plex's final preference flush. A
        # checkpoint failure must NEVER prevent stopping an unsafe container.
        helper = None
        with contextlib.suppress(DomainError, OSError, ValueError):
            await self.checkpoint(policy)
            helper = await self.helper(self.policy(), read_json(self.state_dir / "plex-plan.json"))
        try:
            await self.request("POST", f"/containers/{policy.container}/stop?t=30")
            if helper:
                from types import SimpleNamespace

                with contextlib.suppress(DomainError, OSError, ValueError):
                    content = await self.preferences(SimpleNamespace(container=helper))
                    self.vault.replace(policy.installationId, content)
                    self.last_saved = hashlib.sha256(content).digest()
        finally:
            if helper:
                await self.remove_helper(helper)

    async def update(self):
        if self.update_task and not self.update_task.done():
            raise DomainError("plex_busy", "A Plex update is already running", 409)
        # Validate ownership before admitting a background operation.
        await self.control.inspect(self.control.policy())
        self.operation = {"state": "running", "message": "Checking the image publisher"}
        self.update_task = asyncio.create_task(self._update())
        return self.operation

    async def pull_image(self):
        # Fixed trusted repository; no user-controlled registry, tag or command.
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(self.control.socket)),
                base_url="http://docker",
                timeout=httpx.Timeout(600, connect=5),
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    "/images/create",
                    params={
                        "fromImage": "lscr.io/linuxserver/plex",
                        "tag": "latest",
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if len(line) > 65536 or (line and json.loads(line).get("error")):
                            raise ValueError()
            return await self.request("GET", "/images/lscr.io/linuxserver/plex:latest/json")
        except (httpx.HTTPError, ValueError):
            raise DomainError(
                "plex_update_download_failed", "Plex image could not be downloaded", 503
            ) from None

    async def snapshot_appdata(self, policy, plan):
        """Offline DB/config snapshot. Media and large rebuildable caches excluded."""
        import uuid

        name = plan["name"] + "-backup-" + uuid.uuid4().hex[:8]
        stamp = "before-update-" + uuid.uuid4().hex
        root = Path(plan["appdataPath"])
        code = (
            "import pathlib,shutil,os; r=pathlib.Path('/appdata'); "
            f"source=r/{root.name!r}; target=r/{stamp!r}; "
            "assert source.is_dir() and not source.is_symlink(); "
            "names=['Media','Metadata','Plug-ins','Plug-in Support','Scanners']; "
            "size=sum(p.stat().st_size for n in names for p in (source/n).rglob('*') if p.is_file()); "
            "assert shutil.disk_usage(r).free>size+1024**3, 'Insufficient rollback space'; "
            "assert not any(p.is_symlink() for n in names for p in (source/n).rglob('*')), 'Unsafe app-data link'; "
            "target.mkdir(mode=0o700); "
            "[shutil.copytree(source/n,target/n) for n in names]; "
            "os.sync()"
        )
        await self.request(
            "POST",
            "/containers/create?name=" + name,
            body={
                "Image": self.policy().initImage,
                "User": "0:0",
                "Labels": plan["container"]["Labels"],
                "Entrypoint": ["python", "-c", code],
                "HostConfig": {
                    "NetworkMode": "none",
                    "Mounts": [
                        {
                            "Type": "bind",
                            "Source": str(root.parent),
                            "Target": "/appdata",
                            "ReadOnly": False,
                        }
                    ],
                    "Memory": 128 * 1024**2,
                    "MemorySwap": 128 * 1024**2,
                    "LogConfig": {"Type": "none", "Config": {}},
                    "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                },
            },
        )
        try:
            await self.request("POST", f"/containers/{name}/start")
            for _ in range(600):
                state = (await self.request("GET", f"/containers/{name}/json"))["State"]
                if not state["Running"]:
                    if state["ExitCode"] != 0:
                        raise DomainError(
                            "plex_backup_failed",
                            "Plex rollback snapshot failed; update cancelled",
                            409,
                        )
                    return str(root.parent / stamp)
                await asyncio.sleep(1)
            raise DomainError("plex_backup_timeout", "Plex backup timed out; update cancelled", 503)
        finally:
            await self.remove_helper(name)

    async def _update(self):
        async with self.control.lock:
            stopped = False
            quiesced = False
            try:
                policy = self.control.policy()
                before = await self.control.inspect(policy)
                if not await self.control.storage_verified(policy):
                    raise DomainError(
                        "storage_unavailable", "Media disk is unavailable; update blocked", 409
                    )
                image = await self.pull_image()
                if image["Id"] == policy.imageId:
                    self.operation = {"state": "succeeded", "message": "Plex is already up to date"}
                    return
                digest = next(
                    d
                    for d in image.get("RepoDigests", [])
                    if d.startswith("lscr.io/linuxserver/plex@sha256:")
                )
                plan = read_json(self.state_dir / "plex-plan.json")
                self.operation = {
                    "state": "running",
                    "message": "Saving Plex configuration for rollback",
                }
                desired = self.control.intent(policy)
                self.control.save_intent(policy, False)
                quiesced = True
                if before["State"]["Running"]:
                    await self.stop(policy)
                    stopped = True
                backup = await self.snapshot_appdata(policy, plan)
                checkpoint = self.vault.get(policy.installationId)
                rollback_reference = policy.installationId + "-rollback"
                if self.vault.status(rollback_reference)["configured"]:
                    self.vault.replace(rollback_reference, checkpoint)
                else:
                    self.vault.put(rollback_reference, checkpoint)
                # Keep the old stopped container. The new image is tested before
                # deleting anything, and persistent media is never a delete target.
                old_name = policy.container + "-rollback"
                listing = await self.request("GET", "/containers/json?all=1")
                if any("/" + old_name in row.get("Names", []) for row in listing):
                    previous = read_json(self.state_dir / "plex-update-recovery.json")
                    old = await self.request("GET", f"/containers/{old_name}/json")
                    if (
                        old["State"]["Running"]
                        or old["Image"] != previous["oldImage"]
                        or any(
                            old["Config"].get("Labels", {}).get(k) != v
                            for k, v in plan["container"]["Labels"].items()
                        )
                    ):
                        raise DomainError(
                            "plex_rollback_conflict",
                            "Existing rollback runtime requires inspection",
                            409,
                        )
                    await self.request("DELETE", f"/containers/{old_name}")
                await self.request("POST", f"/containers/{policy.container}/rename?name={old_name}")
                new_plan = json.loads(json.dumps(plan))
                new_plan["container"]["Image"] = digest
                save_json(
                    self.state_dir / "plex-update-recovery.json",
                    {
                        "oldContainer": old_name,
                        "oldImage": policy.imageId,
                        "appdataSnapshot": backup,
                        "oldPlan": plan,
                        "desiredRunning": desired,
                    },
                )
                self.control.save_intent(policy, False)
                self.operation = {"state": "running", "message": "Starting the new Plex version"}
                await self.request(
                    "POST",
                    "/containers/create?name=" + policy.container,
                    body=new_plan["container"],
                )
                policy.imageId = image["Id"]
                save_json(Path(self.control.policy_file), policy.model_dump())
                save_json(self.state_dir / "plex-plan.json", new_plan)
                await self.start(policy)
                for _ in range(45):
                    try:
                        await self.control.plex_get(policy, "/identity")
                        break
                    except DomainError:
                        await asyncio.sleep(1)
                else:
                    raise DomainError(
                        "plex_update_not_ready",
                        "New Plex version did not become ready; rollback is available",
                        503,
                    )
                self.control.save_intent(policy, desired)
                if not desired:
                    await self.checkpoint(policy)
                    await self.request("POST", f"/containers/{policy.container}/stop?t=30")
                self.control.record("updated")
                self.operation = {
                    "state": "succeeded",
                    "message": "Plex updated; configuration rollback snapshot retained",
                }
            except (DomainError, OSError, ValueError, KeyError, StopIteration):
                # Do not repeatedly start a partially migrated database. A failed
                # update stays stopped pending the controlled rollback action.
                if quiesced:
                    with contextlib.suppress(DomainError, OSError, ValueError):
                        policy = self.control.policy()
                        self.control.save_intent(policy, False)
                        if stopped:
                            await self.request("POST", f"/containers/{policy.container}/stop?t=30")
                self.operation = {
                    "state": "failed",
                    "message": "Plex update failed. Media preserved; inspect rollback status before restarting.",
                }
                self.control.record("update_failed")

    async def rollback(self):
        async with self.control.lock:
            policy = self.control.policy()
            recovery = read_json(self.state_dir / "plex-update-recovery.json")
            plan = recovery["oldPlan"]
            root = Path(plan["appdataPath"])
            backup = Path(recovery["appdataSnapshot"])
            if (
                backup.parent != root.parent
                or not backup.name.startswith("before-update-")
                or plan["name"] != policy.container
            ):
                raise DomainError("plex_rollback_invalid", "Rollback metadata is invalid", 409)
            if not await self.control.storage_verified(policy):
                raise DomainError(
                    "storage_unavailable", "Media disk is unavailable; rollback blocked", 409
                )
            old = await self.request("GET", f"/containers/{recovery['oldContainer']}/json")
            if (
                old["Image"] != recovery["oldImage"]
                or old["Config"]["Labels"] != plan["container"]["Labels"]
            ):
                # Image labels may include vendor labels, compare ours below.
                labels = old["Config"].get("Labels", {})
                if old["Image"] != recovery["oldImage"] or any(
                    labels.get(k) != v for k, v in plan["container"]["Labels"].items()
                ):
                    raise DomainError(
                        "plex_rollback_ownership", "Rollback container ownership mismatch", 409
                    )
            self.control.save_intent(policy, False)
            listing = await self.request("GET", "/containers/json?all=1")
            if any("/" + policy.container in row.get("Names", []) for row in listing):
                await self.control.inspect(policy)
                await self.request("POST", f"/containers/{policy.container}/stop?t=30")
                await self.request("DELETE", f"/containers/{policy.container}")
            import uuid

            name = policy.container + "-restore-" + uuid.uuid4().hex[:8]
            failed = "failed-update-" + uuid.uuid4().hex
            code = (
                "import pathlib,shutil,os; r=pathlib.Path('/appdata'); "
                f"source=r/{backup.name!r}; target=r/{root.name!r}; saved=r/{failed!r}; "
                "assert source.is_dir() and not source.is_symlink() and target.is_dir() and not target.is_symlink(); "
                "names=['Media','Metadata','Plug-ins','Plug-in Support','Scanners']; "
                "assert all((source/n).is_dir() and not (source/n).is_symlink() and not (target/n).is_symlink() for n in names); "
                "size=sum(p.stat().st_size for n in names for p in (source/n).rglob('*') if p.is_file()); "
                "assert shutil.disk_usage(r).free>size+1024**3; saved.mkdir(mode=0o700); "
                "[( (target/n).rename(saved/n), shutil.copytree(source/n,target/n)) for n in names]; "
                f"[(os.chown(p,{self.policy().uid},{self.policy().gid})) for n in names for p in [target/n,*(target/n).rglob('*')]]; os.sync()"
            )
            await self.request(
                "POST",
                "/containers/create?name=" + name,
                body={
                    "Image": self.policy().initImage,
                    "User": "0:0",
                    "Labels": plan["container"]["Labels"],
                    "Entrypoint": ["python", "-c", code],
                    "HostConfig": {
                        "NetworkMode": "none",
                        "Mounts": [
                            {
                                "Type": "bind",
                                "Source": str(root.parent),
                                "Target": "/appdata",
                                "ReadOnly": False,
                            }
                        ],
                        "Memory": 128 * 1024**2,
                        "MemorySwap": 128 * 1024**2,
                        "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                        "LogConfig": {"Type": "none", "Config": {}},
                    },
                },
            )
            try:
                await self.request("POST", f"/containers/{name}/start")
                for _ in range(600):
                    state = (await self.request("GET", f"/containers/{name}/json"))["State"]
                    if not state["Running"]:
                        if state["ExitCode"] != 0:
                            raise DomainError(
                                "plex_restore_failed",
                                "Rollback could not finish; all app data retained",
                                409,
                            )
                        break
                    await asyncio.sleep(1)
                else:
                    raise DomainError(
                        "plex_restore_timeout", "Rollback timed out; Plex remains stopped", 503
                    )
            finally:
                await self.remove_helper(name)
            await self.request(
                "POST", f"/containers/{recovery['oldContainer']}/rename?name={policy.container}"
            )
            policy.imageId = recovery["oldImage"]
            self.vault.replace(
                policy.installationId, self.vault.get(policy.installationId + "-rollback")
            )
            self.last_saved = None
            save_json(Path(self.control.policy_file), policy.model_dump())
            save_json(self.state_dir / "plex-plan.json", plan)
            if recovery["desiredRunning"]:
                await self.start(policy)
            self.control.save_intent(policy, recovery["desiredRunning"])
            self.operation = {
                "state": "succeeded",
                "message": "Previous Plex version and database restored; media unchanged",
            }
            self.control.record("rolled_back")
            return self.operation
