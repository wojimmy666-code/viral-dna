from __future__ import annotations

from typing import Protocol

from ..asset_library import Asset


class ReplicaSyncScheduler(Protocol):
    async def schedule_asset_sync(self, asset: Asset) -> None: ...


class LocalOnlySyncScheduler:
    """Current no-op implementation; cloud workers can replace this contract later."""

    async def schedule_asset_sync(self, asset: Asset) -> None:
        return None
