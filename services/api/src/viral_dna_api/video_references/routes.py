from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query

from ..media_staging import MediaStagingService
from ..production import ProductionService, ProductionServiceError
from ..reference_routes import VideoReferenceRouteId, resolve_reference_route
from ..video_generation.catalog import VideoModelCatalogError, load_video_model_catalog
from .domain import PersonReferencePolicy
from .models import VideoReferencePlanStep, VideoReferenceStrategyResponse


def _raise_production(exc: ProductionServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def create_video_reference_router(
    production: ProductionService,
    media_staging_service: MediaStagingService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/video-references", tags=["video-references"])

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

        capability = model.capability.reference_route
        managed_bound = bool(detail.plan.managed_asset_bindings)
        has_reference_image = bool(
            detail.plan.image_prompt_mentions
            or any(
                beat.approved_image_candidate_id is not None
                or beat.image_prompt_mentions
                for beat in detail.plan.visual_beats
            )
        )
        selected_depth = [
            item
            for item in detail.plan.depth_control_assets
            if item.enabled and item.usable_for_generation
        ]
        # Reference-route preflight must use the same account-scoped staging
        # readiness check as the generation gateway. Checking only the legacy
        # local proxy here incorrectly blocks a valid OSS configuration.
        public_media_ready = bool(
            media_staging_service is not None
            and await media_staging_service.ready()
        )
        route = resolve_reference_route(
            capability,
            has_managed_identity=managed_bound,
            has_raw_reference_image=has_reference_image,
            has_depth_control_video=bool(selected_depth),
            public_media_transport_ready=public_media_ready,
        )

        if route.route_id == VideoReferenceRouteId.SEEDANCE_MANAGED_ACTOR_DEPTH_GUIDANCE:
            strategy = "managed_actor_depth"
            title = "托管演员 + 人物/场景资产 + 全场景深度视频"
            description = (
                "托管演员决定身份，人物以外的项目资产决定外观；深度视频只提供动作、"
                "空间层次、遮挡和镜头轨迹。"
            )
        elif route.route_id == VideoReferenceRouteId.MINIMAX_IDENTITY_DEPTH_GUIDANCE:
            strategy = "identity_image_depth"
            title = "人物/场景资产 + 全场景深度视频"
            description = (
                "人物资产决定身份，场景、服装和产品资产决定外观；深度视频提供动作与空间引导。"
            )
        elif route.route_id == VideoReferenceRouteId.IMAGE_TEXT_FALLBACK:
            strategy = "image_text"
            title = "人物/场景资产 + 文字动作描述"
            description = "当前模型不接收深度视频，仅使用图片资产与视频提示词。"
        elif route.route_id == VideoReferenceRouteId.PERSON_FREE:
            strategy = "person_free"
            title = "无人物参考"
            description = "当前模型仅接收无人物画面与场景资产。"
        else:
            strategy = "ordered_images"
            title = "有序人物/场景画面参考"
            description = "按画面顺序提交已确认图片与项目资产。"

        steps = [
            VideoReferencePlanStep(
                kind="identity",
                label="人物身份来源",
                source=route.identity_source,
                status=(
                    "ready"
                    if route.identity_source != "none" or not capability.identity_required
                    else "blocked"
                ),
                detail=(
                    "使用 Provider 托管虚拟演员"
                    if route.identity_source == "provider_managed_asset"
                    else "使用已关联的人物资产或已确认人物画面"
                    if route.identity_source == "approved_reference_image"
                    else "该路由不要求人物身份"
                ),
            ),
            VideoReferencePlanStep(
                kind="appearance",
                label="人物外观与场景来源",
                source="project_assets_and_approved_frames",
                status="ready" if has_reference_image else "optional",
                detail="人物、服装、产品和场景由项目资产及已确认画面提供。",
            ),
            VideoReferencePlanStep(
                kind="spatial_control",
                label="动作与空间来源",
                source=route.spatial_control_source,
                status=(
                    "ready"
                    if route.spatial_control_source == "full_scene_depth_video"
                    else "blocked"
                    if capability.requires_depth_control_video
                    else "optional"
                ),
                detail=(
                    "全场景深度视频只提供动作、遮挡、空间层次和镜头轨迹。"
                    if capability.supports_depth_control_video
                    else "当前模型不接收深度控制视频。"
                ),
            ),
        ]
        if capability.requires_public_media_url:
            steps.append(
                VideoReferencePlanStep(
                    kind="transport",
                    label="深度视频传输",
                    source="signed_https_url",
                    status="ready" if public_media_ready else "blocked",
                    detail=(
                        "将使用短期签名 HTTPS 地址提交深度视频。"
                        if public_media_ready
                        else "请先在模型与设置中配置公网 HTTPS 媒体暂存地址。"
                    ),
                )
            )

        return VideoReferenceStrategyResponse(
            model_alias=model.alias,
            model_label=model.label,
            policy=model.capability.person_references.policy,
            strategy=strategy,
            title=title,
            description=description,
            managed_identity_required=(
                model.capability.person_references.policy
                == PersonReferencePolicy.MANAGED_REQUIRED
            ),
            managed_identity_bound=managed_bound,
            generation_allowed=route.generation_allowed,
            blocker_message=route.blocker_message,
            route_id=route.route_id.value,
            route_label=capability.label,
            support_level=capability.support_level.value,
            identity_transport=route.identity_transport.value,
            spatial_control_transport=route.spatial_control_transport.value,
            spatial_control_semantics=route.spatial_control_semantics.value,
            identity_source=route.identity_source,
            spatial_control_source=route.spatial_control_source,
            depth_control_supported=capability.supports_depth_control_video,
            depth_control_required=capability.requires_depth_control_video,
            show_depth_control_controls=capability.show_depth_control_controls,
            selected_depth_control_count=len(selected_depth),
            requires_public_media_url=capability.requires_public_media_url,
            public_media_ready=public_media_ready,
            provider_verified=capability.provider_verified,
            warnings=list(route.warnings),
            plan_steps=steps,
        )

    return router
