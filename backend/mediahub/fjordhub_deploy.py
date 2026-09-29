"""Bounded, administrator-initiated FjordHub deployment over pinned SSH.

Only structured configuration is accepted. Credentials stay in worker memory;
durable job state contains neither credentials nor arbitrary executable input.
"""

import base64
import hashlib
import json
import re
import socket
import threading
import time
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import paramiko
from pydantic import Field, SecretStr, field_validator, model_validator
from sqlalchemy import select

from mediahub.contracts import StrictModel
from mediahub.db import Setting, now
from mediahub.errors import DomainError

PREFIX = "fjordhub.deployment."
TEMPLATES = json.loads(Path(__file__).with_name("fjordhub_scripts.json").read_text())


class DeployConfig(StrictModel):
    target: Literal["lxc", "linux"] = "lxc"
    installPath: str = "/opt/fjordhub"
    dataPath: str = "/srv/mediahub/appdata/fjordhub"
    appPort: str = "8888"
    timezone: str = "Europe/Copenhagen"
    ctid: str = ""
    hostname: str = "fjordhub"
    templateStorage: str = "local"
    storage: str = "local-lvm"
    bridge: str = "vmbr0"
    cores: str = "4"
    memory: str = "10240"
    disk: str = "24"
    dataDisk: str = "32"
    network: Literal["dhcp", "static"] = "dhcp"
    address: str = ""
    gateway: str = ""

    @model_validator(mode="after")
    def validate_config(self):
        for path in (self.installPath, self.dataPath):
            if (
                len(path) > 512
                or not re.fullmatch(r"/(opt|srv|mnt)/[A-Za-z0-9_./-]+", path)
                or any(p in {"", ".", ".."} for p in path.split("/")[1:])
            ):
                raise ValueError("Use a dedicated path under /opt, /srv or /mnt")
        if (
            self.installPath == self.dataPath
            or self.installPath.startswith(self.dataPath + "/")
            or self.dataPath.startswith(self.installPath + "/")
        ):
            raise ValueError("Source and data paths must be separate")
        for field, low, high in (
            ("appPort", 1, 65535),
            ("cores", 1, 128),
            ("memory", 1024, 1048576),
            ("disk", 16, 65536),
            ("dataDisk", 1, 65536),
            ("ctid", 100, 999999999),
        ):
            value = getattr(self, field)
            if field == "ctid" and not value:
                continue
            if not re.fullmatch(r"[0-9]{1,10}", value) or not low <= int(value) <= high:
                raise ValueError(f"Invalid {field}")
        if int(self.appPort) in {80, 8080}:
            raise ValueError("Port conflicts with Traefik")
        if not re.fullmatch(r"[A-Za-z0-9_+/-]{1,100}", self.timezone):
            raise ValueError("Invalid timezone")
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError):
            raise ValueError("Invalid timezone") from None
        for field, pattern in (
            ("hostname", r"[A-Za-z][A-Za-z0-9-]{0,61}[A-Za-z0-9]"),
            ("storage", r"[A-Za-z][A-Za-z0-9_-]{0,63}"),
            ("templateStorage", r"[A-Za-z][A-Za-z0-9_-]{0,63}"),
            ("bridge", r"[A-Za-z][A-Za-z0-9_.-]{0,14}"),
        ):
            if not re.fullmatch(pattern, getattr(self, field)):
                raise ValueError(f"Invalid {field}")
        if self.network == "static":
            interface = IPv4Interface(self.address)
            gateway = IPv4Address(self.gateway)
            if (
                "/" not in self.address
                or interface.network.prefixlen == 0
                or not 0 < int(str(interface.ip).split(".")[0]) < 224
                or not 0 < int(str(gateway).split(".")[0]) < 224
            ):
                raise ValueError("Invalid static network")
        return self


