"""Shared bounded metadata cache and provider-directed cooldown for update checks."""

import asyncio
import hashlib
import math
import time
from email.utils import parsedate_to_datetime

from mediahub.errors import DomainError


class GitHubMetadata:
    def __init__(self, clock=time.time, *, state_file=None):
        self.clock = clock
        self.lock = asyncio.Lock()
        self.cache = {}
        self.cooldowns = {}
        self.state_file = state_file
        if state_file and state_file.exists():
            from agent.install_files import read_json

            try:
                raw = read_json(state_file)
                for key, deadline in list(raw.get("cooldowns", {}).items())[:64]:
                    if (
                        len(key) == 64
                        and isinstance(deadline, (int, float))
                        and math.isfinite(deadline)
                        and deadline > self.clock()
                    ):
                        self.cooldowns[bytes.fromhex(key)] = deadline
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def persist_cooldowns(self):
        if self.state_file:
            from agent.install_files import save_json

            save_json(
                self.state_file,
                {
                    "cooldowns": {
                        key.hex(): deadline
                        for key, deadline in self.cooldowns.items()
                        if deadline > self.clock()
                    }
                },
            )

    async def get(self, client, path):
        identity = hashlib.sha256(client.headers.get("Authorization", "").encode()).digest()
        key = (identity, path)
        async with self.lock:
            now = self.clock()
            cached = self.cache.get(key)
            if cached and now < cached[0]:
                return cached[1]
            retry_at = self.cooldowns.get(identity, 0)
            if now < retry_at:
                error = DomainError(
                    "github_rate_limited",
                    "GitHub's request limit was reached. Wait before checking for updates again.",
                    429,
                )
                error.retry_at = retry_at
                raise error
            response = await client.get("https://api.github.com" + path)
            from mediahub.platform_source import check_github_access

            try:
                check_github_access(response)
            except DomainError as error:
                if error.code == "github_rate_limited":
                    deadlines = [now + 60]
                    retry = response.headers.get("retry-after", "")
                    try:
                        deadlines.append(now + max(0, float(retry)))
                    except ValueError:
                        try:
                            deadlines.append(parsedate_to_datetime(retry).timestamp())
                        except (ValueError, TypeError, OverflowError):
                            pass
                    try:
                        deadlines.append(float(response.headers.get("x-ratelimit-reset", "")))
                    except ValueError:
                        pass
                    if len(deadlines) == 1:
                        deadlines.append(now + 3600)
                    error.retry_at = self.cooldowns[identity] = max(deadlines)
                    self.persist_cooldowns()
                raise
            if response.status_code == 200:
                # Pinned project metadata is immutable; main is deliberately cached briefly.
                ttl = 3600 if "/contents/" in path else 300
                self.cache[key] = (now + ttl, response)
                while len(self.cache) > 128:
                    self.cache.pop(next(iter(self.cache)))
            return response
