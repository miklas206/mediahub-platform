"""Preview and confirm full removal of a dedicated FjordHub LXC."""

import json
import re
import shlex
import time
from pathlib import Path

import paramiko
from pydantic import Field
from sqlalchemy import select

from mediahub.db import ExternalIntegration
from mediahub.errors import DomainError
from mediahub.fjordhub_deploy import DeployConfig, PinnedKey
from mediahub.fjordhub_inspect import InspectDeployment

REMOTE = Path(__file__).with_name("fjordhub_uninstall_remote.py").read_text()


class UninstallDeployment(InspectDeployment):
    planDigest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    externalMediaConfirmed: bool = False


def uninstall_deployment(services, body):
    service = services.fjordhub_deploy
    if not service.inspection_lock.acquire(blocking=False):
        raise DomainError("deployment_busy", "Another deployment operation is running", 409)
    client = None
    job = None
    started = False
    try:
        job = service.latest()
        if (
            not job
            or job["id"] != body.jobId
            or job["host"] != body.host
            or job["state"] == "running"
        ):
            raise DomainError("deployment_changed", "Select the current deployment", 409)
        if job.get("uninstall", {}).get("state") == "removed":
            return job["uninstall"]
        cfg = DeployConfig.model_validate(job["config"]).model_dump()
        ctid = job.get("actualCtid") or cfg["ctid"]
        if not ctid:
            for line in reversed(job.get("logs", [])):
                match = re.search(r"(?:Created LXC |pct enter )([0-9]{3,9})", line)
                if match:
                    ctid = match[1]
                    break
        if cfg["target"] != "lxc" or not re.fullmatch(r"[1-9][0-9]{2,8}", str(ctid or "")):
            raise DomainError(
                "uninstall_unsupported",
                "Full removal requires the recorded ID of a dedicated MediaHub-created LXC. Shared Debian hosts require manual cleanup.",
                409,
            )
        cfg["ctid"] = str(ctid)
        if body.remove:
            preview = job.get("uninstall", {})
            if (
                body.confirmedJobId != job["id"]
                or not body.externalMediaConfirmed
                or preview.get("state") != "ready"
                or not body.planDigest
                or body.planDigest != preview.get("digest")
                or time.time() - preview.get("checkedAt", 0) > 600
            ):
                raise DomainError(
                    "confirmation_required",
                    "Review a fresh uninstall plan and confirm external media before removing this exact deployment",
                    409,
                )
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(PinnedKey(body.fingerprint))
        client.connect(
            body.host,
            port=body.port,
            username="root",
            password=body.password.get_secret_value(),
            allow_agent=False,
            look_for_keys=False,
            timeout=10,
            auth_timeout=15,
            banner_timeout=10,
        )
        if body.remove:
            job["uninstall"] = {**job["uninstall"], "state": "removing"}
            service.save(job)
            started = True
        stdin, stdout, _ = client.exec_command("python3 -c " + shlex.quote(REMOTE), timeout=420)
        stdin.write(json.dumps({"config": cfg, "remove": body.remove, "digest": body.planDigest}))
        stdin.flush()
        stdin.channel.shutdown_write()
        output = stdout.read(131072)
        if stdout.channel.recv_exit_status() != 0:
            raise ValueError("Remote uninstall check failed")
        response = json.loads(output)
        if not response.get("ok"):
            raise DomainError(
                "uninstall_blocked", response.get("message", "Uninstall could not be verified"), 409
            )
        result = response["result"]
        result.update(state="removed" if body.remove else "ready", checkedAt=time.time())
        if body.remove:
            # Only disconnect entries for this guest, not unrelated FjordHub hosts.
            urls = {
                line.split("=", 1)[1].rstrip("/")
                for line in job.get("logs", [])
                if line.startswith("MEDIAHUB_FJORDHUB_URL=")
            }
            with services.sessions() as db:
                identifiers = [
                    row.id
                    for row in db.scalars(select(ExternalIntegration))
                    if row.provider == "fjordhub" and row.base_url.rstrip("/") in urls
                ]
            for identifier in identifiers:
                services.integrations.disconnect(identifier)
                with services.sessions.begin() as db:
                    row = db.get(ExternalIntegration, identifier)
                    if row:
                        db.delete(row)
            job["verification"] = {
                "state": "removed",
                "message": result["message"],
                "checkedAt": result["checkedAt"],
            }
        job["uninstall"] = result
        service.save(job)
        return result
    except DomainError as error:
        if job and started:
            job["uninstall"] = {
                **job.get("uninstall", {}),
                "state": "incomplete",
                "message": error.message,
            }
            service.save(job)
        raise
    except Exception:
        if job and started:
            job["uninstall"] = {
                **job.get("uninstall", {}),
                "state": "incomplete",
                "message": "Uninstall could not be confirmed. Inspect the server before retrying.",
            }
            service.save(job)
        raise DomainError(
            "uninstall_failed",
            "SSH or uninstall verification failed. Removal has not been confirmed; inspect the target before retrying.",
            502,
        ) from None
    finally:
        if client:
            client.close()
        service.inspection_lock.release()