class SSHAddress(StrictModel):
    host: str
    port: int = Field(default=22, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def private_host(cls, value):
        ip = IPv4Address(value)
        if not any(
            ip in IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        ):
            raise ValueError("Use the server's private LAN IPv4 address")
        return str(ip)


class DeployRequest(SSHAddress):
    requestId: UUID
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    password: SecretStr = Field(min_length=1, max_length=1024)
    config: DeployConfig
    acknowledgedJob: str | None = None


def commands(config):
    values = config.model_dump()

    def render(template):
        return re.sub(r"@@([A-Za-z]+)@@", lambda m: values[m[1]], template)

    values["guest"] = render(TEMPLATES["guest"])
    if config.target == "linux":
        return "bash <<'MEDIAHUB_INSTALL'\n" + values["guest"] + "\nMEDIAHUB_INSTALL"
    values["ctidLine"] = (
        f"CTID='{config.ctid}'" if config.ctid else "CTID=$(pvesh get /cluster/nextid)"
    )
    network = "dhcp" if config.network == "dhcp" else config.address + ",gw=" + config.gateway
    values["networkSpec"] = f"name=eth0,bridge={config.bridge},ip={network},ip6=manual"
    return render(TEMPLATES["lxc"])


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


class PinnedKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        if fingerprint(key) != self.expected:
            raise DomainError(
                "ssh_host_key_changed", "SSH fingerprint differs; no commands ran", 409
            )


def probe(address):
    try:
        with socket.create_connection((address.host, address.port), timeout=10) as sock:
            with paramiko.Transport(sock) as transport:
                transport.start_client(timeout=10)
                return {"fingerprint": fingerprint(transport.get_remote_server_key())}
    except (OSError, paramiko.SSHException):
        raise DomainError(
            "ssh_unavailable", "Cannot reach SSH on this address and port", 502
        ) from None


def clean_line(line, password):
    line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
    line = "".join(c for c in line if c.isprintable())
    line = line.replace(password, "[redacted]") if password else line
    line = re.sub(
        r"(?i)(password|token|secret(?:[_-]?key)?|api[_-]?key)(\s*[=:]\s*)\S+",
        r"\1\2[redacted]",
        line,
    )
    line = re.sub(r"(https?://)[^ /@]+:[^ /@]+@", r"\1[redacted]@", line)
    return line[:500]


class FjordHubDeploy:
    def __init__(self, sessions):
        self.sessions = sessions
        self.lock = threading.RLock()
        with sessions.begin() as db:
            for row in db.scalars(select(Setting).where(Setting.key.startswith(PREFIX))):
                if row.value.get("state") == "running":
                    row.value = {
                        **row.value,
                        "state": "interrupted",
                        "message": "MediaHub restarted. Inspect the target before retrying; remote work may still be running.",
                    }

    def latest(self):
        with self.lock, self.sessions() as db:
            row = db.scalar(
                select(Setting)
                .where(Setting.key.startswith(PREFIX))
                .order_by(Setting.created_at.desc())
                .limit(1)
            )
            return row.value if row else None

    def save(self, job):
        with self.lock, self.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == PREFIX + job["id"]))
            row.value = {**job, "updatedAt": now(), "logs": list(job["logs"])}

    def start(self, body):
        with self.lock, self.sessions.begin() as db:
            key = PREFIX + str(body.requestId)
            previous = db.scalar(select(Setting).where(Setting.key == key))
            if previous:
                return previous.value
            latest = self.latest()
            if latest and latest["state"] == "running":
                raise DomainError("deployment_busy", "A deployment is already running", 409)
            if (
                latest
                and latest["state"] in {"failed", "interrupted"}
                and body.acknowledgedJob != latest["id"]
            ):
                raise DomainError(
                    "inspection_required", "Inspect the previous target before retrying", 409
                )
            job = {
                "id": str(body.requestId),
                "state": "running",
                "host": body.host,
                "config": body.config.model_dump(),
                "logs": [],
                "startedAt": now(),
                "message": "Connecting to SSH",
            }
            db.add(Setting(key=key, value=job))
        self.launch(body, job)
        return job

    def launch(self, body, job):
        threading.Thread(target=self.run, args=(body, job), daemon=True).start()

    def run(self, body, job):
        password = body.password.get_secret_value()
        client = paramiko.SSHClient()
        try:
            client.set_missing_host_key_policy(PinnedKey(body.fingerprint))
            client.connect(
                body.host,
                port=body.port,
                username="root",
                password=password,
                allow_agent=False,
                look_for_keys=False,
                timeout=10,
                banner_timeout=10,
                auth_timeout=15,
                channel_timeout=15,
            )
            transport = client.get_transport()
            transport.set_keepalive(15)
            with transport.open_session(timeout=15) as channel:
                channel.set_combine_stderr(True)
                channel.settimeout(15)
                # Fixed command, no PTY, no shell text supplied by the browser.
                channel.exec_command("bash -s")
                channel.sendall((commands(body.config) + "\n").encode())
                channel.shutdown_write()
                job["message"] = "Installing FjordHub; console updates below"
                self.save(job)
                deadline, saved, pending = time.monotonic() + 3600, time.monotonic(), ""
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError()
                    if channel.recv_ready():
                        pending += (
                            channel.recv(8192).decode("utf-8", errors="replace").replace("\r", "\n")
                        )
                        while "\n" in pending or len(pending) > 4096:
                            if "\n" in pending:
                                line, pending = pending.split("\n", 1)
                            else:
                                line, pending = pending[:4096], pending[4096:]
                            line = clean_line(line, password)
                            if line:
                                job["logs"] = (job["logs"] + [line])[-300:]
                    elif channel.exit_status_ready():
                        if pending:
                            job["logs"] = (job["logs"] + [clean_line(pending, password)])[-300:]
                        status = channel.recv_exit_status()
                        if status != 0:
                            raise DomainError(
                                "deployment_failed",
                                f"Installer exited with status {status}. Inspect the target before retrying.",
                            )
                        job.update(
                            state="succeeded",
                            message="FjordHub is installed and its health check passed. Complete administrator setup in FjordHub.",
                        )
                        break
                    elif not transport.is_active():
                        raise ConnectionError()
                    if time.monotonic() - saved >= 1:
                        self.save(job)
                        saved = time.monotonic()
                    time.sleep(0.1)
        except paramiko.AuthenticationException:
            job.update(
                state="failed",
                message="SSH root login failed. Check the password and SSH login settings.",
            )
        except DomainError as error:
            job.update(state="failed", message=error.message)
        except Exception:
            job.update(
                state="interrupted",
                message="SSH connection failed or timed out. Inspect the target before retrying; remote work may still be running.",
            )
        finally:
            client.close()
            self.save(job)
