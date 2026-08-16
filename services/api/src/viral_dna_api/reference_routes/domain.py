from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class VideoReferenceRouteId(StrEnum):
    """Provider-neutral reference recipes.

    Route names describe semantics, not the current provider payload shape. This
    keeps product decisions independent from a concrete API implementation.
    """

    ORDERED_MULTI_IMAGE = "ordered_multi_image"
    SEEDANCE_MANAGED_ACTOR_MOTION_PROXY = "seedance_managed_actor_motion_proxy"
    MINIMAX_IDENTITY_IMAGE_MOTION_PROXY = "minimax_identity_image_motion_proxy"
    WAN_VACE_POSEBODY_REPAINT = "wan_vace_posebody_repaint"
    POSE_IMAGE_TEXT_FALLBACK = "pose_image_text_fallback"
    PERSON_FREE = "person_free"


class IdentityReferenceTransport(StrEnum):
    PROVIDER_MANAGED_ASSET = "provider_managed_asset"
    REFERENCE_IMAGE = "reference_image"
    NONE = "none"


class MotionReferenceTransport(StrEnum):
    REFERENCE_VIDEO = "reference_video"
    CONTROL_VIDEO = "control_video"
    POSE_IMAGE_TEXT = "pose_image_text"
    NONE = "none"


class MotionReferenceSemantics(StrEnum):
    STRUCTURAL_CONTROL = "structural_control"
    GUIDED_REFERENCE = "guided_reference"
    SUGGESTIVE = "suggestive"
    NONE = "none"


class RouteSupportLevel(StrEnum):
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    RESERVED = "reserved"


class VideoReferenceRouteCapability(BaseModel):
    """One model's supported identity/motion route and honest fallback.

    `enabled` controls whether the model may enter the production workflow.
    `provider_verified` controls whether the primary motion transport may cross
    the provider boundary. An unverified primary route must declare a fallback.
    """

    route_id: VideoReferenceRouteId = VideoReferenceRouteId.ORDERED_MULTI_IMAGE
    label: str = Field(default="有序参考画面", min_length=1, max_length=120)
    enabled: bool = True
    support_level: RouteSupportLevel = RouteSupportLevel.VERIFIED
    identity_transport: IdentityReferenceTransport = (
        IdentityReferenceTransport.REFERENCE_IMAGE
    )
    motion_transport: MotionReferenceTransport = MotionReferenceTransport.NONE
    motion_semantics: MotionReferenceSemantics = MotionReferenceSemantics.NONE
    identity_required: bool = False
    accepts_raw_person_images: bool = True
    provider_verified: bool = True
    supports_pose_proxy_image: bool = False
    supports_motion_proxy_video: bool = False
    show_motion_proxy_controls: bool = False
    fallback_route_id: VideoReferenceRouteId | None = None
    fallback_label: str | None = Field(default=None, max_length=160)
    requires_public_media_url: bool = False
    availability_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_route(self) -> VideoReferenceRouteCapability:
        if self.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET:
            if not self.identity_required:
                raise ValueError("托管人物资产路由必须声明人物身份为必需输入")
            if self.accepts_raw_person_images:
                raise ValueError("托管人物资产路由不能同时允许原始真人身份图")
        if self.motion_transport in {
            MotionReferenceTransport.REFERENCE_VIDEO,
            MotionReferenceTransport.CONTROL_VIDEO,
        } and not self.supports_motion_proxy_video:
            raise ValueError("视频动作路由必须声明支持动作代理视频")
        if not self.provider_verified and self.enabled and self.fallback_route_id is None:
            raise ValueError("尚未验证的模型路由必须提供安全回退方案")
        return self
