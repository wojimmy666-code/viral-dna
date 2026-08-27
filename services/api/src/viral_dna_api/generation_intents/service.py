from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ..account_preferences import UserPreferencesService
from ..ai.catalog import default_analysis_profile, load_model_plan
from ..ai.contracts import ModelProviderError, ModelRequest
from ..ai.router import ModelRouter
from ..ai.text_model_routing import preferred_text_model_aliases
from ..models import (
    AnalysisProfile,
    ModelTask,
    ProductionProject,
    ReferenceAsset,
    ShotPlan,
    ShotVideoGenerationDraft,
    VideoGenerationIntentIR,
    VideoIntentBaseline,
    VideoIntentConflict,
    VideoIntentState,
    VideoIntentStatus,
    VideoPromptMention,
)
from ..video_generation.drafts import ShotVideoGenerationDraftService
from ..video_generation.settings import VideoGenerationSettingsService
from .compiler import DIMENSION_LABELS, EDIT_PROCESS_MARKERS, compile_intent_prompt
from .contracts import (
    IntentUnderstandingSummary,
    UnresolvedIntentRequirement,
    VideoIntentCompileRequest,
    VideoIntentCompileResponse,
    VideoIntentRestoreRequest,
)
from .resolver import resolve_intent_references, validate_intent_mentions

SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "ai" / "prompts" / "video_generation_intent_v1.md"
)
PRIMARY_SEMANTIC_ATTEMPTS = 2


class VideoIntentRepository(Protocol):
    async def get_shot_plan(self, shot_plan_id: UUID) -> ShotPlan | None: ...

    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None: ...

    async def get_report_by_analysis(self, analysis_id: UUID): ...

    async def compare_and_swap_video_generation_draft(
        self,
        draft: ShotVideoGenerationDraft,
        expected_draft_version: int,
    ) -> bool: ...


class ProjectAssetReader(Protocol):
    async def list_references(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAsset]: ...


class VideoIntentCompilationError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _fail(status_code: int, code: str, message: str) -> VideoIntentCompilationError:
    return VideoIntentCompilationError(status_code, code, message)


@dataclass(frozen=True, slots=True)
class InterpretedIntent:
    intent: VideoGenerationIntentIR
    requested_model: str
    resolved_model: str
    prompt_version: str
    schema_version: str
    provider_request_id: str | None
    latency_ms: int


class VideoIntentInterpreter(Protocol):
    async def interpret(
        self,
        *,
        intent_text: str,
        context: dict[str, object],
    ) -> InterpretedIntent: ...


