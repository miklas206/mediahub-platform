"""Read-only socket check executed inside the torrent network namespace."""

import sys
from pathlib import Path


class ListeningPortError(ValueError):
    """Preferences match, but there is no eligible TCP listener."""


def listening(rows, port):
    for row in rows.splitlines()[1:]:
        columns = row.split()
        if len(columns) >= 4 and columns[3] == "0A":
            address, _, value = columns[1].rpartition(":")
            if (
                int(value, 16) == port
                and not address.endswith("7F")
                and address != "00000000000000000000000001000000"
            ):
                return True
    return False


if __name__ == "__main__":
    port = int(sys.argv[1])
    found = any(
        listening(path.read_text(), port)
        for path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
        if path.exists()
    )
    print("listening" if found else "not_listening")
    raise SystemExit(0 if found else 1)
