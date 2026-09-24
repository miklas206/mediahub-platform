"""First-install private provisioning. Never writes a plaintext password/profile to disk."""

import base64
import hashlib
import io
import json
import os
import secrets
import tarfile
from pathlib import Path

from mediahub.apps.seedbox_credentials import SeedboxCredentials, VPNProfileRegistry
from mediahub.secret_store import SecretStore

from agent.ram_secrets import RuntimeSecrets, verify_ram_directory


def password_verifier(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100000, 64)
    return base64.b64encode(salt).decode() + ":" + base64.b64encode(derived).decode()


def initial_qbit_config(spec, settings, credentials):
    verifier = password_verifier(credentials.webPassword.get_secret_value())
    return (
        "[BitTorrent]\n"
        "Session\\DefaultSavePath=/downloads\n"
        "Session\\TempPath=/downloads/.incomplete\n"
        f"Session\\TempPathEnabled={str(settings.incompleteDownloads).lower()}\n"
        "Session\\Interface=tun0\nSession\\InterfaceName=tun0\n"
        "Session\\AddTorrentStopped=true\nSession\\LSDEnabled=false\n"
        f"Session\\GlobalMaxConnections={settings.maxConnections}\n"
        f"Session\\MaxConnectionsPerTorrent={settings.maxConnectionsPerTorrent}\n"
        f"Session\\MaxActiveDownloads={settings.maxActiveDownloads}\n"
        "Session\\MaxActiveTorrents=2\nSession\\CheckingMemUsageSize=64\n"
        f"Session\\Port={settings.listenPort}\nSession\\UseUPnP=false\n"
        "[Preferences]\nWebUI\\Address=*\n"
        f"WebUI\\Port={spec.webPort}\nWebUI\\Username={credentials.webUsername}\n"
        f'WebUI\\Password_PBKDF2="@ByteArray({verifier})"\n'
        "WebUI\\LocalHostAuth=true\nWebUI\\AuthSubnetWhitelistEnabled=false\n"
        "WebUI\\CSRFProtection=true\nWebUI\\HostHeaderValidation=true\n"
        "[Application]\nFileLogger\\Enabled=false\n"
    )


def private_record(credentials):
    return json.dumps(
        {
            "vpnConfig": credentials.vpnConfig.get_secret_value(),
            "webUsername": credentials.webUsername,
            "webPassword": credentials.webPassword.get_secret_value(),
        }
    ).encode()


def provision_initial(policy, spec, settings, credentials):
    """Materialize private runtime; leave persistent client data to owned-container provisioning."""
    root = Path(policy.workRoot)
    verify_ram_directory(root / "secrets")
    credentials = SeedboxCredentials.model_validate(credentials)
    credentials.vpnConfig = VPNProfileRegistry().get(spec.protocol).validate(credentials.vpnConfig)
    for path in (Path(policy.paths.appdata), Path(policy.paths.vpnState)):
        if path.resolve() != path or not path.is_relative_to(root):
            raise ValueError("Private runtime directory outside delegation")
        path.mkdir(mode=0o700, exist_ok=True)
    store = SecretStore(root / "vault")
    record = private_record(credentials)
    # Missing is acceptable only for a fresh install; unreadable/corrupt records
    # must not be treated as missing and silently overwritten.
    active = root / "vault" / "seedbox-runtime.sealed"
    if active.exists() or active.is_symlink():
        existing = json.loads(store.get("seedbox-runtime"))
        previous = SeedboxCredentials.model_validate(existing)
        existing["vpnConfig"] = (
            VPNProfileRegistry().get(spec.protocol).validate(previous.vpnConfig).get_secret_value()
        )
        if existing != json.loads(record):
            raise ValueError("Existing credential differs; controlled rotation required")
    else:
        store.put("seedbox-runtime", record)
    dns = Path(policy.paths.dnsConfig)
    if not dns.exists():
        fd = os.open(
            dns, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644
        )
        with os.fdopen(fd, "w") as stream:
            stream.write("nameserver 10.2.0.1\n")
    elif dns.is_symlink():
        raise ValueError("Unsafe DNS file")
    RuntimeSecrets(root).materialize()


def client_config_archive(spec, settings, credentials):
    """In-memory archive containing a password verifier, never plaintext credentials."""
    content = initial_qbit_config(spec, settings, credentials).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        directory = tarfile.TarInfo("qBittorrent")
        directory.type, directory.mode = tarfile.DIRTYPE, 0o700
        directory.uid, directory.gid = spec.uid, spec.gid
        archive.addfile(directory)
        file = tarfile.TarInfo("qBittorrent/qBittorrent.conf")
        file.size, file.mode = len(content), 0o600
        file.uid, file.gid = spec.uid, spec.gid
        archive.addfile(file, io.BytesIO(content))
    return output.getvalue()
