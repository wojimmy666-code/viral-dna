from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from ..workspace import WorkspaceManager
from ..workspace_catalog import AccountContextService
from .domain import VideoEnhancementTarget


class VideoEnhancementSettingsState(BaseModel):
    default_target: VideoEnhancementTarget = VideoEnhancementTarget.FHD
    execution_device: Literal["auto-vulkan"] = "auto-vulkan"
    concurrency: Literal[1] = 1
    model: Literal["realesrgan-x4plus"] = "realesrgan-x4plus"
    updated_at: datetime | None = None


class VideoEnhancementSettingsService:
    def __init__(
        self,
        workspace: WorkspaceManager,
        account_context: AccountContextService,
    ) -> None:
        self.workspace = workspace
        self.account_context = account_context
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self.workspace.paths.metadata_dir / "settings" / "video-enhancement.json"

    async def current_account_id(self) -> UUID:
        return (await self.account_context.current_account()).id

    async def get_current(self) -> tuple[UUID, VideoEnhancementSettingsState]:
        account_id = await self.current_account_id()
        return account_id, await self.get(account_id)

    async def get(self, account_id: UUID) -> VideoEnhancementSettingsState:
        async with self._lock:
            payload = await asyncio.to_thread(self._read)
        account_payload = payload.get("accounts", {}).get(str(account_id), {})
        return VideoEnhancementSettingsState.model_validate(account_payload)

    async def update_current(
        self,
        default_target: VideoEnhancementTarget,
    ) -> tuple[UUID, VideoEnhancementSettingsState]:
        account_id = await self.current_account_id()
        state = VideoEnhancementSettingsState(
            default_target=default_target,
            updated_at=datetime.now(UTC),
        )
        async with self._lock:
            payload = await asyncio.to_thread(self._read)
            accounts = payload.setdefault("accounts", {})
            accounts[str(account_id)] = state.model_dump(mode="json")
            await asyncio.to_thread(self._write, payload)
        return account_id, state

    def _read(self) -> dict[str, object]:
        if not self.path.is_file():
            return {"schema_version": 1, "accounts": {}}
        try:
            payload = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "accounts": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), dict):
            return {"schema_version": 1, "accounts": {}}
        return payload

    def _write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
