#!/usr/bin/env python3
"""Root-owned transactional MediaHub source/image updater.

The host helper consumes only Core-staged, digest-verified release
bundles. It never receives a GitHub token and never traverses media mounts.
Docker/BuildKit need outbound access to fetch base images and dependencies.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import uuid
from pathlib import Path, PurePosixPath

try:
    import fcntl
except ImportError:  # pragma: no cover - the host updater runs only on Linux
    fcntl = None

IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
ID = re.compile(r"^[a-f0-9]{32}$")
MAX_BUNDLE = 2 * 1024**3
LOADED_IMAGE = re.compile(r"^sha256:[a-f0-9]{64}$")


class BuildSpaceError(ValueError):
    """Safe numeric diagnostic; never expose arbitrary exception text."""

    def __init__(self, free):
        super().__init__(
            f"Not enough system disk space to build the update: {free / 1024**3:.2f} GiB free; "
            "at least 8 GiB required. Free unused Docker build cache or expand the system disk. "
            "Running services were not changed."
        )


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_key(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError("Invalid update version")
    return tuple(map(int, value.split(".")))


class HostUpdater:
    def __init__(self, root, runner=None, sleeper=time.sleep):
        self.root = Path(root)
        self.updates = self.root / "updates"
        self.backups = self.root / "update-backups"
        self.compose = self.root / "compose.json"
        self.policy = self.root / "update-policy.json"
        self.installed_version = self.root / "installed-version"
        self.runner = runner or self._run
        self.sleep = sleeper
        self.operation = None
        self.target = None
        self.steps = []
        self.changed_roles = ("core", "agent")
        self.pending_build_cache = None
        self.log_lines = []
        self.last_status = None
        self.private_log_block = False
        self.update_mode = None
        self.update_reason = None

    @staticmethod
    def _run(args, capture=True, on_output=None):
        source_build = args[:2] == ["docker", "build"]
        environment = None
        if source_build:
            # BuildKit needs writable client state even with ProtectHome enabled.
            # Do not inherit host registry credentials or pass GitHub tokens.
            config = Path(args[-1]).parent / "docker-client"
            config.mkdir(mode=0o700, exist_ok=True)
            environment = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(config),
                "DOCKER_CONFIG": str(config),
                "BUILDX_CONFIG": str(config / "buildx"),
                "DOCKER_HOST": "unix:///var/run/docker.sock",
            }
        if source_build and on_output:
            return HostUpdater._stream_build(args, environment, on_output)
        result = subprocess.run(
            args,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
            timeout=1800 if source_build else 600,
            env=environment,
        )
        output = result.stdout or ""
        if len(output) > 65536:
            raise ValueError("Command output exceeded safety limit")
        return output.strip()

    def command(self, *args, capture=True):
        if args[:2] == ("docker", "build") and self.runner == self._run:
            return self._run(list(map(str, args)), capture, self._build_output)
        return self.runner(list(map(str, args)), capture=capture)

    @staticmethod
    def _stream_build(args, environment, on_output):
        # Independent read/write handles avoid pipe deadlocks and preserve the
        # existing build timeout. Raw output stays in the root-only workspace.
        with tempfile.TemporaryDirectory(dir=Path(args[-1]).parent) as temporary:
            path = Path(temporary) / "build.log"
            with path.open("wb") as output:
                process = subprocess.Popen(
                    args, stdout=output, stderr=subprocess.STDOUT, env=environment
                )
                deadline = time.monotonic() + 1800
                pending = ""
                try:
                    with path.open("rb") as incoming:
                        while True:
                            chunk = incoming.read(65536)
                            if chunk:
                                pending += chunk.decode("utf-8", errors="replace")
                                lines = (
                                    pending.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                                )
                                pending = lines.pop()
                                if len(pending) > 4096:
                                    lines.append(pending[:4096])
                                    pending = ""
                                if lines:
                                    on_output(lines)
                            elif process.poll() is not None:
                                break
                            else:
                                time.sleep(0.5)
                            if time.monotonic() > deadline:
                                raise subprocess.TimeoutExpired(args, 1800)
                            if incoming.tell() > 32 * 1024**2:
                                raise ValueError("Build output exceeded safety limit")
                    if pending:
                        on_output([pending])
                    if process.returncode:
                        raise subprocess.CalledProcessError(process.returncode, args)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
        return ""

    def _append_log(self, line):
        if "-----BEGIN " in line and "PRIVATE KEY-----" in line:
            self.private_log_block = True
        if self.private_log_block:
            if "-----END " in line and "PRIVATE KEY-----" in line:
                self.private_log_block = False
            return
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
        line = re.sub(r"(?i)\b(?:github_pat_|gh[pousr]_)[a-z0-9_]+", "[redacted]", line)
        line = re.sub(r"(?i)(authorization\s*[:=]\s*|bearer\s+).*", r"\1[redacted]", line)
        line = re.sub(
            r"(?i)(token|password|passkey|secret|api[_-]?key)(\s*[:=]\s*).*",
            r"\1\2[redacted]",
            line,
        )
        line = re.sub(r"(https?://)[^/\s@]+@", r"\1[redacted]@", line)
        line = re.sub(r"(https?://[^\s?]+)\?\S+", r"\1?[redacted]", line)
        line = "".join(c for c in line if c.isprintable()).strip()
        if line:
            self.log_lines.append(time.strftime("%H:%M:%S UTC ", time.gmtime()) + line[:200])
            self.log_lines = self.log_lines[-40:]

    def _build_output(self, lines):
        for line in lines:
            self._append_log(line)
        if self.last_status:
            self.status(*self.last_status)

    @staticmethod
    def _directory(path, owner=None):
        details = path.lstat()
        if not stat.S_ISDIR(details.st_mode) or path.is_symlink():
            raise ValueError("Unsafe update directory")
        if owner is not None and details.st_uid != owner:
            raise ValueError("Unexpected update directory owner")
        return path

    @staticmethod
    def _read_json(path, limit=1024 * 1024):
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or path.is_symlink()
            or details.st_nlink != 1
            or not 0 < details.st_size <= limit
        ):
            raise ValueError("Unsafe update file")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Invalid update document")
        return value

    @staticmethod
    def _atomic_json(path, value, uid=10001, gid=10001):
        temporary = path.parent / ("." + path.name + "-" + uuid.uuid4().hex)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)

    @staticmethod
    def _atomic_text(path, value, uid=0, gid=0):
        temporary = path.parent / ("." + path.name + "-" + uuid.uuid4().hex)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)

    @staticmethod
    def _trusted_file(path, limit=65536):
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or path.is_symlink()
            or details.st_nlink != 1
            or details.st_uid != 0
            or details.st_mode & 0o022
            or not 0 < details.st_size <= limit
        ):
            raise ValueError("Unsafe root-owned update policy")
        return path.read_text(encoding="utf-8")

    def _trusted_policy(self):
        value = json.loads(self._trusted_file(self.policy))
        if set(value) not in (
            {"coreRepository", "agentRepository"},
            {"coreRepository", "agentRepository", "sourceRepository"},
        ):
            raise ValueError("Invalid update policy")
        expected = {
            "core": value["coreRepository"],
            "agent": value["agentRepository"],
        }
        if not all(
            isinstance(repository, str)
            and re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+", repository)
            for repository in expected.values()
        ):
            raise ValueError("Invalid trusted image repository")
        return expected

    def _trusted_source(self):
        value = json.loads(self._trusted_file(self.policy))
        repository = value.get("sourceRepository")
        if not isinstance(repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            raise ValueError("Source builds require an explicit trusted GitHub repository")
        return repository

    def status(self, state, progress, message):
        current = (state, progress, message)
        if current != self.last_status:
            self._append_log(message)
        self.last_status = current
        self._atomic_json(
            self.updates / "status.json",
            {
                "schemaVersion": 1,
                "state": state,
                "progress": progress,
                "message": message,
                "operationId": self.operation,
                "fromVersion": self.request.get("fromVersion"),
                "toVersion": self.target,
                "steps": self.steps,
                "logs": self.log_lines,
                "updateMode": self.update_mode,
                "updateReason": self.update_reason,
                "changedServices": list(self.changed_roles) if self.update_mode else [],
                "updatedAt": time.time(),
            },
        )

    @staticmethod
    def _tree_size(path):
        total = 0
        for root, directories, files in os.walk(path, followlinks=False):
            current = Path(root)
            for name in directories + files:
                candidate = current / name
                details = candidate.lstat()
                if stat.S_ISLNK(details.st_mode):
                    raise ValueError("Configuration backup contains a symbolic link")
                if stat.S_ISREG(details.st_mode):
                    total += details.st_size
                    if total > 8 * 1024**3:
                        raise ValueError("Configuration backup is unexpectedly large")
        return total

    def _validate_request(self):
        request_path = self.updates / "request.json"
        request = self._read_json(request_path, 65536)
        expected_fields = {
            "schemaVersion",
            "operationId",
            "fromVersion",
            "toVersion",
            "stage",
            "manifestSha256",
        }
        if request.get("schemaVersion") == 3:
            expected_fields.add("fromCommit")
            if request.get("fromCommit") is not None and not re.fullmatch(
                r"[a-f0-9]{40}", str(request["fromCommit"])
            ):
                raise ValueError("Invalid installed commit")
        if set(request) != expected_fields:
            raise ValueError("Unexpected update request fields")
        if request["schemaVersion"] not in (1, 2, 3) or not ID.fullmatch(request["operationId"]):
            raise ValueError("Invalid update request")
        if not VERSION.fullmatch(request["fromVersion"]) or not VERSION.fullmatch(
            request["toVersion"]
        ):
            raise ValueError("Invalid update version")
        expected_stage = f"staging/{request['operationId']}"
        if request["stage"] != expected_stage:
            raise ValueError("Invalid update stage")
        if not re.fullmatch(r"[a-f0-9]{64}", request["manifestSha256"]):
            raise ValueError("Invalid manifest digest")
        stage = self.updates / "staging" / request["operationId"]
        self._directory(stage, owner=10001)
        source_mode = request["schemaVersion"] in (2, 3)
        manifest_path = stage / (
            "mediahub-source-release.json" if source_mode else "mediahub-release.json"
        )
        if sha256(manifest_path) != request["manifestSha256"]:
            raise ValueError("Manifest digest mismatch")
        manifest = self._read_json(manifest_path)
        if source_mode:
            self._validate_source_manifest(manifest, request, stage)
            running = self.updates / ("running-" + request["operationId"] + ".json")
            os.replace(request_path, running)
            return request, manifest, stage
        if set(manifest) != {
            "schemaVersion",
            "version",
            "images",
            "bundles",
            "updatePolicy",
        }:
            raise ValueError("Unexpected release manifest fields")
        if manifest["schemaVersion"] != 1 or manifest["version"] != request["toVersion"]:
            raise ValueError("Release manifest version mismatch")
        if manifest["updatePolicy"] != {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        }:
            raise ValueError("Unsafe release policy")
        if set(manifest["images"]) != {"core", "agent"} or not all(
            isinstance(value, str) and IMAGE.fullmatch(value)
            for value in manifest["images"].values()
        ):
            raise ValueError("Unsafe image references")
        if set(manifest["bundles"]) != {"core", "agent"}:
            raise ValueError("Release bundles are incomplete")
        for role in ("core", "agent"):
            bundle = manifest["bundles"][role]
            expected_name = f"mediahub-{role}-image.tar.gz"
            if set(bundle) != {"name", "sha256"} or bundle["name"] != expected_name:
                raise ValueError("Unexpected release bundle")
            if not re.fullmatch(r"[a-f0-9]{64}", bundle["sha256"]):
                raise ValueError("Invalid bundle digest")
            path = stage / expected_name
            details = path.lstat()
            if (
                not stat.S_ISREG(details.st_mode)
                or path.is_symlink()
                or details.st_nlink != 1
                or not 0 < details.st_size <= MAX_BUNDLE
                or sha256(path) != bundle["sha256"]
            ):
                raise ValueError("Release bundle verification failed")
        running = self.updates / ("running-" + request["operationId"] + ".json")
        os.replace(request_path, running)
        return request, manifest, stage

    def _validate_source_manifest(self, manifest, request, stage):
        if set(manifest) != {"schemaVersion", "version", "source", "updatePolicy"}:
            raise ValueError("Unexpected source manifest fields")
        if (
            manifest["schemaVersion"] not in (2, 3)
            or manifest["schemaVersion"] != request["schemaVersion"]
            or manifest["version"] != request["toVersion"]
        ):
            raise ValueError("Source version mismatch")
        if manifest["updatePolicy"] != {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        }:
            raise ValueError("Unsafe source update policy")
        source = manifest["source"]
        if not isinstance(source, dict) or set(source) != {
            "name",
            "sha256",
            "repository",
            "commit",
        }:
            raise ValueError("Invalid source metadata")
        if (
            source["name"] != "mediahub-source.tar.gz"
            or source["repository"] != self._trusted_source()
            or not isinstance(source["commit"], str)
            or not re.fullmatch(r"[a-f0-9]{40}", source["commit"])
            or not isinstance(source["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
        ):
            raise ValueError("Untrusted source metadata")
        path = stage / source["name"]
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or path.is_symlink()
            or details.st_nlink != 1
            or not 0 < details.st_size <= 256 * 1024**2
            or sha256(path) != source["sha256"]
        ):
            raise ValueError("Source archive verification failed")

    @staticmethod
    def _extract_source(archive, destination):
        """Extract regular source files only; no links, devices or path escapes."""
        # The enclosing build workspace stays root-only (0700). Source modes
        # must remain readable after Docker COPY into non-root runtime images.
        destination.mkdir(mode=0o755)
        total = 0
        seen = set()
        with tarfile.open(archive, "r:gz") as bundle:
            for index, member in enumerate(bundle):
                path = PurePosixPath(member.name)
                if (
                    index >= 50000
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in member.name
                    or ":" in member.name
                    or not path.parts
                    or path.parts[0] != "mediahub-source"
                    or not (member.isfile() or member.isdir())
                    or path in seen
                ):
                    raise ValueError("Unsafe source archive entry")
                seen.add(path)
                if len(path.parts) == 1:
                    if not member.isdir():
                        raise ValueError("Invalid source archive root")
                    continue
                target = destination.joinpath(*path.parts[1:])
                if member.isdir():
                    target.mkdir(mode=0o755, parents=True, exist_ok=True)
                    continue
                total += member.size
                if member.size < 0 or total > 2 * 1024**3:
                    raise ValueError("Expanded source exceeds limit")
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                with bundle.extractfile(member) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
        # A systemd UMask=0077 also masks mkdir(mode=0755); explicitly normalize
        # source-only directories, never the private enclosing workspace.
        for directory, _, _ in os.walk(destination):
            Path(directory).chmod(0o755)

    @staticmethod
    def _agent_fingerprint(source):
        """Fingerprint actual Agent build inputs; unknown recipes require a full build.

        Core always builds with Docker's layer cache to publish the new release
        version. Agent can remain running when its COPY/ADD inputs are unchanged.
        Derive inputs from the recipe so adding a new copied directory cannot
        silently leave the Agent on stale code.
        """
        recipe = source / "docker/Agent.Dockerfile"
        try:
            lines = recipe.read_text(encoding="utf-8").replace("\\\n", " ").splitlines()
        except (OSError, UnicodeError):
            return None
        inputs = {recipe}
        for name in (".dockerignore", "docker/Agent.Dockerfile.dockerignore"):
            if (source / name).is_file():
                inputs.add(source / name)
        for line in lines:
            line = line.strip()
            if re.match(r"#\s*(escape|syntax)\s*=", line, re.IGNORECASE):
                return None
            if not line or line.startswith("#"):
                continue
            words = line.split(None, 1)
            instruction = words[0]
            arguments = words[1] if len(words) == 2 else ""
            # Alternate syntax, build-context mounts and ONBUILD can introduce
            # inputs this deliberately small parser cannot safely determine.
            if "--mount" in line or "<<" in line or instruction.upper() == "ONBUILD":
                return None
            if instruction.upper() not in {"COPY", "ADD"}:
                continue
            if arguments.startswith("--"):
                return None
            try:
                parts = (
                    json.loads(arguments) if arguments.startswith("[") else shlex.split(arguments)
                )
            except (ValueError, TypeError):
                return None
            if not isinstance(parts, list) or len(parts) < 2:
                return None
            for value in parts[:-1]:
                if not isinstance(value, str) or re.search(r"[\\$*?\[\]:]", value):
                    return None
                relative = PurePosixPath(value)
                if relative.is_absolute() or ".." in relative.parts:
                    return None
                path = source / relative
                if not path.exists():
                    return None
                if path.is_dir():
                    inputs.add(path)
                    inputs.update(path.rglob("*"))
                else:
                    inputs.add(path)
        digest = hashlib.sha256(b"mediahub-agent-inputs-v2\0")
        for path in sorted(inputs):
            relative = path.relative_to(source).as_posix()
            content = path.read_bytes() if path.is_file() else b""
            if relative == "pyproject.toml":
                content = re.sub(
                    rb'(?m)^version = "[0-9]+\.[0-9]+\.[0-9]+"\r?$', b'version = "release"', content
                )
            elif relative == "backend/mediahub/__init__.py":
                content = re.sub(
                    rb'(?m)^__version__ = "[0-9]+\.[0-9]+\.[0-9]+"\r?$',
                    b'__version__ = "release"',
                    content,
                )
            digest.update(relative.encode() + b"\0")
            digest.update(b"file\0" if path.is_file() else b"directory\0")
            digest.update(str(path.stat().st_mode & 0o111).encode() + b"\0")
            digest.update(hashlib.sha256(content).digest())
        return digest.hexdigest()

    def _reusable_agent(self, fingerprint):
        # Only trust an identity recorded by this root-owned helper after health
        # verification, bound to the currently configured immutable image.
        if fingerprint is None:
            return None
        try:
            cache = json.loads(self._trusted_file(self.root / "agent-build-cache.json"))
            image = cache["agentImage"]
            compose = json.loads(self._trusted_file(self.compose, 2 * 1024**2))
            if (
                cache["agentFingerprint"] == fingerprint
                and isinstance(image, str)
                and LOADED_IMAGE.fullmatch(image)
                and compose["services"]["agent"]["image"] == image
                and self.command("docker", "image", "inspect", "--format", "{{.Id}}", image)
                == image
            ):
                container = self._compose_command("ps", "-q", "agent")
                if (
                    container
                    and self.command("docker", "inspect", "--format", "{{.Image}}", container)
                    == image
                    and self.command(
                        "docker", "inspect", "--format", "{{.State.Running}}", container
                    )
                    == "true"
                ):
                    return image
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            pass
        return None

    def _build_source_images(self, stage, manifest):
        """Build before stopping services. Never pass credentials or host data to Docker."""
        free = shutil.disk_usage(self.root).free
        if free < 8 * 1024**3:
            raise BuildSpaceError(free)
        workspace = self.root / ("source-build-" + self.operation)
        workspace.mkdir(mode=0o700)
        try:
            archive = workspace / "source.tar.gz"
            shutil.copyfile(stage / manifest["source"]["name"], archive)
            # Recheck the private, root-owned copy, not the mutable Core-owned spool.
            if sha256(archive) != manifest["source"]["sha256"]:
                raise ValueError("Source changed while preparing the build")
            source = workspace / "source"
            self._extract_source(archive, source)
            project = tomllib.loads((source / "pyproject.toml").read_text())
            if project.get("project", {}).get("version") != manifest["version"]:
                raise ValueError("Source version does not match requested version")
            images = {}
            fingerprint = self._agent_fingerprint(source)
            reusable_agent = self._reusable_agent(fingerprint)
            self.changed_roles = ("core",) if reusable_agent else ("core", "agent")
            self.update_mode = "fast" if reusable_agent else "full"
            self.update_reason = (
                "Agent build inputs are unchanged; only Core needs rebuilding."
                if reusable_agent
                else "Agent inputs changed or no verified reusable Agent image is available."
            )
            if fingerprint is None:
                self.update_reason = (
                    "Agent build inputs could not be determined; rebuilding both services."
                )
            self.status(
                "building",
                61,
                ("Fast update selected. " if reusable_agent else "Full update selected. ")
                + self.update_reason,
            )
            for step in self.steps:
                if step["id"] == "build":
                    step["label"] = (
                        "Fast update: build Core only" if reusable_agent else "Build Core and Agent"
                    )
            for index, role in enumerate(("core", "agent")):
                if role == "agent" and reusable_agent:
                    images[role] = reusable_agent
                    self.status("building", 67, "Agent source unchanged; keeping the running Agent")
                    continue
                self.status(
                    "building", 62 + index * 5, f"Building {role} from GitHub source on this server"
                )
                dockerfile = "docker/Dockerfile" if role == "core" else "docker/Agent.Dockerfile"
                if not (source / dockerfile).is_file():
                    raise ValueError("Source Dockerfile is missing")
                tag = f"mediahub-{role}:source-{manifest['version']}-{manifest['source']['sha256'][:12]}"
                self.command(
                    "docker",
                    "build",
                    "--progress=plain",
                    "--file",
                    source / dockerfile,
                    "--tag",
                    tag,
                    "--label",
                    "org.opencontainers.image.revision=" + manifest["source"]["commit"],
                    source,
                    capture=False,
                )
                image_id = self.command("docker", "image", "inspect", "--format", "{{.Id}}", tag)
                if not LOADED_IMAGE.fullmatch(image_id):
                    raise ValueError("Source build did not produce a valid image")
                # Exercise the image's actual non-root user before downtime.
                # No network, host mounts, credentials or production state.
                self.command(
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--memory",
                    "128m",
                    "--pids-limit",
                    "64",
                    "--entrypoint",
                    "python",
                    image_id,
                    "-c",
                    "import agent, mediahub, os; from pathlib import Path; "
                    "assert os.geteuid() != 0; "
                    "assert all(os.access(p, os.R_OK | (os.X_OK if p.is_dir() else 0)) "
                    "for root in ('/app/agent', '/app/backend', '/app/apps') "
                    "for p in Path(root).rglob('*'))",
                    capture=False,
                )
                images[role] = image_id
            self.pending_build_cache = {
                "agentFingerprint": fingerprint,
                "agentImage": images["agent"],
            }
            return images
        finally:
            shutil.rmtree(workspace)

    def _compose_command(self, *args, capture=True):
        return self.command("docker", "compose", "-f", self.compose, *args, capture=capture)

    def _load_release_image(self, role, stage, manifest):
        """Load a verified offline bundle and give its image an immutable local tag.

        Docker archives exported from a registry digest can legitimately load by
        image ID only.  The bundle hash has already been validated against the
        trusted release manifest, so the loaded ID is safe to bind to a local,
        version-and-bundle-specific tag without contacting a registry.
        """
        bundle = manifest["bundles"][role]
        output = self.command("docker", "load", "--input", stage / bundle["name"])
        candidates = []
        for line in output.splitlines():
            for prefix in ("Loaded image ID: ", "Loaded image: "):
                if line.startswith(prefix):
                    candidates.append(line.removeprefix(prefix).strip())
        if len(candidates) != 1:
            raise ValueError("Offline image bundle did not identify exactly one image")
        image_id = self.command("docker", "image", "inspect", "--format", "{{.Id}}", candidates[0])
        if not LOADED_IMAGE.fullmatch(image_id):
            raise ValueError("Offline image bundle returned an invalid image ID")
        local_tag = f"mediahub-{role}:release-{manifest['version']}-{bundle['sha256'][:12]}"
        self.command("docker", "tag", image_id, local_tag)
        inspected = self.command("docker", "image", "inspect", "--format", "{{.Id}}", local_tag)
        if inspected != image_id:
            raise ValueError("Offline image tag verification failed")
        return local_tag

    def _wait(self, service, health=False, timeout=150):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            identifier = self._compose_command("ps", "-q", service)
            if identifier:
                template = "{{.State.Health.Status}}" if health else "{{.State.Running}}"
                state = self.command("docker", "inspect", "--format", template, identifier)
                if state == ("healthy" if health else "true"):
                    return
            self.sleep(2)
        raise ValueError(f"{service} did not become healthy")

    def installed_source(self):
        path = self.updates / "installed-source.json"
        if not path.exists():
            return {}
        value = json.loads(self._trusted_file(path, 4096))
        if not isinstance(value, dict) or not re.fullmatch(
            r"[a-f0-9]{40}", str(value.get("commit", ""))
        ):
            raise ValueError("Invalid installed source marker")
        return value

    def write_installed_source(self, source):
        path = self.updates / "installed-source.json"
        self._atomic_json(
            path, {"repository": source["repository"], "commit": source["commit"]}, uid=0, gid=0
        )
        path.chmod(0o644)

    def _backup_preflight(self):
        total = sum(self._tree_size(self.root / name) for name in self._state_directories())
        if shutil.disk_usage(self.root).free < total * 2 + 1024**3:
            raise ValueError("Insufficient space for rollback snapshot")
        return total

    def _state_directories(self):
        return tuple("data" if role == "core" else "agent" for role in self.changed_roles)

    def _copy_configuration(self, backup):
        temporary = self.backups / ("." + self.operation + "-preparing")
        if backup.exists() or temporary.exists():
            raise ValueError("Rollback snapshot destination already exists")
        temporary.mkdir(mode=0o700, parents=True)
        try:
            shutil.copy2(self.compose, temporary / "compose.json")
            shutil.copy2(self.installed_version, temporary / "installed-version")
            marker = self.updates / "installed-source.json"
            if marker.exists():
                self.installed_source()  # Validate before copying root-owned metadata.
                shutil.copy2(marker, temporary / "installed-source.json")
            for name in self._state_directories():
                shutil.copytree(self.root / name, temporary / name, symlinks=False)
                self._copy_ownership(self.root / name, temporary / name)
            os.replace(temporary, backup)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _copy_ownership(source, destination):
        # copytree/copy2 preserve modes and timestamps, not uid/gid. Losing
        # ownership makes restored secrets unreadable to non-root containers.
        if not hasattr(os, "chown"):
            return
        for original in [source, *source.rglob("*")]:
            details = original.lstat()
            if stat.S_ISLNK(details.st_mode):
                raise ValueError("Configuration ownership reference contains a symbolic link")
            target = destination / original.relative_to(source)
            if target.is_symlink():
                raise ValueError("Configuration ownership destination contains a symbolic link")
            os.chown(target, details.st_uid, details.st_gid, follow_symlinks=False)

    def _restore_configuration(self, backup):
        self._compose_command("stop", "-t", "30", *self.changed_roles, capture=False)
        shutil.copy2(backup / "compose.json", self.compose)
        if (backup / "installed-version").exists():
            shutil.copy2(backup / "installed-version", self.installed_version)
        marker = self.updates / "installed-source.json"
        if (backup / "installed-source.json").exists():
            shutil.copy2(backup / "installed-source.json", marker)
        else:
            marker.unlink(missing_ok=True)
        for name in self._state_directories():
            current = self.root / name
            failed = self.root / f"{name}.failed-{self.operation}"
            if failed.exists():
                raise ValueError("Rollback destination already exists")
            os.replace(current, failed)
            try:
                shutil.copytree(backup / name, current, symlinks=False)
                self._copy_ownership(backup / name, current)
            except Exception:
                if current.exists():
                    shutil.rmtree(current)
                os.replace(failed, current)
                raise
        if "agent" in self.changed_roles:
            self._compose_command("up", "-d", "--no-deps", "agent", capture=False)
        self._wait("agent")
        self._compose_command("up", "-d", "--no-deps", "core", capture=False)
        self._wait("core", health=True)

    def _cleanup_update_images(self):
        """Only remove owned source tags, preserving containers and rollback images."""
        protected = set()
        compose_files = [self.compose] + [
            path / "compose.json" for path in self.backups.iterdir() if path.is_dir()
        ]
        for path in compose_files:
            value = self._read_json(path, 2 * 1024 * 1024)
            for role in ("core", "agent"):
                reference = value["services"][role]["image"]
                image = self.command("docker", "image", "inspect", "--format", "{{.Id}}", reference)
                if not LOADED_IMAGE.fullmatch(image):
                    raise ValueError("Rollback image could not be verified")
                protected.add(image)
        containers = self.command("docker", "ps", "-aq").splitlines()
        for container in containers:
            image = self.command("docker", "inspect", "--format", "{{.Image}}", container)
            if not LOADED_IMAGE.fullmatch(image):
                raise ValueError("Container image could not be verified")
            protected.add(image)
        candidates = {}
        listing = self.command("docker", "image", "ls", "--no-trunc", "--format", "{{json .}}")
        for line in listing.splitlines():
            row = json.loads(line)
            image = row["ID"]
            tag = row["Repository"] + ":" + row["Tag"]
            candidates.setdefault(image, []).append(tag)
        removed = 0
        for image, tags in candidates.items():
            if image in protected or not LOADED_IMAGE.fullmatch(image):
                continue
            if not all(
                re.fullmatch(
                    r"mediahub-(core|agent):source-[0-9]+\.[0-9]+\.[0-9]+-[a-f0-9]{12}", tag
                )
                for tag in tags
            ):
                continue
            # No --force: Docker provides a final guard against container use.
            self.command("docker", "image", "rm", *tags)
            removed += len(tags)
        self._append_log(
            f"Cleanup removed {removed} unused MediaHub source tags; rollback images retained"
        )

    def _cleanup_after_success(self, stage):
        # Maintenance is best effort and must never roll back a verified update.
        try:
            shutil.rmtree(stage)
            backups = sorted(
                (path for path in self.backups.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for old in backups[2:]:
                if old.is_symlink() or old.resolve().parent != self.backups.resolve():
                    raise ValueError("Unsafe backup path")
                shutil.rmtree(old)
            self._cleanup_update_images()
            self.command(
                "docker",
                "builder",
                "prune",
                "--force",
                "--filter",
                "until=24h",
                "--keep-storage",
                "4GB",
            )
        except Exception:
            self._append_log("Update succeeded; some optional cleanup could not be completed")
        self.status("succeeded", 100, f"MediaHub {self.target} installed successfully")

    def process(self):
        if fcntl is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise ValueError("Host updater must run as root")
        self._directory(self.root)
        self._directory(self.updates, owner=10001)
        self._directory(self.updates / "staging", owner=10001)
        if self.root == Path("/") or self.root.is_symlink() or not self.compose.is_file():
            raise ValueError("Unsafe MediaHub root")
        self.backups.mkdir(mode=0o700, exist_ok=True)
        lock_path = self.updates / "host-updater.lock"
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            request = manifest = stage = backup = None
            services_stopped = False
            try:
                request, manifest, stage = self._validate_request()
                self.request = request
                self.operation = request["operationId"]
                self.target = request["toVersion"]
                source_mode = manifest.get("schemaVersion") in (2, 3)
                self.steps = [
                    {"id": "download", "label": "Download verified release", "state": "complete"},
                    {"id": "backup", "label": "Back up configuration", "state": "running"},
                    {"id": "replace", "label": "Replace Core and Agent", "state": "pending"},
                    {"id": "verify", "label": "Verify health or roll back", "state": "pending"},
                ]
                installed = self._trusted_file(self.installed_version, 128).strip()
                if request["fromVersion"] != installed:
                    raise ValueError("Installed version does not match the update request")
                if manifest.get("schemaVersion") == 3:
                    previous_source = self.installed_source()
                    previous_commit = (
                        previous_source.get("commit")
                        if previous_source.get("repository") == self._trusted_source()
                        else None
                    )
                    if request.get("fromCommit") != previous_commit:
                        raise ValueError("Installed commit does not match the update request")
                    if manifest["source"]["commit"] == previous_commit:
                        raise ValueError("Source commit is already installed")
                    if version_key(self.target) < version_key(installed):
                        raise ValueError("Source version must not downgrade")
                elif version_key(self.target) <= version_key(installed):
                    raise ValueError("Update must move to a newer stable version")
                built_images = None
                if source_mode:
                    self._validate_source_manifest(manifest, request, stage)
                    self.steps[0]["label"] = "Download verified source"
                    self.steps.insert(
                        1, {"id": "build", "label": "Build on this server", "state": "running"}
                    )
                    self.steps[2]["state"] = "pending"
                    built_images = self._build_source_images(stage, manifest)
                    if self.changed_roles == ("core",):
                        self.steps[3]["label"] = "Replace Core; keep unchanged Agent"
                    self.steps[1]["state"] = "complete"
                    self.steps[2]["state"] = "running"
                else:
                    trusted_repositories = self._trusted_policy()
                    for role in ("core", "agent"):
                        repository = manifest["images"][role].partition("@")[0]
                        if repository != trusted_repositories[role]:
                            raise ValueError("Release image is outside the trusted repository")
                offset = 1 if source_mode else 0
                self.status("installing", 70, "Stopping changed services for a safe snapshot")
                compose = self._read_json(self.compose, 2 * 1024 * 1024)
                if compose.get("name") != "mediahub-platform" or set(
                    compose.get("services", {})
                ) < {"core", "agent"}:
                    raise ValueError("Compose ownership validation failed")
                self._backup_preflight()
                services_stopped = True
                self._compose_command("stop", "-t", "30", *self.changed_roles, capture=False)
                backup_destination = self.backups / self.operation
                self._copy_configuration(backup_destination)
                backup = backup_destination
                self.steps[1 + offset]["state"] = "complete"
                self.steps[2 + offset]["state"] = "running"
                self.status("installing", 72, "Applying images for changed services")
                for role in self.changed_roles:
                    compose["services"][role]["image"] = (
                        built_images[role]
                        if built_images
                        else self._load_release_image(role, stage, manifest)
                    )
                    compose["services"][role].pop("build", None)
                    compose["services"][role]["pull_policy"] = "never"
                self._atomic_json(self.compose, compose, uid=0, gid=0)
                if "agent" in self.changed_roles:
                    self._compose_command("up", "-d", "--no-deps", "agent", capture=False)
                self._wait("agent")
                self._compose_command("up", "-d", "--no-deps", "core", capture=False)
                self.steps[2 + offset]["state"] = "complete"
                self.steps[-1]["state"] = "running"
                self.status("verifying", 90, "Verifying the updated MediaHub services")
                self._wait("core", health=True)
                if self.pending_build_cache is not None:
                    self._atomic_json(
                        self.root / "agent-build-cache.json",
                        self.pending_build_cache,
                        uid=0,
                        gid=0,
                    )
                self._atomic_text(self.installed_version, self.target)
                if source_mode:
                    self.write_installed_source(manifest["source"])
                self.steps[-1]["state"] = "complete"
                self.status("succeeded", 100, f"MediaHub {self.target} installed successfully")
                self._cleanup_after_success(stage)
            except Exception as error:
                if request is None:
                    raise
                if not services_stopped:
                    for step in self.steps:
                        if step["state"] == "running":
                            step["state"] = "error"
                    self.status(
                        "failed",
                        100,
                        str(error)
                        if isinstance(error, BuildSpaceError)
                        else "Update was rejected before any running service was changed",
                    )
                    return
                try:
                    self.steps[-1]["state"] = "running"
                    self.status("rolling_back", 95, "Update failed; restoring the previous version")
                    if backup and backup.is_dir():
                        self._restore_configuration(backup)
                    elif services_stopped:
                        if "agent" in self.changed_roles:
                            self._compose_command("up", "-d", "--no-deps", "agent", capture=False)
                        self._wait("agent")
                        self._compose_command("up", "-d", "--no-deps", "core", capture=False)
                        self._wait("core", health=True)
                    self.steps[-1]["state"] = "complete"
                    self.status(
                        "rolled_back", 100, "Update failed and the previous version was restored"
                    )
                except Exception:
                    self.steps[-1]["state"] = "error"
                    self.status(
                        "failed",
                        100,
                        "Update and automatic rollback failed; administrator recovery is required",
                    )
                    raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/opt/mediahub")
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_absolute() or root == Path("/") or ".." in root.parts:
        raise ValueError("Use a bounded absolute MediaHub root")
    HostUpdater(root).process()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        print("MediaHub host update failed; inspect the protected status file", file=sys.stderr)
        raise SystemExit(1)
