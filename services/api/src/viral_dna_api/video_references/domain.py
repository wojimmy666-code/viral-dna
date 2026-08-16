from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PersonReferencePolicy(StrEnum):
    """How a concrete model accepts human identity reference material."""

    MANAGED_REQUIRED = "managed_required"
    RAW_SUPPORTED = "raw_supported"
    MANAGED_OPTIONAL = "managed_optional"
    NO_PERSON = "no_person"
    UNKNOWN = "unknown"


class VideoReferenceRole(StrEnum):
    ACTOR_IDENTITY = "actor_identity"
    MOTION = "motion"
    COMPOSITION = "composition"
    SCENE = "scene"
    PRODUCT = "product"
    WARDROBE = "wardrobe"
    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    TRANSITION = "transition"


class VideoReferenceSourceKind(StrEnum):
    LOCAL_ORIGINAL = "local_original"
    PROJECT_ASSET = "project_asset"
    PROVIDER_MANAGED = "provider_managed"
    GENERATED_PROXY = "generated_proxy"
    GENERATED_CLEAN_PLATE = "generated_clean_plate"


class VideoReferenceMediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class ReferenceProxyKind(StrEnum):
    POSE_PROXY_IMAGE = "pose_proxy_image"
    MOTION_PROXY_VIDEO = "motion_proxy_video"
    SKELETON_IMAGE = "skeleton_image"
    SKELETON_VIDEO = "skeleton_video"
    SILHOUETTE_IMAGE = "silhouette_image"
    SILHOUETTE_VIDEO = "silhouette_video"


class ReferenceProxyRenderProfile(StrEnum):
    """Requested visual quality for an identity-free reference proxy."""

    STRUCTURAL = "structural"
    AI_ENHANCED = "ai_enhanced"


class ReferenceProxyPrivacyMode(StrEnum):
    """Which source class may cross a remote model boundary."""

    LOCAL_ONLY = "local_only"
    ANONYMOUS_STRUCTURE_ONLY = "anonymous_structure_only"
    RAW_MEDIA_ALLOWED = "raw_media_allowed"


class ReferenceProxyEngineClass(StrEnum):
    DETERMINISTIC_LOCAL = "deterministic_local"
    GENERATIVE_REMOTE = "generative_remote"


class PersonContentClass(StrEnum):
    NO_PERSON = "no_person"
    REAL_PERSON = "real_person"
    SYNTHETIC_PHOTOREAL_PERSON = "synthetic_photoreal_person"
    NON_PHOTOREAL_PROXY = "non_photoreal_proxy"
    PROVIDER_MANAGED_PERSON = "provider_managed_person"
    UNKNOWN = "unknown"


class ReferenceProxyStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


class ReferenceProxyQualityStatus(StrEnum):
    """Semantic quality of a generated motion proxy.

    File readiness and identity removal are intentionally tracked elsewhere. A
    proxy may remain previewable while being blocked from provider submission
    when its pose fidelity needs review.
    """

    PENDING = "pending"
    PASSED = "passed"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"
    LEGACY_UNVERIFIED = "legacy_unverified"


class PersonReferenceCapability(BaseModel):
    """Model-specific policy; provider defaults must never override this object."""

    policy: PersonReferencePolicy = PersonReferencePolicy.UNKNOWN
    allow_raw_photoreal_person: bool = False
    allow_provider_managed_identity: bool = False
    allow_asset_only_generation: bool = False
    supports_pose_proxy_image: bool = False
    supports_motion_proxy_video: bool = False
    supports_person_free_scene_reference: bool = True
    supported_roles: list[VideoReferenceRole] = Field(
        default_factory=lambda: [
            VideoReferenceRole.ACTOR_IDENTITY,
            VideoReferenceRole.COMPOSITION,
            VideoReferenceRole.SCENE,
            VideoReferenceRole.PRODUCT,
        ],
        max_length=20,
    )
    provider_scoped_assets: bool = True

    @model_validator(mode="after")
    def validate_policy(self) -> PersonReferenceCapability:
        if self.policy == PersonReferencePolicy.MANAGED_REQUIRED:
            if not self.allow_provider_managed_identity:
                raise ValueError("托管人物必需策略必须允许 Provider 托管身份")
            if self.allow_raw_photoreal_person:
                raise ValueError("托管人物必需策略不能同时允许原始写实人物")
        if self.policy == PersonReferencePolicy.RAW_SUPPORTED:
            if not self.allow_raw_photoreal_person:
                raise ValueError("原始人物策略必须允许原始写实人物")
        return self


