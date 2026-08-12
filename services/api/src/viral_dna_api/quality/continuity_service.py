from __future__ import annotations

from typing import Protocol
from uuid import UUID

from viral_dna_api.models import (
    GenerationCandidate,
    GenerationRun,
    ProductionProject,
    ReferenceBinding,
    ShotLifecycleStatus,
    ShotPlan,
)

from .continuity import (
    build_continuity_snapshot,
    evaluate_continuity,
    stale_continuity_report,
    update_finding_decision,
)
from .contracts import (
    ContinuityDecision,
    ContinuityFindingDecisionRequest,
    ContinuityFindingState,
    ContinuityReport,
    ContinuityReportRunRequest,
    ContinuityReportStatus,
)


class ContinuityRepository(Protocol):
    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None: ...

    async def list_shot_plans(self, project_id: UUID) -> list[ShotPlan]: ...

    async def list_reference_bindings(
        self,
        shot_plan_id: UUID,
    ) -> list[ReferenceBinding]: ...

    async def get_generation_candidate(
        self,
        candidate_id: UUID,
    ) -> GenerationCandidate | None: ...

    async def get_generation_run(
        self,
        run_id: UUID,
    ) -> GenerationRun | None: ...

    async def save_continuity_report(
        self,
        report: ContinuityReport,
    ) -> ContinuityReport: ...

    async def get_continuity_report(
        self,
        report_id: UUID,
    ) -> ContinuityReport | None: ...

    async def list_continuity_reports(
        self,
        project_id: UUID,
    ) -> list[ContinuityReport]: ...


class ContinuityServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ContinuityService:
    def __init__(self, repository: ContinuityRepository) -> None:
        self.repository = repository

    async def _project(self, project_id: UUID) -> ProductionProject:
        project = await self.repository.get_production_project(project_id)
        if project is None:
            raise ContinuityServiceError(404, "production_not_found", "创作方案不存在")
        return project

    @staticmethod
    def _require_revision(project: ProductionProject, expected_revision_id: UUID) -> None:
        if project.current_revision_id != expected_revision_id:
            raise ContinuityServiceError(
                409,
                "production_revision_conflict",
                "创作方案已更新，请刷新后重新执行连续性质检",
            )

    async def list_reports(self, project_id: UUID) -> list[ContinuityReport]:
        await self._project(project_id)
        return await self.repository.list_continuity_reports(project_id)

    async def latest_report(self, project_id: UUID) -> ContinuityReport | None:
        reports = await self.list_reports(project_id)
        return max(reports, key=lambda item: item.created_at, default=None)

    async def run_report(
        self,
        project_id: UUID,
        payload: ContinuityReportRunRequest,
    ) -> ContinuityReport:
        project = await self._project(project_id)
        self._require_revision(project, payload.expected_revision_id)
        plans = [
            item
            for item in await self.repository.list_shot_plans(project_id)
            if item.lifecycle_status == ShotLifecycleStatus.ACTIVE and item.required
        ]
        snapshots = []
        for plan in sorted(plans, key=lambda item: item.index):
            bindings = await self.repository.list_reference_bindings(plan.id)
            candidate = (
                await self.repository.get_generation_candidate(plan.approved_video_candidate_id)
                if plan.approved_video_candidate_id is not None
                else None
            )
            run = (
                await self.repository.get_generation_run(candidate.generation_run_id)
                if candidate is not None
                else None
            )
            snapshots.append(build_continuity_snapshot(plan, bindings, candidate, run))
        previous = await self.latest_report(project_id)
        report = evaluate_continuity(
            project_id=project.id,
            revision_id=project.current_revision_id,
            snapshots=snapshots,
            previous_report=previous,
        )
        if (
            previous is not None
            and previous.status == ContinuityReportStatus.COMPLETED
            and previous.input_fingerprint == report.input_fingerprint
        ):
            return previous
        return await self.repository.save_continuity_report(report)

    async def ensure_current_report(self, project_id: UUID) -> ContinuityReport:
        project = await self._project(project_id)
        latest = await self.latest_report(project_id)
        if (
            latest is not None
            and latest.status == ContinuityReportStatus.COMPLETED
            and latest.revision_id == project.current_revision_id
        ):
            return latest
        return await self.run_report(
            project_id,
            ContinuityReportRunRequest(
                expected_revision_id=project.current_revision_id,
            ),
        )

    async def invalidate_for_shot(
        self,
        project_id: UUID,
        shot_plan_id: UUID,
        invalidated_by_revision_id: UUID,
    ) -> ContinuityReport | None:
        latest = await self.latest_report(project_id)
        if latest is None:
            return None
        stale = stale_continuity_report(
            latest,
            shot_plan_id=shot_plan_id,
            invalidated_by_revision_id=invalidated_by_revision_id,
        )
        if stale == latest:
            return latest
        return await self.repository.save_continuity_report(stale)

    async def decide_finding(
        self,
        project_id: UUID,
        report_id: UUID,
        finding_key: str,
        payload: ContinuityFindingDecisionRequest,
    ) -> ContinuityReport:
        project = await self._project(project_id)
        self._require_revision(project, payload.expected_revision_id)
        report = await self.repository.get_continuity_report(report_id)
        if report is None or report.project_id != project_id:
            raise ContinuityServiceError(
                404,
                "continuity_report_not_found",
                "连续性质检报告不存在",
            )
        state = {
            ContinuityDecision.RESOLVE: ContinuityFindingState.RESOLVED,
            ContinuityDecision.WAIVE: ContinuityFindingState.WAIVED,
            ContinuityDecision.REOPEN: ContinuityFindingState.OPEN,
        }[payload.decision]
        try:
            updated = update_finding_decision(
                report,
                finding_key=finding_key,
                state=state,
                reason=(payload.reason.strip() if payload.reason else None),
            )
        except KeyError as exc:
            raise ContinuityServiceError(
                404,
                "continuity_finding_not_found",
                "连续性问题不存在",
            ) from exc
        return await self.repository.save_continuity_report(updated)
