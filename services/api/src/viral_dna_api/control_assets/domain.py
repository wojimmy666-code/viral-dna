from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DepthControlKind(StrEnum):
    """The only control representation supported by the current workflow."""

    FULL_SCENE_DEPTH_VIDEO = "full_scene_depth_video"


class DepthControlStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DepthControlValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class DepthConvention(StrEnum):
    """How grayscale values map to distance in the generated control video."""

    NEAR_WHITE_FAR_BLACK = "near_white_far_black"


class DepthControlAsset(BaseModel):
    """A full-scene depth video derived from one source-shot interval.

    The asset intentionally carries geometry only. Identity, appearance, scene
    texture and colour always come from separately selected creative assets.
    """

    id: UUID = Field(default_factory=uuid4)
    kind: DepthControlKind = DepthControlKind.FULL_SCENE_DEPTH_VIDEO
    status: DepthControlStatus = DepthControlStatus.PENDING
    enabled: bool = True
    source_video_id: UUID
    source_relative_path: str = Field(min_length=1, max_length=2048)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    relative_path: str | None = Field(default=None, max_length=2048)
    thumbnail_relative_path: str | None = Field(default=None, max_length=2048)
    manifest_relative_path: str | None = Field(default=None, max_length=2048)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    engine: str = Field(default="video_depth_anything", min_length=1, max_length=80)
    engine_version: str = Field(default="1.0", min_length=1, max_length=80)
    model_variant: str = Field(default="vits", min_length=1, max_length=40)
    depth_convention: DepthConvention = DepthConvention.NEAR_WHITE_FAR_BLACK
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    fps: float | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    frame_count: int | None = Field(default=None, ge=1)
    validation_status: DepthControlValidationStatus = (
        DepthControlValidationStatus.PENDING
    )
    validation_message: str | None = Field(default=None, max_length=1000)
    validation_metrics: dict[str, float | int | str | bool] = Field(
        default_factory=dict
    )
    error_code: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_asset(self) -> DepthControlAsset:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("深度控制素材结束时间必须晚于开始时间")
        if self.status == DepthControlStatus.READY:
            required = (
                self.relative_path,
                self.thumbnail_relative_path,
                self.manifest_relative_path,
                self.sha256,
                self.width,
                self.height,
                self.fps,
                self.duration_seconds,
                self.frame_count,
            )
            if any(value is None for value in required):
                raise ValueError("已就绪的深度控制素材缺少文件或媒体元数据")
            if self.validation_status != DepthControlValidationStatus.PASSED:
                raise ValueError("深度控制素材必须通过质检后才能标记为就绪")
        return self

    @property
    def usable_for_generation(self) -> bool:
        return bool(
            self.enabled
            and self.status == DepthControlStatus.READY
            and self.validation_status == DepthControlValidationStatus.PASSED
            and self.relative_path
            and self.thumbnail_relative_path
            and self.manifest_relative_path
            and self.sha256
        )
