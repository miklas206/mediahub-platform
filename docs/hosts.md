# Hosts and pairing

Core addresses registered Agents, not hardcoded LXC/VM classes. `local` is the
default trusted host. Host records retain name/address, last-seen time and the last
successful metadata response. Background collection marks failures offline and
retains stale metadata explicitly; Core remains available.

Remote enrollment uses a cryptographically random 384-bit code, a five-minute
expiry, hashed storage and a single-use database claim. Permanent Agent tokens
are encrypted using Core's existing encryption key and excluded from frontend
responses. Protect and back up that key with the database. Pairing does not
grant public access or configure firewall rules.

1. Provision the remote Agent token locally with `mediahub agent-init`.
2. Configure trusted HTTPS for Core and Agent. Current LAN-only HTTP cannot enroll
   remote Agents. No reverse proxy is installed by Phase 3.
3. In Hosts, enter the intended Agent's private HTTPS IP address and generate a code.
4. On that Agent run `python -m agent.pair --core https://core.example --address
   https://PRIVATE_IP:18767`, optionally `--ca /path/to/ca.pem`. Enter the code at
   the hidden prompt, not as a command-line argument.
5. Core must trust the Agent certificate, including its IP SAN. Agent must trust
   Core's certificate. TLS verification and redirects are never bypassed.

The remote Agent retains its original random credential; enrollment stores it
encrypted in Core. The Agent stores the assigned host ID in its persistent state.
After an ambiguous network failure inspect Hosts before retrying: the code may
already be consumed. This phase does not implement automatic credential rotation,
host deletion, or a full certificate lifecycle.

The built-in local transport is restricted to the private Docker control network
or loopback. Agent has no LAN-published port. For remote operation, trusted TLS
must be supplied explicitly; no insecure fallback is used.

App plans accept `host_id` and `logical_mappings`. Manifest `hostCapabilities` and
`recommendedIsolation` describe compatibility. Per-installation policy can reject
Seedbox on the local host without imposing that layout on other installations.
All real app install plans remain non-executable in this phase.

See [shared storage](shared-storage.md). Logical registration never performs mounts.
