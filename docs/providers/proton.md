# Proton WireGuard and NAT-PMP

The implemented provider uses an imported WireGuard profile for a P2P server with
NAT-PMP enabled. Import is data-only; profile scripts/hooks are rejected. OpenVPN
provisioning is not implemented and must not silently fall back to WireGuard.

The Agent first verifies the real tunnel route and public egress. A short-lived
helper in the VPN container's network namespace binds its UDP socket to `tun0`
and requests both TCP and UDP mappings from `10.2.0.1:5351`. Internal port is 1,
preferred external port is 0, requested lifetime is 60 seconds. Response version,
opcode, result, internal port, port range, lifetime and matching TCP/UDP port are
validated. There is no router discovery or alternative-interface fallback.

The helper uses the already-pinned qBittorrent image, no secrets, no mounts,
read-only rootfs and only NET_RAW for interface binding. Only the newly created
helper is removed afterwards; no Docker volumes are deleted.

Owned, tagged `INPUT -i tun0` rules permit the assigned torrent port in the VPN
namespace. Old exact owned rules are reconciled even after an Agent restart;
other firewall rules and the VPN kill switch remain untouched. WebUI and service
ports are rejected. No host/router/WAN management ports are opened.

The authenticated qBittorrent API applies and reads back the port, with UPnP and
random-port selection disabled and interface binding still `tun0`. Renewals occur
before expiry, with monotonic lease validity. A failed renewal/application becomes
Degraded with bounded exponential retry intervals (5–120 seconds); this does not
remove VPN isolation. Validity is re-established after process restart, never
assumed from an old saved timestamp.

Public status exposes only state, current port, last renewal, expiry and the
qBittorrent verification result. A changed port is handled by the same workflow.
Unit tests simulate port changes; a real provider-issued changed port requires a
separate runtime observation and must not be claimed from simulation alone.

References: [Proton manual forwarding](https://protonvpn.com/support/port-forwarding-manual-setup),
[NAT-PMP protocol](https://www.rfc-editor.org/rfc/rfc6886.html).
