from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    IdentityReferenceTransport,
    SpatialControlSemantics,
    SpatialControlTransport,
    VideoReferenceRouteCapability,
    VideoReferenceRouteId,
)


@dataclass(frozen=True, slots=True)
class ResolvedReferenceRoute:
    route_id: VideoReferenceRouteId
    identity_transport: IdentityReferenceTransport
    spatial_control_transport: SpatialControlTransport
    spatial_control_semantics: SpatialControlSemantics
    identity_source: str
    spatial_control_source: str
    generation_allowed: bool
    blocker_code: str | None = None
    blocker_message: str | None = None
    warnings: tuple[str, ...] = ()


def resolve_reference_route(
    capability: VideoReferenceRouteCapability,
    *,
    has_managed_identity: bool,
    has_raw_reference_image: bool,
    has_depth_control_video: bool,
    public_media_transport_ready: bool = False,
) -> ResolvedReferenceRoute:
    """Resolve the exact route without legacy proxy or implicit fallback logic."""

    route_id = capability.route_id
    if not capability.enabled:
        return ResolvedReferenceRoute(
            route_id=route_id,
            identity_transport=capability.identity_transport,
            spatial_control_transport=capability.spatial_control_transport,
            spatial_control_semantics=capability.spatial_control_semantics,
            identity_source="none",
            spatial_control_source="none",
            generation_allowed=False,
            blocker_code="video_reference_route_disabled",
            blocker_message=capability.availability_note or "当前模型参考路由尚未开放",
        )

    if capability.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET:
        if not has_managed_identity:
            return ResolvedReferenceRoute(
                route_id=route_id,
                identity_transport=capability.identity_transport,
                spatial_control_transport=capability.spatial_control_transport,
                spatial_control_semantics=capability.spatial_control_semantics,
                identity_source="none",
                spatial_control_source="none",
                generation_allowed=False,
                blocker_code="video_managed_identity_required",
                blocker_message="请先绑定当前 Provider 的托管虚拟演员",
            )
        identity_source = "provider_managed_asset"
    elif capability.identity_transport == IdentityReferenceTransport.REFERENCE_IMAGE:
        if capability.identity_required and not has_raw_reference_image:
            return ResolvedReferenceRoute(
                route_id=route_id,
                identity_transport=capability.identity_transport,
                spatial_control_transport=capability.spatial_control_transport,
                spatial_control_semantics=capability.spatial_control_semantics,
                identity_source="none",
                spatial_control_source="none",
                generation_allowed=False,
                blocker_code="video_identity_image_required",
                blocker_message="请先确认人物参考图或包含目标人物的首帧",
            )
        identity_source = "approved_reference_image" if has_raw_reference_image else "none"
    else:
        identity_source = "none"

    if capability.requires_depth_control_video and not has_depth_control_video:
        return ResolvedReferenceRoute(
            route_id=route_id,
            identity_transport=capability.identity_transport,
            spatial_control_transport=capability.spatial_control_transport,
            spatial_control_semantics=capability.spatial_control_semantics,
            identity_source=identity_source,
            spatial_control_source="none",
            generation_allowed=False,
            blocker_code="depth_control_required",
            blocker_message="请先从原分镜生成并启用全场景深度控制视频",
        )
    if (
        has_depth_control_video
        and capability.requires_public_media_url
        and not public_media_transport_ready
    ):
        return ResolvedReferenceRoute(
            route_id=route_id,
            identity_transport=capability.identity_transport,
            spatial_control_transport=capability.spatial_control_transport,
            spatial_control_semantics=capability.spatial_control_semantics,
            identity_source=identity_source,
            spatial_control_source="full_scene_depth_video",
            generation_allowed=False,
            blocker_code="depth_control_public_url_required",
            blocker_message="当前模型需要可访问的 HTTPS 深度视频地址，请先配置媒体暂存服务",
        )

    warnings: list[str] = []
    if (
        has_depth_control_video
        and capability.spatial_control_semantics
        == SpatialControlSemantics.GUIDED_DEPTH_REFERENCE
    ):
        warnings.append("当前模型将深度视频作为引导参考，不保证逐像素严格控制")
    spatial_source = (
        "full_scene_depth_video"
        if has_depth_control_video and capability.supports_depth_control_video
        else "none"
    )
    return ResolvedReferenceRoute(
        route_id=route_id,
        identity_transport=capability.identity_transport,
        spatial_control_transport=capability.spatial_control_transport,
        spatial_control_semantics=capability.spatial_control_semantics,
        identity_source=identity_source,
        spatial_control_source=spatial_source,
        generation_allowed=True,
        warnings=tuple(warnings),
    )