class ModelVideoIntentInterpreter:
    def __init__(
        self,
        router: ModelRouter | None = None,
        *,
        profile: AnalysisProfile | None = None,
        preferences: UserPreferencesService | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.profile = profile
        self.preferences = preferences
        self.system_prompt = SYSTEM_PROMPT_PATH.read_text("utf-8").strip()

    async def interpret(
        self,
        *,
        intent_text: str,
        context: dict[str, object],
    ) -> InterpretedIntent:
        profile = self.profile or default_analysis_profile()
        if self.preferences is None:
            plan = load_model_plan(profile)
        else:
            settings = (await self.preferences.get()).settings
            plan = load_model_plan(
                profile,
                preferred_aliases=preferred_text_model_aliases(
                    settings.text_model_alias,
                    settings.text_model_task_overrides,
                ),
                fallback_enabled=settings.text_model_fallback_enabled,
            )
        if plan is None:
            raise _fail(
                503,
                "video_intent_model_not_configured",
                "尚未配置用于理解创作意图的文本模型",
            )
        targets = plan.targets_for(ModelTask.VIDEO_INTENT)
        if not targets:
            raise _fail(
                503,
                "video_intent_model_route_missing",
                "当前模型计划没有创作意图解析路由",
            )
        schema = json.dumps(VideoGenerationIntentIR.model_json_schema(), ensure_ascii=False)
        base_user_prompt = (
            f"用户创作意图：\n{intent_text.strip()}\n\n"
            "当前分镜、可用资产和已选输入：\n"
            f"{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}\n\n"
            "请输出结构化创作意图，严格遵守以下 JSON Schema：\n"
            f"{schema}"
        )
        failures: list[str] = []
        validation_issues: list[str] = []
        for target_index, target in enumerate(targets):
            attempts = PRIMARY_SEMANTIC_ATTEMPTS if target_index == 0 else 1
            repair_candidate: VideoGenerationIntentIR | None = None
            repair_issues: list[str] = []
            for attempt_index in range(attempts):
                user_prompt = base_user_prompt
                if repair_candidate is not None:
                    user_prompt += _semantic_repair_instructions(
                        repair_candidate,
                        repair_issues,
                    )
                try:
                    provider = self.router.provider_for(target)
                    result = await provider.generate(
                        ModelRequest(
                            task=ModelTask.VIDEO_INTENT,
                            target=target,
                            system_prompt=self.system_prompt,
                            user_prompt=user_prompt,
                        ),
                        VideoGenerationIntentIR,
                    )
                except ModelProviderError as exc:
                    failures.append(f"{target.model}：{exc}")
                    break
                issues = _intent_output_issues(
                    result.data,
                    intent_text=intent_text,
                    intent_context=context,
                )
                if not issues:
                    return InterpretedIntent(
                        intent=result.data,
                        requested_model=target.model,
                        resolved_model=result.resolved_model,
                        prompt_version=target.prompt_version,
                        schema_version=target.schema_version,
                        provider_request_id=result.provider_request_id,
                        latency_ms=result.latency_ms,
                    )
                validation_issues.extend(issues)
                attempt_label = "首次输出" if attempt_index == 0 else "纠错输出"
                failures.append(f"{target.model} {attempt_label}：{'；'.join(issues)}")
                repair_candidate = result.data
                repair_issues = issues
        if validation_issues:
            issue_summary = "；".join(dict.fromkeys(validation_issues))
            raise _fail(
                502,
                "video_intent_model_validation_failed",
                f"提示词校验失败，请重新生成。模型未能满足：{issue_summary}",
            )
        raise _fail(
            502,
            "video_intent_model_failed",
            failures[-1] if failures else "创作意图模型没有返回有效结果",
        )


def _semantic_repair_instructions(
    candidate: VideoGenerationIntentIR,
    issues: list[str],
) -> str:
    candidate_json = json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False)
    return (
        "\n\n你上一次输出没有通过最终视频提示词语义校验。"
        "请根据校验错误修正上一次结果，并重新输出完整 JSON；不得只解释修改内容。\n"
        f"上一次输出：\n{candidate_json}\n"
        "校验错误：\n- "
        + "\n- ".join(issues)
    )


def _intent_output_issues(
    intent: VideoGenerationIntentIR,
    *,
    intent_text: str,
    intent_context: dict[str, object] | None = None,
) -> list[str]:
    issues: list[str] = []
    if not intent.final_state_instruction.strip():
        issues.append("final_state_instruction 不能为空，必须描述变更完成后的可见画面")
    for field_name in ("final_state_instruction", "creative_instruction"):
        text = str(getattr(intent, field_name) or "")
        if "@" in text:
            issues.append(f"{field_name} 不得包含 @引用，引用只能通过 directive 绑定")
        markers = [marker for marker in EDIT_PROCESS_MARKERS if marker in text]
        if markers:
            issues.append(
                f"{field_name} 仍包含编辑过程词：{'、'.join(dict.fromkeys(markers))}"
            )
    transition_text = intent.transition_instruction.strip()
    if "@" in transition_text:
        issues.append("transition_instruction 不得包含 @引用")
    if any(marker in transition_text for marker in ("保留原", "保持原", "沿用原", "复刻原")):
        issues.append("transition_instruction 必须直接描述最终转场效果，不能描述保留原视频")
    transition_directives = [
        item
        for item in intent.directives
        if item.dimension.value == "transition" and item.operation.value != "unspecified"
    ]
    if transition_text and not transition_directives:
        issues.append("填写 transition_instruction 时必须同时输出 transition directive")
    if "转场" in intent_text and not transition_directives:
        issues.append("用户明确提到转场，必须输出 transition directive")
    visual_beats = ((intent_context or {}).get("shot") or {}).get("visual_beats") or []
    expects_generated_transition = any(
        str(item.get("transition_to_next_type") or "") == "model_generated"
        for item in visual_beats
        if isinstance(item, dict)
    )
    transition_directive_text = " ".join(
        text
        for item in transition_directives
        for text in (item.target_name, item.instruction)
        if text
    )
    model_selected_hard_cut = "硬切" in f"{transition_text} {transition_directive_text}"
    if expects_generated_transition and model_selected_hard_cut and "硬切" not in intent_text:
        issues.append("当前分镜要求模型生成连续转场；用户未指定硬切时不得擅自改为硬切")
    return list(dict.fromkeys(issues))


