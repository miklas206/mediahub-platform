# Linux / Proxmox preparation — not deployed

Target assumptions: a dedicated Debian 12-class Linux environment, Python 3.12 container image,
64-bit architecture supported by the chosen images, local filesystem with POSIX permissions,
and Docker Engine + Compose v2 for the optional container deployment. Core itself needs no Docker.
Windows is development only. The runtime paths and code do not require Windows in production.

`compose.production.yaml` is a preparation skeleton for **new Core + Agent only**. No Plex, qBittorrent,
VPN, reverse proxy, existing media or engine socket is included. It uses non-root UID/GID 10001,
dropped capabilities, private control networking and separately named persistent volumes.
Core publishes loopback 18765; Agent 18767 is not published. Core data/key live in `core_data`, Agent
token in `agent_state`, new planned appdata in `new_storage`. The private network intentionally has
no public egress; app image installation is outside this phase.

On a NEW Linux development host only, after reviewing the files:

```sh
docker compose -f compose.production.yaml build
docker compose -f compose.production.yaml run --rm agent python -c 'from agent.main import AgentConfig, initialize; initialize(AgentConfig())'
docker compose -f compose.production.yaml up -d
```

No installation token is required. Keep the instance private until the first
administrator is created; the first visitor can claim an unconfigured instance.

Use an SSH tunnel for browser access to loopback, or configure your own authenticated TLS proxy
with exact origins/trusted proxy addresses. Do not expose Agent or bypass authentication.
Do not run volume-deleting cleanup commands. Stop/start only this new Compose project if needed.

For Proxmox, use a NEW dedicated unprivileged LXC after verifying nesting, cgroups, storage permissions
and Docker support for that host. Do not convert the existing VM or enable privileged LXC merely to
make Docker work. Native Linux Core + Agent is another future packaging option. GPU/media mounts,
USB storage, lifecycle permissions and real service migration require a separate reviewed phase.

This skeleton has not been built/run on Linux/Docker/Proxmox in this Windows verification. Pin release
image digests, validate volume ownership and resource limits, test backup/restore and harden the
host before production deployment. Docker/Compose readiness is reported honestly as unavailable
when not installed; it is not an installation success indicator.
