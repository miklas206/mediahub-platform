# Unprivileged LXC deployment

Create a new unprivileged Debian LXC with approximately 2 cores, 4GiB RAM, 1GiB swap
and a 32GiB root disk. Enable nesting/keyctl for the Docker workload. Do not switch
to privileged mode or disable AppArmor merely to work around a failure. Stop and
review isolation changes first. Use a dedicated VM for untrusted workloads.

Install Docker Engine/CLI and Compose from the [official Debian repository](https://docs.docker.com/engine/install/debian/).
Verify engine, Compose, cgroup version and a harmless test container. No Docker
installation belongs on the Proxmox host for this deployment.

## New filesystem only

Use an operator-selected root, for example `/opt/mediahub`:

- `releases/<release>`: immutable application source/build inputs
- `config/production.env`: instance configuration, root-only
- `data`: Core SQLite database, settings and encryption key, UID/GID10001, mode0700
- `secrets/agent`: persistent Agent token/identity, UID/GID10001, mode0700
- `storage/appdata`, `storage/backups`, `storage/temp`: new Agent-approved paths,
  UID/GID10001, mode0750; no existing media in this phase
- `logs`: bounded build/diagnostic output; container logs rotate at 10MB x3

Set `MEDIAHUB_ROOT`, explicit private `LAN_IP` and `DOCKER_GID` (from the numeric
group of `/var/run/docker.sock`) in the environment file. Optional
`SEEDBOX_REQUIRES_REMOTE_HOST=true` prohibits local Seedbox planning on this installation.
No user-specific IP, guest ID or media path is a generic default.

From the release directory:

```sh
docker compose --env-file /opt/mediahub/config/production.env -f compose.production.yaml build
docker compose --env-file /opt/mediahub/config/production.env -f compose.production.yaml run --rm --no-deps agent python -m mediahub.cli agent-init
docker compose --env-file /opt/mediahub/config/production.env -f compose.production.yaml up -d
```

Adjust the example environment-file path for your root. The app runs as10001 with
all capabilities dropped and no-new-privileges. Agent's supplemental group grants
Docker socket access, which is root-equivalent within the LXC even when mounted RO.
Core has no socket or media mount. Agent has no published port. Core binds only the
explicit LAN IPv4 on18765, not every IPv4/IPv6 interface. No proxy or router changes.

Complete the real wizard using a privately retrieved `mediahub bootstrap-token`.
The operator enters their own admin password. Choose only new appdata/backups/temp
directories in this phase. Local mappings can reference `/storage/...` inside the
Agent; metadata is distinct from future Docker host bind-source translation.

Validate restart/recreate persistence, Agent stop/reconnect, runtime outage and LXC
reboot before declaring production ready. Never use `down -v`. Back up SQLite with
its encryption key and Agent identity. Root-disk persistence is not an external backup.
Reserve the LXC's DHCP address before relying on a stable LAN endpoint; do not guess
a static address or change the router without authorization.
