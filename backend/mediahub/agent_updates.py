"""Commit-based updates for the paired Seedbox Agent, including legacy bootstrap."""

import asyncio
import hashlib
import io
import json
import shlex
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import paramiko
from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field, SecretStr, model_validator
from sqlalchemy import select

from mediahub.contracts import StrictModel
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.fjordhub_deploy import PinnedKey, SSHAddress, clean_line, probe
from mediahub.platform_source import GitHubSourceProvider, download_source, normalize_source

KEY = "seedbox.agent.update"
SSH_KEY = "seedbox.agent.ssh.encrypted"
SSH_KEY_V2 = "seedbox.agent.ssh.v2.encrypted"
GENERATED_KEY = "seedbox.agent.ssh.generated.encrypted"


class SSHSetup(StrictModel):
    password: SecretStr | None = Field(default=None, min_length=1, max_length=1024)
    private_key: SecretStr | None = Field(default=None, min_length=1, max_length=16384)
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    port: int = Field(default=22, ge=1, le=65535)
    remember: bool = False

    @model_validator(mode="after")
    def one_credential(self):
        if (self.password is None) == (self.private_key is None):
            raise ValueError("Provide either an SSH password or a private key")
        return self

    def credentials(self):
        return {
            name: value.get_secret_value()
            for name, value in (("password", self.password), ("private_key", self.private_key))
            if value is not None
        }

    def log_line(self, line):
        for value in self.credentials().values():
            if value:
                for part in value.splitlines():
                    line = line.replace(part, "[redacted]")
        return clean_line(line, "")