class VideoReferenceBinding(BaseModel):
    """Persisted creative reference selection, independent of provider request shape."""

    id: UUID = Field(default_factory=uuid4)
    role: VideoReferenceRole
    source_kind: VideoReferenceSourceKind
    media_type: VideoReferenceMediaType
    visual_beat_id: UUID | None = None
    image_candidate_id: UUID | None = None
    reference_asset_id: UUID | None = None
    managed_asset_binding_id: UUID | None = None
    proxy_asset_id: UUID | None = None
    person_class: PersonContentClass = PersonContentClass.UNKNOWN
    rights_state: Literal["confirmed", "provider_verified", "unknown"] = "unknown"
    order: int = Field(default=1, ge=1, le=100)
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_source_reference(self) -> VideoReferenceBinding:
        source_ids = [
            self.image_candidate_id,
            self.reference_asset_id,
            self.managed_asset_binding_id,
            self.proxy_asset_id,
        ]
        if sum(value is not None for value in source_ids) != 1:
            raise ValueError("视频参考绑定必须且只能指向一个素材来源")
        expected = {
            VideoReferenceSourceKind.LOCAL_ORIGINAL: self.image_candidate_id,
            VideoReferenceSourceKind.PROJECT_ASSET: self.reference_asset_id,
            VideoReferenceSourceKind.PROVIDER_MANAGED: self.managed_asset_binding_id,
            VideoReferenceSourceKind.GENERATED_PROXY: self.proxy_asset_id,
            VideoReferenceSourceKind.GENERATED_CLEAN_PLATE: self.proxy_asset_id,
        }[self.source_kind]
        if expected is None:
            raise ValueError("视频参考来源类型与素材标识不匹配")
        return self


