from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from .contracts import (
    CreativeActionRequest,
    CreativeGenerateRequest,
    CreativeIdeaEdit,
    CreativePlanEdit,
    ViralConceptGenerateRequest,
    ViralConceptPublishRequest,
    ViralConceptPublishResult,
    ViralConceptSet,
    ViralInsightReport,
)
from .creative_errors import present_batch_error
from .creative_idea_edit import edit_idea
from .service import ViralInsightService, ViralInsightServiceError
from .production_style import ProductionStyleUpdate, production_style


def create_viral_insight_router(service: ViralInsightService, creative=None) -> APIRouter:
    router = APIRouter(tags=["viral-insights"])

    def http_error(exc: ViralInsightServiceError) -> HTTPException:
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        )

    @router.get(
        "/analyses/{analysis_id}/viral-insight",
        response_model=ViralInsightReport,
    )
    async def get_viral_insight(analysis_id: UUID) -> ViralInsightReport:
        try:
            return await service.get_insight(analysis_id)
        except ViralInsightServiceError as exc:
            raise http_error(exc) from exc

    @router.get(
        "/analyses/{analysis_id}/viral-concepts/latest",
        response_model=ViralConceptSet | None,
    )
    async def latest_viral_concepts(
        analysis_id: UUID,
        category_profile_id: Annotated[UUID | None, Query()] = None,
    ) -> ViralConceptSet | None:
        try:
            item = await service.latest_concepts(analysis_id, category_profile_id)
            return present_batch_error(item) if item is not None else None
        except ViralInsightServiceError as exc:
            raise http_error(exc) from exc

    @router.post(
        "/analyses/{analysis_id}/viral-concepts",
        response_model=ViralConceptSet,
        status_code=status.HTTP_202_ACCEPTED if creative is not None else status.HTTP_201_CREATED,
    )
    async def generate_viral_concepts(
        analysis_id: UUID,
        payload: CreativeGenerateRequest | ViralConceptGenerateRequest,
    ) -> ViralConceptSet:
        try:
            if creative is not None:
                if not isinstance(payload, CreativeGenerateRequest):
                    raise ViralInsightServiceError(
                        422, "creative_request_required", "请刷新页面，使用先生成创意再展开的流程"
                    )
                return await creative.generate(analysis_id, payload)
            return await service.generate_concepts(analysis_id, payload)
        except ViralInsightServiceError as exc:
            raise http_error(exc) from exc

    if creative is not None:

        @router.get("/viral-concept-sets/{concept_set_id}/production-style")
        async def read_production_style(concept_set_id: UUID):
            from ..production import ProductionServiceError
            try:
                return await production_style(creative, concept_set_id)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc
            except ProductionServiceError as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc

        @router.put("/viral-concept-sets/{concept_set_id}/production-style")
        async def update_production_style(concept_set_id: UUID, payload: ProductionStyleUpdate):
            from ..production import ProductionServiceError
            try:
                return await production_style(creative, concept_set_id, payload)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc
            except ProductionServiceError as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, "制作风格版本无效，请重新读取") from exc

        @router.get(
            "/analyses/{analysis_id}/viral-concepts/history", response_model=list[ViralConceptSet]
        )
        async def history(analysis_id: UUID, category_profile_id: UUID | None = None):
            try:
                return await creative.history(analysis_id, category_profile_id)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc

        @router.get("/viral-concept-sets/{concept_set_id}", response_model=ViralConceptSet)
        async def get_batch(concept_set_id: UUID):
            try:
                return await creative.get(concept_set_id)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc

        @router.post(
            "/viral-concept-sets/{concept_set_id}/ideas/{idea_id}/regenerate",
            response_model=ViralConceptSet,
            status_code=202,
        )
        async def regenerate(concept_set_id: UUID, idea_id: UUID, payload: CreativeActionRequest):
            try:
                return await creative.act(concept_set_id, idea_id, payload, expand=False)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc

        @router.post(
            "/viral-concept-sets/{concept_set_id}/ideas/{idea_id}/edit",
            response_model=ViralConceptSet,
        )
        async def revise_idea(concept_set_id: UUID, idea_id: UUID, payload: CreativeIdeaEdit):
            try:
                return await edit_idea(creative, concept_set_id, idea_id, payload)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc

        @router.post(
            "/viral-concept-sets/{concept_set_id}/ideas/{idea_id}/expand",
            response_model=ViralConceptSet,
            status_code=202,
        )
        async def expand(concept_set_id: UUID, idea_id: UUID, payload: CreativeActionRequest):
            try:
                return await creative.act(concept_set_id, idea_id, payload, expand=True)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc

        @router.post("/viral-concept-sets/{concept_set_id}/cancel", response_model=ViralConceptSet)
        async def cancel(concept_set_id: UUID):
            try:
                return await creative.cancel(concept_set_id)
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc

        @router.post("/viral-concept-sets/{concept_set_id}/edit", response_model=ViralConceptSet)
        async def edit(concept_set_id: UUID, payload: CreativePlanEdit):
            try:
                return await creative.edit(concept_set_id, payload)
            except ValueError as exc:
                raise HTTPException(422, detail={"message": "分镜编号或来源引用无效"}) from exc
            except ViralInsightServiceError as exc:
                raise http_error(exc) from exc

    @router.post(
        "/viral-concept-sets/{concept_set_id}/concepts/{concept_id}/publish",
        response_model=ViralConceptPublishResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def publish_viral_concept(
        concept_set_id: UUID,
        concept_id: UUID,
        payload: ViralConceptPublishRequest,
    ) -> ViralConceptPublishResult:
        try:
            if creative is not None:
                async with creative.lock(concept_set_id):
                    return await service.publish_concept(concept_set_id, concept_id, payload)
            return await service.publish_concept(concept_set_id, concept_id, payload)
        except ViralInsightServiceError as exc:
            raise http_error(exc) from exc

    return router
