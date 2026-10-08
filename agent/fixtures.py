"""Synthetic test/development inputs. No real service names, paths or credentials."""


def containers():
    def base(letter, name, image, target):
        return {
            "Id": letter * 64,
            "Name": "/example-" + name,
            "Config": {
                "Image": image,
                "Env": [
                    "PUID=1000",
                    "PGID=1000",
                    "EXAMPLE_PASSWORD=fixture-value-must-not-leave-agent",
                ],
            },
            "State": {"Status": "running"},
            "HostConfig": {"NetworkMode": "bridge"},
            "NetworkSettings": {"Ports": {}, "Networks": {"example": {}}},
            "Mounts": [
                {"Type": "bind", "Source": "/example/" + name, "Destination": target, "RW": True}
            ],
        }

    plex = base("a", "plex", "lscr.io/linuxserver/plex:example", "/config")
    plex["NetworkSettings"]["Ports"] = {"32400/tcp": [{"HostPort": "32400", "HostIp": "0.0.0.0"}]}
    torrent = base("b", "qbittorrent", "lscr.io/linuxserver/qbittorrent:example", "/downloads")
    torrent["HostConfig"]["NetworkMode"] = "container:" + "c" * 64
    vpn = base("c", "vpn", "qmcgaw/gluetun:example", "/gluetun")
    vpn["Config"]["Env"] += [
        "VPN_TYPE=wireguard",
        "WIREGUARD_PRIVATE_KEY=fixture-key-must-not-leave-agent",
    ]
    return [plex, torrent, vpn]
