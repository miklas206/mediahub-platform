"""Configure the verified VPN port before the torrent client starts."""


async def configure_stopped_port(driver, port, spec):
    import io
    import tarfile

    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("No port allocation")
    client = await driver.container("torrent")
    if client["State"]["Running"]:
        raise ValueError("Client must be stopped")
    response = await driver.request(
        "GET",
        "/containers/" + client["Id"] + "/archive",
        params={"path": "/config/qBittorrent/qBittorrent.conf"},
    )
    with tarfile.open(fileobj=io.BytesIO(response.content)) as archive:
        members = archive.getmembers()
        if len(members) != 1 or not members[0].isfile():
            raise ValueError("Invalid configuration archive")
        config = archive.extractfile(members[0]).read().decode()
    import re

    if len(config) > 1024 * 1024:
        raise ValueError("Invalid configuration")
    config, count = re.subn(r"(?m)^Session\\Port=.*$", lambda _: f"Session\\Port={port}", config)
    if count != 1:
        raise ValueError("Missing client port setting")
    payload = config.encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        member = tarfile.TarInfo("qBittorrent.conf")
        member.size = len(payload)
        member.mode = 0o600
        member.uid = spec.uid
        member.gid = spec.gid
        archive.addfile(member, io.BytesIO(payload))
    await driver.request(
        "PUT",
        "/containers/" + client["Id"] + "/archive",
        params={"path": "/config/qBittorrent"},
        content=buffer.getvalue(),
        headers={"Content-Type": "application/x-tar"},
    )
