"""Expose a tiny sanitized cloudflared status document to one trusted LAN client."""

import json
import os
import re
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = os.environ.get("MEDIAHUB_CLOUDFLARED_LISTEN", "127.0.0.1")
PORT = int(os.environ.get("MEDIAHUB_CLOUDFLARED_PORT", "20242"))
ALLOWED_SOURCE = os.environ.get("MEDIAHUB_CLOUDFLARED_ALLOWED_SOURCE", "127.0.0.1")
UPSTREAM = os.environ.get("MEDIAHUB_CLOUDFLARED_METRICS", "http://127.0.0.1:20241/metrics")
METRIC = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+(?P<value>[-+0-9.eE]+)$"
)


def summarize(text):
    values = {
        "cloudflared_tunnel_ha_connections": 0.0,
        "cloudflared_tunnel_total_requests": 0.0,
        "cloudflared_tunnel_request_errors": 0.0,
    }
    version = None
    for line in text.splitlines():
        if line.startswith("cloudflared_build_info"):
            match = re.search(r'version="([^"\\]{1,80})"', line)
            version = match.group(1) if match else version
        match = METRIC.match(line)
        if match and match.group("name") in values:
            values[match.group("name")] += float(match.group("value"))
    return {
        "metricsReachable": True,
        "connections": int(values["cloudflared_tunnel_ha_connections"]),
        "totalRequests": int(values["cloudflared_tunnel_total_requests"]),
        "requestErrors": int(values["cloudflared_tunnel_request_errors"]),
        "version": version,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "MediaHubCloudflaredStatus/1"

    def log_message(self, *_):
        return

    def do_GET(self):
        if self.client_address[0] != ALLOWED_SOURCE or self.path != "/status":
            self.send_error(404)
            return
        try:
            with urllib.request.urlopen(UPSTREAM, timeout=2) as response:
                body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("metrics response too large")
            output = summarize(body.decode("utf-8", "replace"))
            code = 200
        except Exception:
            output = {
                "metricsReachable": False,
                "connections": 0,
                "totalRequests": 0,
                "requestErrors": 0,
                "version": None,
            }
            code = 503
        payload = json.dumps(output, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    ThreadingHTTPServer((LISTEN, PORT), Handler).serve_forever()
