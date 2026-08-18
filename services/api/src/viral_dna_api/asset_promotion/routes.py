from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..asset_library import AssetLibraryError
from .contracts import (
    GeneratedArtifactBatchPromotionRequest,
    GeneratedArtifactBatchPromotionResponse,
    GeneratedArtifactPromotionRequest,
    GeneratedArtifactPromotionResponse,
    GeneratedArtifactPromotionStatus,
    GeneratedArtifactPromotionStatusRequest,
)
from .service import GeneratedAssetPromotionService


def create_generated_asset_promotion_router(
    service: GeneratedAssetPromotionService,
) -> APIRouter:
    router = APIRouter(tags=["generated-assets"])

    @router.post(
        "/assets/from-generated-artifact",
        response_model=GeneratedArtifactPromotionResponse,
    )
    async def promote_generated_artifact(
        payload: GeneratedArtifactPromotionRequest,
    ) -> GeneratedArtifactPromotionResponse:
        try:
            return await service.promote(payload)
        except AssetLibraryError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post(
        "/assets/from-generated-artifacts/batch",
        response_model=GeneratedArtifactBatchPromotionResponse,
    )
    async def promote_generated_artifacts_batch(
        payload: GeneratedArtifactBatchPromotionRequest,
    ) -> GeneratedArtifactBatchPromotionResponse:
        try:
            return await service.promote_batch(payload)
        except AssetLibraryError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post(
        "/assets/generated-artifact-status",
        response_model=GeneratedArtifactPromotionStatus,
    )
    async def generated_artifact_status(
        payload: GeneratedArtifactPromotionStatusRequest,
    ) -> GeneratedArtifactPromotionStatus:
        return await service.status(payload.kind, payload.source_entity_id)

    @router.get("/assets/{asset_id}/provenance")
    async def get_asset_provenance(asset_id: UUID):
        try:
            return await service.get_provenance(asset_id)
        except AssetLibraryError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return router
