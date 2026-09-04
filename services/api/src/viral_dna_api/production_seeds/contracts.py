from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python


def utc_now() -> datetime:
    return datetime.now(UTC)


def seconds_to_frame(seconds: float | Decimal, fps: int) -> int:
    """Project seconds onto the integer-frame timebase exactly once."""

    if fps <= 0:
        raise ValueError("帧率必须大于零")
    value = Decimal(str(seconds)) * Decimal(fps)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def frame_to_seconds(frame: int, fps: int) -> float:
    if frame < 0:
        raise ValueError("帧位置不能小于零")
    if fps <= 0:
        raise ValueError("帧率必须大于零")
    return float(Decimal(frame) / Decimal(fps))


def canonical_digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude={"content_hash"})
    else:
        value = to_jsonable_python(value)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ProductionSeedOrigin(StrEnum):
    ANALYSIS = "analysis"
    SKILL_RUN = "skill_run"


class ProductionSeedReference(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    asset_id: UUID | None = None
    role: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    media_kind: Literal["image", "video", "audio", "document"] = "image"
    content_url: str | None = Field(default=None, max_length=8192)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fidelity: Literal[
        "exact",
        "identity_lock",
        "structural",
        "style_only",
        "loose_reference",
    ] = "loose_reference"
    rights_status: Literal["confirmed", "restricted", "unknown", "expired"] = "unknown"


class ExactOverlayInstruction(BaseModel):
    asset_usage_id: UUID
    placement: str = Field(min_length=1, max_length=500)
    scale_mode: Literal["contain", "cover", "native", "fit_width", "fit_height"] = "contain"
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    tracking_mode: Literal["static", "planar", "point", "manual_keyframes"] = "static"
    occlusion_policy: str = Field(default="preserve", min_length=1, max_length=120)
    blend_mode: str = Field(default="normal", min_length=1, max_length=80)
    safe_area: str = Field(default="title_safe", min_length=1, max_length=120)
    required_review: bool = True

    @model_validator(mode="after")
    def validate_range(self) -> ExactOverlayInstruction:
        if self.end_frame <= self.start_frame:
            raise ValueError("确定性叠加的结束帧必须晚于开始帧")
        return self


class ProductionSeedShot(BaseModel):
    stable_shot_key: str = Field(pattern=r"^shot_[a-z0-9]{8,64}$")
    order: int = Field(ge=1)
    narrative_role: str = Field(default="body", min_length=1, max_length=80)
    start_frame: int = Field(ge=0)
    duration_frames: int = Field(gt=0)
    source_start_frame: int | None = Field(default=None, ge=0)
    source_duration_frames: int | None = Field(default=None, gt=0)
    handle_in_frames: int = Field(default=0, ge=0, le=600)
    handle_out_frames: int = Field(default=0, ge=0, le=600)
    description: str = Field(default="", max_length=4000)
    image_prompt: str = Field(default="", max_length=8000)
    image_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    video_prompt: str = Field(default="", max_length=8000)
    video_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    image_asset_usage_ids: list[UUID] = Field(default_factory=list, max_length=50)
    video_reference_usage_ids: list[UUID] = Field(default_factory=list, max_length=50)
    exact_overlays: list[ExactOverlayInstruction] = Field(default_factory=list, max_length=20)
    continuity_group_ids: list[str] = Field(default_factory=list, max_length=30)
    dialogue_or_voiceover: str = Field(default="", max_length=4000)
    caption_intent: str = Field(default="", max_length=2000)
    output_mode: Literal["source_video", "image_to_video"] = "image_to_video"
    required_model_capabilities: list[str] = Field(default_factory=list, max_length=30)
    source_keyframe_url: str | None = Field(default=None, max_length=2048)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator(
        "image_negative_constraints",
        "video_negative_constraints",
        "continuity_group_ids",
        "required_model_capabilities",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("ProductionSeed 镜头列表字段不能包含重复项")
        return values


class ProductionSeedAudioIntent(BaseModel):
    clip_audio_strategy: Literal["candidate", "source", "muted"] = "muted"
    music_strategy: Literal["none", "select", "generate"] = "none"
    narration_strategy: Literal["none", "recorded", "generated"] = "none"
    sfx_enabled: bool = False
    creative_direction: dict[str, Any] = Field(default_factory=dict)


class ProductionSeedSubtitleIntent(BaseModel):
    enabled: bool = False
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    source: Literal["final_speech", "manual", "none"] = "none"
    style: dict[str, Any] = Field(default_factory=dict)


class ProductionSeed(BaseModel):
    """Immutable bridge from an upstream workflow into Production."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["viral-dna-production-seed/v1"] = (
        "viral-dna-production-seed/v1"
    )
    id: UUID = Field(default_factory=uuid4)
    owner_project_id: UUID
    origin_type: ProductionSeedOrigin
    origin_id: UUID
    name: str = Field(min_length=1, max_length=120)
    output_aspect_ratio: str = Field(pattern=r"^\d{1,5}:\d{1,5}$")
    output_width: int = Field(ge=256, le=8192)
    output_height: int = Field(ge=256, le=8192)
    fps: int = Field(default=30, ge=1, le=120)
    source_video_id: UUID | None = None
    source_analysis_id: UUID | None = None
    source_prompt_package_id: UUID | None = None
    style_bible_revision_id: UUID | None = None
    style_bible_snapshot: dict[str, Any] = Field(default_factory=dict)
    reference_assets: list[ProductionSeedReference] = Field(default_factory=list)
    shots: list[ProductionSeedShot] = Field(min_length=1, max_length=500)
    audio_intent: ProductionSeedAudioIntent = Field(default_factory=ProductionSeedAudioIntent)
    subtitle_intent: ProductionSeedSubtitleIntent = Field(
        default_factory=ProductionSeedSubtitleIntent
    )
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_origin_and_timing(self) -> ProductionSeed:
        analysis_fields = (
            self.source_video_id,
            self.source_analysis_id,
            self.source_prompt_package_id,
        )
        if self.origin_type == ProductionSeedOrigin.ANALYSIS and any(
            item is None for item in analysis_fields
        ):
            raise ValueError("analysis ProductionSeed 必须绑定视频、分析和提示词包")
        if self.origin_type == ProductionSeedOrigin.SKILL_RUN:
            if any(item is not None for item in analysis_fields):
                raise ValueError("skill_run ProductionSeed 不得伪造分析来源字段")
            if self.style_bible_revision_id is None:
                raise ValueError("skill_run ProductionSeed 必须绑定 Style Bible")
        orders = [item.order for item in self.shots]
        keys = [item.stable_shot_key for item in self.shots]
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValueError("ProductionSeed 镜头顺序必须从 1 连续编号")
        if len(keys) != len(set(keys)):
            raise ValueError("ProductionSeed stable_shot_key 不能重复")
        if canonical_digest(self) != self.content_hash:
            raise ValueError("ProductionSeed 内容摘要不匹配")
        return self
