"""Initialize only new Docker volumes; invoked inside the built Agent image."""

import argparse
import ipaddress
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

VOLUMES = ("data", "state", "storage", "credentials", "core-tls", "agent-tls", "trust", "authority")


def compose_config(project, address):
    if project != "mediahub-guided":
        raise ValueError("Unexpected installation project")
    ip = ipaddress.IPv4Address(address)
    if not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_link_local:
        raise ValueError("Use a local IPv4 address")
    origin = f"https://{ip}:18765"
    common = {
        "restart": "unless-stopped",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "mem_limit": "512m",
        "memswap_limit": "512m",
        "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
    }
    core = {
        **common,
        "image": f"{project}-core:local",
        "ports": [f"{ip}:18765:18765"],
        "networks": ["control", "lan"],
        "volumes": [
            "data:/data",
            "core-tls:/tls:ro",
            "trust:/trust:ro",
            "credentials:/credentials:ro",
            "storage:/storage:ro",
        ],
        "environment": {
            "MEDIAHUB_BASE_URL": origin,
            "MEDIAHUB_ALLOWED_ORIGINS": json.dumps([origin]),
            "MEDIAHUB_BROWSER_TLS_CERT": "/tls/server.pem",
            "MEDIAHUB_BROWSER_TLS_KEY": "/tls/server.key",
            "MEDIAHUB_AGENT_URL": "https://agent:18767",
            "MEDIAHUB_AGENT_TOKEN_FILE": "/credentials/token",
            "MEDIAHUB_AGENT_CA_FILE": "/trust/ca.pem",
            "MEDIAHUB_STORAGE_ROOTS": '["/storage"]',
            "MEDIAHUB_SETUP_STORAGE": json.dumps([
                {"name": name, "kind": kind, "path": f"/storage/{kind}"}
                for name, kind in (
                    ("Appdata", "appdata"), ("Movies", "movies"),
                    ("TV", "tv"), ("Downloads", "downloads"),
                )
            ]),
            "MEDIAHUB_DEV_MODE": "false",
            "MEDIAHUB_MOCK_APP": "false",
            "MEDIAHUB_SEEDBOX_REQUIRES_REMOTE_HOST": "true",
        },
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                f"import ssl,urllib.request;r=urllib.request.Request('https://127.0.0.1:18765/api/health',headers={{'Host':'{ip}:18765'}});urllib.request.urlopen(r,context=ssl.create_default_context(cafile='/trust/ca.pem'),timeout=4)",
            ],
            "interval": "10s",
            "timeout": "5s",
            "retries": 12,
            "start_period": "30s",
        },
    }
    agent = {
        **common,
        "image": f"{project}-agent:local",
        "networks": ["control"],
        "volumes": [
            "state:/state",
            "credentials:/credentials:ro",
            "storage:/storage",
            "agent-tls:/tls:ro",
            "trust:/trust:ro",
        ],
        "environment": {
            "MEDIAHUB_AGENT_STATE_DIR": "/state",
            "MEDIAHUB_AGENT_TOKEN_FILE": "/credentials/token",
            "MEDIAHUB_AGENT_STORAGE_ROOTS": '["/storage"]',
            "MEDIAHUB_AGENT_CREATE_ENABLED": "true",
            "MEDIAHUB_AGENT_LISTEN_HOST": "0.0.0.0",
            "MEDIAHUB_AGENT_TLS_CERT": "/tls/server.pem",
            "MEDIAHUB_AGENT_TLS_KEY": "/tls/server.key",
        },
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                "import pathlib,ssl,urllib.request;r=urllib.request.Request('https://127.0.0.1:18767/v1/health',headers={'Authorization':'Bearer '+pathlib.Path('/credentials/token').read_text().strip()});urllib.request.urlopen(r,context=ssl.create_default_context(cafile='/trust/ca.pem'),timeout=4)",
            ],
            "interval": "10s",
            "timeout": "5s",
            "retries": 12,
            "start_period": "30s",
        },
    }
    return {
        "name": project,
        "services": {"core": core, "agent": agent},
        "networks": {"control": {"internal": True}, "lan": {}},
        "volumes": {name: {"external": True, "name": f"{project}-{name}"} for name in VOLUMES},
    }


def write_new(path, content, mode=0o600, owner=10001):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
    os.chown(path, owner, owner)


def initialize(address, root=Path("/bootstrap"), output=Path("/output")):
    config = compose_config("mediahub-guided", address)
    for name in VOLUMES:
        directory = root / name
        if not directory.is_dir() or any(directory.iterdir()):
            raise ValueError(f"Volume {name} is missing or not empty; nothing overwritten")
    if (output / "compose.json").exists() or (output / "ca.pem").exists():
        raise ValueError("Installation output already exists")
    for name in VOLUMES:
        directory = root / name
        directory.chmod(0o700)
        os.chown(
            directory, 0 if name == "authority" else 10001, 0 if name == "authority" else 10001
        )
    for name in ("movies", "tv", "other", "downloads", "appdata"):
        directory = root / "storage" / name
        directory.mkdir(mode=0o2770)
        os.chown(directory, 10001, 1000)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MediaHub Guided Local CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    def private_bytes(key):
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    public_ca = ca.public_bytes(serialization.Encoding.PEM)
    write_new(root / "authority" / "ca.key", private_bytes(ca_key), owner=0)
    write_new(root / "authority" / "ca.pem", public_ca, owner=0)
    write_new(root / "trust" / "ca.pem", public_ca, mode=0o644)
    for role in ("core", "agent"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        sans = [x509.DNSName(role), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        if role == "core":
            sans.extend([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(address))])
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, role)]))
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        write_new(root / f"{role}-tls" / "server.key", private_bytes(key))
        write_new(
            root / f"{role}-tls" / "server.pem", cert.public_bytes(serialization.Encoding.PEM)
        )
    write_new(root / "credentials" / "token", secrets.token_urlsafe(48).encode())
    write_new(output / "ca.pem", public_ca, mode=0o644, owner=0)
    write_new(output / "compose.json", json.dumps(config, indent=2).encode(), mode=0o644, owner=0)
    print("Public CA SHA-256:", ca.fingerprint(hashes.SHA256()).hex())
    print("New volumes initialized. No existing media mounted or modified.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1")
    initialize(parser.parse_args().address)
