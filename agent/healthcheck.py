"""Container health probe using the same configured identity and TLS validation."""

import os
import ssl
import urllib.request

from agent.main import AgentConfig


def main():
    config = AgentConfig()
    hostname = os.environ.get("MEDIAHUB_AGENT_HEALTH_HOST", config.listen_host)
    if hostname in {"0.0.0.0", "::"}:
        hostname = "127.0.0.1"
    context = None
    scheme = "http"
    if config.tls_cert:
        scheme = "https"
        context = ssl.create_default_context(cafile=str(config.tls_cert.parent / "ca.pem"))
    request = urllib.request.Request(
        f"{scheme}://{hostname}:{config.port}/v1/health",
        headers={"Authorization": "Bearer " + config.token_file.read_text().strip()},
    )
    handlers = [urllib.request.ProxyHandler({})]
    if context:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("Unhealthy Agent")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(1) from None
