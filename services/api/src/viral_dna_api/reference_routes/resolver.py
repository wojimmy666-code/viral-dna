from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    IdentityReferenceTransport,
    MotionReferenceSemantics,
    MotionReferenceTransport,
    VideoReferenceRouteCapability,
    VideoReferenceRouteId,
)


@dataclass(frozen=True, slots=True)
class ResolvedReferenceRoute:
    route_id: VideoReferenceRouteId
    effective_route_id: VideoReferenceRouteId
    identity_transport: IdentityReferenceTransport
    motion_transport: MotionReferenceTransport
    motion_semantics: MotionReferenceSemantics
    identity_source: str
    motion_source: str
    fallback_applied: bool
    generation_allowed: bool
    blocker_code: str | None = None
    blocker_message: str | None = None
    warnings: tuple[str, ...] = ()


def resolve_reference_route(
    capability: VideoReferenceRouteCapability,
    *,
    has_managed_identity: bool,
    has_raw_reference_image: bool,
    has_pose_proxy_image: bool,
    has_motion_proxy_video: bool,
    public_media_transport_ready: bool = False,
) -> ResolvedReferenceRoute:
    """Resolve an honest, model-specific submission plan.

    This function never upgrades a weak reference into structural control and
    never submits an unverified provider transport merely because a file exists.
    """

    route_id = capability.route_id
    warnings: list[str] = []
    effective = route_id
    fallback = False
    motion_transport = capability.motion_transport
    motion_semantics = capability.motion_semantics

    if not capability.enabled:
        return ResolvedReferenceRoute(
            route_id=route_id,
            effective_route_id=route_id,
            identity_transport=capability.identity_transport,
            motion_transport=motion_transport,
            motion_semantics=motion_semantics,
            identity_source="none",
            motion_source="none",
            fallback_applied=False,
            generation_allowed=False,
            blocker_code="video_reference_route_disabled",
            blocker_message=capability.availability_note or "当前模型参考路由尚未开放",
        )

    if capability.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET:
        if not has_managed_identity:
            return ResolvedReferenceRoute(
                route_id=route_id,
                effective_route_id=route_id,
                identity_transport=capability.identity_transport,
                motion_transport=motion_transport,
                motion_semantics=motion_semantics,
                identity_source="none",
                motion_source="none",
                fallback_applied=False,
                generation_allowed=False,
                blocker_code="video_managed_identity_required",
                blocker_message="请先绑定当前 Provider 的托管演员身份",
            )
        identity_source = "provider_managed_asset"
    elif capability.identity_transport == IdentityReferenceTransport.REFERENCE_IMAGE:
        if capability.identity_required and not has_raw_reference_image:
            return ResolvedReferenceRoute(
                route_id=route_id,
                effective_route_id=route_id,
                identity_transport=capability.identity_transport,
                motion_transport=motion_transport,
                motion_semantics=motion_semantics,
                identity_source="none",
                motion_source="none",
                fallback_applied=False,
                generation_allowed=False,
                blocker_code="video_identity_image_required",
                blocker_message="请先确认一张目标人物参考图",
            )
        identity_source = "approved_reference_image" if has_raw_reference_image else "none"
    else:
        identity_source = "none"

    if capability.requires_public_media_url and not public_media_transport_ready:
        return ResolvedReferenceRoute(
            route_id=route_id,
            effective_route_id=route_id,
            identity_transport=capability.identity_transport,
            motion_transport=motion_transport,
            motion_semantics=motion_semantics,
            identity_source=identity_source,
            motion_source="none",
            fallback_applied=False,
            generation_allowed=False,
            blocker_code="video_public_media_transport_required",
            blocker_message=(
                "该模型要求 Provider 可访问的公网媒体 URL；"
                "当前工作区尚未配置媒体暂存服务"
            ),
        )

    wants_video = motion_transport in {
        MotionReferenceTransport.REFERENCE_VIDEO,
        MotionReferenceTransport.CONTROL_VIDEO,
    }
    if wants_video and capability.provider_verified and has_motion_proxy_video:
        motion_source = "motion_proxy_video"
    elif wants_video:
        if capability.fallback_route_id is None:
            code = (
                "video_motion_proxy_required"
                if capability.provider_verified
                else "video_reference_transport_unverified"
            )
            message = (
                "请先生成并启用视频白模"
                if capability.provider_verified
                else "当前模型的视频参考通道尚未完成 Provider 验证"
            )
            return ResolvedReferenceRoute(
                route_id=route_id,
                effective_route_id=route_id,
                identity_transport=capability.identity_transport,
                motion_transport=motion_transport,
                motion_semantics=motion_semantics,
                identity_source=identity_source,
                motion_source="none",
                fallback_applied=False,
                generation_allowed=False,
                blocker_code=code,
                blocker_message=message,
            )
        fallback = True
        effective = capability.fallback_route_id
        motion_transport = MotionReferenceTransport.POSE_IMAGE_TEXT
        motion_semantics = MotionReferenceSemantics.SUGGESTIVE
        motion_source = "pose_proxy_image" if has_pose_proxy_image else "prompt_motion_description"
        reason = (
            "未找到已启用的视频白模"
            if capability.provider_verified
            else "Provider 尚未验证视频参考输入"
        )
        fallback_label = capability.fallback_label or "图片姿态 + 文本动作描述"
        warnings.append(f"{reason}，已回退为{fallback_label}；动作还原强度会降低")
    elif motion_transport == MotionReferenceTransport.POSE_IMAGE_TEXT:
        motion_source = "pose_proxy_image" if has_pose_proxy_image else "prompt_motion_description"
    else:
        motion_source = "none"

    return ResolvedReferenceRoute(
        route_id=route_id,
        effective_route_id=effective,
        identity_transport=capability.identity_transport,
        motion_transport=motion_transport,
        motion_semantics=motion_semantics,
        identity_source=identity_source,
        motion_source=motion_source,
        fallback_applied=fallback,
        generation_allowed=True,
        warnings=tuple(warnings),
    )
