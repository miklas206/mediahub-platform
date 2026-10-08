"""Read selected stopped-client configuration through an ephemeral read-only helper.

No chmod, no downloads mount, no network, no credentials in container metadata.
"""

import io
import tarfile
import uuid
from pathlib import PurePosixPath

import httpx
from mediahub.app_backups import LIMIT


async def client_configuration(driver):
    policy, spec = driver.binding()
    name = "mediahub-backup-" + uuid.uuid4().hex
    body = {
        "Image": policy.paths.torrentImage,
        "User": f"{spec.uid}:{spec.gid}",
        "Entrypoint": ["/bin/true"],
        "Labels": {"mediahub.backup": spec.installationId},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 64 * 1024**2,
            "MemorySwap": 64 * 1024**2,
            "LogConfig": {"Type": "none"},
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": policy.paths.appdata,
                    "Target": "/config",
                    "ReadOnly": True,
                }
            ],
        },
    }
    identifier = (
        await driver.request("POST", "/containers/create", params={"name": name}, json=body)
    ).json()["Id"]
    entries = {}
    try:
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(driver.socket)),
            base_url="http://docker",
            trust_env=False,
            timeout=30,
        ) as client:
            for filename in [
                "categories.json",
                "qBittorrent-data.conf",
                "watched_folders.json",
                "BT_backup",
                "rss",
            ]:
                data = bytearray()
                async with client.stream(
                    "GET",
                    f"/containers/{identifier}/archive",
                    params={"path": "/config/qBittorrent/" + filename},
                ) as response:
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    async for block in response.aiter_bytes():
                        data.extend(block)
                        if len(data) > LIMIT:
                            raise ValueError("Configuration exceeds bounded size")
                with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                    for member in archive:
                        p = PurePosixPath(member.name)
                        if member.isdir():
                            continue
                        if (
                            not member.isfile()
                            or p.is_absolute()
                            or ".." in p.parts
                            or p.parts[0] != filename
                        ):
                            raise ValueError("Unsafe configuration archive")
                        if (
                            member.size + sum(map(len, entries.values())) > LIMIT
                            or len(entries) >= 10000
                        ):
                            raise ValueError("Configuration exceeds bounded size")
                        entries["qBittorrent/" + member.name] = archive.extractfile(member).read(
                            member.size + 1
                        )
        return entries
    finally:
        await driver.request(
            "DELETE", f"/containers/{identifier}", params={"force": "true", "v": "false"}
        )
