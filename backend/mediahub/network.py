"""Deployment-neutral URL/cookie policy; never trusts arbitrary Host/forwarded host."""

from urllib.parse import urlsplit

from mediahub.errors import DomainError


def browser_origin(request, config):
    # Scheme is normalized by trusted-proxy middleware, never by reading raw headers here.
    origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin not in config.origins:
        raise DomainError("origin_rejected", "Browser address is not configured", 403)
    return origin


def cookie_options(request, config):
    origin = browser_origin(request, config)
    return {
        "httponly": True,
        "secure": origin.startswith("https://"),
        "samesite": config.cookie_samesite,
        "path": "/",
    }


def absolute_url(config, path, *, request=None, public=False):
    parsed = urlsplit(path)
    if not path.startswith("/") or path.startswith("//") or parsed.netloc or parsed.scheme:
        raise ValueError("Expected a local absolute path")
    if "\\" in path or any(ord(c) < 32 for c in path):
        raise ValueError("Unsafe URL path")
    if public:
        if not config.public_url:
            raise ValueError("Public URL is not configured")
        origin = config.public_url
    else:
        origin = browser_origin(request, config) if request else config.base_url
    return origin + path
