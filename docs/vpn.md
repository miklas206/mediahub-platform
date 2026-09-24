# VPN safety

Torrent traffic shares the VPN container network namespace and binds to `tun0`.
The kill switch remains active independently of Core/Agent availability. A healthy
Docker container, a configured profile or a displayed country is not tunnel proof:
verify routing and public egress and compare qBittorrent with the VPN.

VPN credentials are encrypted at rest and materialized only on protected tmpfs.
See [secret custody](security/secrets.md). Provider/profile adapters remain separate
from generic lifecycle control; unsupported protocols must fail explicitly.
See [Proton forwarding](providers/proton.md).

Port-forwarding health is separate from tunnel health. Missing forwarding reduces
inbound peer connectivity but must never enable direct WAN fallback. VPN encryption
does not make a server anonymous: the ISP can still see a VPN connection and traffic
timing/volume, while the VPN provider becomes a trusted party.
