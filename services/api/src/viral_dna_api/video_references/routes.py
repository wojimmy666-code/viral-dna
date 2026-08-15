from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import FileResponse

from ..production import ProductionService, ProductionServiceError
from ..video_generation.catalog import VideoModelCatalogError, load_video_model_catalog
from .domain import PersonReferencePolicy, VideoReferenceSourceKind
from .models import (
    ProxyEngineInstallationResponse,
    ReferenceProxyCapabilityResponse,
    ReferenceProxyCreate,
    ReferenceProxyCreateResponse,
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
        if policy == PersonReferencePolicy.MANAGED_REQUIRED:
            strategy = (
                "managed_identity_with_proxy" if selected_proxies else "managed_identity"
            )
            allowed = managed_bound
            title = "托管演员 + 无身份动作参考"
            description = (
                "托管演员是唯一人物身份来源；原始真人关键帧不会提交。"
                + (
                    f" 已选择 {len(selected_proxies)} 个图片/视频动作代理。"
                    if selected_proxies
                    else " 可按需生成图片或视频动作代理。"
                )
            )
            blocker = None if allowed else "请先绑定当前 Provider 的托管演员身份"
        elif policy in {
            PersonReferencePolicy.RAW_SUPPORTED,
            PersonReferencePolicy.MANAGED_OPTIONAL,
        }:
            strategy = "raw_references"
            allowed = True
            title = "使用原始参考素材"
            description = "当前模型允许直接提交已确认的原始人物、动作、构图和场景参考。"
            blocker = None
        elif policy == PersonReferencePolicy.NO_PERSON:
            strategy = "person_free"
            allowed = not managed_bound
            title = "仅无人物参考"
            description = "当前模型不允许人物或托管演员参考。"
            blocker = None if allowed else "请解除托管人物绑定后再生成"
        else:
            strategy = "unknown"
            allowed = True
            title = "兼容模式"
            description = "当前模型尚未声明人物参考策略，生成前请人工确认。"
            blocker = None
        return VideoReferenceStrategyResponse(
            model_alias=model.alias,
            model_label=model.label,
            policy=policy,
            strategy=strategy,
            title=title,
            description=description,
            managed_identity_required=policy == PersonReferencePolicy.MANAGED_REQUIRED,
            managed_identity_bound=managed_bound,
            raw_person_references_submitted=capability.allow_raw_photoreal_person,
            proxy_image_supported=capability.supports_pose_proxy_image,
            proxy_video_supported=capability.supports_motion_proxy_video,
            selected_proxy_count=len(selected_proxies),
            excluded_local_reference_count=(
                len(detail.plan.visual_beats)
                if policy == PersonReferencePolicy.MANAGED_REQUIRED
                else 0
            ),
            generation_allowed=allowed,
            blocker_message=blocker,
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
