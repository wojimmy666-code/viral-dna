from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from .contracts import (
    ViralConceptGenerateRequest,
    ViralConceptPublishRequest,
    ViralConceptPublishResult,
    ViralConceptSet,
    ViralInsightReport,
)
from .service import ViralInsightService, ViralInsightServiceError


def create_viral_insight_router(service: ViralInsightService) -> APIRouter:
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
            return await service.latest_concepts(analysis_id, category_profile_id)
        except ViralInsightServiceError as exc:
            raise http_error(exc) from exc

    @router.post(
        "/analyses/{analysis_id}/viral-concepts",
        response_model=ViralConceptSet,
        status_code=status.HTTP_201_CREATED,
    )
    async def generate_viral_concepts(
        analysis_id: UUID,
        payload: ViralConceptGenerateRequest,
    ) -> ViralConceptSet:
        try:
            return await service.generate_concepts(analysis_id, payload)
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
            return await service.publish_concept(concept_set_id, concept_id, payload)
        except ViralInsightServiceError as exc:
            raise http_error(exc) from exc

    return router
