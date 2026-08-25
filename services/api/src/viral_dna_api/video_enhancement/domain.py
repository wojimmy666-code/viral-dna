from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class VideoEnhancementTarget(StrEnum):
    FHD = "1080p"
    UHD = "4k"


class VideoEnhancementJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


ACTIVE_VIDEO_ENHANCEMENT_STATUSES = frozenset(
    {
        VideoEnhancementJobStatus.QUEUED,
        VideoEnhancementJobStatus.RUNNING,
        VideoEnhancementJobStatus.CANCELLATION_REQUESTED,
    }
)


class VideoEnhancementJobStage(StrEnum):
    QUEUED = "queued"
    PROBING = "probing"
    EXTRACTING = "extracting"
    UPSCALING = "upscaling"
    ENCODING = "encoding"
    VALIDATING = "validating"
    COMPLETED = "completed"


class VideoEnhancementJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID | None = None
    project_id: UUID
    shot_plan_id: UUID
    generation_run_id: UUID
    candidate_id: UUID
    record_id: UUID
    submitted_revision_id: UUID
    source_relative_path: str = Field(min_length=1, max_length=2048)
    source_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    source_width: int = Field(gt=0, le=32768)
    source_height: int = Field(gt=0, le=32768)
    duration_seconds: float = Field(gt=0)
    target: VideoEnhancementTarget = VideoEnhancementTarget.FHD
    target_width: int = Field(gt=0, le=8192)
    target_height: int = Field(gt=0, le=8192)
    engine: str = "realesrgan-ncnn-vulkan"
    engine_version: str = "0.2.0"
    model: str = "realesrgan-x4plus"
    execution_device: Literal["auto-vulkan"] = "auto-vulkan"
    upscale_factor: int = Field(default=2, ge=2, le=4)
    status: VideoEnhancementJobStatus = VideoEnhancementJobStatus.QUEUED
    stage: VideoEnhancementJobStage = VideoEnhancementJobStage.QUEUED
    progress_percent: int = Field(default=0, ge=0, le=100)
    progress_message: str = Field(default="任务已加入队列", max_length=500)
    processed_frames: int | None = Field(default=None, ge=0)
    total_frames: int | None = Field(default=None, ge=1)
    estimated_seconds_remaining: int | None = Field(default=None, ge=0)
    process_id: int | None = Field(default=None, gt=0)
    result_relative_path: str | None = Field(default=None, max_length=2048)
    result_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    result_width: int | None = Field(default=None, gt=0, le=8192)
    result_height: int | None = Field(default=None, gt=0, le=8192)
    result_size_bytes: int | None = Field(default=None, ge=0)
    active_for_final: bool = False
    retry_of_job_id: UUID | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1000)
    technical_detail: str | None = Field(default=None, max_length=6000)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
