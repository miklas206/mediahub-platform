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
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

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


def configure_vpn_tun(cfg):
    """Backfill the same narrow device mapping used by fresh runtime Compose."""
    app = cfg["services"]["app"]
    devices = []
    for item in app.get("devices", []):
        if isinstance(item, str):
            parts = item.split(":")
            source, target = parts[0], parts[1] if len(parts) > 1 else parts[0]
        else:
            source, target = item.get("source"), item.get("target")
        if target == "/dev/net/tun":
            if source != "/dev/net/tun":
                raise ValueError("Existing MediaVPN TUN mapping has an unexpected source")
            continue
        devices.append(item)
    devices.append({"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rwm"})
    app["devices"] = devices


def fingerprint(source=SOURCE):
    files = sorted(p for p in bundle_root(source).rglob("*") if p.is_file())
    # Preparation-only fixes must run even when the bundled app source is unchanged.
    files += [
        p
        for p in (
            source / "scripts/prepare_local_apps.py",
            source / "scripts/prepare_managed_install.py",
            source / "scripts/platform_update_host.py",
        )
        if p.is_file()
    ]
    return hashlib.sha256(
        b"".join(
            p.relative_to(source).as_posix().encode()
            + b"\0"
            + p.read_bytes().replace(b"\r\n", b"\n")
            for p in files
        )
    ).hexdigest()


def refresh_host_updater(root, source):
    """Upgrade the owned one-shot helper while holding the host updater lock."""
    target = root / "platform_update_host.py"
    reviewed = source / "scripts/platform_update_host.py"
    if not target.exists():
        return  # The fresh installer writes its reviewed helper after app preparation.
    if not reviewed.is_file() or reviewed.is_symlink() or target.is_symlink():
        raise ValueError("Reviewed host updater source is unavailable")
    info = target.stat()
    if os.name == "posix" and (info.st_mode & 0o022 or info.st_uid != 0):
        raise ValueError("Host updater ownership changed")
    content = reviewed.read_bytes()
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("Host updater source exceeds its limit")
    compile(content, str(reviewed), "exec")
    if target.read_bytes() != content:
        backup = root / "updates/platform_update_host.previous.py"
        if backup.is_symlink():
            raise ValueError("Unsafe host updater backup")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target, backup)
        backup.chmod(0o600)
        descriptor, temporary = tempfile.mkstemp(prefix=".host-updater-", dir=root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o700)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    capabilities = root / "updates/host-capabilities.json"
    if capabilities.is_symlink():
        raise ValueError("Unsafe host capability metadata")
    value = json.loads(capabilities.read_text()) if capabilities.exists() else {}
    value.update(ownedHelperCleanup=True, maintenance=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".capabilities-", dir=capabilities.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        os.chmod(temporary, 0o644)
        os.replace(temporary, capabilities)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare_vpn_helpers(context, root):
    """Prepare native gateway dependencies without starting any provider or app."""
    definitions = (
        ("relay", "relay_image", ("Dockerfile", "runtime.py"), "org.mediahub.vpn.relay-source"),
        ("gateway", "gateway_image", ("Dockerfile", "config.py", "observer.py", "natpmp.py", "plex_port.py"), "org.mediahub.gateway.source"),
    )
    images = {}
    for kind, folder, names, label in definitions:
        source = context / "mediavpn" / folder
        if not source.is_dir():
            # Older reviewed bundles only included the relay; never invent sources.
            continue
        digest = hashlib.sha256(b"".join((source / name).read_bytes().replace(b"\r\n", b"\n") for name in names)).hexdigest()
        tag = "mediahub-vpn-relay:1" if kind == "relay" else "mediahub-web-gateway:" + digest[:16]
        inspected = None
        try:
            inspected = json.loads(run("docker", "image", "inspect", tag))[0]
        except subprocess.CalledProcessError:
            pass
        if inspected and not inspected.get("Config", {}).get("Labels", {}).get(label):
            raise ValueError("VPN helper image ownership could not be verified")
        if not inspected or inspected["Config"]["Labels"][label] != digest:
            run("docker", "build", "--pull", "--label", label + "=" + digest,
                "--label", "org.mediahub.managed-component=vpn-" + kind,
                "--tag", tag, str(source))
            inspected = json.loads(run("docker", "image", "inspect", tag))[0]
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", inspected.get("Id", "")) or inspected.get("Config", {}).get("Labels", {}).get(label) != digest:
            raise ValueError("VPN helper image could not be verified after preparation")
        images[kind] = inspected["Id"]
    if images:
        provider = "qmcgaw/gluetun:v3.40.0"
        run("docker", "pull", provider)
        inspected = json.loads(run("docker", "image", "inspect", provider))[0]
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", inspected.get("Id", "")) or not any(
            re.fullmatch(r"(?:docker.io/)?qmcgaw/gluetun@sha256:[a-f0-9]{64}", ref)
            for ref in inspected.get("RepoDigests", [])
        ):
            raise ValueError("The VPN provider image publisher could not be verified")
        images["provider"] = inspected["Id"]
        path = root / "local-apps/vpn-helper-images.json"
        previous = json.loads(path.read_text()) if path.exists() else {}
        private(path, "{}")
        previous_ids = list(dict.fromkeys(previous.get("images", {}).values()))
        path.write_text(json.dumps({"images": images, "previousImages": previous_ids}))
    return images


