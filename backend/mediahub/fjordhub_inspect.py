"""Pinned SSH checks and runtime-only removal of an explicitly selected deployment."""

import json
import re
import shlex
import time

import paramiko
from pydantic import Field, SecretStr

from mediahub.errors import DomainError
from mediahub.fjordhub_deploy import DeployConfig, PinnedKey, SSHAddress


class InspectDeployment(SSHAddress):
    jobId: str = Field(min_length=1, max_length=80)
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    password: SecretStr = Field(min_length=1, max_length=1024)
    remove: bool = False
    confirmedJobId: str | None = None


# Executed only over pinned SSH. No deletion of files, volumes, images or LXCs.
GUEST = r"""
import json,subprocess,pathlib,sys
cfg=json.loads(sys.argv[1]);root=pathlib.Path(cfg['installPath'])
def run(args):return subprocess.run(args,capture_output=True,text=True,timeout=90)
def done(state,message):print(json.dumps({'state':state,'message':message}));sys.exit(0)
if not root.exists():done('removed','FjordHub source directory is missing on the selected host.')
if root.resolve()!=root:done('unknown','Source path changed; ownership cannot be verified.')
origin=run(['git','-C',str(root),'remote','get-url','origin'])
if origin.returncode or origin.stdout.strip().removesuffix('.git')!='https://github.com/qlerup/fjordhub':done('unknown','Source repository ownership could not be verified.')
rows=run(['docker','ps','-aq','--filter','label=com.docker.compose.project.working_dir='+str(root)])
if rows.returncode:done('unknown','Docker could not be queried.')
ids=rows.stdout.split()
if not ids:done('removed','No FjordHub runtime containers remain. Existing app data is preserved.')
result=run(['docker','inspect',*ids])
if result.returncode:done('unknown','Container inspection failed.')
items=json.loads(result.stdout)
for item in items:
 labels=item.get('Config',{}).get('Labels',{})
 if labels.get('com.docker.compose.project.working_dir')!=str(root) or not labels.get('com.docker.compose.service'):done('unknown','Container ownership does not match the deployment.')
if cfg.get('remove'):
 for item in items:
  if item['State']['Running'] and run(['docker','stop','--time','30',item['Id']]).returncode:done('unknown','Could not stop FjordHub. Removal was interrupted.')
  if run(['docker','rm',item['Id']]).returncode:done('unknown','Could not remove a stopped container. App data is preserved.')
 done('removed','FjordHub containers removed. LXC, source, settings and app data are preserved.')
if not any(item['Config']['Labels'].get('com.docker.compose.service')=='fjordhub' for item in items):done('stopped','Some deployment containers remain, but the FjordHub application container is missing.')
if not all(item['State']['Running'] for item in items):done('stopped','FjordHub containers exist, but one or more services are stopped.')
done('installed','FjordHub runtime containers are present and running on the checked host.')
"""


def inspect_deployment(service, body):
    if not service.inspection_lock.acquire(blocking=False):
        raise DomainError("deployment_busy", "Another deployment operation is running", 409)
    try:
        return _inspect_deployment(service, body)
    finally:
        service.inspection_lock.release()


def _inspect_deployment(service, body):
    job = service.latest()
    if not job or job["id"] != body.jobId or job["host"] != body.host or job["state"] == "running":
        raise DomainError(
            "deployment_changed", "Select the current completed deployment before checking it", 409
        )
    if body.remove and body.confirmedJobId != job["id"]:
        raise DomainError("confirmation_required", "Confirm this exact FjordHub deployment", 409)
    cfg = DeployConfig.model_validate(job["config"]).model_dump()
    cfg["remove"] = body.remove
    ctid = cfg["ctid"]
    if cfg["target"] == "lxc" and not ctid:
        for line in reversed(job.get("logs", [])):
            match = re.search(r"(?:Created LXC |pct enter )([0-9]{3,9})", line)
            if match:
                ctid = match[1]
                break
    # A new deployment stores the actual ID before long build logs can rotate away.
    ctid = job.get("actualCtid") or ctid
    client = paramiko.SSHClient()
    try:
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
        command = "python3 -c " + shlex.quote(GUEST) + " " + shlex.quote(json.dumps(cfg))
        if cfg["target"] == "lxc":
            _, stdout, _ = client.exec_command(
                "pvesh get /cluster/resources --type vm --output-format json", timeout=15
            )
            resources = json.loads(stdout.read(262144))
            matches = [
                r
                for r in resources
                if r.get("type") == "lxc"
                and (str(r.get("vmid")) == ctid if ctid else r.get("name") == cfg["hostname"])
            ]
            if not matches:
                result = {
                    "state": "removed" if ctid else "unknown",
                    "message": "The FjordHub LXC no longer exists on this Proxmox cluster."
                    if ctid
                    else "No matching LXC was found, but the original ID was not recorded. Its identity cannot be verified.",
                }
            elif len(matches) != 1 or matches[0].get("name") != cfg["hostname"]:
                result = {
                    "state": "unknown",
                    "message": "LXC identity changed; no action was taken.",
                }
            elif body.remove and not ctid:
                result = {
                    "state": "unknown",
                    "message": "The original LXC ID was not recorded. Verify the guest identity manually before removing it.",
                }
            elif matches[0].get("status") != "running":
                result = {
                    "state": "stopped",
                    "message": "The FjordHub LXC exists but is stopped. Start it before checking or removing its containers.",
                }
            else:
                command = "pct exec " + str(int(matches[0]["vmid"])) + " -- " + command
                result = None
        else:
            result = None
        if result is None:
            _, stdout, _ = client.exec_command(command, timeout=180)
            output = stdout.read(32768)
            if stdout.channel.recv_exit_status() != 0:
                raise ValueError()
            result = json.loads(output)
        result["checkedAt"] = time.time()
        job["verification"] = result
        service.save(job)
        return result
    except DomainError:
        raise
    except Exception:
        result = {
            "state": "unknown",
            "message": "SSH or runtime verification failed. The installation has not been confirmed as removed.",
            "checkedAt": time.time(),
        }
        job["verification"] = result
        service.save(job)
        return result
    finally:
        client.close()
