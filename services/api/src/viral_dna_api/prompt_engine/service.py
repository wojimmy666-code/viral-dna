from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from viral_dna_api.models import AnalysisReport, PromptPackage, PromptShot

from .compiler import compile_prompt_draft, draft_from_shot
from .contracts import (
    PromptCompileRequest,
    PromptCompileResponse,
    PromptDraftUpdateRequest,
    PromptShotDraft,
)
from .language_policy import (
    find_prompt_draft_language_issues,
    normalize_prompt_draft,
    summarize_language_issues,
)


class PromptDraftRepository(Protocol):
    async def get_report_by_analysis(self, analysis_id: UUID) -> AnalysisReport | None: ...

    async def save_report(self, report: AnalysisReport) -> AnalysisReport: ...


class PromptDraftServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _initial_revision_id(package_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"viral-dna:prompt-package:{package_id}:draft-v2")


class PromptDraftService:
    def __init__(self, repository: PromptDraftRepository) -> None:
        self.repository = repository

    async def _report(self, analysis_id: UUID) -> AnalysisReport:
        report = await self.repository.get_report_by_analysis(analysis_id)
        if report is None:
            raise PromptDraftServiceError(
                404,
                "analysis_report_not_found",
                "分析报告不存在，请先完成视频分析",
            )
        return report

    @staticmethod
    def _hydrate(report: AnalysisReport) -> PromptPackage:
        package = report.prompt_package.model_copy(deep=True)
        source_by_id = {shot.id: shot for shot in report.shots}
        hydrated_shots: list[PromptShot] = []
        for prompt_shot in package.shots:
            source = source_by_id.get(prompt_shot.shot_id)
            draft = prompt_shot.draft
            if draft is None and source is not None:
                draft = draft_from_shot(
                    source,
                    negative_constraints=prompt_shot.negative_constraints,
                )
            if draft is None:
                hydrated_shots.append(prompt_shot)
                continue
            draft = normalize_prompt_draft(draft)
            source_draft = prompt_shot.source_draft or draft.model_copy(deep=True)
            source_draft = normalize_prompt_draft(source_draft)
            language_issues = find_prompt_draft_language_issues(draft)
            compiled = compile_prompt_draft(draft, package.target_model)
            hydrated_shots.append(
                prompt_shot.model_copy(
                    update={
                        "draft": draft,
                        "source_draft": source_draft,
                        "prompt": compiled or prompt_shot.prompt,
                        "language_issues": [issue.field for issue in language_issues],
                    }
                )
            )
        return package.model_copy(
            update={
                "shots": hydrated_shots,
                "revision_id": package.revision_id or _initial_revision_id(package.id),
                "revision_number": max(1, package.revision_number),
                "updated_at": package.updated_at or package.created_at,
            }
        )

    @staticmethod
    def _validate_draft(shot_id: str, draft: PromptShotDraft, report: AnalysisReport) -> None:
        source = next((item for item in report.shots if item.id == shot_id), None)
        if source is None:
            raise PromptDraftServiceError(404, "prompt_shot_not_found", "分镜不存在")
        lower = float(source.start_seconds) - 0.05
        upper = float(source.end_seconds) + 0.05
        invalid = [
            phase
            for phase in draft.phases
            if phase.start_seconds < lower or phase.end_seconds > upper
        ]
        if invalid:
            raise PromptDraftServiceError(
                422,
                "prompt_phase_out_of_bounds",
                "时间轴阶段必须位于当前分镜的时间范围内",
            )

    async def get_package(self, analysis_id: UUID) -> PromptPackage:
        report = await self._report(analysis_id)
        return self._hydrate(report)

    async def update_package(
        self,
        analysis_id: UUID,
        payload: PromptDraftUpdateRequest,
    ) -> PromptPackage:
        report = await self._report(analysis_id)
        package = self._hydrate(report)
        if package.revision_id != payload.expected_revision_id:
            raise PromptDraftServiceError(
                409,
                "prompt_revision_conflict",
                "提示词已在其他窗口更新，请刷新后重试",
            )

        updates = {
            item.shot_id: normalize_prompt_draft(item.draft)
            for item in payload.shots
        }
        known_ids = {item.shot_id for item in package.shots}
        unknown = [shot_id for shot_id in updates if shot_id not in known_ids]
        if unknown:
            raise PromptDraftServiceError(404, "prompt_shot_not_found", "分镜不存在")
        for shot_id, draft in updates.items():
            self._validate_draft(shot_id, draft, report)
            language_issues = find_prompt_draft_language_issues(draft)
            if language_issues:
                raise PromptDraftServiceError(
                    422,
                    "prompt_language_invalid",
                    summarize_language_issues(language_issues),
                )

        next_prompt_shots: list[PromptShot] = []
        compiled_by_id: dict[str, str] = {}
        for prompt_shot in package.shots:
            draft = updates.get(prompt_shot.shot_id, prompt_shot.draft)
            if draft is None:
                next_prompt_shots.append(prompt_shot)
                continue
            compiled = compile_prompt_draft(draft, package.target_model)
            compiled_by_id[prompt_shot.shot_id] = compiled
            next_prompt_shots.append(
                prompt_shot.model_copy(
                    update={
                        "draft": draft,
                        "prompt": compiled,
                        "language_issues": [],
                    }
                )
            )

        now = datetime.now(UTC)
        next_package = package.model_copy(
            update={
                "shots": next_prompt_shots,
                "revision_id": uuid4(),
                "revision_number": package.revision_number + 1,
                "updated_at": now,
            }
        )
        next_report_shots = [
            shot.model_copy(update={"prompt": compiled_by_id[shot.id]})
            if shot.id in compiled_by_id
            else shot
            for shot in report.shots
        ]
        next_report = report.model_copy(
            update={"prompt_package": next_package, "shots": next_report_shots}
        )
        saved = await self.repository.save_report(next_report)
        return saved.prompt_package

    @staticmethod
    def compile(payload: PromptCompileRequest) -> PromptCompileResponse:
        draft = normalize_prompt_draft(payload.draft)
        language_issues = find_prompt_draft_language_issues(draft)
        if language_issues:
            raise PromptDraftServiceError(
                422,
                "prompt_language_invalid",
                summarize_language_issues(language_issues),
            )
        compiled = compile_prompt_draft(draft, payload.target_model)
        warnings: list[str] = []
        if len(compiled) > 4000:
            warnings.append("提示词超过 4000 字，部分视频模型可能截断输入")
        return PromptCompileResponse(
            target_model=payload.target_model,
            compiled_prompt=compiled,
            character_count=len(compiled),
            warnings=warnings,
        )
