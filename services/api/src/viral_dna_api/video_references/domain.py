from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PersonReferencePolicy(StrEnum):
    """How a concrete video model accepts human identity references."""

    MANAGED_REQUIRED = "managed_required"
    RAW_SUPPORTED = "raw_supported"
    MANAGED_OPTIONAL = "managed_optional"
    NO_PERSON = "no_person"
    UNKNOWN = "unknown"


class VideoReferenceRole(StrEnum):
    ACTOR_IDENTITY = "actor_identity"
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


class VideoReferenceMediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class PersonContentClass(StrEnum):
    NO_PERSON = "no_person"
    REAL_PERSON = "real_person"
    SYNTHETIC_PHOTOREAL_PERSON = "synthetic_photoreal_person"
    PROVIDER_MANAGED_PERSON = "provider_managed_person"
    UNKNOWN = "unknown"


class PersonReferenceCapability(BaseModel):
    """Model-specific identity policy; spatial control is modelled separately."""

    policy: PersonReferencePolicy = PersonReferencePolicy.UNKNOWN
    allow_raw_photoreal_person: bool = False
    allow_provider_managed_identity: bool = False
    allow_asset_only_generation: bool = False
    supports_person_free_scene_reference: bool = True
    supported_roles: list[VideoReferenceRole] = Field(
        default_factory=lambda: [
            VideoReferenceRole.ACTOR_IDENTITY,
            VideoReferenceRole.COMPOSITION,
            VideoReferenceRole.SCENE,
            VideoReferenceRole.PRODUCT,
            VideoReferenceRole.WARDROBE,
        ],
        max_length=20,
    )
    provider_scoped_assets: bool = True

    @model_validator(mode="after")
    def validate_policy(self) -> PersonReferenceCapability:
        if self.policy == PersonReferencePolicy.MANAGED_REQUIRED:
            if not self.allow_provider_managed_identity:
                raise ValueError("托管人物策略必须允许 Provider 托管身份")
            if self.allow_raw_photoreal_person:
                raise ValueError("托管人物策略不能同时允许原始真人参考图")
        if (
            self.policy == PersonReferencePolicy.RAW_SUPPORTED
            and not self.allow_raw_photoreal_person
        ):
            raise ValueError("原始人物策略必须允许原始真人参考图")
        return self


class VideoReferenceBinding(BaseModel):
    """Persisted creative image/managed-asset selection.

    Full-scene depth controls are first-class control assets and deliberately do
    not pass through this image-reference binding model.
    """

    id: UUID = Field(default_factory=uuid4)
    role: VideoReferenceRole
    source_kind: VideoReferenceSourceKind
    media_type: VideoReferenceMediaType
    visual_beat_id: UUID | None = None
    image_candidate_id: UUID | None = None
    reference_asset_id: UUID | None = None
    managed_asset_binding_id: UUID | None = None
    person_class: PersonContentClass = PersonContentClass.UNKNOWN
    rights_state: str = Field(default="unknown", pattern=r"^(confirmed|provider_verified|unknown)$")
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
        ]
        if sum(value is not None for value in source_ids) != 1:
            raise ValueError("视频参考绑定必须且只能指向一个素材来源")
        expected = {
            VideoReferenceSourceKind.LOCAL_ORIGINAL: self.image_candidate_id,
            VideoReferenceSourceKind.PROJECT_ASSET: self.reference_asset_id,
            VideoReferenceSourceKind.PROVIDER_MANAGED: self.managed_asset_binding_id,
        }[self.source_kind]
        if expected is None:
            raise ValueError("视频参考来源类型与素材标识不匹配")
        return self
