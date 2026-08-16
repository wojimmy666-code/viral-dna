from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import FileResponse

from ..production import ProductionService, ProductionServiceError
from ..reference_routes import VideoReferenceRouteId, resolve_reference_route
from ..video_generation.catalog import VideoModelCatalogError, load_video_model_catalog
from .domain import PersonReferencePolicy, VideoReferenceSourceKind
from .models import (
    ProxyEngineInstallationResponse,
    ReferenceProxyCapabilityResponse,
    ReferenceProxyCreate,
    ReferenceProxyCreateResponse,
    ReferenceProxyDeleteResponse,
    VideoReferencePlanStep,
    VideoReferenceStrategyResponse,
)
from .proxies import ReferenceProxyService, ReferenceProxyServiceError
from .proxies.contracts import ProxyEngineCapability
from .proxies.service import ProxyEngineInstallation


def _capability_response(
    item: ProxyEngineCapability,
) -> ReferenceProxyCapabilityResponse:
    return ReferenceProxyCapabilityResponse(
        engine=item.engine,
        version=item.version,
        kinds=list(item.kinds),
        available=item.available,
        availability_note=item.availability_note,
        production_ready=item.production_ready,
        wholebody=item.wholebody,
        hand_keypoints=item.hand_keypoints,
        video_tracking=item.video_tracking,
        runtime_provider=item.runtime_provider,
    )


def _installation_response(
    item: ProxyEngineInstallation,
) -> ProxyEngineInstallationResponse:
    return ProxyEngineInstallationResponse(
        id=item.id,
        engine=item.engine,
        status=item.status,
        progress_percent=item.progress_percent,
        downloaded_bytes=item.downloaded_bytes,
        total_bytes=item.total_bytes,
        message=item.message,
        error_code=item.error_code,
        capability=(
            _capability_response(item.capability) if item.capability is not None else None
        ),
    )