class ReferenceProxyAsset(BaseModel):
    """Non-photoreal motion/composition proxy derived from local media.

    A proxy intentionally carries no identity. It is a first-class derived asset,
    not a hidden replacement for a real-person reference.
    """

    id: UUID = Field(default_factory=uuid4)
    visual_beat_id: UUID
    role: VideoReferenceRole = VideoReferenceRole.MOTION
    order: int = Field(default=1, ge=1, le=100)
    kind: ReferenceProxyKind
    media_type: VideoReferenceMediaType
    status: ReferenceProxyStatus = ReferenceProxyStatus.PENDING
    source_image_candidate_id: UUID | None = None
    source_video_candidate_id: UUID | None = None
    source_video_id: UUID | None = None
    source_relative_path: str | None = Field(default=None, max_length=2048)
    relative_path: str | None = Field(default=None, max_length=2048)
    thumbnail_relative_path: str | None = Field(default=None, max_length=2048)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    engine: str = Field(default="unassigned", min_length=1, max_length=80)
    engine_version: str = Field(default="unassigned", min_length=1, max_length=80)
    requested_render_profile: ReferenceProxyRenderProfile = (
        ReferenceProxyRenderProfile.STRUCTURAL
    )
    effective_render_profile: ReferenceProxyRenderProfile = (
        ReferenceProxyRenderProfile.STRUCTURAL
    )
    privacy_mode: ReferenceProxyPrivacyMode = ReferenceProxyPrivacyMode.LOCAL_ONLY
    base_engine: str | None = Field(default=None, max_length=80)
    base_engine_version: str | None = Field(default=None, max_length=80)
    provider: str | None = Field(default=None, max_length=80)
    provider_model: str | None = Field(default=None, max_length=160)
    provider_request_id: str | None = Field(default=None, max_length=300)
    raw_source_uploaded: bool = False
    fallback_applied: bool = False
    fallback_reason: str | None = Field(default=None, max_length=1000)
    estimated_cost_micros: int | None = Field(default=None, ge=0)
    actual_cost_micros: int | None = Field(default=None, ge=0)
    cost_estimate_known: bool = False
    actual_cost_known: bool = False
    person_class: PersonContentClass = PersonContentClass.NON_PHOTOREAL_PROXY
    identity_removed: bool = False
    validation_status: Literal["pending", "passed", "failed"] = "pending"
    validation_message: str | None = Field(default=None, max_length=1000)
    semantic_validation_status: ReferenceProxyQualityStatus = (
        ReferenceProxyQualityStatus.LEGACY_UNVERIFIED
    )
    quality_score: float | None = Field(default=None, ge=0, le=1)
    quality_metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)
    manifest_relative_path: str | None = Field(default=None, max_length=2048)
    quality_report_relative_path: str | None = Field(default=None, max_length=2048)
    model_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    error_code: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_proxy(self) -> ReferenceProxyAsset:
        sources = [
            self.source_image_candidate_id,
            self.source_video_candidate_id,
            self.source_video_id,
        ]
        if sum(value is not None for value in sources) != 1:
            raise ValueError("动作代理必须且只能绑定一个源图片或源视频")
        expected_media = {
            ReferenceProxyKind.POSE_PROXY_IMAGE: VideoReferenceMediaType.IMAGE,
            ReferenceProxyKind.SKELETON_IMAGE: VideoReferenceMediaType.IMAGE,
            ReferenceProxyKind.SILHOUETTE_IMAGE: VideoReferenceMediaType.IMAGE,
            ReferenceProxyKind.MOTION_PROXY_VIDEO: VideoReferenceMediaType.VIDEO,
            ReferenceProxyKind.SKELETON_VIDEO: VideoReferenceMediaType.VIDEO,
            ReferenceProxyKind.SILHOUETTE_VIDEO: VideoReferenceMediaType.VIDEO,
        }[self.kind]
        if self.media_type != expected_media:
            raise ValueError("动作代理类型与媒体类型不匹配")
        if self.status == ReferenceProxyStatus.READY:
            if not self.relative_path or not self.sha256:
                raise ValueError("已就绪的动作代理必须包含文件路径和摘要")
            if not self.identity_removed or self.validation_status != "passed":
                raise ValueError("动作代理只有在身份去除校验通过后才能标记为就绪")
        if (
            self.privacy_mode == ReferenceProxyPrivacyMode.ANONYMOUS_STRUCTURE_ONLY
            and self.raw_source_uploaded
        ):
            raise ValueError("仅上传匿名结构稿时不得标记为已上传原始素材")
        if self.effective_render_profile == ReferenceProxyRenderProfile.AI_ENHANCED:
            if not self.provider or not self.provider_model:
                raise ValueError("AI 增强白模必须记录 Provider 与模型")
            if self.privacy_mode == ReferenceProxyPrivacyMode.LOCAL_ONLY:
                raise ValueError("远程 AI 增强不能标记为仅本机处理")
        if self.fallback_applied and not self.fallback_reason:
            raise ValueError("白模发生回退时必须记录原因")
        return self

    @property
    def usable_for_generation(self) -> bool:
        """Return whether this proxy may cross the provider request boundary."""

        return bool(
            self.status == ReferenceProxyStatus.READY
            and self.identity_removed
            and self.validation_status == "passed"
            and self.semantic_validation_status == ReferenceProxyQualityStatus.PASSED
            and self.quality_score is not None
            and self.relative_path
            and self.sha256
            and self.manifest_relative_path
            and self.quality_report_relative_path
            and self.model_sha256
        )
