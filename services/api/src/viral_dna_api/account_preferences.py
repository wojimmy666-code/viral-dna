from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .workspace_catalog import AccountContextService, default_account_catalog_path


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_model: Literal["seedance", "generic"] = "seedance"
    analysis_profile: Literal["quality", "balanced", "economy"] = "balanced"
    max_cost_cny: float | None = Field(default=1.0, gt=0, le=1000)
    image_model_alias: str | None = Field(default=None, max_length=160)
    image_candidate_count: int = Field(default=1, ge=1, le=4)
    video_model_alias: str | None = Field(default=None, max_length=160)
    video_resolution: str | None = Field(default=None, max_length=32)

    @field_validator("image_model_alias", "video_model_alias", "video_resolution")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = " ".join((value or "").split()).strip()
        return normalized or None


class UserPreferencesResponse(BaseModel):
    account_id: UUID
    revision: int = Field(ge=1)
    settings: UserPreferences


class UserPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int | None = Field(default=None, ge=1)
    settings: UserPreferences


class UserPreferencesState(BaseModel):
    schema_version: int = 1
    revisions: dict[str, int] = Field(default_factory=dict)
    accounts: dict[str, UserPreferences] = Field(default_factory=dict)


class UserPreferencesConflict(RuntimeError):
    pass


class UserPreferencesRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._lock = asyncio.Lock()

    async def get(self, account_id: UUID) -> UserPreferencesResponse:
        async with self._lock:
            state = await asyncio.to_thread(self._read)
            key = str(account_id)
            return UserPreferencesResponse(
                account_id=account_id,
                revision=state.revisions.get(key, 1),
                settings=state.accounts.get(key, UserPreferences()),
            )

    async def update(
        self,
        account_id: UUID,
        payload: UserPreferencesUpdate,
    ) -> UserPreferencesResponse:
        async with self._lock:
            state = await asyncio.to_thread(self._read)
            key = str(account_id)
            current_revision = state.revisions.get(key, 1)
            if payload.revision is not None and payload.revision != current_revision:
                raise UserPreferencesConflict("设置已在其他页面更新，请刷新后重试")
            next_revision = current_revision + 1
            state.accounts[key] = payload.settings
            state.revisions[key] = next_revision
            await asyncio.to_thread(self._write, state)
            return UserPreferencesResponse(
                account_id=account_id,
                revision=next_revision,
                settings=payload.settings,
            )

    def _read(self) -> UserPreferencesState:
        if not self.path.is_file():
            return UserPreferencesState()
        try:
            return UserPreferencesState.model_validate_json(
                self.path.read_text("utf-8-sig")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return UserPreferencesState()

    def _write(self, state: UserPreferencesState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(raw_path)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(state.model_dump_json(indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


def default_user_preferences_path() -> Path:
    return default_account_catalog_path().with_name("user-settings.json")


class UserPreferencesService:
    def __init__(
        self,
        account_context: AccountContextService,
        repository: UserPreferencesRepository | None = None,
    ) -> None:
        self.account_context = account_context
        self.repository = repository or UserPreferencesRepository(
            default_user_preferences_path()
        )

    async def get(self) -> UserPreferencesResponse:
        account = await self.account_context.current_account()
        return await self.repository.get(account.id)

    async def update(self, payload: UserPreferencesUpdate) -> UserPreferencesResponse:
        account = await self.account_context.current_account()
        return await self.repository.update(account.id, payload)


def create_user_preferences_router(service: UserPreferencesService) -> APIRouter:
    router = APIRouter(prefix="/me/settings", tags=["user-settings"])

    @router.get("/preferences", response_model=UserPreferencesResponse)
    async def get_preferences() -> UserPreferencesResponse:
        return await service.get()

    @router.put("/preferences", response_model=UserPreferencesResponse)
    async def update_preferences(
        payload: UserPreferencesUpdate,
    ) -> UserPreferencesResponse:
        try:
            return await service.update(payload)
        except UserPreferencesConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