def _raise_production(exc: ProductionServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _raise_proxy(exc: ReferenceProxyServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def create_video_reference_router(
    production: ProductionService,
    proxies: ReferenceProxyService,
) -> APIRouter:
    router = APIRouter(prefix="/video-references", tags=["video-references"])

    @router.get(
        "/proxy-engines",
        response_model=list[ReferenceProxyCapabilityResponse],
    )
    async def list_proxy_engines() -> list[ReferenceProxyCapabilityResponse]:
        return [_capability_response(item) for item in proxies.capabilities()]

    @router.post(
        "/proxy-engines/{engine_name}/installations",
        response_model=ProxyEngineInstallationResponse,
        status_code=202,
    )
    async def start_proxy_engine_installation(
        engine_name: Annotated[str, Path(min_length=1, max_length=80)],
    ) -> ProxyEngineInstallationResponse:
        try:
            item = await proxies.start_engine_installation(engine_name)
        except ReferenceProxyServiceError as exc:
            _raise_proxy(exc)
        return _installation_response(item)

    @router.get(
        "/proxy-engines/installations/{installation_id}",
        response_model=ProxyEngineInstallationResponse,
    )
    async def get_proxy_engine_installation(
        installation_id: UUID,
    ) -> ProxyEngineInstallationResponse:
        try:
            item = proxies.engine_installation(installation_id)
        except ReferenceProxyServiceError as exc:
            _raise_proxy(exc)
        return _installation_response(item)

    @router.post(
        "/proxy-engines/{engine_name}/install",
        response_model=ReferenceProxyCapabilityResponse,
    )
    async def install_proxy_engine(
        engine_name: Annotated[str, Path(min_length=1, max_length=80)],
    ) -> ReferenceProxyCapabilityResponse:
        try:
            item = await proxies.install_engine(engine_name)
        except ReferenceProxyServiceError as exc:
            _raise_proxy(exc)
        return _capability_response(item)

    @router.get(
        "/shots/{shot_plan_id}/strategy",
        response_model=VideoReferenceStrategyResponse,
    )
    async def get_strategy(
        shot_plan_id: Annotated[UUID, Path()],
        model_alias: Annotated[str, Query(min_length=1, max_length=80)],
    ) -> VideoReferenceStrategyResponse:
        try:
            detail = await production.get_shot(shot_plan_id)
        except ProductionServiceError as exc:
            _raise_production(exc)
        try:
            model = load_video_model_catalog().option(model_alias)
        except VideoModelCatalogError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "video_model_invalid", "message": str(exc)},
            ) from exc
        capability = model.capability.person_references
        policy = capability.policy
        managed_bound = bool(detail.plan.managed_asset_bindings)
        proxy_assets = {
            item.id: item for item in detail.plan.reference_proxy_assets
        }
        selected_proxies = [
            proxy
            for item in detail.plan.video_reference_bindings
            if item.enabled
            and item.source_kind == VideoReferenceSourceKind.GENERATED_PROXY
            and item.proxy_asset_id is not None
            and (proxy := proxy_assets.get(item.proxy_asset_id)) is not None
            and proxy.usable_for_generation
        ]
        route_capability = model.capability.reference_route
        route = resolve_reference_route(
            route_capability,
            has_managed_identity=managed_bound,
            has_raw_reference_image=any(
                item.required and item.approved_image_candidate_id is not None
                for item in detail.plan.visual_beats
            ),
            has_pose_proxy_image=any(item.media_type == "image" for item in selected_proxies),
            has_motion_proxy_video=any(item.media_type == "video" for item in selected_proxies),
            public_media_transport_ready=False,
        )
        if policy == PersonReferencePolicy.MANAGED_REQUIRED:
            strategy = (
                "managed_identity_with_proxy" if selected_proxies else "managed_identity"
            )
            allowed = route.generation_allowed
            title = "托管演员 + 无身份动作参考"
            description = (
                "托管演员是唯一人物身份来源；原始真人关键帧不会提交。"
                + (
                    f" 已选择 {len(selected_proxies)} 个图片/视频动作代理。"
                    if selected_proxies
                    else " 可按需生成图片或视频动作代理。"
                )
            )
            blocker = route.blocker_message
        elif policy in {
            PersonReferencePolicy.RAW_SUPPORTED,
            PersonReferencePolicy.MANAGED_OPTIONAL,
        }:
            strategy = "raw_references"
            allowed = route.generation_allowed
            title = "使用原始参考素材"
            description = "当前模型允许直接提交已确认的原始人物、动作、构图和场景参考。"
            blocker = route.blocker_message
        elif policy == PersonReferencePolicy.NO_PERSON:
            strategy = "person_free"
            allowed = route.generation_allowed and not managed_bound
            title = "仅无人物参考"
            description = "当前模型不允许人物或托管演员参考。"
            blocker = route.blocker_message
            if not allowed and blocker is None:
                blocker = "请解除托管人物绑定后再生成"
        else:
            strategy = "unknown"
            allowed = route.generation_allowed
            title = "兼容模式"
            description = "当前模型尚未声明人物参考策略，生成前请人工确认。"
            blocker = route.blocker_message
        if route.route_id == VideoReferenceRouteId.MINIMAX_IDENTITY_IMAGE_MOTION_PROXY:
            title = "目标人物图 + 动作参考视频"
            description = (
                "目标人物图是身份与外观来源；视频白模只提供动作、姿态和镜头运动。"
                if route.motion_source == "motion_proxy_video"
                else "当前没有启用视频白模，已自动改用目标人物图与文字动作描述。"
            )
        elif route.route_id == VideoReferenceRouteId.WAN_VACE_POSEBODY_REPAINT:
            title = "目标人物图 + PoseBody 结构控制"
            description = (
                "目标人物图替换主体身份，视频白模通过 video_repainting(posebody)"
                " 提供肢体动作结构。"
            )
        elif route.route_id == VideoReferenceRouteId.POSE_IMAGE_TEXT_FALLBACK:
            title = "目标关键帧 + 文字动作描述"
            description = (
                "当前模型不接收参考视频；使用已确认的目标关键帧与文字动作描述生成，"
                "不会显示或提交视频白模。"
            )
        elif route.route_id == VideoReferenceRouteId.ORDERED_MULTI_IMAGE:
            title = "有序目标画面参考"
            description = "按画面顺序提交已确认的目标关键帧，保持主体、场景与转场关系。"
        identity_ready = route.identity_source != "none"
        motion_ready = route.motion_source not in {"none", "prompt_motion_description"}
        steps = [
            VideoReferencePlanStep(
                kind="identity",
                label="人物身份来源",
                source=route.identity_source,
                status=(
                    "ready"
                    if identity_ready or not route_capability.identity_required
                    else "blocked"
                ),
                detail=(
                    "Provider 托管演员是唯一身份来源"
                    if route.identity_source == "provider_managed_asset"
                    else "使用已确认的目标人物参考图"
                    if route.identity_source == "approved_reference_image"
                    else "该路由不需要人物身份输入"
                ),
            ),
            VideoReferencePlanStep(
                kind="motion",
                label="动作与运镜来源",
                source=route.motion_source,
                status=(
                    "fallback"
                    if route.fallback_applied
                    else "ready"
                    if motion_ready
                    else "optional"
                ),
                detail=(
                    "视频白模只提供动作、姿态、位置和镜头运动，不提供人物身份"
                    if route.motion_source == "motion_proxy_video"
                    else "使用图片姿态和文字动作描述，动作还原强度低于视频控制"
                    if route.motion_source in {"pose_proxy_image", "prompt_motion_description"}
                    else "该模型不接收视频动作参考"
                ),
            ),
        ]
        if policy == PersonReferencePolicy.MANAGED_REQUIRED:
            steps.append(
                VideoReferencePlanStep(
                    kind="privacy",
                    label="真人素材隔离",
                    source="local_reference_filter",
                    status="excluded",
                    detail="原始真人关键帧不会提交给 Seedance；只保留托管身份与无身份动作信息",
                )
            )
        if route_capability.requires_public_media_url:
            steps.append(
                VideoReferencePlanStep(
                    kind="transport",
                    label="Provider 媒体传输",
                    source="public_media_url",
                    status="ready" if route.generation_allowed else "blocked",
                    detail="VACE 只接受 Provider 可访问的 HTTP/HTTPS/OSS 媒体 URL",
                )
            )
        return VideoReferenceStrategyResponse(
            model_alias=model.alias,
            model_label=model.label,
            policy=policy,
            strategy=strategy,
            title=title,
            description=description,
            managed_identity_required=policy == PersonReferencePolicy.MANAGED_REQUIRED,
            managed_identity_bound=managed_bound,
            raw_person_references_submitted=route_capability.accepts_raw_person_images,
            proxy_image_supported=route_capability.supports_pose_proxy_image,
            proxy_video_supported=route_capability.supports_motion_proxy_video,
            selected_proxy_count=len(selected_proxies),
            excluded_local_reference_count=(
                len(detail.plan.visual_beats)
                if policy == PersonReferencePolicy.MANAGED_REQUIRED
                else 0
            ),
            generation_allowed=allowed,
            blocker_message=blocker,
            route_id=route.route_id.value,
            route_label=route_capability.label,
            effective_route_id=route.effective_route_id.value,
            support_level=route_capability.support_level.value,
            identity_transport=route.identity_transport.value,
            motion_transport=route.motion_transport.value,
            motion_semantics=route.motion_semantics.value,
            identity_source=route.identity_source,
            motion_source=route.motion_source,
            fallback_applied=route.fallback_applied,
            requires_public_media_url=route_capability.requires_public_media_url,
            provider_verified=route_capability.provider_verified,
            warnings=list(route.warnings),
            plan_steps=steps,
        )

    @router.post(
        "/shots/{shot_plan_id}/proxies",
        response_model=ReferenceProxyCreateResponse,
        status_code=201,
    )
    async def create_proxy(
        shot_plan_id: Annotated[UUID, Path()],
        payload: ReferenceProxyCreate,
    ) -> ReferenceProxyCreateResponse:
        try:
            return await production.create_reference_proxy(shot_plan_id, payload)
        except ProductionServiceError as exc:
            _raise_production(exc)

    @router.delete(
        "/shots/{shot_plan_id}/proxies/{proxy_asset_id}",
        response_model=ReferenceProxyDeleteResponse,
    )
    async def delete_proxy(
        shot_plan_id: Annotated[UUID, Path()],
        proxy_asset_id: Annotated[UUID, Path()],
        expected_revision_id: Annotated[UUID, Query()],
    ) -> ReferenceProxyDeleteResponse:
        try:
            return await production.delete_reference_proxy(
                shot_plan_id,
                proxy_asset_id,
                expected_revision_id,
            )
        except ProductionServiceError as exc:
            _raise_production(exc)

    @router.get(
        "/shots/{shot_plan_id}/proxies/{proxy_asset_id}/content",
        response_class=FileResponse,
    )
    async def get_proxy_content(
        shot_plan_id: Annotated[UUID, Path()],
        proxy_asset_id: Annotated[UUID, Path()],
        thumbnail: Annotated[bool, Query()] = False,
        download: Annotated[bool, Query()] = False,
    ) -> FileResponse:
        try:
            detail = await production.get_shot(shot_plan_id)
        except ProductionServiceError as exc:
            _raise_production(exc)
        asset = next(
            (
                item
                for item in detail.plan.reference_proxy_assets
                if item.id == proxy_asset_id
            ),
            None,
        )
        if asset is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "reference_proxy_not_found",
                    "message": "当前分镜中不存在该白模",
                },
            )
        try:
            path, media_type, filename = await proxies.resolve_content(
                asset,
                thumbnail=thumbnail,
            )
        except ReferenceProxyServiceError as exc:
            _raise_proxy(exc)
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename,
            content_disposition_type="attachment" if download else "inline",
            headers={
                "Cache-Control": "private, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