def _reference_key(reference) -> str:
    if reference.visual_beat_id is not None:
        return f"{reference.reference_kind.value}:visual_beat:{reference.visual_beat_id}"
    return f"{reference.reference_kind.value}:{reference.reference_id}"


def _summary(intent: VideoGenerationIntentIR, reference_count: int) -> IntentUnderstandingSummary:
    buckets = {
        "preserve": [],
        "replace": [],
        "redesign": [],
        "remove": [],
    }
    for directive in intent.directives:
        target = buckets.get(directive.operation.value)
        if target is None:
            continue
        label = DIMENSION_LABELS[directive.dimension]
        if directive.target_name:
            label = f"{label} → {directive.target_name}"
        if label not in target:
            target.append(label)
    return IntentUnderstandingSummary(
        preserved=buckets["preserve"],
        replaced=buckets["replace"],
        redesigned=buckets["redesign"],
        removed=buckets["remove"],
        reference_count=reference_count,
    )


def _route_explanation(sources: list) -> str:
    labels = {
        "approved_images": "分镜图片",
        "project_assets": "项目资产",
        "provider_managed_assets": "托管人物",
        "reference_video": "原视频参考",
        "depth_control": "深度视频",
    }
    values = [labels.get(item.value, item.value) for item in sources]
    return " + ".join(values) if values else "纯文本生成"


