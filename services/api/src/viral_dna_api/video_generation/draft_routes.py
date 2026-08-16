from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..models import ShotVideoGenerationDraft, ShotVideoGenerationDraftUpdate
from ..workspace_catalog import AccountContextService
from .drafts import ShotVideoGenerationDraftError, ShotVideoGenerationDraftService


def create_video_generation_draft_router(
    service: ShotVideoGenerationDraftService,
    account_context: AccountContextService,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/production-shots/{shot_plan_id}/video-generation-draft",
        response_model=ShotVideoGenerationDraft,
    )
    async def get_video_generation_draft(
        shot_plan_id: UUID,
    ) -> ShotVideoGenerationDraft:
        try:
            return await service.get(shot_plan_id)
        except ShotVideoGenerationDraftError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.patch(
        "/production-shots/{shot_plan_id}/video-generation-draft",
        response_model=ShotVideoGenerationDraft,
    )
    async def update_video_generation_draft(
        shot_plan_id: UUID,
        payload: ShotVideoGenerationDraftUpdate,
    ) -> ShotVideoGenerationDraft:
        try:
            context = await account_context.ensure_current()
            return await service.update(
                shot_plan_id,
                payload,
                actor_account_id=context.account.id,
            )
        except ShotVideoGenerationDraftError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return router
