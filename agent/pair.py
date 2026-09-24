"""Explicit remote enrollment. Never prints permanent credentials or skips TLS validation."""

import argparse
import getpass
import json
import os
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mediahub.hosts import remote_address

from agent.main import AgentConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True)
    parser.add_argument(
        "--address", required=True, help="Agent private HTTPS URL, as entered in Core"
    )
    parser.add_argument("--ca", type=Path, help="Trusted CA bundle for Core")
    args = parser.parse_args()
    parsed = urlsplit(args.core)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        parser.error("Core must be an HTTPS origin")
    address = remote_address(args.address)
    config = AgentConfig()
    identity_path = config.state_dir / "identity.json"
    if identity_path.exists():
        parser.error("Agent already has an identity; automatic overwrite is refused")
    token = getpass.getpass("Single-use pairing code: ")
    context = ssl.create_default_context(cafile=str(args.ca) if args.ca else None)
    try:
        with httpx.Client(
            verify=context, trust_env=False, follow_redirects=False, timeout=10
        ) as client:
            response = client.post(
                args.core.rstrip("/") + "/api/v1/hosts/pair",
                json={
                    "token": token,
                    "address": address,
                    "agent_token": config.token_file.read_text().strip(),
                },
            )
        response.raise_for_status()
        result = response.json()["data"]
        fd = os.open(identity_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"host_id": result["host_id"], "core": args.core}, stream)
        print("Agent paired. Identity persisted; credential not displayed.")
    except (httpx.HTTPError, OSError, KeyError, ValueError):
        raise SystemExit(
            "Enrollment failed. Check TLS, connectivity and pairing status in Core; credentials were not printed."
        ) from None


if __name__ == "__main__":
    main()
