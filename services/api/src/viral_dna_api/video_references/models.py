from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from .domain import (
    PersonReferencePolicy,
    ReferenceProxyAsset,
    ReferenceProxyKind,
)


class ReferenceProxyCapabilityResponse(BaseModel):
    engine: str
    version: str
    kinds: list[ReferenceProxyKind] = Field(default_factory=list)
    available: bool
    availability_note: str = ""
    production_ready: bool = False
    wholebody: bool = False
    hand_keypoints: bool = False
    video_tracking: bool = False
    runtime_provider: str = ""


class ProxyEngineInstallationResponse(BaseModel):
    id: UUID
    engine: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress_percent: int = Field(default=0, ge=0, le=100)
    downloaded_bytes: int = Field(default=0, ge=0)
    total_bytes: int = Field(default=0, ge=0)
    message: str = ""
    error_code: str | None = None
    capability: ReferenceProxyCapabilityResponse | None = None


class ReferenceProxyCreate(BaseModel):
    expected_revision_id: UUID
    source_kind: Literal[
        "image_candidate",
        "video_candidate",
        "source_shot_video",
    ] = "image_candidate"
    source_candidate_id: UUID | None = None
    visual_beat_id: UUID
    kind: ReferenceProxyKind
    order: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def validate_source_kind(self) -> ReferenceProxyCreate:
        video_kind = self.kind in {
            ReferenceProxyKind.MOTION_PROXY_VIDEO,
            ReferenceProxyKind.SKELETON_VIDEO,
            ReferenceProxyKind.SILHOUETTE_VIDEO,
        }
        if self.source_kind == "image_candidate" and video_kind:
            raise ValueError("图片候选不能生成视频动作代理")
        if self.source_kind in {"video_candidate", "source_shot_video"} and not video_kind:
            raise ValueError("视频来源只能生成视频动作代理")
        if self.source_kind != "source_shot_video" and self.source_candidate_id is None:
            raise ValueError("候选来源必须提供 source_candidate_id")
        if self.source_kind == "source_shot_video" and self.source_candidate_id is not None:
            raise ValueError("原视频分镜来源不需要 source_candidate_id")
        if video_kind and self.order < 1:
            raise ValueError("视频动作代理顺序无效")
        return self


class ReferenceProxyCreateResponse(BaseModel):
    current_revision_id: UUID
    proxy: ReferenceProxyAsset


class VideoReferenceStrategyResponse(BaseModel):
    model_alias: str
    model_label: str
    policy: PersonReferencePolicy
    strategy: Literal[
        "managed_identity",
        "managed_identity_with_proxy",
        "raw_references",
        "person_free",
        "unknown",
    ]
    title: str
    description: str
    managed_identity_required: bool
    managed_identity_bound: bool
    raw_person_references_submitted: bool
    proxy_image_supported: bool
    proxy_video_supported: bool
    selected_proxy_count: int = Field(default=0, ge=0)
    excluded_local_reference_count: int = Field(default=0, ge=0)
    generation_allowed: bool
    blocker_message: str | None = None
