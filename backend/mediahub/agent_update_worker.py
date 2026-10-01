"""Standalone root SSH worker. Only the matched Compose Agent is recreated."""

import hashlib
import json
import os
import subprocess
import tarfile
import time
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=120)


def select_agent(rows, digest, token_digest):
    matches = []
    for row in rows:
        env = dict(v.split("=", 1) for v in row["Config"].get("Env", []) if "=" in v)
        token = env.get("MEDIAHUB_AGENT_TOKEN_FILE")
        if token and token_digest(row["Id"], token) == digest:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("Exactly one paired Agent container is required")
    return matches[0]


def plan(row, config):
    labels = row["Config"].get("Labels") or {}
    service = labels.get("com.docker.compose.service")
    project = labels.get("com.docker.compose.project")
    files = labels.get("com.docker.compose.project.config_files", "").split(",")
    if not service or not project or len(files) != 1 or not Path(files[0]).is_absolute():
        raise ValueError("A single-file Docker Compose Agent installation is required")
    if service not in config.get("services", {}):
        raise ValueError("Agent service missing from Compose configuration")
    return service, project, Path(files[0])


def extract(archive, destination):
    with tarfile.open(archive, "r:gz") as source:
        total = 0
        for member in source:
            path = Path(member.name)
            total += member.size
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != "mediahub-source"
                or not (member.isdir() or member.isfile())
                or total > 2 * 1024**3
            ):
                raise ValueError("Unsafe source archive")
            source.extract(member, destination, filter="data")
    # The data filter ignores archived directory modes. With the worker's
    # private umask, directories are otherwise 0700 and Docker COPY preserves
    # those root-only modes in the image used by the unprivileged Agent.
    source_root = destination / "mediahub-source"
    for path in [source_root, *source_root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)


def main(root):
    import fcntl

    os.umask(0o077)
    manifest = json.loads((root / "manifest.json").read_text())

    def status(state, message):
        temp = root / "status.tmp"
        temp.write_text(json.dumps({"state": state, "message": message}))
        temp.replace(root / "status.json")
        print(message, flush=True)

    lock = open(root.parent / "update.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        status("failed", "Another Agent update holds the host lock; nothing was changed")
        return
    original = None
    config_path = None
    changed = False
    try:
        status("building", "Identifying the paired Agent and backing up its Compose configuration")
        ids = run("docker", "ps", "-q").split()
        if not ids:
            raise ValueError("No running containers")
        rows = json.loads(run("docker", "inspect", *ids))

        def token_digest(identifier, path):
            try:
                script = "import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_text().strip().encode()).hexdigest())"
                return run("docker", "exec", identifier, "python", "-c", script, path).strip()
            except Exception:
                return None

        row = select_agent(rows, manifest["tokenDigest"], token_digest)
        labels = row["Config"]["Labels"]
        files = labels.get("com.docker.compose.project.config_files", "").split(",")
        if len(files) != 1 or not Path(files[0]).is_absolute():
            raise ValueError("A single-file Compose installation is required")
        config_path = Path(files[0])
        if config_path.is_symlink() or not config_path.is_file():
            raise ValueError("Compose configuration must be a regular file")
        compose = [
            "docker",
            "compose",
            "-p",
            labels["com.docker.compose.project"],
            "-f",
            str(config_path),
        ]
        config = json.loads(run(*compose, "config", "--format", "json"))
        service, project, config_path = plan(row, config)
        original = config_path.read_bytes()
        try:
            # Preserve expressions and unrelated fields in native JSON installations.
            raw_config = json.loads(original)
            if service in raw_config.get("services", {}):
                config = raw_config
        except ValueError:
            pass
        (root / "compose.backup").write_bytes(original)
        archive = root / "source.tar.gz"
        if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("Source checksum mismatch")
        extract(archive, root)
        source = root / "mediahub-source"
        tag = "mediahub-agent:update-" + manifest["commit"]
        status(
            "building", "Building the commit-pinned Agent image; the existing Agent keeps running"
        )
        with (root / "build.log").open("w") as output:
            subprocess.run(
                [
                    "docker",
                    "build",
                    "-f",
                    str(source / "docker/Agent.Dockerfile"),
                    "--build-arg",
                    "MEDIAHUB_SOURCE_COMMIT=" + manifest["commit"],
                    "-t",
                    tag,
                    str(source),
                ],
                stdout=output,
                stderr=output,
                check=True,
                timeout=3600,
            )
        image = run("docker", "image", "inspect", "--format", "{{.Id}}", tag).strip()
        config["services"][service]["image"] = image
        config["services"][service].pop("build", None)
        # Compose's canonical JSON keeps the resolved mounts, ports, environment and peers.
        # Save the exact original bytes for rollback; only recreate this service.
        updated = json.dumps(config, indent=2).encode()
        if config_path.read_bytes() != original:
            raise ValueError("Compose configuration changed while building")
        status(
            "installing", "Replacing only the Agent; torrent client, VPN and media stay in place"
        )
        temp = config_path.with_name(config_path.name + ".agent-update.tmp")
        temp.write_bytes(updated)
        temp.replace(config_path)
        changed = True
        run(*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", service)
        status("verifying", "Waiting for Core to verify the new Agent over authenticated HTTPS")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            accept = root / "accepted"
            if accept.exists() and accept.read_text() == manifest["commit"]:
                status(
                    "succeeded",
                    "Agent updated; installed commit and authenticated connection verified",
                )
                return
            time.sleep(2)
        raise ValueError("New Agent did not pass authenticated verification")
    except Exception as error:
        if changed:
            status(
                "rolling_back",
                "Verification failed; restoring the previous Agent and Compose configuration",
            )
            config_path.write_bytes(original)
            try:
                run(*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", service)
                status(
                    "rolled_back",
                    "Previous Agent configuration restored; inspect connection before retrying",
                )
            except Exception:
                status(
                    "failed",
                    "Rollback could not complete. Use the saved Compose backup on the Seedbox host",
                )
        else:
            status(
                "failed",
                ("Agent update blocked: " + str(error)[:200])
                if isinstance(error, ValueError)
                else "Agent update preflight or build failed; existing services were not changed. Inspect the private host build log",
            )


if __name__ == "__main__":
    main(Path(__file__).resolve().parent)
