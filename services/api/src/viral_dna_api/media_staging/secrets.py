from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from ..platform_connections.models import PlatformKind
from ..platform_connections.secret_store import (
    PlatformSecretStoreError,
    WindowsDpapiSecretStore,
)


class MediaStagingSecretStore:
    """Account-scoped DPAPI storage using a dedicated pseudo-device namespace.

    Reuses the repository's audited atomic DPAPI implementation. The fixed UUID
    and platform filename keep media credentials physically separate from
    browser-cookie secrets.
    """

    _NAMESPACE_ID = UUID("938c87ff-cf85-4d58-8b5b-1f02ec9b6e62")

    def __init__(self, root: Path) -> None:
        self._delegate = WindowsDpapiSecretStore(root / "media-staging")
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._delegate.available

    async def save(self, account_id: UUID, access_key_id: str, secret: str) -> None:
        payload = json.dumps(
            {"access_key_id": access_key_id, "access_key_secret": secret},
            ensure_ascii=False,
        ).encode("utf-8")
        async with self._lock:
            await self._delegate.save(
                account_id,
                self._NAMESPACE_ID,
                PlatformKind.DOUYIN,
                payload,
            )

    async def read(self, account_id: UUID) -> tuple[str, str] | None:
        async with self._lock:
            try:
                payload = await self._delegate.read(
                    account_id,
                    self._NAMESPACE_ID,
                    PlatformKind.DOUYIN,
                )
            except PlatformSecretStoreError as exc:
                if exc.code == "platform_cookie_secret_missing":
                    return None
                raise
        data = json.loads(payload.decode("utf-8"))
        return str(data["access_key_id"]), str(data["access_key_secret"])

    async def delete(self, account_id: UUID) -> None:
        async with self._lock:
            await self._delegate.delete(
                account_id,
                self._NAMESPACE_ID,
                PlatformKind.DOUYIN,
            )