class VideoIntentCompilationService:
    def __init__(
        self,
        repository: VideoIntentRepository,
        drafts: ShotVideoGenerationDraftService,
        assets: ProjectAssetReader,
        video_settings: VideoGenerationSettingsService,
        interpreter: VideoIntentInterpreter | None = None,
    ) -> None:
        self.repository = repository
        self.drafts = drafts
        self.assets = assets
        self.video_settings = video_settings
        self.interpreter = interpreter or ModelVideoIntentInterpreter()

    async def _context(
        self,
        project: ProductionProject,
        shot: ShotPlan,
        assets: list[ReferenceAsset],
        draft: ShotVideoGenerationDraft,
        intent_mentions: list[VideoPromptMention],
    ) -> dict[str, object]:
        report = await self.repository.get_report_by_analysis(project.base_analysis_id)
        source = None
        if report is not None:
            source = next(
                (item for item in report.shots if item.id == shot.source_shot_id),
                None,
            ) or next(
                (item for item in report.shots if item.index == shot.index),
                None,
            )
        source_facts = {}
        if source is not None:
            source_facts = {
                "subjects": source.subjects,
                "action": source.action,
                "scene": source.scene,
                "camera": source.camera,
                "composition": source.composition,
                "dialogue": source.dialogue,
                "transition": source.transition,
                "start_seconds": source.start_seconds,
                "end_seconds": source.end_seconds,
            }
        return {
            "output": {
                "aspect_ratio": getattr(project, "output_aspect_ratio", ""),
                "width": getattr(project, "output_width", None),
                "height": getattr(project, "output_height", None),
            },
            "shot": {
                "index": shot.index,
                "duration_seconds": shot.duration_seconds,
                "generation_duration_seconds": draft.duration_seconds,
                "source_facts": source_facts,
                "visual_beats": [
                    {
                        "index": item.index,
                        "title": item.title,
                        "start_ratio": item.start_ratio,
                        "end_ratio": item.end_ratio,
                        "image_prompt": item.image_prompt[:1600],
                        "has_approved_image": item.approved_image_candidate_id is not None,
                        "transition_to_next_type": item.transition_to_next_type,
                        "transition_to_next_prompt": item.transition_to_next_prompt,
                    }
                    for item in sorted(shot.visual_beats, key=lambda value: value.index)
                ],
            },
            "assets": [
                {
                    "name": item.name,
                    "type": item.type.value,
                    "description": item.description[:300],
                    "tags": item.tags,
                    "rights_confirmed": item.rights_confirmed,
                }
                for item in assets
                if item.archived_at is None
            ],
            "managed_assets": [
                {"name": item.name, "provider": item.provider, "kind": item.kind.value}
                for item in shot.managed_asset_bindings
            ],
            "has_ready_depth_video": any(
                item.enabled and item.usable_for_generation for item in shot.depth_control_assets
            ),
            "current_references": [
                {
                    "label": item.label,
                    "kind": item.reference_kind.value,
                    "role": item.role.value,
                    "locked": item.locked or _reference_key(item) in draft.locked_reference_keys,
                }
                for item in draft.input_plan.references
            ],
            "selected_video_model": draft.model_alias,
            "intent_mentions": [
                {
                    "reference_key": (f"{item.reference_kind.value}:{item.reference_id}"),
                    "token": f"@{item.label}",
                    "kind": item.reference_kind.value,
                    "role": item.role.value,
                }
                for item in intent_mentions
            ],
        }

    def _recommended_model(
        self,
        draft: ShotVideoGenerationDraft,
        input_plan,
    ) -> str | None:
        available = {item.alias for item in self.video_settings.get().models if item.available}
        references = input_plan.references
        has_depth = any(item.reference_kind.value == "depth_control" for item in references)
        has_managed = any(
            item.reference_kind.value == "provider_managed_asset" for item in references
        )
        if has_depth and has_managed and "seedance_2_0_fast" in available:
            return "seedance_2_0_fast"
        if has_depth and "minimax_h3" in available:
            return "minimax_h3"
        if draft.model_alias in available:
            return draft.model_alias
        return "bailian_wan_2_7_r2v" if "bailian_wan_2_7_r2v" in available else None

    async def compile(
        self,
        shot_plan_id: UUID,
        payload: VideoIntentCompileRequest,
        *,
        actor_account_id: UUID | None,
    ) -> VideoIntentCompileResponse:
        current = await self.drafts.get(shot_plan_id)
        if current.draft_version != payload.expected_draft_version:
            raise _fail(409, "video_draft_conflict", "视频生成设置已更新，请重新解析创作意图")
        shot = await self.repository.get_shot_plan(shot_plan_id)
        if shot is None:
            raise _fail(404, "shot_not_found", "分镜不存在")
        project = await self.repository.get_production_project(shot.project_id)
        if project is None:
            raise _fail(404, "production_project_not_found", "创作方案不存在")
        assets = await self.assets.list_references(project.id, include_archived=False)
        mention_failures = validate_intent_mentions(
            payload.intent_mentions,
            shot=shot,
            assets=assets,
        )
        if mention_failures:
            raise _fail(
                422,
                "video_intent_reference_invalid",
                mention_failures[0].message,
            )
        context = await self._context(
            project,
            shot,
            assets,
            current,
            payload.intent_mentions,
        )
        interpreted = await self.interpreter.interpret(
            intent_text=payload.intent_text,
            context=context,
        )
        resolved = resolve_intent_references(
            intent=interpreted.intent,
            shot=shot,
            assets=assets,
            explicit_mentions=payload.intent_mentions,
            current_plan=current.input_plan,
            excluded_visual_beat_ids=current.auto_reference_exclusions,
            removed_intent_reference_keys=current.removed_intent_reference_keys,
            locked_reference_keys=current.locked_reference_keys,
        )
        prompt, mentions, negatives = compile_intent_prompt(
            interpreted.intent,
            resolved.input_plan.references,
            shot,
            duration_seconds=current.duration_seconds,
            output_aspect_ratio=getattr(project, "output_aspect_ratio", None),
        )
        baseline = VideoIntentBaseline(
            video_prompt=prompt,
            video_prompt_mentions=mentions,
            video_negative_constraints=negatives,
            input_plan=resolved.input_plan,
        )
        preserve_prompt = (
            payload.merge_strategy == "preserve_manual" and current.prompt_manually_modified
        )
        conflicts: list[VideoIntentConflict] = []
        if preserve_prompt:
            conflicts.append(
                VideoIntentConflict(
                    code="manual_prompt_preserved",
                    message="自动提示词已更新；当前人工提示词已保留，请展开提示词查看差异",
                )
            )
        unresolved = list(resolved.unresolved)
        unresolved.extend(
            UnresolvedIntentRequirement(
                code="intent_ambiguity",
                dimension="general",
                message=message,
            )
            for message in interpreted.intent.ambiguities
        )
        if unresolved:
            conflicts.extend(
                VideoIntentConflict(code=item.code, message=item.message) for item in unresolved
            )
        now = datetime.now(UTC)
        next_draft = current.model_copy(
            update={
                "schema_version": "viral-dna-shot-video-draft/v2",
                "input_plan": resolved.input_plan,
                "video_prompt": current.video_prompt if preserve_prompt else prompt,
                "video_prompt_mentions": (
                    current.video_prompt_mentions if preserve_prompt else mentions
                ),
                "video_negative_constraints": (
                    current.video_negative_constraints if preserve_prompt else negatives
                ),
                "intent": VideoIntentState(
                    text=payload.intent_text.strip(),
                    mentions=payload.intent_mentions,
                    revision=current.intent.revision + 1,
                    status=(
                        VideoIntentStatus.NEEDS_INPUT if unresolved else VideoIntentStatus.READY
                    ),
                    interpretation=interpreted.intent,
                    requested_model=interpreted.requested_model,
                    resolved_model=interpreted.resolved_model,
                    prompt_version=interpreted.prompt_version,
                    schema_version=interpreted.schema_version,
                    provider_request_id=interpreted.provider_request_id,
                    latency_ms=interpreted.latency_ms,
                    generated_at=now,
                ),
                "auto_baseline": baseline,
                "intent_conflicts": conflicts,
                "prompt_manually_modified": preserve_prompt,
                "draft_version": current.draft_version + 1,
                "origin": "intent_generated",
                "updated_by_account_id": actor_account_id,
                "updated_at": now,
            }
        )
        saved = await self.repository.compare_and_swap_video_generation_draft(
            next_draft,
            expected_draft_version=current.draft_version,
        )
        if not saved:
            raise _fail(409, "video_draft_conflict", "解析期间视频生成设置已更新，请重试")
        recommendation = self._recommended_model(next_draft, resolved.input_plan)
        return VideoIntentCompileResponse(
            draft=next_draft,
            summary=_summary(interpreted.intent, len(resolved.input_plan.references)),
            unresolved_requirements=unresolved,
            warnings=list(resolved.warnings),
            recommended_model_alias=recommendation,
            route_explanation=_route_explanation(resolved.input_plan.sources),
            transition_evidence=resolved.transition_evidence,
        )

    async def restore(
        self,
        shot_plan_id: UUID,
        payload: VideoIntentRestoreRequest,
        *,
        actor_account_id: UUID | None,
    ) -> ShotVideoGenerationDraft:
        current = await self.drafts.get(shot_plan_id)
        if current.draft_version != payload.expected_draft_version:
            raise _fail(409, "video_draft_conflict", "视频生成设置已更新，请重试")
        baseline = current.auto_baseline
        if baseline is None:
            raise _fail(409, "video_intent_baseline_missing", "当前没有可恢复的自动生成版本")
        parts = set(payload.parts)
        updates: dict[str, object] = {
            "schema_version": "viral-dna-shot-video-draft/v2",
            "draft_version": current.draft_version + 1,
            "origin": "intent_generated",
            "updated_by_account_id": actor_account_id,
            "updated_at": datetime.now(UTC),
            "intent_conflicts": [],
        }
        if "prompt" in parts:
            updates.update(
                video_prompt=baseline.video_prompt,
                video_prompt_mentions=baseline.video_prompt_mentions,
                prompt_manually_modified=False,
            )
        if "negative_constraints" in parts:
            updates["video_negative_constraints"] = baseline.video_negative_constraints
        if "references" in parts:
            updates.update(
                input_plan=baseline.input_plan,
                removed_intent_reference_keys=[],
                locked_reference_keys=[],
            )
        next_draft = current.model_copy(update=updates)
        saved = await self.repository.compare_and_swap_video_generation_draft(
            next_draft,
            expected_draft_version=current.draft_version,
        )
        if not saved:
            raise _fail(409, "video_draft_conflict", "恢复期间视频生成设置已更新，请重试")
        return next_draft
