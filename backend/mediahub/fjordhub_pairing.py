"""Installer-owned, restart-safe pairing with FjordHub's native read-only token API.

Only a SHA256 verifier reaches the guest. The bearer token stays encrypted in Core.
A bounded timer waits for the first real administrator; no hidden account is created.
"""

import hashlib
import json
import secrets
import time
from types import SimpleNamespace

from pydantic import SecretStr

# Executed in the FjordHub container, using its installed AuthService and schema.
ACTIVATE = r"""import os, sys
from pathlib import Path
from services.auth import AuthService, _hash_api_key
spec = __import__("json").loads(sys.stdin.read())
auth = AuthService(Path(os.environ.get("DATA_DIR", "/data")) / "hub.db")
with auth._conn() as db:
    existing = db.execute("SELECT id FROM access_tokens WHERE token_hash=?", (spec["hash"],)).fetchone()
    if existing:
        sys.exit(0)  # Never reinstate an explicitly revoked token.
    owner = db.execute("SELECT id FROM users WHERE role='admin' AND must_change_password=0 ORDER BY id LIMIT 1").fetchone()
if not owner:
    sys.exit(75)
# Keep the upstream administrator checks and token metadata contract.
generated = auth.create_access_token("MediaHub read-only integration", int(owner[0]), days=0)
with auth._conn() as db:
    changed = db.execute("UPDATE access_tokens SET token_hash=?, prefix=? WHERE token_hash=?", (spec["hash"], spec["prefix"], _hash_api_key(generated)))
    if changed.rowcount != 1:
        sys.exit(76)
    db.commit()
"""


def installer_script(config, ctid, spec, unit):
    # Paths originate from validated DeployConfig. Payload has only a hash and prefix.
    activation = ACTIVATE + "\n"
    worker = "import subprocess, time\n" + "spec=" + repr(json.dumps(spec)) + "\n"
    worker += (
        "command="
        + repr(["docker", "compose", "exec", "-T", "fjordhub", "python", "-c", activation])
        + "\n"
    )
    worker += f"result=75 if time.time() > {int(time.time()) + 7 * 86400} else subprocess.run(command,input=spec,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode\n"
    worker += f"if result == 0 or time.time() > {int(time.time()) + 7 * 86400}:\n subprocess.run(['systemctl','disable','--now','{unit}.timer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)\n"
    worker += "raise SystemExit(result)\n"
    setup = "import os, pathlib, subprocess\n"
    setup += "root=pathlib.Path(" + repr(config.installPath) + ")\n"
    probe = [
        "docker",
        "compose",
        "exec",
        "-T",
        "fjordhub",
        "python",
        "-c",
        "from services.auth import AuthService, _hash_api_key; assert callable(AuthService.create_access_token)",
    ]
    setup += f"subprocess.run({probe!r},cwd=root,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)\n"
    setup += (
        "file=root / '.mediahub-pairing.py'\nfile.write_text("
        + repr(worker)
        + ", encoding='utf-8')\nfile.chmod(0o600)\n"
    )
    service = f"[Unit]\nDescription=MediaHub FjordHub token pairing\nAfter=docker.service\n[Service]\nType=oneshot\nWorkingDirectory={config.installPath}\nExecStart=/usr/bin/python3 {config.installPath}/.mediahub-pairing.py\nTimeoutStartSec=50\n"
    timer = f"[Unit]\nDescription=Wait for FjordHub administrator setup\n[Timer]\nOnBootSec=30\nOnCalendar=*-*-* *:*:00\nPersistent=true\nUnit={unit}.service\n[Install]\nWantedBy=timers.target\n"
    setup += f"pathlib.Path('/etc/systemd/system/{unit}.service').write_text({service!r})\n"
    setup += f"pathlib.Path('/etc/systemd/system/{unit}.timer').write_text({timer!r})\n"
    setup += f"subprocess.run(['systemctl','daemon-reload'],check=True)\nsubprocess.run(['systemctl','enable','--now','{unit}.timer'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
    command = "python3 -"
    if config.target == "lxc":
        if not ctid or not str(ctid).isdigit():
            raise ValueError("Missing verified guest ID")
        command = f"pct exec {int(ctid)} -- python3 -"
    return command, setup.encode()


def pair_installed(client, config, job, integrations):
    origins = [
        line.split("=", 1)[1] for line in job["logs"] if line.startswith("MEDIAHUB_FJORDHUB_URL=")
    ]
    if not origins:
        raise ValueError("Missing health-verified guest origin")
    origin = integrations.origin(origins[-1], True)
    # Preserve an existing manually paired or deliberately disconnected origin.
    existing = next((row for row in integrations.list() if row["baseUrl"] == origin), None)
    if existing and (existing["tokenConfigured"] or not existing["enabled"]):
        return "existing"
    token = "fh_at_" + secrets.token_urlsafe(32)
    spec = {"hash": hashlib.sha256(token.encode()).hexdigest(), "prefix": token[:12]}
    unit = (
        "mediahub-fjordhub-pairing-" + hashlib.sha256(config.installPath.encode()).hexdigest()[:12]
    )
    command, payload = installer_script(config, job.get("actualCtid") or config.ctid, spec, unit)
    with client.get_transport().open_session(timeout=15) as channel:
        channel.settimeout(15)
        channel.exec_command(command)
        channel.sendall(payload)
        channel.shutdown_write()
        deadline = time.monotonic() + 60
        count = 0
        while not channel.exit_status_ready():
            if channel.recv_ready():
                count += len(channel.recv(4096))
            if channel.recv_stderr_ready():
                count += len(channel.recv_stderr(4096))
            if time.monotonic() > deadline or count > 65536:
                raise TimeoutError("Pairing bootstrap timed out")
            time.sleep(0.05)
        if channel.recv_exit_status() != 0:
            raise ValueError("Pairing bootstrap unavailable")
    result = integrations.save(
        SimpleNamespace(
            name="FjordHub",
            baseUrl=origin,
            allowHttp=origin.startswith("http://"),
            accessToken=SecretStr(token),
        )
    )
    with integrations.sessions.begin() as db:
        from mediahub.db import ExternalIntegration

        row = db.get(ExternalIntegration, result["id"])
        row.snapshot = {
            "status": "pending_setup",
            "pairingPending": True,
            "pairingDeadline": int(time.time()) + 7 * 86400,
        }
    return "pending_setup"
