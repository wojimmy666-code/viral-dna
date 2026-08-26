from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .domain import VideoEnhancementJob, VideoEnhancementTarget


class VideoEnhancementCapabilityResponse(BaseModel):
    engine: str
    version: str
    model: str
    available: bool
    availability_note: str
    repository_url: str
    installation_path: str
    executable_path: str | None = None
    execution_device: str
    license: str
    installable: bool


class VideoEnhancementSettingsUpdate(BaseModel):
    default_target: VideoEnhancementTarget


class VideoEnhancementSettingsResponse(BaseModel):
    default_target: VideoEnhancementTarget
    execution_device: Literal["auto-vulkan"] = "auto-vulkan"
    concurrency: Literal[1] = 1
    model: Literal["realesrgan-x4plus"] = "realesrgan-x4plus"
    updated_at: datetime | None = None
    capability: VideoEnhancementCapabilityResponse


class VideoEnhancementInstallationResponse(BaseModel):
    id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    progress_percent: int = Field(ge=0, le=100)
    message: str = Field(max_length=500)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime
    updated_at: datetime
    capability: VideoEnhancementCapabilityResponse | None = None


class VideoEnhancementJobCreate(BaseModel):
    expected_revision_id: UUID
    target: VideoEnhancementTarget | None = None


class VideoEnhancementActivateRequest(BaseModel):
    expected_revision_id: UUID


class VideoEnhancementJobResponse(BaseModel):
    job: VideoEnhancementJob
    content_url: str | None = None
    original_content_url: str


class VideoEnhancementSourceResponse(BaseModel):
    width: int = Field(gt=0, le=32768)
    height: int = Field(gt=0, le=32768)
    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    frame_count: int = Field(gt=0)


class VideoEnhancementJobListResponse(BaseModel):
    items: list[VideoEnhancementJobResponse] = Field(default_factory=list)
    source: VideoEnhancementSourceResponse | None = None


class VideoEnhancementVersionSelectionResponse(BaseModel):
    candidate_id: UUID
    active_job_id: UUID | None = None
    active_target: VideoEnhancementTarget | None = None
    content_url: str
