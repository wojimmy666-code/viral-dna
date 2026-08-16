from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from viral_dna_api.models import PromptPackage

from .contracts import PromptCompileRequest, PromptCompileResponse, PromptDraftUpdateRequest
from .service import PromptDraftService, PromptDraftServiceError


def create_prompt_draft_router(service: PromptDraftService) -> APIRouter:
    router = APIRouter(tags=["prompt-drafts"])

    def http_error(exc: PromptDraftServiceError) -> HTTPException:
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        )

    @router.get(
        "/analyses/{analysis_id}/prompt-draft",
        response_model=PromptPackage,
    )
    async def get_prompt_draft(analysis_id: UUID) -> PromptPackage:
        try:
            return await service.get_package(analysis_id)
        except PromptDraftServiceError as exc:
            raise http_error(exc) from exc

    @router.patch(
        "/analyses/{analysis_id}/prompt-draft",
        response_model=PromptPackage,
    )
    async def update_prompt_draft(
        analysis_id: UUID,
        payload: PromptDraftUpdateRequest,
    ) -> PromptPackage:
        try:
            return await service.update_package(analysis_id, payload)
        except PromptDraftServiceError as exc:
            raise http_error(exc) from exc

    @router.post(
        "/analyses/{analysis_id}/prompt-draft/compile",
        response_model=PromptCompileResponse,
    )
    async def compile_prompt_draft(
        analysis_id: UUID,
        payload: PromptCompileRequest,
    ) -> PromptCompileResponse:
        try:
            await service.get_package(analysis_id)
            return service.compile(payload)
        except PromptDraftServiceError as exc:
            raise http_error(exc) from exc

    return router
