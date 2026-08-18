from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, status
from fastapi.responses import FileResponse

from ..production import ProductionService, ProductionServiceError
from .engines import DepthEngineCapability
from .jobs.domain import DepthExecutionPreference
from .jobs.service import DepthControlJobService, DepthControlJobServiceError
from .models import (
    DepthControlCreate,
    DepthControlCreateResponse,
    DepthControlDeleteResponse,
    DepthControlJobCancelResponse,
    DepthControlJobCreate,
    DepthControlJobListResponse,
    DepthControlJobResponse,
    DepthControlJobRetryResponse,
    DepthControlUpdate,
    DepthControlUpdateResponse,
    DepthEngineCapabilityResponse,
    DepthEngineInstallationResponse,
    DepthExecutionModeStatus,
    DepthGenerationSettingsResponse,
    DepthGenerationSettingsUpdate,
)
from .service import (
    DepthControlService,
    DepthControlServiceError,
    DepthEngineInstallation,
)
from .settings import DepthGenerationSettingsService


def _raise_production(exc: ProductionServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _raise_depth(exc: DepthControlServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _raise_job(exc: DepthControlJobServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _capability_response(
    capability: DepthEngineCapability,
) -> DepthEngineCapabilityResponse:
    return DepthEngineCapabilityResponse(
        engine=capability.engine,
        version=capability.version,
        model_variant=capability.model_variant,
        available=capability.available,
        availability_note=capability.availability_note,
        repository_url=capability.repository_url,
        checkpoint_path=(
            str(capability.checkpoint_path)
            if capability.checkpoint_path is not None
            else None
        ),
        runtime_path=(
            str(capability.runtime_path)
            if capability.runtime_path is not None
            else None
        ),
        license=capability.license,
    )


def _installation_response(
    installation: DepthEngineInstallation,
) -> DepthEngineInstallationResponse:
    return DepthEngineInstallationResponse(
        id=installation.id,
        engine=installation.engine,
        status=installation.status,
        progress_percent=installation.progress_percent,
        message=installation.message,
        error=installation.error,
        created_at=installation.created_at,
        updated_at=installation.updated_at,
        capability=(
            _capability_response(installation.capability)
            if installation.capability is not None
            else None
        ),
    )


def create_depth_control_router(
    production: ProductionService,
    service: DepthControlService,
    jobs: DepthControlJobService,
) -> APIRouter:
    router = APIRouter(prefix="/depth-controls", tags=["depth-controls"])

    @router.get("/engines", response_model=list[DepthEngineCapabilityResponse])
    async def list_engines() -> list[DepthEngineCapabilityResponse]:
        return [_capability_response(item) for item in service.capabilities()]

    @router.post(
        "/engines/{engine_name}/installations",
        response_model=DepthEngineInstallationResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def install_engine(
        engine_name: Annotated[str, Path(min_length=1, max_length=80)],
    ) -> DepthEngineInstallationResponse:
        try:
            return _installation_response(await service.start_installation(engine_name))
        except DepthControlServiceError as exc:
            _raise_depth(exc)

    @router.get(
        "/engines/installations/{installation_id}",
        response_model=DepthEngineInstallationResponse,
    )
    async def get_engine_installation(
        installation_id: Annotated[UUID, Path()],
    ) -> DepthEngineInstallationResponse:
        try:
            return _installation_response(service.installation(installation_id))
        except DepthControlServiceError as exc:
            _raise_depth(exc)

    @router.post(
        "/shots/{shot_plan_id}/jobs",
        response_model=DepthControlJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_job(
        shot_plan_id: Annotated[UUID, Path()],
        payload: DepthControlJobCreate,
    ) -> DepthControlJobResponse:
        try:
            return DepthControlJobResponse(
                job=await jobs.submit(
                    shot_plan_id,
                    expected_revision_id=payload.expected_revision_id,
                    preset=payload.preset,
                )
            )
        except DepthControlJobServiceError as exc:
            _raise_job(exc)

    @router.get(
        "/shots/{shot_plan_id}/jobs",
        response_model=DepthControlJobListResponse,
    )
    async def list_jobs(
        shot_plan_id: Annotated[UUID, Path()],
        active_only: Annotated[bool, Query()] = False,
    ) -> DepthControlJobListResponse:
        return DepthControlJobListResponse(
            items=await jobs.list_for_shot(shot_plan_id, active_only=active_only)
        )

    @router.get(
        "/jobs/{job_id}",
        response_model=DepthControlJobResponse,
    )
    async def get_job(
        job_id: Annotated[UUID, Path()],
    ) -> DepthControlJobResponse:
        try:
            return DepthControlJobResponse(job=await jobs.get(job_id))
        except DepthControlJobServiceError as exc:
            _raise_job(exc)

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=DepthControlJobCancelResponse,
    )
    async def cancel_job(
        job_id: Annotated[UUID, Path()],
    ) -> DepthControlJobCancelResponse:
        try:
            return DepthControlJobCancelResponse(job=await jobs.cancel(job_id))
        except DepthControlJobServiceError as exc:
            _raise_job(exc)

    @router.post(
        "/jobs/{job_id}/retry",
        response_model=DepthControlJobRetryResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_job(
        job_id: Annotated[UUID, Path()],
    ) -> DepthControlJobRetryResponse:
        try:
            return DepthControlJobRetryResponse(job=await jobs.retry(job_id))
        except DepthControlJobServiceError as exc:
            _raise_job(exc)

    @router.post(
        "/shots/{shot_plan_id}",
        response_model=DepthControlCreateResponse,
        status_code=201,
    )
    async def create_control(
        shot_plan_id: Annotated[UUID, Path()],
        payload: DepthControlCreate,
    ) -> DepthControlCreateResponse:
        try:
            return await production.create_depth_control(shot_plan_id, payload)
        except ProductionServiceError as exc:
            _raise_production(exc)

    @router.patch(
        "/shots/{shot_plan_id}/{asset_id}",
        response_model=DepthControlUpdateResponse,
    )
    async def update_control(
        shot_plan_id: Annotated[UUID, Path()],
        asset_id: Annotated[UUID, Path()],
        payload: DepthControlUpdate,
    ) -> DepthControlUpdateResponse:
        try:
            return await production.update_depth_control(shot_plan_id, asset_id, payload)
        except ProductionServiceError as exc:
            _raise_production(exc)

    @router.delete(
        "/shots/{shot_plan_id}/{asset_id}",
        response_model=DepthControlDeleteResponse,
    )
    async def delete_control(
        shot_plan_id: Annotated[UUID, Path()],
        asset_id: Annotated[UUID, Path()],
        expected_revision_id: Annotated[UUID, Query()],
    ) -> DepthControlDeleteResponse:
        try:
            return await production.delete_depth_control(
                shot_plan_id,
                asset_id,
                expected_revision_id,
            )
        except ProductionServiceError as exc:
            _raise_production(exc)

    @router.get(
        "/shots/{shot_plan_id}/{asset_id}/content",
        response_class=FileResponse,
    )
    async def get_content(
        shot_plan_id: Annotated[UUID, Path()],
        asset_id: Annotated[UUID, Path()],
        thumbnail: Annotated[bool, Query()] = False,
        download: Annotated[bool, Query()] = False,
    ) -> FileResponse:
        try:
            detail = await production.get_shot(shot_plan_id)
        except ProductionServiceError as exc:
            _raise_production(exc)
        asset = next(
            (item for item in detail.plan.depth_control_assets if item.id == asset_id),
            None,
        )
        if asset is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "depth_control_not_found",
                    "message": "当前分镜中不存在该深度控制视频",
                },
            )
        try:
            path, media_type, filename = await service.resolve_content(
                asset,
                thumbnail=thumbnail,
            )
        except DepthControlServiceError as exc:
            _raise_depth(exc)
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename,
            content_disposition_type="attachment" if download else "inline",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    return router


async def _depth_settings_response(
    settings: DepthGenerationSettingsService,
    service: DepthControlService,
) -> DepthGenerationSettingsResponse:
    _, state = await settings.get_current()
    cpu_available, cpu_note = service.selector.cpu_available()
    gpu_available, gpu_note, gpu_profile = await service.selector.gpu_available()
    resolved_mode = None
    resolved_engine = None
    resolved_device_name = None
    selection_reason = ""
    try:
        profile = await service.selector.resolve(
            preference=state.execution_preference,
        )
        resolved_mode = (
            DepthExecutionPreference.GPU
            if profile.device.value == "cuda"
            else DepthExecutionPreference.CPU
        )
        resolved_engine = profile.engine_id
        resolved_device_name = profile.device_name
        selection_reason = profile.selection_reason
    except Exception as exc:
        selection_reason = str(exc)
    auto_available = cpu_available or gpu_available
    return DepthGenerationSettingsResponse(
        execution_preference=state.execution_preference,
        resolved_mode=resolved_mode,
        resolved_engine=resolved_engine,
        resolved_device_name=resolved_device_name,
        selection_reason=selection_reason,
        updated_at=state.updated_at,
        modes=[
            DepthExecutionModeStatus(
                mode=DepthExecutionPreference.AUTO,
                available=auto_available,
                note=(
                    "优先使用 NVIDIA CUDA；不可用时自动切换到 CPU ONNX。"
                    if auto_available
                    else f"GPU：{gpu_note}；CPU：{cpu_note}"
                ),
                engine=resolved_engine,
                device_name=resolved_device_name,
                installable=not cpu_available,
            ),
            DepthExecutionModeStatus(
                mode=DepthExecutionPreference.CPU,
                available=cpu_available,
                note=cpu_note,
                engine=service.cpu_engine.engine_id,
                device_name="CPU · ONNX Runtime",
                installable=not cpu_available,
            ),
            DepthExecutionModeStatus(
                mode=DepthExecutionPreference.GPU,
                available=gpu_available,
                note=gpu_note,
                engine=service.async_engine.engine_id,
                device_name=(gpu_profile.device_name if gpu_profile else None),
                installable=False,
            ),
        ],
    )


def create_depth_generation_settings_router(
    settings: DepthGenerationSettingsService,
    service: DepthControlService,
) -> APIRouter:
    router = APIRouter(
        prefix="/settings/depth-generation",
        tags=["depth-generation-settings"],
    )

    @router.get("", response_model=DepthGenerationSettingsResponse)
    async def get_settings() -> DepthGenerationSettingsResponse:
        return await _depth_settings_response(settings, service)

    @router.put("", response_model=DepthGenerationSettingsResponse)
    async def update_settings(
        payload: DepthGenerationSettingsUpdate,
    ) -> DepthGenerationSettingsResponse:
        if payload.execution_preference == DepthExecutionPreference.GPU:
            available, note, _ = await service.selector.gpu_available()
            if not available:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "depth_gpu_unavailable", "message": note},
                )
        await settings.update_current(payload.execution_preference)
        return await _depth_settings_response(settings, service)

    @router.post("/probe", response_model=DepthGenerationSettingsResponse)
    async def probe_settings() -> DepthGenerationSettingsResponse:
        return await _depth_settings_response(settings, service)

    return router
