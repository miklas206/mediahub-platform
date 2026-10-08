"""Bounded synthetic test, executed in the verified VPN namespace only."""

import json
import time
import urllib.request


def measure():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    rates = {}
    for direction, size in (("download", 8 * 1024**2), ("upload", 2 * 1024**2)):
        url = "https://speed.cloudflare.com/__down?bytes=" + str(size)
        data = None
        if direction == "upload":
            url, data = "https://speed.cloudflare.com/__up", b"0" * size
        request = urllib.request.Request(url, data=data, headers={"Cache-Control": "no-cache"})
        started = time.monotonic()
        with opener.open(request, timeout=8) as response:
            received = 0
            while chunk := response.read(65536):
                received += len(chunk)
                if received > size + 65536 or time.monotonic() - started > 10:
                    raise ValueError("Probe limit exceeded")
            if direction == "download" and received != size:
                raise ValueError("Incomplete sample")
        rates[direction + "Mbps"] = round(size * 8 / (time.monotonic() - started) / 1e6, 2)
    return rates


if __name__ == "__main__":
    try:
        print(json.dumps(measure()))
    except Exception:
        print(json.dumps({"error": "Speed measurement unavailable"}))
        raise SystemExit(1) from None