def tls_permissions(tls, uid, gid):
    if tls.is_symlink() or not tls.is_dir():
        raise ValueError("Unsafe app TLS directory")
    for name in ("cert.pem", "key.pem"):
        path = tls / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Incomplete app TLS identity; no key was replaced")
    tls.chmod(0o700)
    os.chown(tls, uid, gid)
    for name in ("cert.pem", "key.pem"):
        path = tls / name
        path.chmod(0o600)
        os.chown(path, uid, gid)


def certificate(root, folder, lan):
    tls = folder / "tls"
    uid = 0 if folder.name == "mediavpn" else 1000
    if (tls / "cert.pem").exists() and (tls / "key.pem").exists():
        tls_permissions(tls, uid, uid)
        return
    if tls.exists() and list(tls.iterdir()):
        raise ValueError("Incomplete app TLS identity; repair it without replacing keys")
    tls.mkdir(mode=0o700, exist_ok=True)
    os.chown(tls, uid, uid)
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
    tls_permissions(tls, uid, uid)


def repair_tls_permissions(folder, cfg):
    kind = folder.name
    service = cfg["services"].get("sso-proxy" if kind == "mediavpn" else "app", {})
    mounts = [
        v
        for v in service.get("volumes", [])
        if isinstance(v, dict) and v.get("target") == "/app-tls"
    ]
    if not mounts:
        return  # Legacy/custom setups without a managed TLS bind keep their own identity.
    tls = folder / "tls"
    if len(mounts) != 1 or mounts[0].get("type") != "bind" or mounts[0].get("source") != str(tls):
        raise ValueError("Managed app TLS mount ownership changed")
    user = str(service.get("user") or ("0:0" if kind == "mediavpn" else "1000:1000"))
    user = {"root": "0:0", "mediaseed": "1000:1000"}.get(user, user)
    parts = user.split(":")
    if len(parts) > 2 or not all(part.isdigit() for part in parts):
        raise ValueError("App TLS consumer needs an explicit numeric user")
    uid, gid = int(parts[0]), int(parts[-1])
    tls_permissions(tls, uid, gid)
    # Traefik does not reload certificates merely because file ownership changed.
    # Compose must recreate a running consumer once for this migration.
    service.setdefault("labels", {})["org.mediahub.tls.identity"] = (
        "owner-v1-"
        + str(uid)
        + "-"
        + str(gid)
        + "-"
        + hashlib.sha256((tls / "cert.pem").read_bytes()).hexdigest()
    )


def hub_browser_origin(hub_compose, lan):
    env = hub_compose["services"]["core"].get("environment", {})
    value = (
        env.get("MEDIAHUB_PUBLIC_URL")
        or env.get("MEDIAHUB_BASE_URL")
        or "https://" + lan + ":18765"
    )
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or any(ord(c) < 33 for c in value)
        or "\\" in value
    ):
        raise ValueError("Managed app browser login requires a configured HTTPS hub origin")
    _ = parsed.port
    return value.rstrip("/")


