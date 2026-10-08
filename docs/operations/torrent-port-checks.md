# Torrent port checks

The Seedbox panel separates port configuration, the listening socket, and reachability.
Agent synchronizes the Proton allocation and the narrow VPN firewall rule as before.
It now also verifies a non-loopback TCP LISTEN entry in the torrent namespace after
applying the qBittorrent port. A bounded rebind wait allows qBittorrent to change sockets.
Diagnostic messages distinguish VPN identity, Proton lease, firewall and client checks.
No router port is opened and the existing VPN isolation remains in place.

Core checks the paired Agent's verified public VPN address and torrent port every minute.
The target is not accepted from a browser, and private, reserved and multicast addresses,
expired leases and unsafe ports are rejected. Core tests TCP with a five-second timeout,
then confirms the endpoint is unchanged before publishing a result. A manual check is
available and rate-limited to one per 15 seconds. Results older than 90 seconds become
unknown. The UI also hides a success for a different endpoint or invalid lease.

Two consecutive TCP failures generate a notification. A successful check clears it.
A failed connection is a diagnostic, not proof of a VPN leak; the system does not disable
the kill switch or blindly restart containers to make this test succeed.

The probe originates on Core, outside the torrent VPN namespace. It verifies TCP from
that location, not UDP, tracker timing or universal reachability from every peer. A Core
host itself routed through the same VPN may encounter provider hairpin restrictions.
The new Core supplies the connection test and UI; the new Agent supplies socket verification.
