# Seedbox Agent updates

Updates shows the paired Seedbox Agent separately from the qBittorrent/VPN app.
The Agent installed commit is compared to the configured GitHub repository main branch.
Older Agents without a commit marker are shown as needing an update, not as current.

1. Install the new Core through its existing updater.
2. Open Updates over HTTPS and find Seedbox Agent.
3. Read and verify the SSH fingerprint for the automatically selected paired host.
4. Enter that host's root SSH password and choose Prepare SSH for update.
5. Optionally enable Remember SSH access before verification. Only successfully verified
   credentials are saved, encrypted using MediaHub's existing encryption key and bound
   to the paired host ID, IP, SSH port and trusted fingerprint. They survive Core restarts
   and enable Update Agent and Update all without entering the password again.
6. Without Remember, preparation expires after 15 minutes and is consumed by one job.
   Forget saved SSH access removes the encrypted entry and temporary preparation; it does
   not cancel a job already running. Passwords are never returned to the browser or logs.
   Verify saved SSH access reconnects and can reconcile an interrupted remote job.

Saved credentials reside on the MediaHub server, not in browser storage. First setup
still requires valid root SSH access. A forgotten password must be recovered or reset
through an existing administrator console; this feature does not bypass SSH authentication.

The console includes build progress and verification. Update all updates Agent before
Core; an Agent failure stops the queue. qBittorrent's displayed version is independent.

## Supported installations

The remote host must have Python 3.11 with tarfile data-filter support, Docker and
Compose v2. The Agent must be a running service from a single existing Compose file.
The worker identifies it by comparing a digest of its configured token to the paired
token; it refuses missing or ambiguous matches. Other layouts need operator migration.
No guessed container name, host path or replacement configuration is accepted from the browser.

Source is downloaded by Core from a pinned GitHub commit, normalized, hashed and uploaded
through fingerprint-pinned SSH. The host builds the Agent while the old image runs,
saves the original Compose file and replaces only the Agent image. Only that service
is recreated with --no-deps. Torrent/VPN containers and media are not updated by this job.
For JSON Compose files, unrelated configuration and expressions are preserved. For YAML,
Compose's resolved JSON is written back (valid YAML); environment interpolation is resolved
at that point. The exact original file is retained in the private job folder for rollback.

Core must verify the new commit through the paired authenticated HTTPS connection within
two minutes after replacement, otherwise the worker restores the old Compose configuration
and Agent. A failed rollback is explicitly reported. The previous image is retained.
A detached worker and host lock prevent loss of SSH from leaving an unverified install
accepted, or concurrent jobs replacing the Agent simultaneously.

Jobs and backups are stored in /var/lib/mediahub-agent-updates/<operationId> on the
Seedbox host, mode 0700. Core persists sanitized console/status and, only when explicitly selected, an encrypted SSH credential entry. If Core or SSH
was interrupted, wait for remote completion/rollback and prepare SSH again to reconcile
the saved job before retrying. Do not start another host update outside MediaHub concurrently.

Verification for this change uses simulated Docker/SSH and local UI tests. Installation
and live behavior on a user's server require a separately initiated update.
