from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class IntegrationSnapshot:
    status: str
    version: str | None = None
    api_version: str | None = None
    capabilities: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    apps: list[dict] = field(default_factory=list)
    storage: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cursor: str | None = None
    retry_after: int | None = None
    failed_endpoint: str | None = None
    stale: bool = False


class IntegrationProvider(Protocol):
    async def sync(self, *, cursor: str | None = None) -> IntegrationSnapshot: ...

    async def test(self) -> IntegrationSnapshot: ...
