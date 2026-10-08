#!/bin/sh
# Run from a reviewed source checkout. No curl-to-shell, disk formatting or migration.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 scripts/install_linux.py "$@"
