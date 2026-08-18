from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class DepthControlJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class DepthControlJobStage(StrEnum):
    QUEUED = "queued"
    VALIDATING_INPUT = "validating_input"
    PROBING_MEDIA = "probing_media"
    CLIPPING_SOURCE = "clipping_source"
    LOADING_MODEL = "loading_model"
    INFERRING_DEPTH = "inferring_depth"
    WRITING_DEPTH = "writing_depth"
    ENCODING_VIDEO = "encoding_video"
    VALIDATING_OUTPUT = "validating_output"
    PERSISTING_ASSET = "persisting_asset"
    COMPLETED = "completed"


class DepthControlPreset(StrEnum):
    AUTO = "auto"
    CPU_FAST = "cpu_fast"
    BALANCED = "balanced"
    QUALITY = "quality"


class DepthExecutionPreference(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    GPU = "gpu"


class DepthExecutionDevice(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"


ACTIVE_DEPTH_JOB_STATUSES = frozenset(
    {
        DepthControlJobStatus.QUEUED,
        DepthControlJobStatus.RUNNING,
        DepthControlJobStatus.CANCELLATION_REQUESTED,
    }
)


class DepthControlJob(BaseModel):
    """Durable execution state for one full-scene depth generation."""

    id: UUID = Field(default_factory=uuid4)
    account_id: UUID | None = None
    project_id: UUID
    shot_plan_id: UUID
    record_id: UUID
    submitted_revision_id: UUID
    source_video_id: UUID
    source_relative_path: str = Field(min_length=1, max_length=2048)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    source_fingerprint: str = Field(min_length=64, max_length=64)
    engine: str = Field(default="video_depth_anything", min_length=1, max_length=80)
    engine_version: str = Field(default="official-cli-v1", min_length=1, max_length=80)
    model_variant: str = Field(default="vits", min_length=1, max_length=40)
    requested_execution_preference: DepthExecutionPreference = (
        DepthExecutionPreference.AUTO
    )
    selection_reason: str = Field(default="", max_length=500)
    runtime_version: str | None = Field(default=None, max_length=120)
    requested_preset: DepthControlPreset = DepthControlPreset.AUTO
    effective_preset: DepthControlPreset = DepthControlPreset.CPU_FAST
    execution_device: DepthExecutionDevice = DepthExecutionDevice.CPU
    device_name: str = Field(default="CPU", max_length=160)
    target_fps: int = Field(default=12, ge=1, le=60)
    input_size: int = Field(default=392, ge=196, le=1036)
    max_resolution: int = Field(default=960, ge=320, le=4096)
    timeout_seconds: int = Field(default=1800, ge=60, le=21600)
    status: DepthControlJobStatus = DepthControlJobStatus.QUEUED
    stage: DepthControlJobStage = DepthControlJobStage.QUEUED
    progress_percent: int = Field(default=0, ge=0, le=100)
    progress_message: str = Field(default="任务已加入队列", max_length=500)
    processed_frames: int | None = Field(default=None, ge=0)
    total_frames: int | None = Field(default=None, ge=1)
    estimated_seconds_remaining: int | None = Field(default=None, ge=0)
    retry_of_job_id: UUID | None = None
    result_asset_id: UUID | None = None
    result_revision_id: UUID | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1000)
    technical_detail: str | None = Field(default=None, max_length=6000)
    process_id: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_job(self) -> DepthControlJob:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("深度任务结束时间必须晚于开始时间")
        if self.processed_frames is not None and self.total_frames is not None:
            if self.processed_frames > self.total_frames:
                raise ValueError("已处理帧数不能大于总帧数")
        if self.status == DepthControlJobStatus.SUCCEEDED:
            if self.result_asset_id is None or self.result_revision_id is None:
                raise ValueError("成功任务必须记录结果资产和版本")
            if self.progress_percent != 100:
                raise ValueError("成功任务进度必须为 100%")
        return self

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_DEPTH_JOB_STATUSES
