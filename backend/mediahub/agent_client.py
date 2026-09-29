import ssl
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Protocol

import httpx

from mediahub.errors import DomainError


class RuntimeAgent(Protocol):
    async def request(self, method: str, path: str, payload: dict | None = None): ...

    async def upload_chunk(
        self,
        identifier: str,
        root: str,
        offset: int,
        content: AsyncIterable[bytes],
        expected_size: int,
    ): ...

    async def upload(
        self,
        path: str,
        filename: str,
        content: AsyncIterable[bytes],
        expected_size: int | None = None,
    ): ...


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

    async def upload(self, path, filename, content, expected_size=None):
        """Stream an upload to the authenticated Agent without buffering it in Core."""

        return await self._stream_upload(
            "/v1/files/upload",
            {
                "path": path,
                "filename": filename,
                **({"expected_size": str(expected_size)} if expected_size is not None else {}),
            },
            content,
            expected_size,
        )

    async def upload_chunk(self, identifier, root, offset, content, expected_size):
        return await self._stream_upload(
            "/v1/uploads/" + identifier,
            {"root": root, "offset": str(offset)},
            content,
            expected_size,
        )

    async def _stream_upload(self, endpoint, params, content, expected_size):
        try:
            token = self.token or Path(self.config.agent_token_file).read_text().strip()
            if len(token) < 40:
                raise ValueError()
            transport = (
                httpx.AsyncHTTPTransport(uds=str(self.config.agent_socket))
                if self.config.agent_socket
                else None
            )
            headers = {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/octet-stream",
            }
            if expected_size is not None:
                headers["Content-Length"] = str(expected_size)
            async with httpx.AsyncClient(
                base_url=self.config.agent_url,
                transport=transport,
                timeout=httpx.Timeout(connect=8, read=60, write=None, pool=8),
                trust_env=False,
                follow_redirects=False,
                verify=ssl.create_default_context(
                    cafile=getattr(self.config, "agent_ca_file", None)
                ),
            ) as client:
                response = await client.put(
                    endpoint,
                    params=params,
                    content=content,
                    headers=headers,
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
                    body.get("message", "Agent upload failed"),
                    response.status_code,
                )
            return body
        except DomainError:
            raise
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