class AgentUpdates:
    def __init__(self, svc):
        self.svc = svc
        self.lock = threading.RLock()
        self.prepared = None
        state = self.operation()
        if state["state"] in {"running", "building", "installing", "verifying", "rolling_back"}:
            self.save(
                {
                    **state,
                    "state": "interrupted",
                    "message": "Core restarted. Inspect the remote job before retrying; unverified installs roll back after two minutes.",
                }
            )

    def binding(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
            identifier = row.value.get("hostId") if row else None
        if not identifier or identifier == "local":
            raise DomainError("agent_host_required", "No separate Seedbox Agent is paired", 409)
        client = self.svc.hosts.client(identifier)
        address = SSHAddress(host=urlsplit(client.config.agent_url).hostname)
        return identifier, client, address

    def ready(self, identifier):
        with self.lock:
            if self.prepared and self.prepared[1] <= time.monotonic():
                self.prepared = None
            return bool(self.prepared and self.prepared[0] == identifier)

    def saved_setup(self, identifier, address):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == SSH_KEY_V2))
            if row is None:
                row = db.scalar(select(Setting).where(Setting.key == SSH_KEY))
            encrypted = row.value.get("encrypted") if row else None
        if not encrypted:
            return None
        try:
            value = json.loads(self.svc.catalog.cipher.decrypt(encrypted.encode()))
            if value["hostId"] != identifier or value["host"] != address.host:
                return None
            return SSHSetup(**value["setup"])
        except (InvalidToken, ValueError, KeyError, TypeError, AttributeError):
            raise DomainError(
                "agent_ssh_storage",
                "Saved SSH access cannot be decrypted; forget it and prepare SSH again",
                409,
            ) from None

    def save_setup(self, identifier, address, setup):
        payload = {
            "hostId": identifier,
            "host": address.host,
            "setup": {
                **setup.model_dump(mode="json", exclude_none=True),
                **setup.credentials(),
            },
        }
        encrypted = self.svc.catalog.cipher.encrypt(json.dumps(payload).encode()).decode()
        with self.svc.sessions.begin() as db:
            storage_key = SSH_KEY_V2 if setup.private_key else SSH_KEY
            old = db.scalar(
                select(Setting).where(Setting.key == (SSH_KEY if setup.private_key else SSH_KEY_V2))
            )
            if old:
                db.delete(old)
            row = db.scalar(select(Setting).where(Setting.key == storage_key))
            if row:
                row.value = {"encrypted": encrypted}
            else:
                db.add(Setting(key=storage_key, value={"encrypted": encrypted}))

    def forget_setup(self):
        with self.lock, self.svc.sessions.begin() as db:
            for row in db.scalars(
                select(Setting).where(Setting.key.in_([SSH_KEY, SSH_KEY_V2, GENERATED_KEY]))
            ):
                db.delete(row)
            self.prepared = None
        return {"credentialsStored": False, "installReady": False}

    def generated_setup(self, identifier, address):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == GENERATED_KEY))
            encrypted = row.value.get("encrypted") if row else None
        if not encrypted:
            return None
        try:
            value = json.loads(self.svc.catalog.cipher.decrypt(encrypted.encode()))
            if value["hostId"] != identifier or value["host"] != address.host:
                return None
            return value
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise DomainError(
                "agent_ssh_storage", "Generated SSH access cannot be decrypted", 409
            ) from None

    def generated_access(self, create=False):
        identifier, _, address = self.binding()
        with self.lock:
            value = self.generated_setup(identifier, address)
            if value is None and create:
                key = Ed25519PrivateKey.generate()
                value = {
                    "hostId": identifier,
                    "host": address.host,
                    "private_key": key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.OpenSSH,
                        serialization.NoEncryption(),
                    ).decode(),
                    "publicKey": key.public_key()
                    .public_bytes(
                        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
                    )
                    .decode()
                    + " mediahub-agent-updates",
                }
                encrypted = self.svc.catalog.cipher.encrypt(json.dumps(value).encode()).decode()
                with self.svc.sessions.begin() as db:
                    row = db.scalar(select(Setting).where(Setting.key == GENERATED_KEY))
                    if row:
                        row.value = {"encrypted": encrypted}
                    else:
                        db.add(Setting(key=GENERATED_KEY, value={"encrypted": encrypted}))
            if value is None:
                return {"created": False, "host": address.host}
            public = shlex.quote(value["publicKey"])
            script = (
                'test "$(id -u)" -eq 0 || { echo "Run this command as root" >&2; exit 1; }; '
                "install -d -m 700 -o root -g root /root/.ssh && "
                "touch /root/.ssh/authorized_keys && "
                "chown root:root /root/.ssh/authorized_keys && "
                "chmod 600 /root/.ssh/authorized_keys && "
                f"(grep -qxF -- {public} /root/.ssh/authorized_keys || "
                f"printf '\\n%s\\n' {public} >> /root/.ssh/authorized_keys) && "
                "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"
            )
            return {
                "created": True,
                "host": address.host,
                "publicKey": value["publicKey"],
                "command": "sh -c " + shlex.quote(script),
            }

    def prepare_generated(self, fingerprint, port):
        identifier, _, address = self.binding()
        with self.lock:
            value = self.generated_setup(identifier, address)
            if value is None:
                raise DomainError("agent_ssh_required", "Create update access first", 409)
            result = self.prepare(
                SSHSetup(
                    private_key=value["private_key"],
                    fingerprint=fingerprint,
                    port=port,
                    remember=True,
                )
            )
            with self.svc.sessions.begin() as db:
                row = db.scalar(select(Setting).where(Setting.key == GENERATED_KEY))
                if row:
                    db.delete(row)
            return result

    def prepare_saved(self, fingerprint=None, port=None):
        identifier, _, address = self.binding()
        setup = self.saved_setup(identifier, address)
        if setup is None:
            raise DomainError("agent_ssh_required", "No saved SSH access for this host", 409)
        if fingerprint is not None:
            setup = SSHSetup(
                **{**setup.model_dump(), "fingerprint": fingerprint, "port": port, "remember": True}
            )
        return self.prepare(setup)

    async def check(self):
        identifier, client, address = self.binding()
        version = await client.request("GET", "/v1/version")
        checked = await GitHubSourceProvider(
            version.get("version", "unknown"), version.get("sourceCommit")
        ).check(self.svc.settings.get().release_repository, self.svc.release_credentials.token())
        stored = self.saved_setup(identifier, address) is not None
        return {
            **checked,
            "id": "seedbox-agent",
            "name": "Seedbox Agent",
            "host": address.host,
            "hostId": identifier,
            "installReady": self.ready(identifier) or stored,
            "credentialsStored": stored,
            "installedVersion": version.get("sourceCommit") or version.get("version"),
            "message": checked.get("message")
            if checked.get("configured") is False
            else "Agent code on GitHub main; prepare SSH below to install"
            if checked["updateAvailable"]
            else "Seedbox Agent matches GitHub main",
        }

    def operation(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            return (
                dict(row.value)
                if row
                else {"state": "idle", "message": "No Agent update started", "logs": []}
            )

    def save(self, value):
        with self.svc.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            if row:
                row.value = dict(value)
            else:
                db.add(Setting(key=KEY, value=dict(value)))

    @staticmethod
    def connect(address, setup):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(PinnedKey(setup.fingerprint))
        try:
            pkey = None
            if setup.private_key:
                for key_type in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
                    try:
                        pkey = key_type.from_private_key(
                            io.StringIO(setup.private_key.get_secret_value())
                        )
                        break
                    except (paramiko.SSHException, ValueError):
                        continue
                if pkey is None:
                    raise DomainError(
                        "agent_ssh_key",
                        "Use a valid unencrypted OpenSSH or PEM private key; MediaHub encrypts saved keys",
                        409,
                    )
            client.connect(
                address.host,
                port=setup.port,
                username="root",
                password=setup.password.get_secret_value() if setup.password else None,
                pkey=pkey,
                allow_agent=False,
                look_for_keys=False,
                timeout=10,
                banner_timeout=10,
                auth_timeout=15,
            )
            return client
        except DomainError:
            client.close()
            raise
        except paramiko.BadAuthenticationType as exc:
            client.close()
            message = (
                "This server requires SSH key authentication. Select SSH private key instead of password."
                if "publickey" in exc.allowed_types and "password" not in exc.allowed_types
                else "This SSH authentication method is not accepted by the server"
            )
            raise DomainError("agent_ssh_auth_method", message, 409) from None
        except Exception:
            client.close()
            raise DomainError(
                "agent_ssh_failed", "SSH login or fingerprint verification failed", 409
            ) from None

    def prepare(self, setup):
        identifier, _, address = self.binding()
        client = self.connect(address, setup)
        try:
            previous = self.operation()
            if previous["state"] == "interrupted" and previous.get("hostId") == identifier:
                remote = "/var/lib/mediahub-agent-updates/" + previous["operationId"]
                with client.open_sftp() as sftp:
                    with sftp.open(remote + "/status.json") as state:
                        current = json.loads(state.read(8192))
                    if current["state"] in {"succeeded", "failed", "rolled_back"}:
                        self.save({**previous, **current})
                    else:
                        raise DomainError(
                            "agent_update_busy",
                            "Previous remote job is still running; wait for completion or rollback",
                            409,
                        )
        finally:
            client.close()
        with self.lock:
            if setup.remember:
                self.save_setup(identifier, address, setup)
            else:
                self.forget_setup()
            self.prepared = (identifier, time.monotonic() + 900, setup)

        def expire():
            with self.lock:
                if self.prepared and self.prepared[2] is setup:
                    self.prepared = None

        timer = threading.Timer(900, expire)
        timer.daemon = True
        timer.start()
        return {
            "installReady": True,
            "credentialsStored": setup.remember,
            "message": "SSH verified and saved encrypted on this MediaHub server"
            if setup.remember
            else "SSH verified for one update within 15 minutes; credentials are held only in memory",
        }

    def fingerprint(self, port):
        _, _, address = self.binding()
        return probe(SSHAddress(host=address.host, port=port))

    async def start(self):
        checked = await self.check()
        identifier, client, address = self.binding()
        with self.lock:
            previous = self.operation()
            if previous["state"] in {
                "running",
                "building",
                "installing",
                "verifying",
                "rolling_back",
                "interrupted",
            }:
                raise DomainError(
                    "agent_update_busy",
                    "Inspect or finish the existing Agent update before starting another",
                    409,
                )
            if not checked["updateAvailable"]:
                raise DomainError("agent_current", "Agent already matches GitHub main", 409)
            setup = (
                self.prepared[2]
                if self.ready(identifier)
                else self.saved_setup(identifier, address)
            )
            if setup is None:
                raise DomainError(
                    "agent_ssh_required", "Prepare the Seedbox Agent SSH connection first", 409
                )
            self.prepared = None
            job = {
                "operationId": uuid4().hex,
                "state": "running",
                "message": "Downloading verified GitHub source",
                "logs": [],
                "commit": checked["latestCommit"],
                "hostId": identifier,
            }
            self.save(job)
            threading.Thread(
                target=self.run, args=(job, checked, client, address, setup), daemon=True
            ).start()
        return job

    def run(self, job, checked, agent, address, setup):
        ssh = None
        launched = False
        try:
            with tempfile.TemporaryDirectory(prefix="mediahub-agent-") as directory:
                root = Path(directory)

                async def download():
                    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                        await download_source(
                            client,
                            checked["repository"],
                            checked["latestCommit"],
                            root / "download.tar.gz",
                            self.svc.release_credentials.token(),
                        )

                asyncio.run(download())
                digest = normalize_source(root / "download.tar.gz", root / "source.tar.gz")
                ssh = self.connect(address, setup)
                _, stdout, _ = ssh.exec_command(
                    "python3 -c 'import sys,tarfile; assert sys.version_info >= (3,11) and hasattr(tarfile,\"data_filter\")'",
                    timeout=15,
                )
                if stdout.channel.recv_exit_status() != 0:
                    raise ValueError("Remote host requires Python 3.11 with safe tar extraction")
                remote = "/var/lib/mediahub-agent-updates/" + job["operationId"]
                command = (
                    "test ! -L /var/lib/mediahub-agent-updates && install -d -m 0700 /var/lib/mediahub-agent-updates && mkdir -m 0700 "
                    + remote
                )
                _, stdout, _ = ssh.exec_command(command, timeout=15)
                if stdout.channel.recv_exit_status() != 0:
                    raise ValueError("Remote staging unavailable")
                with ssh.open_sftp() as sftp:
                    sftp.put(str(root / "source.tar.gz"), remote + "/source.tar.gz")
                    sftp.put(
                        str(Path(__file__).with_name("agent_update_worker.py")),
                        remote + "/worker.py",
                    )
                    manifest = {
                        "commit": checked["latestCommit"],
                        "sha256": digest,
                        "tokenDigest": hashlib.sha256(agent.token.encode()).hexdigest(),
                    }
                    with sftp.open(remote + "/manifest.json", "w") as out:
                        out.write(json.dumps(manifest))
                    _, stdout, _ = ssh.exec_command(
                        "nohup python3 "
                        + remote
                        + "/worker.py >"
                        + remote
                        + "/console.log 2>&1 < /dev/null &",
                        timeout=15,
                    )
                    if stdout.channel.recv_exit_status() != 0:
                        raise ValueError("Remote worker not started")
                    launched = True
                    deadline = time.monotonic() + 4500
                    build_offset = 0
                    while time.monotonic() < deadline:
                        try:
                            with sftp.open(remote + "/status.json") as state:
                                current = json.loads(state.read(8192))
                        except FileNotFoundError:
                            time.sleep(2)
                            continue
                        try:
                            with sftp.open(remote + "/build.log") as build:
                                build.seek(build_offset)
                                data = build.read(8192)
                                build_offset += len(data)
                                for line in data.decode("utf-8", errors="replace").splitlines():
                                    safe = setup.log_line(line)
                                    if safe:
                                        job["logs"] = (job["logs"] + [safe])[-200:]
                        except FileNotFoundError:
                            pass
                        if current["message"] != job["message"]:
                            job["logs"] = (job["logs"] + [current["message"]])[-200:]
                        job.update(current)
                        self.save(job)
                        if current["state"] == "verifying":
                            verification_message = None
                            try:
                                version = asyncio.run(agent.request("GET", "/v1/version"))
                                if version.get("sourceCommit") == checked["latestCommit"]:
                                    with sftp.open(remote + "/accepted", "w") as accept:
                                        accept.write(checked["latestCommit"])
                                else:
                                    verification_message = "Verification: Agent responded, but its installed commit does not match the requested update"
                            except DomainError as error:
                                verification_message = "Verification: " + setup.log_line(str(error))
                            if verification_message and verification_message not in job["logs"]:
                                job["logs"] = (job["logs"] + [verification_message])[-200:]
                                self.save(job)
                        if current["state"] in {"succeeded", "failed", "rolled_back"}:
                            return
                        time.sleep(2)
                    raise TimeoutError()
        except Exception as error:
            # Only expose known, controlled SSH errors. Download and transport
            # exceptions can contain credentials or signed source URLs.
            code = error.code if isinstance(error, DomainError) else "agent_update_failed"
            details = {
                "ssh_host_key_changed": "SSH fingerprint differs; no commands ran",
                "agent_ssh_failed": "SSH login or fingerprint verification failed",
                "agent_ssh_auth_method": "This SSH authentication method is not accepted by the server",
                "agent_ssh_key": "Use a valid unencrypted OpenSSH or PEM private key; MediaHub encrypts saved keys",
            }
            detail = details.get(code)
            job.update(
                state="interrupted" if launched else "failed",
                message="Agent update connection failed. Inspect the job on the Seedbox host; unverified installs roll back after two minutes."
                if launched
                else "Source download or SSH staging failed; the Agent was not changed.",
                errorCode=code,
            )
            if detail:
                job["logs"] = (job["logs"] + [detail])[-200:]
                if not launched:
                    job["message"] = detail
            self.save(job)
        finally:
            if ssh:
                ssh.close()
