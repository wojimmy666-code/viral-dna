from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .domain import DepthControlAsset, DepthControlKind
from .jobs.domain import (
    DepthControlJob,
    DepthControlPreset,
    DepthExecutionPreference,
)


class DepthEngineCapabilityResponse(BaseModel):
    engine: str
    version: str
    model_variant: str
    kind: DepthControlKind = DepthControlKind.FULL_SCENE_DEPTH_VIDEO
    available: bool
    availability_note: str = ""
    repository_url: str
    checkpoint_path: str | None = None
    runtime_path: str | None = None
    license: str


class DepthEngineInstallationResponse(BaseModel):
    id: UUID
    engine: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress_percent: int = Field(ge=0, le=100)
    message: str = Field(default="", max_length=500)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime
    updated_at: datetime
    capability: DepthEngineCapabilityResponse | None = None


class DepthGenerationSettingsUpdate(BaseModel):
    execution_preference: DepthExecutionPreference


class DepthExecutionModeStatus(BaseModel):
    mode: DepthExecutionPreference
    available: bool
    note: str = ""
    engine: str | None = None
    device_name: str | None = None
    installable: bool = False


class DepthGenerationSettingsResponse(BaseModel):
    execution_preference: DepthExecutionPreference
    resolved_mode: DepthExecutionPreference | None = None
    resolved_engine: str | None = None
    resolved_device_name: str | None = None
    selection_reason: str = ""
    modes: list[DepthExecutionModeStatus] = Field(default_factory=list)
    updated_at: datetime | None = None


class DepthControlCreate(BaseModel):
    expected_revision_id: UUID


class DepthControlJobCreate(BaseModel):
    expected_revision_id: UUID
    preset: DepthControlPreset = DepthControlPreset.AUTO


class DepthControlJobResponse(BaseModel):
    job: DepthControlJob


class DepthControlJobListResponse(BaseModel):
    items: list[DepthControlJob] = Field(default_factory=list)


class DepthControlJobCancelResponse(BaseModel):
    job: DepthControlJob


class DepthControlJobRetryResponse(BaseModel):
    job: DepthControlJob


class DepthControlCreateResponse(BaseModel):
    current_revision_id: UUID
    asset: DepthControlAsset


class DepthControlUpdate(BaseModel):
    expected_revision_id: UUID
    enabled: bool


class DepthControlUpdateResponse(BaseModel):
    current_revision_id: UUID
    asset: DepthControlAsset


class DepthControlDeleteResponse(BaseModel):
    current_revision_id: UUID
    asset_id: UUID
    local_content_removed: bool = True
    cleanup_warning: str | None = Field(default=None, max_length=500)