def approved_media_storage(root):
    """Read only the administrator's host policy; verify the live mount identity."""
    path = root / "agent/container-apps.json"
    if not path.exists():
        return []  # Standalone installations keep their existing local volume.
    policy = json.loads(path.read_text())
    snapshot = json.loads(Path(policy["hostMountSnapshot"]).read_text())
    required = policy.get("requiredMounts", {})
    uuids = policy.get("requiredFilesystemUuids", {})
    if (
        snapshot.get("scope") != "host-mount-namespace"
        or snapshot.get("available") is not True
        or not 0 <= time.time() - snapshot["observedAt"] <= 30
        or not (required or uuids)
    ):
        raise ValueError("Media storage mount evidence unavailable")
    for field, requirements in (("source", required), ("uuid", uuids)):
        for mount, expected in requirements.items():
            rows = [r for r in snapshot["mounts"] if r.get("path") == mount]
            if (
                len(rows) != 1
                or rows[0].get(field) != expected
                or "ro" in rows[0].get("options", [])
            ):
                raise ValueError("Media storage mount identity changed")
    markers = policy.get("storageMarkers", {})
    if not markers or any(Path(p).read_text().strip() != value for p, value in markers.items()):
        raise ValueError("Media storage marker changed")
    locations = []
    for identifier, value in policy.get("storage", {}).items():
        if value.get("kind") not in {"movies", "tv", "downloads", "other"}:
            continue
        if (
            not identifier.isascii()
            or not identifier.replace("-", "").isalnum()
            or identifier == "local"
        ):
            raise ValueError("Invalid storage identifier")
        source = Path(value["path"])
        if (
            not source.is_absolute()
            or source.resolve(strict=True) != source
            or not source.is_dir()
            or not any(source.is_relative_to(Path(p)) for p in set(required) | set(uuids))
        ):
            raise ValueError("Unapproved media storage directory")
        locations.append(
            {
                "id": identifier,
                "label": value["label"],
                "path": "/downloads/media/" + identifier,
                "source": str(source),
            }
        )
    return locations


def configure_media_storage(cfg, locations):
    public = [{k: row[k] for k in ("id", "label", "path")} for row in locations]
    cfg["services"]["app"].setdefault("environment", {})["MEDIASEED_STORAGE_ROOTS"] = json.dumps(
        public
    )
    for service in ("app", "qbittorrent"):
        if service not in cfg["services"]:
            if locations:
                raise ValueError("MediaSeed storage requires its owned torrent service")
            continue
        values = cfg["services"][service]
        volumes = values.setdefault("volumes", [])
        for row in locations:
            target = row["path"]
            existing = [v for v in volumes if isinstance(v, dict) and v.get("target") == target]
            if existing and (
                len(existing) != 1
                or existing[0].get("source") != row["source"]
                or existing[0].get("type") != "bind"
            ):
                raise ValueError("MediaSeed storage mount ownership changed")
            if not existing:
                volumes.append(
                    {
                        "type": "bind",
                        "source": row["source"],
                        "target": target,
                        "read_only": False,
                        "bind": {"create_host_path": False},
                    }
                )
        # Both consumers use gid 1000. Host permissions are never changed here.


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
    refresh_host_updater(root, source)
    browser_origin = hub_browser_origin(hub_compose, lan)
    locations = approved_media_storage(root)
    # Domain changes must invalidate the marker too, without changing internal API URLs.
    digest = hashlib.sha256(
        (
            fingerprint(source)
            + "\0"
            + browser_origin
            + "\0"
            + json.dumps(locations, sort_keys=True)
        ).encode()
    ).hexdigest()
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
        cfg["services"]["app"].setdefault("environment", {})[kind.upper() + "_HUB_BROWSER_URL"] = (
            browser_origin
        )
        metadata = context / "pyproject.toml"
        if metadata.is_file():
            version = tomllib.loads(metadata.read_text())["project"]["version"]
            cfg["services"]["app"].setdefault("labels", {})["org.mediahub.app.version"] = version
        if kind == "mediavpn":
            configure_vpn_tun(cfg)
        repair_tls_permissions(folder, cfg)
        if kind == "mediaseed":
            configure_media_storage(cfg, locations)
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
            cfg["services"]["app"]["environment"]["MEDIAVPN_MEDIASEED_PROJECT"] = (
                "mediahub-mediaseed"
            )
            cfg["services"]["app"]["environment"]["MEDIAVPN_MEDIASEED_STORAGE"] = json.dumps(
                locations
            )
        previous_compose = compose_path.read_text() if compose_path.exists() else None
        private(
            compose_path.with_suffix(".before-" + digest[:16] + ".json"),
            previous_compose or json.dumps(cfg),
        )
        command = ["docker", "compose", "-p", project, "-f", str(compose_path)]
        try:
            if approved_media_storage(root) != locations:
                raise ValueError("Approved media storage changed during preparation")
            compose_path.write_text(json.dumps(cfg))
            run(*command, "build", "app")
            if kind == "mediavpn":
                prepare_vpn_helpers(context, root)
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
