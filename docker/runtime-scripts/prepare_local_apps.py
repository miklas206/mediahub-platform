"""Install/update bundled first-party app prerequisites without deleting data.

Host-only entrypoint. Inputs are the approved Hub root and LAN IPv4 address,
never Docker specs or paths received from an HTTP caller. Apps already stopped
or removed remain stopped; only previously running owned services are resumed.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

from prepare_managed_install import prepare

SOURCE = Path(__file__).resolve().parents[1]


def run(*args, env=None):
    return (
        subprocess.check_output(list(map(str, args)), env=env, stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


def private(path, content, uid=0, gid=0):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Unsafe app metadata path")
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        os.chown(path, uid, gid)


def bundle_root(source):
    # Checkout layout remains compatible with old source archive allowlists;
    # the image places the same reviewed files at /app/bundled.
    return source / "docker/bundled" if (source / "docker/bundled").is_dir() else source / "bundled"


def fingerprint(source=SOURCE):
    files = sorted(p for p in bundle_root(source).rglob("*") if p.is_file())
    return hashlib.sha256(
        b"".join(
            p.relative_to(source).as_posix().encode()
            + b"\0"
            + p.read_bytes().replace(b"\r\n", b"\n")
            for p in files
        )
    ).hexdigest()


def certificate(root, folder, lan):
    tls = folder / "tls"
    if (tls / "cert.pem").exists() and (tls / "key.pem").exists():
        return
    if tls.exists() and list(tls.iterdir()):
        raise ValueError("Incomplete app TLS identity; repair it without replacing keys")
    tls.mkdir(mode=0o700, exist_ok=True)
    os.chown(tls, 1000, 1000)
    extension = folder / "certificate.ext"
    private(
        extension,
        "subjectAltName=IP:"
        + lan
        + ",IP:127.0.0.1\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n",
    )
    run(
        "openssl",
        "req",
        "-new",
        "-newkey",
        "rsa:3072",
        "-nodes",
        "-subj",
        "/CN=MediaHub " + folder.name,
        "-keyout",
        tls / "key.pem",
        "-out",
        folder / "certificate.csr",
    )
    run(
        "openssl",
        "x509",
        "-req",
        "-in",
        folder / "certificate.csr",
        "-CA",
        root / "authority/ca.pem",
        "-CAkey",
        root / "authority/ca.key",
        "-set_serial",
        str(secrets.randbits(120)),
        "-days",
        "365",
        "-extfile",
        extension,
        "-out",
        tls / "cert.pem",
    )
    for path in tls.iterdir():
        path.chmod(0o600)
        os.chown(path, 1000, 1000)


def provision(root, lan, source=SOURCE):
    ip = ipaddress.ip_address(lan)
    if (
        ip.version != 4
        or not ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
    ):
        raise ValueError("Choose the approved private LAN IPv4 address")
    if root.resolve() != root or not (root / "compose.json").is_file():
        raise ValueError("Expected an existing owned MediaHub installation")
    hub_compose = json.loads((root / "compose.json").read_text())
    if hub_compose.get("name") != "mediahub-platform":
        raise ValueError("MediaHub installation ownership changed")
    digest = fingerprint(source)
    marker = root / "local-apps/source.json"
    if marker.exists() and json.loads(marker.read_text()).get("fingerprint") == digest:
        return
    policy_path = root / "data/managed-apps.json"
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
    if set(policy) - {"org.mediahub.mediavpn", "org.mediahub.mediaseed"}:
        raise ValueError("Unknown managed app policy")
    projects = root / "local-apps"
    projects.mkdir(mode=0o700, exist_ok=True)
    vpn_data = projects / "mediavpn/data"
    vpn_data.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_path = vpn_data / "integrations/mediaseed.token"
    private(token_path, secrets.token_urlsafe(48))
    token = token_path.read_text().strip()
    management = vpn_data / "integrations/mediahub.token"
    private(management, secrets.token_urlsafe(48))
    management_copy = root / "data/app-integration/mediahub-vpn.token"
    private(management_copy, management.read_text(), 10001, 10001)
    if management_copy.read_text().strip() != management.read_text().strip():
        raise ValueError("Existing Hub management identities differ; no key was overwritten")
    for path, uid, gid in (
        (projects / "seed-auth/mediaseed.token", 1000, 1000),
        (root / "data/app-integration/mediaseed.token", 10001, 10001),
    ):
        private(path, token, uid, gid)
        os.chown(path.parent, uid, gid)
        if path.read_text().strip() != token:
            raise ValueError("Existing integration identities differ; no key was overwritten")
    for kind in ("mediavpn", "mediaseed"):
        folder = projects / kind
        folder.mkdir(mode=0o700, exist_ok=True)
        context = folder / ("source-" + digest[:16])
        shutil.copytree(bundle_root(source) / kind, context, dirs_exist_ok=True)
        package = "org.mediahub." + kind
        entry = policy.get(package)
        project = entry["project"] if entry else "mediahub-" + kind
        if project != "mediahub-" + kind:
            raise ValueError("Custom app projects require an explicit migration")
        ids = run(
            "docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project
        ).split()
        before = json.loads(run("docker", "inspect", *ids)) if ids else []
        running = [
            row["Config"]["Labels"]["com.docker.compose.service"]
            for row in before
            if row["State"]["Running"]
        ]
        if before and not entry:
            raise ValueError("Existing app containers have no approved installation record")
        compose_path = folder / "compose.json"
        if compose_path.exists():
            cfg = json.loads(compose_path.read_text())
            if cfg.get("name") != project:
                raise ValueError("App Compose ownership changed")
        else:
            certificate(root, folder, lan)
            env = dict(os.environ)
            prefix = kind.upper()
            env.update(
                {
                    prefix + "_BIND": lan,
                    prefix + "_BASE_URL": "https://"
                    + lan
                    + (":18803" if kind == "mediavpn" else ":18800"),
                    prefix + "_HUB_URL": "https://" + lan + ":18765",
                    prefix + "_HUB_CA_PATH": str(root / "trust/ca.pem"),
                    prefix + "_TLS_PATH": str(folder / "tls"),
                }
            )
            command = [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(context / "compose.yaml"),
                "-f",
                str(context / "compose.hub.yaml"),
            ]
            if kind == "mediavpn":
                command += ["-f", str(context / "compose.runtime.yaml")]
                env["MEDIAVPN_HOST_DATA"] = str(vpn_data)
            else:
                command += ["-f", str(context / "compose.vpn.yaml")]
                env.update(
                    MEDIASEED_VPN_URL="http://" + lan + ":18802",
                    MEDIASEED_VPN_TOKEN_PATH=str(projects / "seed-auth/mediaseed.token"),
                )
            cfg = json.loads(run(*command, "config", "--format", "json", env=env))
            # Copy static proxy routes into persistent host configuration. Build
            # sources are ephemeral; credentials and app volumes are not.
            if kind == "mediavpn":
                private(folder / "hub-proxy.yaml", (context / "hub-proxy.yaml").read_text())
                for volume in cfg["services"]["sso-proxy"].get("volumes", []):
                    if volume.get("target") == "/config/routes.yaml":
                        volume["source"] = str(folder / "hub-proxy.yaml")
            cfg["services"]["app"]["restart"] = "unless-stopped"
        for service, values in cfg["services"].items():
            if "build" in values:
                values["build"] = {"context": str(context), "dockerfile": "Dockerfile"}
                values["image"] = "mediahub-" + kind + ":bundled-" + digest[:16]
            elif "image" in values:
                run("docker", "pull", values["image"])
                image = json.loads(run("docker", "image", "inspect", values["image"]))[0]
                values["image"] = image["RepoDigests"][0]
        if kind == "mediavpn":
            cfg["services"]["app"]["environment"]["MEDIAVPN_SHARED_ADDRESS"] = lan
        previous_compose = compose_path.read_text() if compose_path.exists() else None
        private(
            compose_path.with_suffix(".before-" + digest[:16] + ".json"),
            previous_compose or json.dumps(cfg),
        )
        command = ["docker", "compose", "-p", project, "-f", str(compose_path)]
        try:
            compose_path.write_text(json.dumps(cfg))
            run(*command, "build", "app")
            if kind == "mediaseed":
                run(*command, "build", "client-init")
                # Initialization is idempotent and refuses mismatched existing secrets.
                run(*command, "run", "--rm", "--no-deps", "client-init")
            services = ["app", "sso-proxy"] if kind == "mediavpn" else ["app", "qbittorrent"]
            run(*command, "up", "--no-start", "--no-build", "--no-deps", *services)
            if running:
                run(
                    *command,
                    "up",
                    "-d",
                    "--no-build",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    *running,
                )
        except (OSError, ValueError, subprocess.SubprocessError):
            if previous_compose:
                compose_path.write_text(previous_compose)
                if running:
                    run(*command, "up", "-d", "--no-build", "--no-deps", *running)
            raise
        if not entry:
            entry = {
                "installationId": secrets.token_hex(16),
                "project": project,
                "runtimeLabels": {"org.mediahub.mediavpn.owner": "mediavpn"}
                if kind == "mediavpn"
                else {"org.mediahub.mediavpn.seedbox": "mediaseed"},
            }
            if kind == "mediaseed":
                entry.update(
                    integrationUrl="http://" + lan + ":18802",
                    integrationTokenFile="/data/app-integration/mediaseed.token",
                )
            policy[package] = entry
        if kind == "mediavpn":
            entry["managementTokenFile"] = "/data/app-integration/mediahub-vpn.token"
    private(policy_path, "{}", 10001, 10001)
    policy_path.write_text(json.dumps(policy))
    prepare(policy_path, root / "data", Path("/data"), 10001, 10001)
    private(marker, "{}")
    marker.write_text(json.dumps({"fingerprint": digest}))


if __name__ == "__main__":
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lan-ip")
    args = parser.parse_args()
    with (args.root / "updates/host-updater.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        address = args.lan_ip
        if not address:
            address = json.loads((args.root / "agent/container-apps.json").read_text())[
                "bindAddress"
            ]
        provision(args.root, address)
