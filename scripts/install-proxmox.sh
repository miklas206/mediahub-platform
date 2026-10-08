#!/usr/bin/env bash
# The inherited installer created a new LXC and installed qlerup/fjordhub.
# This private beta fork is deployed to an existing, explicitly selected host.
set -Eeuo pipefail
printf '%s\n' \
  'fjordcopy: automatic creation of a new Proxmox LXC is not configured.' \
  'Install on your existing beta Docker host using README.md.' \
  'No container or server settings have been changed.' >&2
exit 64
