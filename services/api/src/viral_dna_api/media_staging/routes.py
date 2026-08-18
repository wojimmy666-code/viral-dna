from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .domain import (
    MediaStagingSettingsResponse,
    MediaStagingSettingsUpdate,
    MediaStagingValidationResponse,
)
from .service import MediaStagingError, MediaStagingService


def create_media_staging_router(
    service: MediaStagingService,
    *,
    prefix: str = "/settings/media-staging",
    dependencies: list[Any] | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=prefix,
        tags=["media-staging"],
        dependencies=dependencies or [],
    )

    @router.get("", response_model=MediaStagingSettingsResponse)
    async def get_settings() -> MediaStagingSettingsResponse:
        return await service.settings()

    @router.put("", response_model=MediaStagingSettingsResponse)
    async def update_settings(
        payload: MediaStagingSettingsUpdate,
    ) -> MediaStagingSettingsResponse:
        try:
            return await service.update_settings(payload)
        except MediaStagingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post("/validate", response_model=MediaStagingValidationResponse)
    async def validate_settings() -> MediaStagingValidationResponse:
        try:
            return await service.validate()
        except MediaStagingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return router
