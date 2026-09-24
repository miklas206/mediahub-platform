# Seedbox recovery

Recovery operates only on the installation-owned runtime. Storage and tunnel
verification remain prerequisites, never mere container-running checks.

- Storage loss: stop/block qBittorrent; require a fresh host mount observation,
  matching NFS source/marker and app-UID read/write probe before restarting.
- VPN failure: network kill switch remains active; gated recovery stops the client,
  starts/verifies VPN, restores the forwarded port and verifies client namespace,
  API, interface binding and egress.
- qBittorrent failure: retain the VPN and reverify the client after restart.
- Uncertain client-start result: still attempt to stop the client. A timeout is
  not evidence that Docker did not start it.

At most three automatic component-recovery attempts are allowed in a rolling
600-second window. A brief healthy observation or a manual action must not erase
that history. The manual-intervention latch is not cleared just because time
passes. Lease renewal has its separate bounded-backoff mechanism.

This is not proof of the full first-install transaction. Its failure matrix,
credential rotation and final post-install reboot acceptance remain separate gates.
