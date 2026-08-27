from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..models import ShotVideoGenerationDraft
from ..workspace_catalog import AccountContextService
from .contracts import (
    VideoIntentCompileRequest,
    VideoIntentCompileResponse,
    VideoIntentRestoreRequest,
)
from .service import VideoIntentCompilationError, VideoIntentCompilationService


def create_video_intent_router(
    service: VideoIntentCompilationService,
    account_context: AccountContextService,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/production-shots/{shot_plan_id}/video-generation-draft/compile-intent",
        response_model=VideoIntentCompileResponse,
    )
    async def compile_video_intent(
        shot_plan_id: UUID,
        payload: VideoIntentCompileRequest,
    ) -> VideoIntentCompileResponse:
        try:
            context = await account_context.ensure_current()
            return await service.compile(
                shot_plan_id,
                payload,
                actor_account_id=context.account.id,
            )
        except VideoIntentCompilationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post(
        "/production-shots/{shot_plan_id}/video-generation-draft/restore-intent-baseline",
        response_model=ShotVideoGenerationDraft,
    )
    async def restore_video_intent_baseline(
        shot_plan_id: UUID,
        payload: VideoIntentRestoreRequest,
    ) -> ShotVideoGenerationDraft:
        try:
            context = await account_context.ensure_current()
            return await service.restore(
                shot_plan_id,
                payload,
                actor_account_id=context.account.id,
            )
        except VideoIntentCompilationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return router
