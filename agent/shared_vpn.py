"""Private per-app relay namespaces. Only approved MediaHub installations qualify.

Assignment is saved before recreating an app. Failure never restores direct
networking. Private peer keys are generated on their host and never leave it.
"""

import asyncio
import base64
import copy
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from mediahub.errors import DomainError

from agent.diagnostics import Diagnostics, cause, error_fields, trace_async
from agent.install_files import read_json, save_json
from agent.relay_image.runtime import validate

LABEL = "org.mediahub.vpn.relay"
SUPPORTED = {"plex", "jellyfin"}


class SharedVPN:
    def __init__(self, config, apps, plex):
        self.config, self.apps, self.plex = config, apps, plex
        self.diagnostics = Diagnostics(config.state_dir, "shared_vpn")
        self.directory = config.state_dir / "shared-vpn"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        if self.directory.is_symlink():
            raise DomainError(
                "vpn_state_mount", "VPN state must use its own private directory", 409
            )
        self.directory.chmod(0o700)
        self.lock = asyncio.Lock()
        self.request = apps.request

    def path(self, app):
        if app not in SUPPORTED:
            raise DomainError(
                "vpn_app_unsupported", "Choose an installed Plex or Jellyfin app", 422
            )
        return self.directory / (app + ".json")

    def state(self, app):
        path = self.path(app)
        return read_json(path) if path.exists() else {"enabled": False}

    def identity(self, app):
        path = self.path(app).with_suffix(".key.json")
        if not path.exists():
            key = X25519PrivateKey.generate()
            save_json(
                path,
                {
                    "privateKey": base64.b64encode(key.private_bytes_raw()).decode(),
                    "publicKey": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
                },
            )
        return read_json(path)

    async def build_image(self):
        if not self.config.docker_socket or os.name != "posix":
            raise DomainError(
                "vpn_runtime_unavailable", "Shared VPN requires a Docker Linux Agent", 409
            )
        source = Path(__file__).parent / "relay_image"
        fingerprint = hashlib.sha256(
            b"".join(
                (source / name).read_bytes().replace(b"\r\n", b"\n")
                for name in ("Dockerfile", "runtime.py")
            )
        ).hexdigest()
        tag = "mediahub-vpn-relay:" + fingerprint[:16]
        image = await self.request("GET", "/images/" + tag + "/json", missing=True)
        if not image:
            builder_config = self.directory / "docker-builder"
            builder_config.mkdir(mode=0o700, exist_ok=True)
            process = await asyncio.create_subprocess_exec(
                "docker",
                "--host",
                "unix://" + str(self.config.docker_socket),
                "build",
                "--quiet",
                "--label",
                "org.mediahub.vpn.relay-source=" + fingerprint,
                "-t",
                tag,
                str(source),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ, "DOCKER_CONFIG": str(builder_config)},
            )
            try:
                await asyncio.wait_for(process.wait(), 600)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise DomainError(
                    "vpn_dependency_failed", "VPN helper build timed out; app stays stopped", 503
                ) from None
            except asyncio.CancelledError:
                process.kill()
                await process.wait()
                raise
            if process.returncode:
                raise DomainError(
                    "vpn_dependency_failed",
                    "VPN helper could not be installed; app stays stopped",
                    503,
                )
            image = await self.request("GET", "/images/" + tag + "/json")
        if (
            image.get("Config", {}).get("Labels", {}).get("org.mediahub.vpn.relay-source")
            != fingerprint
        ):
            raise DomainError("vpn_image_mismatch", "VPN helper image ownership changed", 409)
        return image["Id"]

    async def host_directory(self):
        # Derive the host bind from this Agent's inspected container, never HTTP input.
        identifier = os.environ.get("HOSTNAME", "")
        if not identifier or not all(c in "0123456789abcdef" for c in identifier):
            raise DomainError("vpn_state_mount", "Agent requires its private state bind mount", 409)
        own = await self.request("GET", "/containers/" + identifier + "/json")
        matches = [
            m
            for m in own.get("Mounts", [])
            if m["Destination"] == str(self.config.state_dir) and m["Type"] == "bind" and m["RW"]
        ]
        if len(matches) != 1 or not matches[0]["Source"].startswith("/"):
            raise DomainError(
                "vpn_state_mount", "Agent private state mount could not be verified", 409
            )
        return matches[0]["Source"] + "/shared-vpn"

    async def owned_relay(self, app):
        row = await self.request("GET", "/containers/mediahub-vpn-" + app + "/json", missing=True)
        if row and (
            row.get("Config", {}).get("Labels", {}).get(LABEL) != app
            or row.get("HostConfig", {}).get("Privileged") is not False
            or row.get("HostConfig", {}).get("NetworkMode") != "bridge"
        ):
            raise DomainError("vpn_relay_ownership", "VPN relay ownership changed", 409)
        return row

    async def relay(self, app, spec):
        state = self.state(app)
        value = {
            **state["peer"],
            "mode": "client",
            "listenPort": 51879,
            "privateKey": self.identity(app)["privateKey"],
        }
        validate(value)
        # Provider IPs are never copied into app ports or Cloudflare routes.
        config_path = self.directory / (app + ".relay.json")
        save_json(config_path, value)
        # The host directory stays 0700. Mount only this app's configuration
        # file; its root helper has no DAC override and cannot read a 0600 file
        # owned by the unprivileged Agent UID. Other apps' key files stay private.
        config_path.chmod(0o644)
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        image = await self.build_image()
        host = await self.host_directory()
        row = await self.owned_relay(app)
        expected_ports = spec["HostConfig"].get("PortBindings", {})
        if row and (
            row["Image"] != image
            or row["HostConfig"].get("PortBindings", {}) != expected_ports
            or row.get("Config", {}).get("Labels", {}).get("org.mediahub.vpn.connection") != digest
        ):
            current = await self.request(
                "GET", "/containers/" + ("mediahub-" + app) + "/json", missing=True
            )
            if current:
                raise DomainError(
                    "vpn_relay_changed",
                    "Stop and recreate the app before replacing its VPN relay",
                    409,
                )
            if row["State"].get("Running"):
                await self.request("POST", "/containers/" + row["Id"] + "/stop?t=10")
            await self.request("DELETE", "/containers/" + row["Id"] + "?v=false")
            row = None
        if not row:
            await self.request(
                "POST",
                "/containers/create?name=mediahub-vpn-" + app,
                {
                    "Image": image,
                    "Labels": {LABEL: app, "org.mediahub.vpn.connection": digest},
                    "ExposedPorts": spec.get("ExposedPorts", {}),
                    "Healthcheck": {
                        "Test": ["CMD", "python3", "/opt/relay/runtime.py", "health"],
                        "Interval": 5_000_000_000,
                        "Timeout": 3_000_000_000,
                        "Retries": 2,
                    },
                    "HostConfig": {
                        "NetworkMode": "bridge",
                        "PortBindings": expected_ports,
                        "Binds": [host + "/" + config_path.name + ":/config/settings.json:ro"],
                        "Privileged": False,
                        "Dns": ["1.1.1.1"],
                        "CapDrop": ["ALL"],
                        "CapAdd": ["NET_ADMIN"],
                        "ReadonlyRootfs": True,
                        "RestartPolicy": {"Name": "no"},
                        "SecurityOpt": ["no-new-privileges:true"],
                        "Tmpfs": {"/run": "rw,noexec,nosuid,nodev,size=1m"},
                        "LogConfig": {"Type": "none", "Config": {}},
                        "Devices": [
                            {
                                "PathOnHost": "/dev/net/tun",
                                "PathInContainer": "/dev/net/tun",
                                "CgroupPermissions": "rwm",
                            }
                        ],
                    },
                    "Env": ["RELAY_CONFIG=/config/settings.json"],
                },
            )
            row = await self.owned_relay(app)
        if not row["State"].get("Running"):
            await self.request("POST", "/containers/" + row["Id"] + "/start")
        elif row["State"].get("Health", {}).get("Status") == "unhealthy":
            await self.request("POST", "/containers/" + row["Id"] + "/stop?t=10")
            await self.request("POST", "/containers/" + row["Id"] + "/start")
        for _ in range(25):
            row = await self.owned_relay(app)
            if row["State"].get("Health", {}).get("Status") == "healthy":
                return row
            if not row["State"].get("Running"):
                break
            await asyncio.sleep(1)
        raise DomainError(
            "vpn_relay_unverified", "VPN relay handshake not verified; app stays stopped", 409
        )

    @staticmethod
    def original_spec(state, spec):
        """Remove only relay networking; retain the latest application settings."""
        result = copy.deepcopy(spec)
        if not spec.get("Labels", {}).get("org.mediahub.vpn.namespace"):
            return result
        previous = state["original"]
        for target, original, fields in (
            (result, previous, ("Hostname", "Domainname", "NetworkingConfig", "ExposedPorts")),
            (
                result["HostConfig"],
                previous["HostConfig"],
                ("NetworkMode", "PortBindings", "Dns", "DnsSearch", "DnsOptions"),
            ),
        ):
            for field in fields:
                if field in original:
                    target[field] = copy.deepcopy(original[field])
                else:
                    target.pop(field, None)
        for label in ("org.mediahub.vpn.namespace", "org.mediahub.vpn.generation"):
            result["Labels"].pop(label, None)
        return result

    async def prepare(self, app, spec):
        if app not in SUPPORTED or not self.state(app)["enabled"]:
            return spec
        state = self.state(app)
        spec = self.original_spec(state, spec)
        original = copy.deepcopy(spec)
        state["original"] = original
        save_json(self.path(app), state)
        row = await self.relay(app, original)
        spec = copy.deepcopy(spec)
        spec["HostConfig"]["NetworkMode"] = "container:" + row["Id"]
        spec["HostConfig"]["PortBindings"] = {}
        for key in (
            "Dns",
            "DnsSearch",
            "DnsOptions",
            "Hostname",
            "Domainname",
            "NetworkingConfig",
            "ExposedPorts",
        ):
            spec.pop(key, None)
            spec["HostConfig"].pop(key, None)
        spec.setdefault("Labels", {})["org.mediahub.vpn.namespace"] = row["Id"]
        spec["Labels"]["org.mediahub.vpn.generation"] = row["State"]["StartedAt"]
        return spec

    async def ready(self, app, inspected):
        state = self.state(app)
        if state.get("phase") == "removing":
            return False
        if state.get("phase") in {"changing", "blocked"} and state.get("requestedEnabled"):
            return False
        if not state["enabled"]:
            return True
        namespace = inspected.get("Config", {}).get("Labels", {}).get("org.mediahub.vpn.namespace")
        row = await self.owned_relay(app)
        return bool(
            row
            and namespace == row["Id"]
            and inspected.get("HostConfig", {}).get("NetworkMode") == "container:" + row["Id"]
            and inspected.get("Config", {}).get("Labels", {}).get("org.mediahub.vpn.generation")
            == row["State"].get("StartedAt")
            and row["State"].get("Running")
            and row["State"].get("Health", {}).get("Status") == "healthy"
        )

    def removal_record(self, app):
        self.path(app)  # Fixed app allowlist; never accept paths from the caller.
        if app == "plex":
            path = self.config.state_dir / "plex-plan.json"
            record = read_json(path) if path.exists() else None
            identity = (record or {}).get("installation", {}).get("installationId")
            if not identity:
                identity = self.plex.operation.get("installationId", "plex-main")
        else:
            path = self.apps.record_path(app)
            record = self.apps.record(app)
            identity = (record or {}).get("name", "mediahub-" + app)
        return path, record, identity

    async def removal_preview(self, app):
        _, record, identity = self.removal_record(app)
        current = await self.request(
            "GET",
            "/containers/" + (record or {}).get("name", "mediahub-" + app) + "/json",
            missing=True,
        )
        relay = await self.owned_relay(app)
        digest = hashlib.sha256(
            json.dumps(
                [identity, record, (current or {}).get("Id"), (relay or {}).get("Id")],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return {
            "installationId": digest,
            "running": bool(current and current.get("State", {}).get("Running")),
        }

    async def cleanup_removed(self, app):
        preview = await self.removal_preview(app)
        return await self.remove_connection(app, preview["installationId"])

    async def remove_connection(self, app, confirmed, *, fence_only=False):
        # Match configuration's lock order, so a reconciler cannot recreate the
        # app between fencing its intent and removing its namespace.
        async with self.lock:
            operation_lock = self.plex.control.lock if app == "plex" else self.apps.locks.get(app)
            self.path(app)
            task = getattr(self.plex, "install_task", None) if app == "plex" else getattr(self.apps, "tasks", {}).get(app)
            if task and not task.done():
                raise DomainError("operation_busy", "Wait for the current app operation", 409)
            if operation_lock.locked():
                raise DomainError("operation_busy", "Wait for the current app operation", 409)
            async with operation_lock:
                path, record, identity = self.removal_record(app)
                expected = (
                    identity if fence_only else (await self.removal_preview(app))["installationId"]
                )
                if confirmed != expected:
                    raise DomainError(
                        "confirmation_required", "Exact installation confirmation required", 409
                    )
                current = await self.request(
                    "GET",
                    "/containers/" + (record or {}).get("name", "mediahub-" + app) + "/json",
                    missing=True,
                )
                if current:
                    if not record:
                        raise DomainError(
                            "vpn_relay_ownership", "App ownership could not be verified", 409
                        )
                    if app == "plex":
                        current = await self.plex.control.inspect(self.plex.control.policy())
                    else:
                        self.apps.verify(current, record)
                    if not fence_only and current.get("State", {}).get("Running"):
                        raise DomainError(
                            "app_dependency",
                            "Stop the remaining app container before cleaning its VPN connection",
                            409,
                        )
                relay = await self.owned_relay(app)
                if relay and not fence_only:
                    listing = await self.request("GET", "/containers/json?all=1")
                    names = {relay["Id"], "mediahub-vpn-" + app}
                    for row in listing:
                        mode = row.get("HostConfig", {}).get("NetworkMode", "")
                        if (
                            mode.startswith("container:")
                            and mode[10:] in names
                            and row["Id"] != (current or {}).get("Id")
                        ):
                            raise DomainError(
                                "app_dependency",
                                "Another app uses this runtime. Disconnect it before removal.",
                                409,
                            )
                state = self.state(app)
                state.update(
                    enabled=False, requestedEnabled=False, desiredRunning=False, phase="removing"
                )
                save_json(self.path(app), state)
                if record:
                    record["desiredRunning"] = False
                    save_json(path, record)
                if fence_only:
                    return {"state": "ready", "installationId": identity}
                if app == "plex" and record and (self.directory / "plex-lan-nat.json").exists():
                    from agent.plex_lan_nat import configure as configure_lan

                    await configure_lan(self, self.original_spec(state, record["container"]), enabled=False)
                if current:
                    await self.request(
                        "DELETE", "/containers/" + current["Id"] + "?force=false&v=false"
                    )
                if relay:
                    if relay.get("State", {}).get("Running"):
                        await self.request("POST", "/containers/" + relay["Id"] + "/stop?t=10")
                    await self.request(
                        "DELETE", "/containers/" + relay["Id"] + "?force=false&v=false"
                    )
                if await self.owned_relay(app):
                    raise DomainError(
                        "removal_unverified", "Runtime removal has not passed its final checks", 409
                    )
                state.update(phase="removed")
                save_json(self.path(app), state)
                return {"state": "succeeded", "installationId": identity, "dataPreserved": True}

    @trace_async("hub", "shared_vpn_configuration")
    async def configuration(self, app, peer, enabled):
        self.diagnostics.record("configuration.requested", action=app, enabled=enabled, reason="configuration_requested")
        async with self.lock:
            state = self.state(app)
            operation_lock = self.plex.control.lock if app == "plex" else self.apps.locks[app]
            if operation_lock.locked():
                raise DomainError("operation_busy", "Wait for the current app operation", 409)
            async with operation_lock:
                if app == "plex":
                    policy = self.plex.control.policy()
                    if policy.vpnEnabled:
                        raise DomainError(
                            "vpn_conflict",
                            "Disable the old dedicated Plex VPN before selecting shared VPN",
                            409,
                        )
                    record_path = self.config.state_dir / "plex-plan.json"
                    record = read_json(record_path)
                    current = await self.request(
                        "GET", "/containers/" + record["name"] + "/json", missing=True
                    )
                    if current:
                        current = await self.plex.control.inspect(policy)
                else:
                    record_path = self.apps.record_path(app)
                    record = self.apps.record(app)
                    if not record:
                        raise DomainError(
                            "app_not_installed", "Install the app before selecting shared VPN", 409
                        )
                    current = await self.request(
                        "GET", "/containers/" + record["name"] + "/json", missing=True
                    )
                    if current:
                        self.apps.verify(current, record)
                if not current and state.get("phase") not in {"changing", "starting", "blocked"}:
                    raise DomainError(
                        "app_not_installed", "Install the app before selecting shared VPN", 409
                    )
                if app == "plex":
                    state["desiredRunning"] = self.plex.control.intent(policy)
                elif current and state.get("phase") not in {"changing", "starting", "blocked"}:
                    state["desiredRunning"] = bool(current["State"].get("Running"))
                original = self.original_spec(state, record["container"])
                if app == "plex" and not enabled and (self.directory / "plex-lan-nat.json").exists():
                    from agent.plex_lan_nat import configure as configure_lan

                    await configure_lan(self, original, enabled=False)
                # Preserve the latest installed image across VPN off/on, rather
                # than resurrecting an old version stored before an update.
                original["Image"] = record["container"]["Image"]
                if app != "plex":
                    # A missing disposable cache must not leave a selected app
                    # permanently absent after recreation. Verify storage and
                    # prepare only its approved cache before stopping anything.
                    try:
                        await self.apps.prepare_storage(app, original, create_config=False)
                    except DomainError as error:
                        state.update(errorCode=error.code, message=error.message)
                        save_json(self.path(app), state)
                        raise
                if enabled:
                    validate(
                        {
                            **peer,
                            "mode": "client",
                            "listenPort": 51879,
                            "privateKey": self.identity(app)["privateKey"],
                        }
                    )
                state.update(
                    requestedEnabled=enabled, peer=peer, original=original, phase="changing"
                )
                save_json(self.path(app), state)
                # Stop before touching published ports. Volumes are never deleted.
                if current and current["State"].get("Running"):
                    self.diagnostics.record("app.stop_requested", action=app, container=current.get("Id"), reason="vpn_configuration_recreate")
                    if app == "plex":
                        await self.plex.stop(policy)
                    else:
                        await self.request("POST", "/containers/" + current["Id"] + "/stop?t=30")
                if current:
                    self.diagnostics.record("app.remove_requested", action=app, container=current.get("Id"), reason="vpn_configuration_recreate")
                    await self.request("DELETE", "/containers/" + current["Id"] + "?v=false")
                state["enabled"] = enabled
                save_json(self.path(app), state)
                try:
                    if not enabled:
                        relay = await self.owned_relay(app)
                        if relay:
                            await self.request("POST", "/containers/" + relay["Id"] + "/stop?t=10")
                            await self.request("DELETE", "/containers/" + relay["Id"] + "?v=false")
                    spec = await self.prepare(app, original)
                    record["container"] = spec
                    save_json(record_path, record)
                    await self.request("POST", "/containers/create?name=" + record["name"], spec)
                    self.diagnostics.record("app.created", action=app, reason="vpn_configuration_recreate")
                    state["phase"] = "starting"
                    save_json(self.path(app), state)
                    if state.get("desiredRunning"):
                        if app == "plex":
                            await self.plex.start(policy)
                        else:
                            await self.request("POST", "/containers/" + record["name"] + "/start")
                    state["phase"] = "ready"
                    state.pop("errorCode", None)
                    state.pop("message", None)
                    save_json(self.path(app), state)
                except Exception as error:
                    self.diagnostics.record("configuration.error", action=app, **error_fields(error))
                    state["phase"] = "blocked"
                    state["errorCode"] = (
                        error.code
                        if isinstance(error, DomainError)
                        else "vpn_app_recreation_failed"
                    )
                    state["message"] = (
                        error.message
                        if isinstance(error, DomainError)
                        else "App recreation failed; persistent data retained"
                    )
                    save_json(self.path(app), state)
                    raise
                return await self.status(app)

    async def status(self, app):
        value = self.state(app)
        row = await self.owned_relay(app) if value["enabled"] else None
        name = "mediahub-" + app
        if app == "plex" and value["enabled"]:
            name = read_json(self.config.state_dir / "plex-plan.json")["name"]
        current = (
            await self.request("GET", "/containers/" + name + "/json", missing=True)
            if value["enabled"]
            else None
        )
        ready = bool(
            value["enabled"]
            and value.get("phase") == "ready"
            and current
            and current.get("State", {}).get("Running")
            and await self.ready(app, current)
        )
        return {
            "enabled": value["enabled"],
            "phase": value.get("phase", "idle"),
            "handshakeVerified": bool(
                row
                and row["State"].get("Running")
                and row["State"].get("Health", {}).get("Status") == "healthy"
            ),
            "publicKey": self.identity(app)["publicKey"],
            "ready": ready,
            "errorCode": value.get("errorCode"),
            "message": value.get("message")
            or (
                "App is stopped or missing; the VPN relay alone is not an active app"
                if value["enabled"] and not ready
                else None
            ),
        }

    async def poll(self):
        while True:
            for app in SUPPORTED:
                state = self.state(app)
                if not state["enabled"] and not (
                    state.get("requestedEnabled") and state.get("phase") in {"changing", "starting", "blocked"}
                ):
                    continue
                try:
                    record = (
                        read_json(self.config.state_dir / "plex-plan.json")
                        if app == "plex"
                        else self.apps.record(app)
                    )
                    if not record or (app != "plex" and record.get("desiredRunning") is not True):
                        continue
                    current = await self.request(
                        "GET", "/containers/" + record["name"] + "/json", missing=True
                    )
                    if state.get("phase") == "ready" and current and await self.ready(app, current):
                        # Updating Agent source also updates this prerequisite.
                        row = await self.owned_relay(app)
                        if row["Image"] == await self.build_image():
                            continue
                    row = await self.owned_relay(app)
                    reason = ("app_missing" if not current else "phase_requires_recovery" if state.get("phase") != "ready"
                              else "relay_missing" if not row else "relay_stopped" if not row["State"].get("Running")
                              else "relay_unhealthy" if row["State"].get("Health", {}).get("Status") != "healthy"
                              else "app_stopped" if not current["State"].get("Running")
                              else "namespace_changed" if current.get("HostConfig", {}).get("NetworkMode") != "container:" + row["Id"]
                              else "namespace_label_changed" if current.get("Config", {}).get("Labels", {}).get("org.mediahub.vpn.namespace") != row["Id"]
                              else "relay_generation_changed" if current.get("Config", {}).get("Labels", {}).get("org.mediahub.vpn.generation") != row["State"].get("StartedAt")
                              else "relay_image_changed")
                    with cause("supervisor", reason):
                        self.diagnostics.record("reconcile.recreate_requested", action=app, reason=reason, phase=state.get("phase"),
                                                container=(current or {}).get("Id"), generation=(row or {}).get("State", {}).get("StartedAt"),
                                                expectedGeneration=(current or {}).get("Config", {}).get("Labels", {}).get("org.mediahub.vpn.generation"),
                                                health=(row or {}).get("State", {}).get("Health", {}).get("Status"))
                        await self.configuration(
                            app, state["peer"], state.get("requestedEnabled", state["enabled"])
                        )
                except (DomainError, OSError, ValueError, KeyError, TypeError) as error:
                    self.diagnostics.record("reconcile.error", action=app, **error_fields(error))
                    pass
            await asyncio.sleep(10)
