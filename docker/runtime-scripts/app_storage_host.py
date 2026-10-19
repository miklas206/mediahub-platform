"""Host-only, additive NAS bindings for owned apps; no media is moved or removed."""

import copy
import fcntl
import http.client
import json
import os
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


class AppStorage:
    def __init__(self, host, error, save):
        self.host, self.error, self.save = host, error, save
        self.views = host.root / "app-storage"

    def docker(self, method, path, body=None):
        connection = DockerConnection("localhost", timeout=60)
        try:
            connection.request(
                method,
                path,
                body=json.dumps(body) if body is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            content = response.read(8 * 1024 * 1024 + 1)
            if response.status >= 300 or len(content) > 8 * 1024 * 1024:
                raise self.error("App container operation failed; existing files were preserved")
            return json.loads(content) if content else {}
        except (OSError, http.client.HTTPException, ValueError):
            raise self.error("Docker is unavailable; app storage was not changed") from None
        finally:
            connection.close()

    def directory(self, path, mode=0o711):
        if path.is_symlink() or path.resolve() != path:
            raise self.error("App storage path ownership changed")
        path.mkdir(mode=mode, exist_ok=True)
        if path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o022:
            raise self.error("App storage directory ownership changed")
        path.chmod(mode)

    def view(self, identifier, *, files=True, read_only=False):
        """A shared parent propagates later NAS mounts into existing app containers."""
        self.directory(self.views)
        parent = self.views / (identifier + ("-ro" if read_only else ""))
        self.directory(parent, 0o755)
        info = self.host.mount_info(parent)
        if info.get("target") != str(parent):
            self.host.run(["mount", "--bind", str(parent), str(parent)])
        self.host.run(["mount", "--make-rshared", str(parent)])
        target = parent / "files"
        current = self.host.mount_info(target)
        if current.get("target") != str(target):
            if target.is_symlink():
                raise self.error("App storage view ownership changed")
            if not target.exists():
                target.mkdir(mode=0o000)
        if files:
            location = self.host.location(identifier)
            expected = self.host.mount_info(Path(location["source"]))
            if current.get("target") == str(target):
                if (current.get("source"), current.get("fstype")) != (
                    expected.get("source"),
                    expected.get("fstype"),
                ):
                    raise self.error("App storage view mount identity changed")
                try:
                    stale = os.stat(target).st_dev != os.stat(location["source"]).st_dev
                except OSError:
                    stale = True
                if stale:
                    self.host.run(["umount", str(target)])
                    current = {}
            if current.get("target") != str(target):
                if any(target.iterdir()):
                    raise self.error("App storage view is occupied; files were preserved")
                target.chmod(0o000)
                self.host.run(
                    [
                        "mount",
                        "--bind",
                        *(["-o", "ro"] if read_only else []),
                        location["source"],
                        str(target),
                    ]
                )
        return parent

    def prepare_views(self):
        for row in self.host.state().get("appBindings", []):
            self.view(row["storageId"], files=False, read_only=row["app"] == "plex")

    def reconcile(self):
        self.cleanup()
        for row in self.host.state().get("appBindings", []):
            try:
                self.view(row["storageId"], read_only=row["app"] == "plex")
            except self.error:
                pass
        self.write_status()

    def write_status(self):
        status = {}
        for identifier in {r["storageId"] for r in self.host.state().get("appBindings", [])}:
            ready = False
            try:
                location = self.host.location(identifier)
                for binding in self.host.state().get("appBindings", []):
                    if binding["storageId"] == identifier:
                        target = self.source(binding, binding["app"] == "plex") / "files"
                        if self.host.mount_info(target).get("target") != str(target):
                            raise self.error("App NAS view is unavailable")
                info = self.host.mount_info(Path(location["source"]))
                if info.get("fstype") == "fuse.rclone":
                    connection = next(r for r in self.host.state()["nas"] if r["id"] == identifier)
                    self.host.run(
                        [
                            str(self.host.rclone_binary()),
                            "about",
                            "mediahub:" + connection["share"],
                            "--config",
                            str(self.host.folder / (identifier + ".rclone.conf")),
                            "--json",
                            "--timeout",
                            "2s",
                            "--contimeout",
                            "1s",
                            "--retries",
                            "1",
                            "--low-level-retries",
                            "1",
                        ],
                        timeout=3,
                    )
                ready = True
            except (self.error, OSError):
                pass
            status[identifier] = ready
        folder = self.host.root / "agent"
        if folder.is_dir():
            path = folder / "nas-storage-status.json"
            self.save(path, {"observedAt": time.time(), "nas": status})
            os.chown(path, 0, 10001)
            path.chmod(0o640)

    def cleanup(self):
        journal = self.host.folder / "app-storage-operation.json"
        if not journal.exists():
            return
        operation = json.loads(journal.read_text())
        if operation.get("state") != "saved" or not operation.get("containers"):
            return
        listing = self.docker("GET", "/containers/json?all=1")
        for old in operation["containers"]:
            row = next((r for r in listing if r["Id"] == old["id"]), None)
            if row:
                if row.get("State") not in {"created", "exited"} or "/" + old[
                    "backup"
                ] not in row.get("Names", []):
                    raise self.error("Retained app storage runtime requires host inspection")
                self.docker("DELETE", "/containers/" + old["id"])
        operation["containers"] = []
        self.save(journal, operation)

    def release_view(self, identifier):
        for suffix in ("", "-ro"):
            parent = self.views / (identifier + suffix)
            child = parent / "files"
            if self.host.mount_info(child).get("target") == str(child):
                self.host.run(["umount", str(child)])
            if self.host.mount_info(parent).get("target") == str(parent):
                self.host.run(["umount", str(parent)])

    def source(self, binding, read_only=False):
        return self.views / (binding["storageId"] + ("-ro" if read_only else ""))

    def label(self, identifier):
        return next(r["label"] for r in self.host.state()["nas"] if r["id"] == identifier)

    def require_flushed(self, row):
        if not row.get("cacheLocationId"):
            return
        try:
            stats = json.loads(
                self.host.run(
                    [
                        str(self.host.rclone_binary()),
                        "rc",
                        "--unix-socket",
                        str(self.host.folder / (row["id"] + ".rc.sock")),
                        "vfs/stats",
                        "--timeout",
                        "2s",
                    ],
                    timeout=3,
                )
            )["diskCache"]
            if not isinstance(stats, dict):
                raise ValueError("Missing cache statistics")
            if any(
                type(stats.get(k)) is not int or stats[k] != 0
                for k in ("uploadsQueued", "uploadsInProgress", "erroredFiles")
            ):
                raise ValueError("Pending cache writes")
        except (self.error, KeyError, ValueError):
            raise self.error(
                "The NAS write cache is not confirmed uploaded. Reconnect the NAS and wait for pending uploads before disconnecting or removing it"
            ) from None

    def cache_path(self, row):
        location = next(
            (r for r in self.host.policy()["locations"] if r["id"] == row.get("cacheLocationId")),
            None,
        )
        return (
            (Path(location["source"]) / ".mediahub-nas-cache" / self.host.installation / row["id"])
            if location
            else None
        )

    def cache_directory(self, row):
        location = self.host.location(row["cacheLocationId"])
        if location["kind"] != "local" or location.get("mountTarget") == "/":
            raise self.error("NAS write cache requires verified local media storage")
        if not os.access(location["source"], os.W_OK | os.X_OK):
            raise self.error("NAS write cache requires writable approved local media storage")
        filesystem = self.host.mount_info(Path(location["source"])).get("fstype")
        if filesystem in {"tmpfs", "ramfs", "overlay", "cifs", "fuse.rclone", "nfs", "nfs4"}:
            raise self.error("NAS write cache requires persistent local media storage")
        path = Path(location["source"]) / ".mediahub-nas-cache"
        for value in (
            path,
            path / self.host.installation,
            path / self.host.installation / row["id"],
        ):
            self.directory(value, 0o700)
        target = path / self.host.installation / row["id"]
        if os.stat(target).st_dev == os.stat("/").st_dev:
            raise self.error(
                "NAS write cache must be on a separate verified media filesystem, not the system disk"
            )
        private = self.host.folder / "cache"
        self.directory(private, 0o700)
        pinned = private / row["id"]
        if pinned.is_symlink():
            raise self.error("NAS cache mount ownership changed")
        info = self.host.mount_info(pinned)
        if info.get("target") != str(pinned):
            pinned.mkdir(mode=0o000, exist_ok=True)
            if any(pinned.iterdir()):
                raise self.error("NAS cache mount target is occupied")
            pinned.chmod(0o000)
            self.host.run(["mount", "--bind", str(target), str(pinned)])
        elif os.stat(pinned).st_dev != os.stat(target).st_dev:
            raise self.error("NAS cache filesystem identity changed")
        return pinned

    def release_cache(self, row):
        if not row.get("cacheLocationId"):
            return
        self.host.run(
            ["systemctl", "stop", "mediahub-nas-" + self.host.installation + "-" + row["id"]]
        )
        target = self.host.folder / "cache" / row["id"]
        if self.host.mount_info(target).get("target") == str(target):
            self.host.run(["umount", str(target)])

    def enable_writes(self, identifier):
        state = self.host.state()
        row = next(r for r in state["nas"] if r["id"] == identifier)
        if row["readOnly"]:
            raise self.error("MediaSeed requires a NAS connection with read and write access")
        if not self.host.userspace_mounts() or row.get("cacheLocationId"):
            return
        bindings = [r for r in state.get("appBindings", []) if r["storageId"] == identifier]
        for package in sorted({r["app"] for r in bindings}):
            self.documents(package, [r for r in state["appBindings"] if r["app"] == package])
        shared = any(r["storageId"] == identifier for r in state["shares"])
        candidates = []
        for location in self.host.locations():
            if (
                location["kind"] != "local"
                or not location["ready"]
                or location.get("mountTarget") == "/"
            ):
                continue
            try:
                available = os.statvfs(location["source"])
                free = available.f_bavail * available.f_frsize
                if free >= 20 * 1024**3 and os.access(location["source"], os.W_OK | os.X_OK):
                    candidates.append((free, location["id"]))
            except OSError:
                continue
        if not candidates:
            raise self.error(
                "Torrent writes need approved local media storage with at least 20 GiB free for the NAS write cache"
            )
        row["cacheLocationId"] = max(candidates)[1]
        self.cache_directory(row)
        if shared:
            self.host.configure_smb([])
        for suffix in ("", "-ro"):
            target = self.views / (identifier + suffix) / "files"
            if self.host.mount_info(target).get("target") == str(target):
                self.host.run(["umount", str(target)])
        self.host.run(["fusermount3", "-u", str(self.host.mounts / identifier)])
        self.host.run(
            ["systemctl", "stop", "mediahub-nas-" + self.host.installation + "-" + identifier]
        )
        self.save(self.host.file, state)
        self.host.mount_nas(row)
        for binding in bindings:
            self.view(identifier, read_only=binding["app"] == "plex")
        if shared:
            self.host.configure_smb(state["shares"])

    def managed(self, kind):
        policy = json.loads((self.host.root / "data/managed-apps.json").read_text())
        entry = policy.get("org.mediahub." + kind, {})
        project = "mediahub-" + kind
        path = self.host.root / "local-apps" / kind / "compose.json"
        if entry.get("project") != project or path.is_symlink():
            raise self.error("Install this app through MediaHub before attaching NAS storage")
        config = json.loads(path.read_text())
        if config.get("name") != project:
            raise self.error("App Compose ownership changed")
        return path, config

    def containers(self, project):
        filters = json.dumps({"label": ["com.docker.compose.project=" + project]})
        from urllib.parse import quote

        return [
            self.docker("GET", "/containers/" + r["Id"] + "/json")
            for r in self.docker("GET", "/containers/json?all=1&filters=" + quote(filters))
        ]

    def stopped(self, rows):
        if not rows or any(r["State"].get("Running") or r["State"].get("Restarting") for r in rows):
            raise self.error(
                "Stop the app first. For MediaSeed, also stop MediaVPN before changing storage"
            )

    @staticmethod
    def specification(row):
        """Preserve the actual image, settings, limits, mounts and private networks."""
        result = copy.deepcopy(row["Config"])
        result["Image"] = row["Image"]
        result["HostConfig"] = copy.deepcopy(row["HostConfig"])
        if result["HostConfig"].get("NetworkMode", "").startswith("container:"):
            # Inspect includes an inherited hostname and image EXPOSE metadata.
            # Docker rejects both on create when another container owns networking.
            # Keep the shared namespace and all actual settings/port ownership intact.
            result.pop("Hostname", None)
            result.pop("ExposedPorts", None)
        result["NetworkingConfig"] = {
            "EndpointsConfig": {
                name: {
                    k: copy.deepcopy(v)
                    for k, v in endpoint.items()
                    if k in {"IPAMConfig", "Links", "Aliases", "DriverOpts", "GwPriority"}
                    and v is not None
                }
                for name, endpoint in (row.get("NetworkSettings", {}).get("Networks") or {}).items()
            }
        }
        return result

    def documents(self, package, bindings):
        """Produce persisted config plus stopped container replacements, before mutation."""
        documents, replacements = {}, []
        if package == "mediaseed":
            path, config = self.managed("mediaseed")
            rows = self.containers(config["name"])
            selected = [
                r
                for r in rows
                if r["Config"]["Labels"].get("com.docker.compose.service") in {"app", "qbittorrent"}
            ]
            if len(selected) != 2 or {
                r["Config"]["Labels"]["com.docker.compose.service"] for r in selected
            } != {"app", "qbittorrent"}:
                raise self.error("The owned MediaSeed containers could not be identified")
            self.stopped(rows)
            vpn_path, vpn = self.managed("mediavpn")
            vpn_rows = self.containers(vpn["name"])
            self.stopped(vpn_rows)
            vpn_app = [
                r
                for r in vpn_rows
                if r["Config"]["Labels"].get("com.docker.compose.service") == "app"
            ]
            if (
                len(vpn_app) != 1
                or vpn_app[0]["Config"]["Labels"].get("org.mediahub.mediavpn.nas-storage")
                != "rslave-v1"
            ):
                raise self.error(
                    "Update MediaVPN to 0.2.31 or newer before attaching NAS storage to MediaSeed"
                )
            # The VPN controller is stopped, so it cannot recreate its client mid-change.
            clones = self.docker(
                "GET",
                "/containers/json?all=1&filters=%7B%22label%22%3A%5B%22org.mediahub.mediavpn.seedbox%3Dmediaseed%22%5D%7D",
            )
            if any(r.get("State") != "exited" and r.get("State") != "created" for r in clones):
                raise self.error(
                    "Stop MediaSeed and its VPN torrent client before changing storage"
                )
            for service in ("app", "qbittorrent"):
                values = config["services"][service]
                values["volumes"] = [
                    v for v in values.get("volumes", []) if not self.is_nas_volume(v)
                ]
                for binding in bindings:
                    values["volumes"].append(self.compose_volume(binding, False))
            env = config["services"]["app"].setdefault("environment", {})
            roots = json.loads(env.get("MEDIASEED_STORAGE_ROOTS", "[]"))
            roots = [r for r in roots if not r["id"].startswith("nas-")]
            roots += [
                {
                    "id": "nas-" + b["storageId"],
                    "label": self.label(b["storageId"]),
                    "path": "/downloads/media/nas-" + b["storageId"] + "/files",
                }
                for b in bindings
            ]
            env["MEDIASEED_STORAGE_ROOTS"] = json.dumps(roots)
            vpn_env = vpn["services"]["app"].setdefault("environment", {})
            storage = [
                r
                for r in json.loads(vpn_env.get("MEDIAVPN_MEDIASEED_STORAGE", "[]"))
                if not r["id"].startswith("nas-")
            ]
            storage += [self.seed_location(b) for b in bindings]
            vpn_env["MEDIAVPN_MEDIASEED_STORAGE"] = json.dumps(storage)
            documents.update({path: config, vpn_path: vpn})
            for r in selected + [
                r
                for r in vpn_rows
                if r["Config"]["Labels"].get("com.docker.compose.service") == "app"
            ]:
                spec = self.specification(r)
                is_seed = r["Config"]["Labels"]["com.docker.compose.project"] == config["name"]
                if is_seed:
                    self.patch_mounts(spec, bindings, False)
                    if r["Config"]["Labels"]["com.docker.compose.service"] == "app":
                        self.patch_env(
                            spec, "MEDIASEED_STORAGE_ROOTS", env["MEDIASEED_STORAGE_ROOTS"]
                        )
                else:
                    self.patch_env(
                        spec, "MEDIAVPN_MEDIASEED_STORAGE", vpn_env["MEDIAVPN_MEDIASEED_STORAGE"]
                    )
                replacements.append((r, spec))
        elif package == "plex":
            folder = self.host.root / "agent"
            path = folder / "plex-managed.json"
            policy = json.loads(path.read_text())
            row = self.docker("GET", "/containers/" + policy["container"] + "/json")
            labels = row["Config"].get("Labels", {})
            actual = sorted((m["Source"], m["Destination"], not m["RW"]) for m in row["Mounts"])
            expected = sorted((m["source"], m["target"], m["readOnly"]) for m in policy["mounts"])
            if (
                labels.get("org.mediahub.package") != "org.mediahub.plex"
                or labels.get("org.mediahub.installation") != policy["installationId"]
                or row["Image"] != policy["imageId"]
                or actual != expected
            ):
                raise self.error("Plex runtime does not match its approved host policy")
            self.stopped([row])
            intent = policy.get("controlStatePath")
            if (
                intent != "/state/plex-intent.json"
                or json.loads((folder / "plex-intent.json").read_text()).get("desiredRunning")
                is not False
            ):
                raise self.error("Stop Plex from MediaHub before changing storage")
            spec = self.specification(row)
            self.patch_mounts(spec, bindings, True)
            policy["mounts"] = [
                m for m in policy["mounts"] if not m["target"].startswith("/media/nas/")
            ]
            policy["mounts"] += [
                {
                    "source": str(self.source(b, True)),
                    "target": self.target("plex", b["storageId"]),
                    "readOnly": True,
                }
                for b in bindings
            ]
            plan_path = folder / "plex-plan.json"
            plan = json.loads(plan_path.read_text())
            if plan["installation"]["installationId"] != policy["installationId"]:
                raise self.error("Plex installation plan ownership changed")
            self.patch_mounts(plan["container"], bindings, True)
            documents.update({path: policy, plan_path: plan})
            # The preserved reset plan only identifies local app data, not NAS media.
            replacements.append((row, spec))
        else:
            raise self.error("This app does not support NAS storage", 422)
        if package == "mediaseed":
            self.update_recipes(replacements, documents)
        return documents, replacements

    def update_recipes(self, replacements, documents):
        for kind in ("mediaseed", "mediavpn"):
            path = self.host.root / "data/managed-install-recipes" / (kind + ".json")
            if not path.exists():
                continue  # Older host preparation backfills the recipe independently.
            recipe = json.loads(path.read_text())
            if recipe.get("packageId") != "org.mediahub." + kind:
                raise self.error("App installation recipe ownership changed")
            changed = False
            for row, spec in replacements:
                for item in recipe["containers"]:
                    if item["name"] == row["Name"].lstrip("/"):
                        if item["spec"].get("Labels") != row["Config"].get("Labels"):
                            raise self.error(
                                "App installation recipe is stale; prepare apps and retry"
                            )
                        item["spec"] = copy.deepcopy(spec)
                        changed = True
            if changed:
                documents[path] = recipe

    @staticmethod
    def target(package, identifier):
        return ("/media/nas/" if package == "plex" else "/downloads/media/nas-") + identifier

    def seed_location(self, binding):
        identifier = binding["storageId"]
        return {
            "id": "nas-" + identifier,
            "label": self.label(identifier),
            "source": str(self.views / identifier),
            "path": self.target("mediaseed", identifier),
        }

    def compose_volume(self, binding, read_only):
        location = self.seed_location(binding)
        return {
            "type": "bind",
            "source": location["source"],
            "target": location["path"],
            "read_only": read_only,
            "bind": {"create_host_path": False, "propagation": "rslave"},
        }

    @staticmethod
    def is_nas_volume(volume):
        return isinstance(volume, dict) and str(volume.get("target", "")).startswith(
            "/downloads/media/nas-"
        )

    def patch_mounts(self, spec, bindings, read_only):
        prefix = "/media/nas/" if read_only else "/downloads/media/nas-"
        host = spec.setdefault("HostConfig", {})
        host["Mounts"] = [
            m for m in (host.get("Mounts") or []) if not m.get("Target", "").startswith(prefix)
        ]
        host["Binds"] = [
            b for b in (host.get("Binds") or []) if not b.split(":")[1].startswith(prefix)
        ]
        for binding in bindings:
            host["Mounts"].append(
                {
                    "Type": "bind",
                    "Source": str(self.source(binding, read_only)),
                    "Target": self.target(
                        "plex" if read_only else "mediaseed", binding["storageId"]
                    ),
                    "ReadOnly": read_only,
                    "BindOptions": {"Propagation": "rslave", "CreateMountpoint": False},
                }
            )

    @staticmethod
    def patch_env(spec, key, value):
        spec["Env"] = [v for v in (spec.get("Env") or []) if not v.startswith(key + "=")] + [
            key + "=" + value
        ]

    @contextmanager
    def runtime_guard(self):
        path = self.host.root / "agent/app-storage.lock"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o640)
        with os.fdopen(descriptor, "a+") as lock:
            info = os.fstat(lock.fileno())
            if info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o022:
                raise self.error("App storage lock ownership changed")
            os.chown(path, os.geteuid(), 10001)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise self.error("Wait for the current app operation to finish") from None
            yield

    def change(self, package, identifier, attach):
        if (
            package not in {"mediaseed", "plex"}
            or not isinstance(identifier, str)
            or len(identifier) != 24
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise self.error("Invalid app storage selection", 422)
        with self.host.lock:
            lock_path = self.host.root / "updates/host-updater.lock"
            with lock_path.open("a+") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise self.error("Wait for the current host update to finish") from None
                with self.runtime_guard():
                    return self._change(package, identifier, attach)

    def _change(self, package, identifier, attach):
        journal = self.host.folder / "app-storage-operation.json"
        if journal.exists() and json.loads(journal.read_text()).get("state") == "changing":
            raise self.error(
                "An interrupted app storage change needs host recovery before retrying"
            )
        self.cleanup()
        state = self.host.state()
        current = state.get("appBindings", [])
        binding = {"app": package, "storageId": identifier}
        if (binding in current) == attach:
            return {"saved": True}
        selected = [r for r in current if r["app"] == package and r != binding]
        if attach:
            location = self.host.location(identifier)
            if location["kind"] != "nas":
                raise self.error("Choose a connected NAS", 422)
            selected.append(binding)
        # Validate stopped state and ownership before any mount/config mutation.
        self.documents(package, [r for r in current if r["app"] == package])
        if attach:
            if package == "mediaseed":
                self.enable_writes(identifier)
            self.view(identifier, read_only=package == "plex")
        documents, replacements = self.documents(package, selected)
        journal = self.host.folder / "app-storage-operation.json"
        if journal.exists() and json.loads(journal.read_text()).get("state") == "changing":
            raise self.error(
                "An interrupted app storage change needs host recovery before retrying"
            )
        if any(p.is_symlink() or p.resolve() != p for p in documents):
            raise self.error("App configuration path ownership changed")
        backups = {
            str(p): {
                "content": p.read_text(),
                "uid": p.stat().st_uid,
                "gid": p.stat().st_gid,
                "mode": p.stat().st_mode & 0o777,
            }
            for p in documents
        }
        operation = {
            "state": "changing",
            "app": package,
            "files": backups,
            "containers": [],
            "bindings": current,
        }
        self.save(journal, operation)
        changed = []
        try:
            for row, spec in replacements:
                # Recheck immediately before rename; never recreate an actively used app.
                actual = self.docker("GET", "/containers/" + row["Id"] + "/json")
                self.stopped([actual])
                if actual["Config"] != row["Config"] or actual["HostConfig"] != row["HostConfig"]:
                    raise self.error("App configuration changed; refresh and retry")
                original = row["Name"].lstrip("/")
                backup = original + "-storage-" + uuid.uuid4().hex[:12]
                operation["containers"].append(
                    {"id": row["Id"], "name": original, "backup": backup}
                )
                self.save(journal, operation)
                self.docker("POST", "/containers/" + row["Id"] + "/rename?name=" + backup)
                changed.append((row, original))
                self.docker("POST", "/containers/create?name=" + original, spec)
            for path, value in documents.items():
                self.save(path, value)
                os.chown(path, backups[str(path)]["uid"], backups[str(path)]["gid"])
                path.chmod(backups[str(path)]["mode"])
            state = self.host.state()  # Preserve the selected write-cache migration.
            state["appBindings"] = [r for r in current if r["app"] != package] + selected
            self.save(self.host.file, state)
            operation["state"] = "saved"
            self.save(journal, operation)
        except Exception:
            rollback_failed = False
            for row, original in reversed(changed):
                try:
                    # Delete only the replacement name; old container is retained by ID.
                    listing = self.docker("GET", "/containers/json?all=1")
                    new = next(
                        (
                            r
                            for r in listing
                            if "/" + original in r["Names"] and r["Id"] != row["Id"]
                        ),
                        None,
                    )
                    if new:
                        self.docker("DELETE", "/containers/" + new["Id"])
                    self.docker("POST", "/containers/" + row["Id"] + "/rename?name=" + original)
                except self.error:
                    rollback_failed = True
            restored = self.host.state()
            restored["appBindings"] = current
            self.save(self.host.file, restored)
            for name, before in backups.items():
                path = Path(name)
                self.save(path, before["content"])
                os.chown(path, before["uid"], before["gid"])
                path.chmod(before["mode"])
            operation["state"] = "changing" if rollback_failed else "rolled_back"
            self.save(journal, operation)
            raise
        # Retry a failed cleanup during reconciliation; keep all media and volumes.
        self.cleanup()
        self.write_status()
        return {"saved": True, "restartRequired": True}

    def recover(self):
        with self.host.lock, self.runtime_guard():
            with (self.host.root / "updates/host-updater.lock").open("a+") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise self.error("Wait for the current host update to finish") from None
                path = self.host.folder / "app-storage-operation.json"
                if not path.exists():
                    return {"saved": True}
                operation = json.loads(path.read_text())
                if operation.get("state") != "changing":
                    return {"saved": True}
                for old in reversed(operation["containers"]):
                    row = self.docker("GET", "/containers/" + old["id"] + "/json")
                    self.stopped([row])
                    if row["Name"] not in {"/" + old["name"], "/" + old["backup"]}:
                        raise self.error("App recovery ownership changed; keep the app stopped")
                    listing = self.docker("GET", "/containers/json?all=1")
                    replacement = next(
                        (
                            r
                            for r in listing
                            if "/" + old["name"] in r.get("Names", []) and r["Id"] != old["id"]
                        ),
                        None,
                    )
                    if replacement:
                        new = self.docker("GET", "/containers/" + replacement["Id"] + "/json")
                        self.stopped([new])
                        if new["Config"].get("Labels") != row["Config"].get("Labels"):
                            raise self.error("App recovery ownership changed; keep the app stopped")
                        self.docker("DELETE", "/containers/" + new["Id"])
                    if row["Name"] != "/" + old["name"]:
                        self.docker(
                            "POST", "/containers/" + old["id"] + "/rename?name=" + old["name"]
                        )
                allowed = {
                    self.host.root / p
                    for p in (
                        "local-apps/mediaseed/compose.json",
                        "local-apps/mediavpn/compose.json",
                        "agent/plex-managed.json",
                        "agent/plex-plan.json",
                        "data/managed-install-recipes/mediaseed.json",
                        "data/managed-install-recipes/mediavpn.json",
                    )
                }
                for name, before in operation["files"].items():
                    target = Path(name)
                    if target not in allowed or target.resolve() != target or target.is_symlink():
                        raise self.error("App recovery path ownership changed")
                    self.save(target, before["content"])
                    os.chown(target, before["uid"], before["gid"])
                    target.chmod(before["mode"])
                state = self.host.state()
                state["appBindings"] = operation["bindings"]
                self.save(self.host.file, state)
                operation["state"] = "rolled_back"
                self.save(path, operation)
                self.write_status()
                return {"saved": True}

    def public(self):
        state = self.host.state()
        operation = self.host.folder / "app-storage-operation.json"
        interrupted = (
            operation.exists() and json.loads(operation.read_text()).get("state") == "changing"
        )
        return {
            "bindings": [
                {
                    **r,
                    "path": self.target(r["app"], r["storageId"]) + "/files",
                    "readOnly": r["app"] == "plex",
                }
                for r in state.get("appBindings", [])
            ],
            "interrupted": interrupted,
        }
