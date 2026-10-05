"""Browser-only app links: no requests, DNS resolution or inferred ports."""

import re
from urllib.parse import unquote, urlsplit

APP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


def validate_launch_url(value: str, base_url: str, allow_http: bool, token: str = ""):
    decoded = unquote(value)
    if (
        len(value) > 500
        or any(ord(char) < 33 or ord(char) == 127 for char in decoded)
        or "\\" in decoded
        or (token and (token in value or token in decoded))
    ):
        raise ValueError("Invalid app launch URL")
    try:
        parsed, base = urlsplit(value), urlsplit(base_url)
        if (
            parsed.scheme not in ({"https", "http"} if allow_http else {"https"})
            or not parsed.hostname
            or parsed.hostname != base.hostname
            or parsed.port == 0
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid app launch URL")
    except ValueError:
        raise ValueError("Invalid app launch URL") from None
    return value
