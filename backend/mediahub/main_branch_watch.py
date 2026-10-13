"""Small conditional GitHub checks; no downloads, builds or app probes."""

import hashlib
import time

import httpx

from mediahub.errors import DomainError
from mediahub.platform_source import REPOSITORY, SHA, headers

MAIN_CHECK_INTERVAL_SECONDS = 15 * 60


class MainBranchWatch:
    def __init__(self, transport=None, clock=time.time, *, source_access=None, metadata_cache=None):
        self.transport, self.clock = transport, clock
        self.source_access = source_access
        self.metadata_cache = metadata_cache
        self.identity = None
        self.etag = None
        self.commit = None
        self.next_check = 0

    async def check(self, repository, token):
        if not REPOSITORY.fullmatch(repository or ""):
            return None
        identity = (repository, hashlib.sha256((token or "").encode()).digest())
        if identity != self.identity:
            self.identity, self.etag, self.commit, self.next_check = identity, None, None, 0
        now = self.clock()
        if now < self.next_check:
            return None
        self.next_check = now + MAIN_CHECK_INTERVAL_SECONDS
        if self.source_access:
            try:
                self.commit = await self.source_access.head(repository)
                return self.commit
            except DomainError:
                return None
        request_headers = headers(token)
        if self.etag:
            request_headers["If-None-Match"] = self.etag
        try:
            async with httpx.AsyncClient(
                headers=request_headers,
                timeout=10,
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                path = f"/repos/{repository}/commits/main"
                response = (
                    await self.metadata_cache.get(client, path)
                    if self.metadata_cache
                    else await client.get("https://api.github.com" + path)
                )
            if response.status_code in (403, 429):
                delays = [900.0]
                for name, offset in (("retry-after", 0), ("x-ratelimit-reset", now)):
                    try:
                        delays.append(float(response.headers.get(name, "0")) - offset)
                    except ValueError:
                        pass
                self.next_check = now + max(delays)
                return None
            if response.status_code == 304:
                return self.commit
            response.raise_for_status()
            commit = response.json().get("sha")
            if not isinstance(commit, str) or not SHA.fullmatch(commit):
                raise ValueError("Invalid commit metadata")
            self.commit, self.etag = commit, response.headers.get("etag")
            return commit
        except DomainError as error:
            self.next_check = max(now + 900, getattr(error, "retry_at", 0))
            return None
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            self.next_check = now + 900
            return None
