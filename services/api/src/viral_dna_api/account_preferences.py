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

from .ai.catalog import load_model_catalog
from .ai.text_model_routing import DEFAULT_TEXT_MODEL_ALIAS
from .models import ModelOption, TextGenerationPurpose
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
    text_model_alias: str = Field(
        default=DEFAULT_TEXT_MODEL_ALIAS,
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    text_model_fallback_enabled: bool = True
    text_model_task_overrides: dict[TextGenerationPurpose, str] = Field(
        default_factory=dict
    )

    @field_validator("image_model_alias", "video_model_alias", "video_resolution")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = " ".join((value or "").split()).strip()
        return normalized or None

    @field_validator("text_model_alias")
    @classmethod
    def normalize_text_model_alias(cls, value: str) -> str:
        return value.strip()

    @field_validator("text_model_task_overrides")
    @classmethod
    def normalize_text_model_task_overrides(
        cls,
        value: dict[TextGenerationPurpose, str],
    ) -> dict[TextGenerationPurpose, str]:
        normalized: dict[TextGenerationPurpose, str] = {}
        for purpose, alias in value.items():
            clean_alias = alias.strip()
            if not clean_alias:
                continue
            if len(clean_alias) > 80:
                raise ValueError("文案模型别名不能超过 80 个字符")
            normalized[purpose] = clean_alias
        return normalized


class TextModelTaskOption(BaseModel):
    id: TextGenerationPurpose
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)


TEXT_MODEL_TASK_OPTIONS = (
    TextModelTaskOption(
        id=TextGenerationPurpose.REPLICATION_PLAN,
        label="分析结论与复刻方案",
        description="控制分析推理结论及其生成的三套复刻方案。",
    ),
    TextModelTaskOption(
        id=TextGenerationPurpose.SHOT_IMAGE_PROMPT,
        label="分镜说明与图片提示词",
        description="分镜事实、画面说明和图片提示词由同一次视觉理解生成。",
    ),
    TextModelTaskOption(
        id=TextGenerationPurpose.VIDEO_PROMPT,
        label="创作意图与视频提示词",
        description="理解创作意图，并编译带资产引用的最终视频提示词。",
    ),
)


class UserPreferencesResponse(BaseModel):
    account_id: UUID
    revision: int = Field(ge=1)
    settings: UserPreferences
    text_models: list[ModelOption] = Field(default_factory=list)
    text_model_tasks: list[TextModelTaskOption] = Field(default_factory=list)


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


class UserPreferencesValidationError(RuntimeError):
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
        return self._decorate(await self.repository.get(account.id))

    async def update(self, payload: UserPreferencesUpdate) -> UserPreferencesResponse:
        self._validate_text_models(payload.settings)
        account = await self.account_context.current_account()
        return self._decorate(await self.repository.update(account.id, payload))

    @staticmethod
    def _validate_text_models(settings: UserPreferences) -> None:
        catalog = load_model_catalog()
        known_aliases = {option.alias for option in catalog.model_options()}
        requested_aliases = {
            settings.text_model_alias,
            *settings.text_model_task_overrides.values(),
        }
        unknown_aliases = sorted(requested_aliases - known_aliases)
        if unknown_aliases:
            raise UserPreferencesValidationError(
                f"文案模型不存在：{'、'.join(unknown_aliases)}"
            )

    @staticmethod
    def _decorate(response: UserPreferencesResponse) -> UserPreferencesResponse:
        return response.model_copy(
            update={
                "text_models": load_model_catalog().model_options(),
                "text_model_tasks": list(TEXT_MODEL_TASK_OPTIONS),
            }
        )


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
        except UserPreferencesValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
