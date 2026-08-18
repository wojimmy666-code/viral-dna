from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel

from ..workspace import WorkspaceManager
from ..workspace_catalog import AccountContextService
from .jobs.domain import DepthExecutionPreference


class DepthGenerationSettingsState(BaseModel):
    execution_preference: DepthExecutionPreference = DepthExecutionPreference.AUTO
    updated_at: datetime | None = None


class DepthGenerationSettingsService:
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
        return self.workspace.paths.metadata_dir / "settings" / "depth-generation.json"

    async def current_account_id(self) -> UUID:
        return (await self.account_context.current_account()).id

    async def get_current(self) -> tuple[UUID, DepthGenerationSettingsState]:
        account_id = await self.current_account_id()
        return account_id, await self.get(account_id)

    async def get(self, account_id: UUID) -> DepthGenerationSettingsState:
        async with self._lock:
            payload = await asyncio.to_thread(self._read)
        account_payload = payload.get("accounts", {}).get(str(account_id), {})
        return DepthGenerationSettingsState.model_validate(account_payload)

    async def update_current(
        self,
        preference: DepthExecutionPreference,
    ) -> tuple[UUID, DepthGenerationSettingsState]:
        account_id = await self.current_account_id()
        state = DepthGenerationSettingsState(
            execution_preference=preference,
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
