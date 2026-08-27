from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from ..models import (
    GenerationKind,
    GenerationRun,
    ShotPlan,
    ShotVideoGenerationDraft,
    ShotVideoGenerationDraftUpdate,
    VideoGenerationInputPlan,
    VideoGenerationInputSource,
    VideoGenerationReference,
    VideoIntentState,
    VideoIntentStatus,
    VideoPromptReferenceKind,
    VideoPromptReferenceRole,
    VideoReferenceOrigin,
    VideoReferenceScope,
    VideoReferenceScopeKind,
)
from .settings import VideoGenerationSettingsService


class ShotVideoGenerationDraftRepository(Protocol):
    async def get_shot_plan(self, shot_plan_id: UUID) -> ShotPlan | None: ...

    async def list_generation_runs(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[GenerationRun]: ...

    async def get_video_generation_draft(
        self,
        shot_plan_id: UUID,
    ) -> ShotVideoGenerationDraft | None: ...

    async def compare_and_swap_video_generation_draft(
        self,
        draft: ShotVideoGenerationDraft,
        expected_draft_version: int,
    ) -> bool: ...


class ShotVideoGenerationDraftError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _fail(status_code: int, code: str, message: str) -> ShotVideoGenerationDraftError:
    return ShotVideoGenerationDraftError(status_code, code, message)


def _now() -> datetime:
    return datetime.now(UTC)


def _bounded_duration(value: object, fallback: float) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        duration = fallback
    return round(min(60.0, max(0.1, duration)), 3)


def _bounded_candidate_count(value: object) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 1
    return min(4, max(1, count))


class ShotVideoGenerationDraftService:
    """Persists non-revisioned video generation choices per production shot."""

    def __init__(
        self,
        repository: ShotVideoGenerationDraftRepository,
        settings: VideoGenerationSettingsService,
    ) -> None:
        self.repository = repository
        self.settings = settings

    async def get(self, shot_plan_id: UUID) -> ShotVideoGenerationDraft:
        plan = await self.repository.get_shot_plan(shot_plan_id)
        if plan is None:
            raise _fail(404, "shot_not_found", "分镜不存在")
        existing = await self.repository.get_video_generation_draft(shot_plan_id)
        if existing is not None:
            return existing

        draft = await self._initial_draft(plan)
        created = await self.repository.compare_and_swap_video_generation_draft(
            draft,
            expected_draft_version=0,
        )
        if created:
            return draft
        concurrent = await self.repository.get_video_generation_draft(shot_plan_id)
        if concurrent is None:
            raise _fail(500, "video_draft_create_failed", "无法初始化视频生成设置")
        return concurrent

    async def update(
        self,
        shot_plan_id: UUID,
        payload: ShotVideoGenerationDraftUpdate,
        *,
        actor_account_id: UUID | None,
    ) -> ShotVideoGenerationDraft:
        current = await self.get(shot_plan_id)
        if current.draft_version != payload.expected_draft_version:
            raise _fail(
                409,
                "video_draft_conflict",
                "视频生成设置已在其他操作中更新，请保留当前选择并重试",
            )
        now = _now()
        intent = current.intent
        intent_text = (
            payload.intent_text if payload.intent_text is not None else current.intent.text
        )
        intent_mentions = (
            payload.intent_mentions
            if payload.intent_mentions is not None
            else current.intent.mentions
        )
        if intent_text != current.intent.text or intent_mentions != current.intent.mentions:
            intent = current.intent.model_copy(
                update={
                    "text": intent_text,
                    "mentions": intent_mentions,
                    "status": (
                        VideoIntentStatus.STALE
                        if current.intent.interpretation is not None
                        else VideoIntentStatus.EMPTY
                    ),
                }
            )
        updated = current.model_copy(
            update={
                "schema_version": "viral-dna-shot-video-draft/v2",
                "model_alias": payload.model_alias,
                "resolution": payload.resolution.upper(),
                "duration_seconds": round(payload.duration_seconds, 3),
                "candidate_count": payload.candidate_count,
                "input_plan": payload.input_plan,
                "video_prompt": payload.video_prompt,
                "video_prompt_mentions": payload.video_prompt_mentions,
                "video_negative_constraints": payload.video_negative_constraints,
                "intent": intent,
                "locked_reference_keys": payload.locked_reference_keys,
                "removed_intent_reference_keys": payload.removed_intent_reference_keys,
                "prompt_manually_modified": payload.prompt_manually_modified,
                "reference_sync_mode": payload.reference_sync_mode,
                "auto_reference_exclusions": payload.auto_reference_exclusions,
                "reference_order_override": payload.reference_order_override,
                "draft_version": current.draft_version + 1,
                "origin": "user",
                "updated_by_account_id": actor_account_id,
                "updated_at": now,
            }
        )
        saved = await self.repository.compare_and_swap_video_generation_draft(
            updated,
            expected_draft_version=current.draft_version,
        )
        if not saved:
            raise _fail(
                409,
                "video_draft_conflict",
                "视频生成设置已在其他操作中更新，请保留当前选择并重试",
            )
        return updated

    async def _initial_draft(self, plan: ShotPlan) -> ShotVideoGenerationDraft:
        runs = await self.repository.list_generation_runs(plan.project_id, plan.id)
        latest_run = next(
            (run for run in reversed(runs) if run.kind == GenerationKind.VIDEO and run.model_alias),
            None,
        )
        settings = self.settings.get()
        now = _now()
        if latest_run is not None:
            request = latest_run.request_payload or {}
            return ShotVideoGenerationDraft(
                project_id=plan.project_id,
                shot_plan_id=plan.id,
                model_alias=latest_run.model_alias or settings.default_model_alias,
                resolution=str(request.get("resolution") or settings.default_resolution).upper(),
                duration_seconds=_bounded_duration(
                    request.get("duration_seconds"),
                    plan.duration_seconds,
                ),
                candidate_count=_bounded_candidate_count(request.get("candidate_count")),
                input_plan=request.get("input_plan") or legacy_video_input_plan(),
                video_prompt=plan.video_prompt,
                video_prompt_mentions=plan.video_prompt_mentions,
                video_negative_constraints=plan.video_negative_constraints,
                intent=VideoIntentState(),
                origin="latest_run",
                created_at=now,
                updated_at=now,
            )
        return ShotVideoGenerationDraft(
            project_id=plan.project_id,
            shot_plan_id=plan.id,
            model_alias=settings.default_model_alias,
            resolution=settings.default_resolution.upper(),
            duration_seconds=_bounded_duration(
                plan.duration_seconds,
                3.0,
            ),
            candidate_count=1,
            input_plan=current_default_input_plan(plan),
            video_prompt=plan.video_prompt,
            video_prompt_mentions=plan.video_prompt_mentions,
            video_negative_constraints=plan.video_negative_constraints,
            intent=VideoIntentState(),
            origin="global_default",
            created_at=now,
            updated_at=now,
        )


def current_default_input_plan(plan: ShotPlan | None = None) -> VideoGenerationInputPlan:
    """Use every approved required visual beat as the default ordered video input."""
    if plan is None:
        return VideoGenerationInputPlan()
    beats = sorted(plan.visual_beats, key=lambda item: item.index)
    required = [item for item in beats if item.required]
    targets = required or beats
    approved_targets = [beat for beat in targets if beat.approved_image_candidate_id is not None]
    references = [
        VideoGenerationReference(
            reference_kind=VideoPromptReferenceKind.APPROVED_IMAGE,
            reference_id=beat.approved_image_candidate_id,
            label=f"分镜图/图{beat.index}",
            role=VideoPromptReferenceRole.COMPOSITION,
            order=order,
            visual_beat_id=beat.id,
            automatic=True,
            origin=VideoReferenceOrigin.VISUAL_BEAT_AUTO,
            scope=VideoReferenceScope(
                kind=VideoReferenceScopeKind.VISUAL_BEATS,
                visual_beat_ids=[beat.id],
                start_ratio=beat.start_ratio,
                end_ratio=beat.end_ratio,
            ),
        )
        for order, beat in enumerate(approved_targets, start=1)
    ]
    return VideoGenerationInputPlan(
        sources=([VideoGenerationInputSource.APPROVED_IMAGES] if approved_targets else []),
        references=references,
    )


def legacy_video_input_plan() -> VideoGenerationInputPlan:
    """Old runs were created from approved shot images unless stated otherwise."""
    return VideoGenerationInputPlan(sources=[VideoGenerationInputSource.APPROVED_IMAGES])
