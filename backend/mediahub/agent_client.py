import ssl
from pathlib import Path
from typing import Protocol

import httpx

from mediahub.errors import DomainError


class RuntimeAgent(Protocol):
    async def request(self, method: str, path: str, payload: dict | None = None): ...


class AgentClient:
    def __init__(self, config, token=None):
        self.config = config
        self.token = token

    async def request(self, method, path, payload=None):
        try:
            token = self.token or Path(self.config.agent_token_file).read_text().strip()
            if len(token) < 40:
                raise ValueError()
            transport = (
                httpx.AsyncHTTPTransport(uds=str(self.config.agent_socket))
                if self.config.agent_socket
                else None
            )
            async with httpx.AsyncClient(
                base_url=self.config.agent_url,
                transport=transport,
                timeout=(
                    180
                    if path.startswith("/v1/backups/")
                    else 90
                    if path
                    in {
                        "/v1/seedbox/torrents/add",
                        "/v1/seedbox/torrents/action",
                        "/v1/plex/install",
                    }
                    else 8
                ),
                trust_env=False,
                follow_redirects=False,
                verify=ssl.create_default_context(
                    cafile=getattr(self.config, "agent_ca_file", None)
                ),
            ) as client:
                response = await client.request(
                    method, path, json=payload, headers={"Authorization": "Bearer " + token}
                )
            if response.status_code in {401, 403}:
                raise DomainError(
                    "agent_rejected",
                    "Agent authentication or path authorization was rejected",
                    response.status_code,
                )
            body = response.json()
            if not response.is_success:
                raise DomainError(
                    body.get("code", "agent_error"),
                    body.get("message", "Agent operation failed"),
                    response.status_code,
                )
            return body
        except (OSError, httpx.HTTPError, ValueError):
            raise DomainError(
                "agent_unavailable", "MediaHub Agent is unavailable or not configured", 503
            ) from None

    async def status(self):
        try:
            return {"connected": True, **await self.request("GET", "/v1/status")}
        except DomainError as error:
            return {
                "connected": False,
                "version": None,
                "docker": {"available": False},
                "message": error.message,
            }
