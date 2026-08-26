from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, status
from fastapi.responses import FileResponse

from .domain import VideoEnhancementJobStatus
from .engine import VideoEnhancementCapability
from .models import (
    VideoEnhancementActivateRequest,
    VideoEnhancementCapabilityResponse,
    VideoEnhancementInstallationResponse,
    VideoEnhancementJobCreate,
    VideoEnhancementJobListResponse,
    VideoEnhancementJobResponse,
    VideoEnhancementSettingsResponse,
    VideoEnhancementSettingsUpdate,
    VideoEnhancementSourceResponse,
    VideoEnhancementVersionSelectionResponse,
)
from .service import (
    VideoEnhancementInstallation,
    VideoEnhancementService,
    VideoEnhancementServiceError,
)
from .settings import VideoEnhancementSettingsService


def _raise_service(exc: VideoEnhancementServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _capability_response(
    capability: VideoEnhancementCapability,
) -> VideoEnhancementCapabilityResponse:
    return VideoEnhancementCapabilityResponse(
        engine=capability.engine,
        version=capability.version,
        model=capability.model,
        available=capability.available,
        availability_note=capability.availability_note,
        repository_url=capability.repository_url,
        installation_path=str(capability.installation_path),
        executable_path=(
            str(capability.executable_path) if capability.executable_path is not None else None
        ),
        execution_device=capability.execution_device,
        license=capability.license,
        installable=capability.installable,
    )


def _installation_response(
    installation: VideoEnhancementInstallation,
) -> VideoEnhancementInstallationResponse:
    return VideoEnhancementInstallationResponse(
        id=installation.id,
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


def _job_response(job) -> VideoEnhancementJobResponse:
    return VideoEnhancementJobResponse(
        job=job,
        content_url=(
            f"/api/v1/video-enhancements/jobs/{job.id}/content"
            if job.status == VideoEnhancementJobStatus.SUCCEEDED and job.result_relative_path
            else None
        ),
        original_content_url=(
            f"/api/v1/generation-candidates/{job.candidate_id}/content?variant=original"
        ),
    )


async def _settings_response(
    settings: VideoEnhancementSettingsService,
    service: VideoEnhancementService,
) -> VideoEnhancementSettingsResponse:
    _, state = await settings.get_current()
    return VideoEnhancementSettingsResponse(
        **state.model_dump(mode="python"),
        capability=_capability_response(service.capability()),
    )


def create_video_enhancement_router(
    service: VideoEnhancementService,
    settings: VideoEnhancementSettingsService,
) -> APIRouter:
    router = APIRouter(tags=["video-enhancement"])

    @router.get(
        "/settings/video-enhancement",
        response_model=VideoEnhancementSettingsResponse,
    )
    async def get_settings() -> VideoEnhancementSettingsResponse:
        return await _settings_response(settings, service)

    @router.put(
        "/settings/video-enhancement",
        response_model=VideoEnhancementSettingsResponse,
    )
    async def update_settings(
        payload: VideoEnhancementSettingsUpdate,
    ) -> VideoEnhancementSettingsResponse:
        await settings.update_current(payload.default_target)
        return await _settings_response(settings, service)

    @router.post(
        "/settings/video-enhancement/probe",
        response_model=VideoEnhancementSettingsResponse,
    )
    async def probe_settings() -> VideoEnhancementSettingsResponse:
        return await _settings_response(settings, service)

    @router.post(
        "/video-enhancements/engine/installations",
        response_model=VideoEnhancementInstallationResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def install_engine() -> VideoEnhancementInstallationResponse:
        return _installation_response(await service.start_installation())

    @router.get(
        "/video-enhancements/engine/installations/{installation_id}",
        response_model=VideoEnhancementInstallationResponse,
    )
    async def get_installation(
        installation_id: Annotated[UUID, Path()],
    ) -> VideoEnhancementInstallationResponse:
        try:
            return _installation_response(service.installation(installation_id))
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)

    @router.post(
        "/video-enhancements/candidates/{candidate_id}/jobs",
        response_model=VideoEnhancementJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_job(
        candidate_id: Annotated[UUID, Path()],
        payload: VideoEnhancementJobCreate,
    ) -> VideoEnhancementJobResponse:
        try:
            return _job_response(
                await service.submit(
                    candidate_id,
                    expected_revision_id=payload.expected_revision_id,
                    target=payload.target,
                )
            )
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)

    @router.get(
        "/video-enhancements/candidates/{candidate_id}/jobs",
        response_model=VideoEnhancementJobListResponse,
    )
    async def list_jobs(
        candidate_id: Annotated[UUID, Path()],
    ) -> VideoEnhancementJobListResponse:
        source_response = None
        try:
            source = await service.source_info(candidate_id)
            source_response = VideoEnhancementSourceResponse(
                width=source.width,
                height=source.height,
                fps=source.fps,
                duration_seconds=source.duration_seconds,
                frame_count=source.frame_count,
            )
        except VideoEnhancementServiceError:
            pass
        return VideoEnhancementJobListResponse(
            items=[_job_response(item) for item in await service.list_for_candidate(candidate_id)],
            source=source_response,
        )

    @router.get(
        "/video-enhancements/jobs/{job_id}",
        response_model=VideoEnhancementJobResponse,
    )
    async def get_job(
        job_id: Annotated[UUID, Path()],
    ) -> VideoEnhancementJobResponse:
        try:
            return _job_response(await service.get(job_id))
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)

    @router.post(
        "/video-enhancements/jobs/{job_id}/cancel",
        response_model=VideoEnhancementJobResponse,
    )
    async def cancel_job(
        job_id: Annotated[UUID, Path()],
    ) -> VideoEnhancementJobResponse:
        try:
            return _job_response(await service.cancel(job_id))
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)

    @router.post(
        "/video-enhancements/jobs/{job_id}/retry",
        response_model=VideoEnhancementJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_job(
        job_id: Annotated[UUID, Path()],
    ) -> VideoEnhancementJobResponse:
        try:
            return _job_response(await service.retry(job_id))
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)

    @router.post(
        "/video-enhancements/jobs/{job_id}/use-for-final",
        response_model=VideoEnhancementVersionSelectionResponse,
    )
    async def use_for_final(
        job_id: Annotated[UUID, Path()],
        payload: VideoEnhancementActivateRequest,
    ) -> VideoEnhancementVersionSelectionResponse:
        try:
            job = await service.get(job_id)
            candidate = await service.activate(
                job_id,
                expected_revision_id=payload.expected_revision_id,
            )
            return VideoEnhancementVersionSelectionResponse(
                candidate_id=candidate.id,
                active_job_id=job.id,
                active_target=job.target,
                content_url=f"/api/v1/generation-candidates/{candidate.id}/content",
            )
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)

    @router.post(
        "/video-enhancements/candidates/{candidate_id}/use-original",
        response_model=VideoEnhancementVersionSelectionResponse,
    )
    async def use_original(
        candidate_id: Annotated[UUID, Path()],
        payload: VideoEnhancementActivateRequest,
    ) -> VideoEnhancementVersionSelectionResponse:
        try:
            candidate = await service.use_original(
                candidate_id,
                expected_revision_id=payload.expected_revision_id,
            )
            return VideoEnhancementVersionSelectionResponse(
                candidate_id=candidate.id,
                content_url=f"/api/v1/generation-candidates/{candidate.id}/content",
            )
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)

    @router.get(
        "/video-enhancements/jobs/{job_id}/content",
        response_class=FileResponse,
    )
    async def get_result_content(
        job_id: Annotated[UUID, Path()],
    ) -> FileResponse:
        try:
            path, media_type = await service.resolve_result_content(job_id)
        except VideoEnhancementServiceError as exc:
            _raise_service(exc)
        return FileResponse(
            path,
            media_type=media_type,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    return router
