from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class VideoReferenceRouteId(StrEnum):
    """Provider-neutral recipes for identity, appearance and depth control."""

    ORDERED_MULTI_IMAGE = "ordered_multi_image"
    SEEDANCE_MANAGED_ACTOR_DEPTH_GUIDANCE = "seedance_managed_actor_depth_guidance"
    MINIMAX_IDENTITY_DEPTH_GUIDANCE = "minimax_identity_depth_guidance"
    WAN_VACE_DEPTH_CONTROL = "wan_vace_depth_control"
    IMAGE_TEXT_FALLBACK = "image_text_fallback"
    PERSON_FREE = "person_free"


class IdentityReferenceTransport(StrEnum):
    PROVIDER_MANAGED_ASSET = "provider_managed_asset"
    REFERENCE_IMAGE = "reference_image"
    NONE = "none"


class SpatialControlTransport(StrEnum):
    REFERENCE_VIDEO = "reference_video"
    CONTROL_VIDEO = "control_video"
    NONE = "none"


class SpatialControlSemantics(StrEnum):
    GUIDED_DEPTH_REFERENCE = "guided_depth_reference"
    STRICT_DEPTH_CONTROL = "strict_depth_control"
    NONE = "none"


class RouteSupportLevel(StrEnum):
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    RESERVED = "reserved"


class VideoReferenceRouteCapability(BaseModel):
    """One model's exact creative-reference and depth-control route."""

    route_id: VideoReferenceRouteId = VideoReferenceRouteId.ORDERED_MULTI_IMAGE
    label: str = Field(default="有序参考画面", min_length=1, max_length=120)
    enabled: bool = True
    support_level: RouteSupportLevel = RouteSupportLevel.VERIFIED
    identity_transport: IdentityReferenceTransport = (
        IdentityReferenceTransport.REFERENCE_IMAGE
    )
    spatial_control_transport: SpatialControlTransport = SpatialControlTransport.NONE
    spatial_control_semantics: SpatialControlSemantics = SpatialControlSemantics.NONE
    identity_required: bool = False
    accepts_raw_person_images: bool = True
    provider_verified: bool = True
    supports_depth_control_video: bool = False
    requires_depth_control_video: bool = False
    show_depth_control_controls: bool = False
    requires_public_media_url: bool = False
    availability_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_route(self) -> VideoReferenceRouteCapability:
        if self.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET:
            if not self.identity_required:
                raise ValueError("托管人物路由必须声明人物身份为必需输入")
            if self.accepts_raw_person_images:
                raise ValueError("托管人物路由不能同时允许原始真人身份图")
        if self.spatial_control_transport != SpatialControlTransport.NONE:
            if not self.supports_depth_control_video:
                raise ValueError("视频空间控制路由必须声明支持深度控制视频")
            if self.spatial_control_semantics == SpatialControlSemantics.NONE:
                raise ValueError("视频空间控制路由必须声明控制语义")
        if self.requires_depth_control_video and not self.supports_depth_control_video:
            raise ValueError("必需深度控制的路由必须支持深度控制视频")
        if self.show_depth_control_controls and not self.supports_depth_control_video:
            raise ValueError("只有支持深度控制的模型才能显示深度控制界面")
        return self
