from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from .continuity_service import ContinuityService, ContinuityServiceError
from .contracts import (
    ContinuityFindingDecisionRequest,
    ContinuityReport,
    ContinuityReportRunRequest,
)


def create_continuity_router(service: ContinuityService) -> APIRouter:
    router = APIRouter(tags=["continuity-quality"])

    @router.get(
        "/productions/{project_id}/continuity-reports",
        response_model=list[ContinuityReport],
    )
    async def list_continuity_reports(project_id: UUID) -> list[ContinuityReport]:
        try:
            return await service.list_reports(project_id)
        except ContinuityServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.get(
        "/productions/{project_id}/continuity-reports/latest",
        response_model=ContinuityReport | None,
    )
    async def get_latest_continuity_report(
        project_id: UUID,
    ) -> ContinuityReport | None:
        try:
            return await service.latest_report(project_id)
        except ContinuityServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post(
        "/productions/{project_id}/continuity-reports",
        response_model=ContinuityReport,
    )
    async def run_continuity_report(
        project_id: UUID,
        payload: ContinuityReportRunRequest,
    ) -> ContinuityReport:
        try:
            return await service.run_report(project_id, payload)
        except ContinuityServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post(
        "/productions/{project_id}/continuity-reports/{report_id}/findings/{finding_key}/decision",
        response_model=ContinuityReport,
    )
    async def decide_continuity_finding(
        project_id: UUID,
        report_id: UUID,
        finding_key: str,
        payload: ContinuityFindingDecisionRequest,
    ) -> ContinuityReport:
        try:
            return await service.decide_finding(
                project_id,
                report_id,
                finding_key,
                payload,
            )
        except ContinuityServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return router
