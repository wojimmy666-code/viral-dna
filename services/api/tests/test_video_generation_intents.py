from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import viral_dna_api.generation_intents.service as intent_service_module
from viral_dna_api.control_assets.domain import (
    DepthControlAsset,
    DepthControlStatus,
    DepthControlValidationStatus,
)
from viral_dna_api.generation_intents.compiler import compile_intent_prompt
from viral_dna_api.generation_intents.contracts import VideoIntentCompileRequest
from viral_dna_api.generation_intents.service import (
    InterpretedIntent,
    ModelVideoIntentInterpreter,
    VideoIntentCompilationError,
    VideoIntentCompilationService,
)
from viral_dna_api.models import (
    AnalysisProfile,
    ManagedAssetKind,
    ManagedAssetMediaType,
    ModelPlanSnapshot,
    ModelRouteSnapshot,
    ModelTargetSnapshot,
    ModelTask,
    ProviderManagedAssetBinding,
    ReferenceAsset,
    ReferenceAssetType,
    ShotPlan,
    ShotVideoGenerationDraft,
    ShotVisualBeat,
    VideoGenerationInputSource,
    VideoGenerationIntentIR,
    VideoGenerationReference,
    VideoIntentDimension,
    VideoIntentDirective,
    VideoIntentFidelity,
    VideoIntentOperation,
    VideoIntentStatus,
    VideoPromptMention,
    VideoPromptReferenceKind,
    VideoPromptReferenceRole,
    VideoReferenceOrigin,
)
from viral_dna_api.video_generation.drafts import current_default_input_plan


class FakeDraftService:
    def __init__(self, draft: ShotVideoGenerationDraft) -> None:
        self.draft = draft

    async def get(self, _shot_plan_id):
        return self.draft


class FakeRepository:
    def __init__(self, shot: ShotPlan, draft: ShotVideoGenerationDraft) -> None:
        self.shot = shot
        self.draft = draft
        self.project = SimpleNamespace(
            id=shot.project_id,
            base_analysis_id=uuid4(),
            output_aspect_ratio="9:16",
            output_width=1080,
            output_height=1920,
        )

    async def get_shot_plan(self, shot_plan_id):
        return self.shot if shot_plan_id == self.shot.id else None

    async def get_production_project(self, project_id):
        return self.project if project_id == self.project.id else None

    async def get_report_by_analysis(self, _analysis_id):
        return None

    async def compare_and_swap_video_generation_draft(
        self,
        draft,
        expected_draft_version,
    ):
        if self.draft.draft_version != expected_draft_version:
            return False
        self.draft = draft
        return True


class FakeAssets:
    def __init__(self, assets) -> None:
        self.assets = assets

    async def list_references(self, _project_id, *, include_archived=False):
        assert include_archived is False
        return self.assets


class FakeSettings:
    def get(self):
        return SimpleNamespace(models=[SimpleNamespace(alias="minimax_h3", available=True)])


class FakeInterpreter:
    def __init__(self, intent: VideoGenerationIntentIR) -> None:
        self.intent = intent

    async def interpret(self, *, intent_text, context):
        assert intent_text
        assert context["shot"]["visual_beats"]
        return InterpretedIntent(
            intent=self.intent,
            requested_model="qwen3.6-flash-2026-04-16",
            resolved_model="qwen3.6-flash-2026-04-16",
            prompt_version="video-generation-intent-v1",
            schema_version="video-generation-intent-v1",
            provider_request_id="intent-request-1",
            latency_ms=42,
        )


class UnexpectedInterpreter:
    async def interpret(self, *, intent_text, context):
        raise AssertionError("失效资产必须在调用大模型前被拒绝")


class ValidationFailingInterpreter:
    async def interpret(self, *, intent_text, context):
        assert intent_text
        assert context["shot"]["visual_beats"]
        raise VideoIntentCompilationError(
            502,
            "video_intent_model_validation_failed",
            "提示词校验失败，请重新生成",
        )


class SequenceIntentProvider:
    provider_id = "dashscope"

    def __init__(self, responses) -> None:
        self.responses = responses
        self.calls = []
        self.requests = []

    async def generate(self, request, _response_schema):
        self.calls.append(request.target.model)
        self.requests.append(request)
        configured = self.responses[request.target.model]
        if isinstance(configured, list):
            call_index = self.calls.count(request.target.model) - 1
            intent = configured[min(call_index, len(configured) - 1)]
        else:
            intent = configured
        return SimpleNamespace(
            data=intent,
            resolved_model=request.target.model,
            provider_request_id=f"request-{len(self.calls)}",
            latency_ms=10,
        )


class SequenceIntentRouter:
    def __init__(self, provider) -> None:
        self.provider = provider

    def provider_for(self, _target):
        return self.provider


def make_shot() -> ShotPlan:
    first = ShotVisualBeat(
        index=1,
        title="起始画面",
        start_ratio=0,
        end_ratio=0.5,
        image_prompt=(
            "双马尾女性身穿白色印花长袖睡衣套装，站在粉色圆形地垫中央；"
            "背景为明亮白墙、粉色挂饰和系蓝色蝴蝶结的白色兔子玩偶。"
        ),
        approved_image_candidate_id=uuid4(),
        transition_to_next_prompt="人物抬手遮满镜头后显露下一套服装",
    )
    second = ShotVisualBeat(
        index=2,
        title="结束画面",
        start_ratio=0.5,
        end_ratio=1,
        image_prompt=(
            "同一名双马尾女性身穿浅绿色水手服与百褶裙，搭配白色过膝袜和黑色乐福鞋，"
            "站在同一块粉色圆形地垫中央，右手抬起展示。"
        ),
        approved_image_candidate_id=uuid4(),
    )
    return ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-001",
        index=1,
        start_seconds=0,
        end_seconds=4,
        duration_seconds=4,
        visual_beats=[first, second],
    )


def make_asset(project_id, name: str = "白色睡衣") -> ReferenceAsset:
    return ReferenceAsset(
        project_id=project_id,
        type=ReferenceAssetType.WARDROBE,
        name=name,
        description="白色印花长袖睡衣",
        relative_path="assets/wardrobe.webp",
        mime_type="image/webp",
        width=1080,
        height=1920,
        sha256="a" * 64,
        rights_confirmed=True,
    )


def test_intent_compilation_resolves_assets_and_preserves_model_generated_transition() -> None:
    async def scenario() -> None:
        shot = make_shot()
        draft = ShotVideoGenerationDraft(
            project_id=shot.project_id,
            shot_plan_id=shot.id,
            model_alias="minimax_h3",
            resolution="720P",
            duration_seconds=4,
            input_plan=current_default_input_plan(shot),
            video_prompt="旧提示词",
        )
        repository = FakeRepository(shot, draft)
        drafts = FakeDraftService(draft)
        selected_asset = make_asset(shot.project_id)
        same_name_asset = make_asset(shot.project_id)
        mention = VideoPromptMention(
            reference_kind=VideoPromptReferenceKind.PROJECT_ASSET,
            reference_id=selected_asset.id,
            label="资产/女装/白色睡衣",
            role=VideoPromptReferenceRole.WARDROBE,
            order=1,
        )
        intent = VideoGenerationIntentIR(
            summary="替换服装并保留原来的遮挡转场",
            directives=[
                VideoIntentDirective(
                    dimension=VideoIntentDimension.WARDROBE,
                    operation=VideoIntentOperation.REPLACE,
                    target_name="白色睡衣",
                    target_reference_key=(f"project_asset:{selected_asset.id}"),
                    preferred_source="project_asset",
                ),
                VideoIntentDirective(
                    dimension=VideoIntentDimension.TRANSITION,
                    operation=VideoIntentOperation.PRESERVE,
                    preferred_source="source_transition",
                ),
            ],
            final_state_instruction="人物身穿白色印花长袖睡衣，自然完成遮挡转场。",
            creative_instruction="人物自然完成换装前后的动作承接。",
        )
        service = VideoIntentCompilationService(
            repository,
            drafts,
            FakeAssets([selected_asset, same_name_asset]),
            FakeSettings(),
            interpreter=FakeInterpreter(intent),
        )

        result = await service.compile(
            shot.id,
            VideoIntentCompileRequest(
                expected_draft_version=1,
                intent_text=("服装换成 @资产/女装/白色睡衣，保留原遮挡转场"),
                intent_mentions=[mention],
            ),
            actor_account_id=uuid4(),
        )

        assert result.draft.schema_version == "viral-dna-shot-video-draft/v2"
        assert result.draft.intent.status == VideoIntentStatus.READY
        assert result.draft.intent.mentions == [mention]
        assert result.draft.auto_baseline is not None
        assert result.transition_evidence == "analyzed_facts"
        assert [item.reference_kind.value for item in result.draft.input_plan.references] == [
            "approved_image",
            "approved_image",
            "project_asset",
        ]
        assert result.draft.input_plan.references[-1].label == "资产/女装/白色睡衣"
        assert result.draft.input_plan.references[-1].reference_id == selected_asset.id
        assert result.draft.input_plan.references[-1].origin.value == "intent_explicit"
        assert "@资产/女装/白色睡衣" in result.draft.video_prompt
        assert "【最终画面】" in result.draft.video_prompt
        assert "【创作意图】" not in result.draft.video_prompt
        assert "替换服装" not in result.draft.video_prompt
        assert "全程人物服装以 @资产/女装/白色睡衣" in result.draft.video_prompt
        assert "0.00–2.00 秒" in result.draft.video_prompt
        assert "转场由视频模型生成，不使用硬切" in result.draft.video_prompt
        assert result.unresolved_requirements == []
        assert repository.draft.draft_version == 2

    asyncio.run(scenario())


def test_successful_regeneration_replaces_old_intent_identity_references() -> None:
    async def scenario() -> None:
        shot = make_shot()
        managed = ProviderManagedAssetBinding(
            provider="volc_ark",
            asset_id="managed-person-1",
            kind=ManagedAssetKind.VIRTUAL_PERSON,
            name="小喵酱",
            media_type=ManagedAssetMediaType.IMAGE,
            project_name="default",
        )
        depth = DepthControlAsset(
            status=DepthControlStatus.READY,
            source_video_id=uuid4(),
            source_relative_path="source/video.mp4",
            source_start_seconds=0,
            source_end_seconds=4,
            relative_path="depth/control.mp4",
            thumbnail_relative_path="depth/control.webp",
            manifest_relative_path="depth/control.json",
            sha256="d" * 64,
            width=1080,
            height=1920,
            fps=30,
            duration_seconds=4,
            frame_count=120,
            validation_status=DepthControlValidationStatus.PASSED,
        )
        shot = shot.model_copy(
            update={
                "managed_asset_bindings": [managed],
                "depth_control_assets": [depth],
            }
        )
        old_identity = make_asset(shot.project_id, "旧人物面部").model_copy(
            update={"type": ReferenceAssetType.PERSON}
        )
        old_reference = VideoGenerationReference(
            reference_kind=VideoPromptReferenceKind.PROJECT_ASSET,
            reference_id=old_identity.id,
            label="资产/小喵酱/面部",
            role=VideoPromptReferenceRole.ACTOR_IDENTITY,
            order=3,
            origin=VideoReferenceOrigin.INTENT_EXPLICIT,
        )
        default_plan = current_default_input_plan(shot)
        draft = ShotVideoGenerationDraft(
            project_id=shot.project_id,
            shot_plan_id=shot.id,
            model_alias="minimax_h3",
            resolution="720P",
            duration_seconds=4,
            input_plan=default_plan.model_copy(
                update={
                    "sources": [
                        *default_plan.sources,
                        VideoGenerationInputSource.PROJECT_ASSETS,
                    ],
                    "references": [*default_plan.references, old_reference],
                }
            ),
            video_prompt="@资产/小喵酱/面部\n\n上一版人物提示词",
            video_prompt_mentions=[
                VideoPromptMention(**old_reference.model_dump(mode="python"))
            ],
            prompt_manually_modified=True,
        )
        managed_mention = VideoPromptMention(
            reference_kind=VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET,
            reference_id=managed.id,
            label="托管角色/小喵酱",
            role=VideoPromptReferenceRole.ACTOR_IDENTITY,
            order=1,
        )
        depth_mention = VideoPromptMention(
            reference_kind=VideoPromptReferenceKind.DEPTH_CONTROL,
            reference_id=depth.id,
            label="深度视频/分镜动作1",
            role=VideoPromptReferenceRole.DEPTH,
            order=2,
        )
        intent = VideoGenerationIntentIR(
            summary="指定托管人物身份并采用深度动作",
            directives=[
                VideoIntentDirective(
                    dimension=VideoIntentDimension.IDENTITY,
                    operation=VideoIntentOperation.REPLACE,
                    target_name="小喵酱",
                    target_reference_key=f"provider_managed_asset:{managed.id}",
                    preferred_source="managed_asset",
                    visual_beat_indexes=[1, 2],
                ),
                VideoIntentDirective(
                    dimension=VideoIntentDimension.MOTION,
                    operation=VideoIntentOperation.PRESERVE,
                    target_reference_key=f"depth_control:{depth.id}",
                    preferred_source="depth_control",
                    visual_beat_indexes=[1, 2],
                ),
            ],
            final_state_instruction="同一名双马尾年轻女性完成跳跃和抬手展示。",
            creative_instruction="人物动作自然连续，固定机位保持不变。",
        )
        repository = FakeRepository(shot, draft)
        service = VideoIntentCompilationService(
            repository,
            FakeDraftService(draft),
            FakeAssets([old_identity]),
            FakeSettings(),
            interpreter=FakeInterpreter(intent),
        )

        result = await service.compile(
            shot.id,
            VideoIntentCompileRequest(
                expected_draft_version=1,
                intent_text=(
                    "将人物五官换成 @托管角色/小喵酱，"
                    "动作使用 @深度视频/分镜动作1"
                ),
                intent_mentions=[managed_mention, depth_mention],
                merge_strategy="replace_all",
            ),
            actor_account_id=None,
        )

        reference_kinds = [
            item.reference_kind for item in result.draft.input_plan.references
        ]
        assert reference_kinds == [
            VideoPromptReferenceKind.APPROVED_IMAGE,
            VideoPromptReferenceKind.APPROVED_IMAGE,
            VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET,
            VideoPromptReferenceKind.DEPTH_CONTROL,
        ]
        assert all(
            item.reference_id != old_identity.id
            for item in result.draft.input_plan.references
        )
        assert "@托管角色/小喵酱" in result.draft.video_prompt
        assert "@深度视频/分镜动作1" in result.draft.video_prompt
        assert "@资产/小喵酱/面部" not in result.draft.video_prompt
        assert "上一版人物提示词" not in result.draft.video_prompt
        assert result.draft.prompt_manually_modified is False
        assert [item.reference_id for item in result.draft.video_prompt_mentions] == [
            item.reference_id for item in result.draft.input_plan.references
        ]

    asyncio.run(scenario())


def test_compile_request_rejects_unbound_at_reference() -> None:
    with pytest.raises(ValidationError, match="尚未选择完成"):
        VideoIntentCompileRequest(
            expected_draft_version=1,
            intent_text="将人物换成 @",
        )


def test_compile_request_defaults_to_replacing_generated_prompt() -> None:
    payload = VideoIntentCompileRequest(
        expected_draft_version=1,
        intent_text="重新生成当前资产引用与视频提示词",
    )

    assert payload.merge_strategy == "replace_all"


def test_model_interpreter_retries_preferred_model_with_validation_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = VideoGenerationIntentIR(
        summary="替换面部并保留动作",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.IDENTITY,
                operation=VideoIntentOperation.REPLACE,
                target_reference_key="project_asset:00000000-0000-0000-0000-000000000001",
            )
        ],
        final_state_instruction="人物面部来自 @资产/人物/面部。",
        transition_instruction="保留原视频转场。",
    )
    valid = VideoGenerationIntentIR(
        summary="人物身份使用指定资产，动作节奏来自深度控制",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.IDENTITY,
                operation=VideoIntentOperation.REPLACE,
                target_reference_key="project_asset:00000000-0000-0000-0000-000000000001",
            ),
            VideoIntentDirective(
                dimension=VideoIntentDimension.TRANSITION,
                operation=VideoIntentOperation.PRESERVE,
                preferred_source="text",
            ),
            VideoIntentDirective(
                dimension=VideoIntentDimension.SCENE,
                operation=VideoIntentOperation.PRESERVE,
                visual_beat_indexes=[1, 2],
            ),
        ],
        final_state_instruction=(
            "一名双马尾年轻女性先身穿白色印花睡衣跳跃，随后身穿浅绿色水手服站立展示。"
        ),
        transition_instruction="人物跳跃落地时完成动作匹配变装，机位和身体中心连续。",
    )
    targets = [
        ModelTargetSnapshot(
            alias="qwen37",
            provider="dashscope",
            model="qwen3.7-plus-2026-05-26",
            prompt_version="video-generation-intent-v1",
            schema_version="video-generation-intent-v1",
        ),
        ModelTargetSnapshot(
            alias="qwen36flash",
            provider="dashscope",
            model="qwen3.6-flash-2026-04-16",
            prompt_version="video-generation-intent-v1",
            schema_version="video-generation-intent-v1",
        ),
    ]
    plan = ModelPlanSnapshot(
        profile=AnalysisProfile.BALANCED,
        catalog_version="test",
        pricing_version="test",
        routes=[ModelRouteSnapshot(task=ModelTask.VIDEO_INTENT, targets=targets)],
    )
    monkeypatch.setattr(intent_service_module, "load_model_plan", lambda _profile: plan)
    provider = SequenceIntentProvider({
        targets[0].model: [invalid, valid],
        targets[1].model: invalid,
    })

    interpreted = asyncio.run(
        ModelVideoIntentInterpreter(router=SequenceIntentRouter(provider)).interpret(
            intent_text="人物换成 @资产/人物/面部，动作使用深度视频",
            context={"shot": {"visual_beats": [{"index": 1}, {"index": 2}]}},
        )
    )

    assert provider.calls == [targets[0].model, targets[0].model]
    assert "上一次输出" in provider.requests[1].user_prompt
    assert "final_state_instruction 不得包含 @引用" in provider.requests[1].user_prompt
    assert "@资产/人物/面部" in provider.requests[1].user_prompt
    assert interpreted.resolved_model == targets[0].model
    assert interpreted.intent == valid


def test_model_interpreter_normalizes_unrequested_hard_cut_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hard_cut = VideoGenerationIntentIR(
        summary="替换人物并硬切变装",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.TRANSITION,
                operation=VideoIntentOperation.REDESIGN,
                preferred_source="text",
            )
        ],
        final_state_instruction="一名年轻女性先穿白色睡衣跳跃，随后穿浅绿色水手服站立展示。",
        transition_instruction="人物落地时直接硬切为水手服画面。",
    )
    targets = [
        ModelTargetSnapshot(
            alias="qwen37",
            provider="dashscope",
            model="qwen3.7-plus-2026-05-26",
            prompt_version="video-generation-intent-v1",
            schema_version="video-generation-intent-v1",
        ),
        ModelTargetSnapshot(
            alias="qwen36flash",
            provider="dashscope",
            model="qwen3.6-flash-2026-04-16",
            prompt_version="video-generation-intent-v1",
            schema_version="video-generation-intent-v1",
        ),
    ]
    plan = ModelPlanSnapshot(
        profile=AnalysisProfile.BALANCED,
        catalog_version="test",
        pricing_version="test",
        routes=[ModelRouteSnapshot(task=ModelTask.VIDEO_INTENT, targets=targets)],
    )
    monkeypatch.setattr(intent_service_module, "load_model_plan", lambda _profile: plan)
    provider = SequenceIntentProvider({target.model: hard_cut for target in targets})

    interpreted = asyncio.run(
        ModelVideoIntentInterpreter(router=SequenceIntentRouter(provider)).interpret(
            intent_text="人物换成指定面部资产，动作使用深度视频",
            context={
                "shot": {
                    "visual_beats": [
                        {"index": 1, "transition_to_next_type": "model_generated"},
                        {"index": 2, "transition_to_next_type": "cut"},
                    ]
                }
            },
        )
    )

    assert provider.calls == [targets[0].model]
    assert interpreted.resolved_model == targets[0].model
    assert "连续视觉转场" in interpreted.intent.transition_instruction
    assert "硬切" not in interpreted.intent.transition_instruction
    assert interpreted.intent.directives[0].operation == VideoIntentOperation.REDESIGN


def test_model_interpreter_preserves_user_requested_hard_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hard_cut = VideoGenerationIntentIR(
        summary="人物落地时硬切变装",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.TRANSITION,
                operation=VideoIntentOperation.REDESIGN,
                target_name="硬切",
                preferred_source="text",
                instruction="人物落地时直接硬切为水手服画面。",
            )
        ],
        final_state_instruction="人物落地后身穿浅绿色水手服站立展示。",
        transition_instruction="人物落地时直接硬切为水手服画面。",
    )
    target = ModelTargetSnapshot(
        alias="qwen37",
        provider="dashscope",
        model="qwen3.7-plus-2026-05-26",
        prompt_version="video-generation-intent-v1",
        schema_version="video-generation-intent-v1",
    )
    plan = ModelPlanSnapshot(
        profile=AnalysisProfile.BALANCED,
        catalog_version="test",
        pricing_version="test",
        routes=[ModelRouteSnapshot(task=ModelTask.VIDEO_INTENT, targets=[target])],
    )
    monkeypatch.setattr(intent_service_module, "load_model_plan", lambda _profile: plan)
    provider = SequenceIntentProvider({target.model: hard_cut})

    interpreted = asyncio.run(
        ModelVideoIntentInterpreter(router=SequenceIntentRouter(provider)).interpret(
            intent_text="人物落地时直接硬切为下一套服装",
            context={
                "shot": {
                    "visual_beats": [
                        {"index": 1, "transition_to_next_type": "model_generated"},
                        {"index": 2, "transition_to_next_type": "cut"},
                    ]
                }
            },
        )
    )

    assert provider.calls == [target.model]
    assert interpreted.intent.transition_instruction == hard_cut.transition_instruction
    assert interpreted.intent.directives == hard_cut.directives


def test_model_interpreter_rejects_every_invalid_model_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = VideoGenerationIntentIR(
        summary="替换人物并硬切变装",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.IDENTITY,
                operation=VideoIntentOperation.REPLACE,
                target_reference_key="project_asset:00000000-0000-0000-0000-000000000001",
            ),
            VideoIntentDirective(
                dimension=VideoIntentDimension.TRANSITION,
                operation=VideoIntentOperation.REDESIGN,
                target_name="硬切",
                preferred_source="source_transition",
                instruction="人物落地时瞬间硬切为水手服画面。",
            ),
        ],
        final_state_instruction="人物面部来自 @资产/人物/面部。",
        transition_instruction="人物落地时切换为水手服画面。",
    )
    targets = [
        ModelTargetSnapshot(
            alias="qwen37",
            provider="dashscope",
            model="qwen3.7-plus-2026-05-26",
            prompt_version="video-generation-intent-v1",
            schema_version="video-generation-intent-v1",
        ),
        ModelTargetSnapshot(
            alias="qwen36flash",
            provider="dashscope",
            model="qwen3.6-flash-2026-04-16",
            prompt_version="video-generation-intent-v1",
            schema_version="video-generation-intent-v1",
        ),
    ]
    plan = ModelPlanSnapshot(
        profile=AnalysisProfile.BALANCED,
        catalog_version="test",
        pricing_version="test",
        routes=[ModelRouteSnapshot(task=ModelTask.VIDEO_INTENT, targets=targets)],
    )
    monkeypatch.setattr(intent_service_module, "load_model_plan", lambda _profile: plan)
    provider = SequenceIntentProvider({target.model: invalid for target in targets})

    with pytest.raises(VideoIntentCompilationError) as failure:
        asyncio.run(
            ModelVideoIntentInterpreter(router=SequenceIntentRouter(provider)).interpret(
                intent_text="人物换成指定面部资产，动作使用深度视频",
                context={
                    "shot": {
                        "visual_beats": [
                            {"index": 1, "transition_to_next_type": "model_generated"},
                            {"index": 2, "transition_to_next_type": "cut"},
                        ]
                    }
                },
            )
        )

    assert provider.calls == [targets[0].model, targets[0].model, targets[1].model]
    assert failure.value.status_code == 502
    assert failure.value.code == "video_intent_model_validation_failed"
    assert "提示词校验失败" in str(failure.value)
    assert "final_state_instruction 不得包含 @引用" in str(failure.value)
    assert "用户未指定硬切时不得擅自改为硬切" not in str(failure.value)
    assert "模型输出已降级清理" not in str(failure.value)


def test_compile_does_not_save_draft_when_model_validation_fails() -> None:
    async def scenario() -> None:
        shot = make_shot()
        draft = ShotVideoGenerationDraft(
            project_id=shot.project_id,
            shot_plan_id=shot.id,
            model_alias="minimax_h3",
            resolution="720P",
            duration_seconds=4,
        )
        repository = FakeRepository(shot, draft)
        service = VideoIntentCompilationService(
            repository,
            FakeDraftService(draft),
            FakeAssets([]),
            FakeSettings(),
            interpreter=ValidationFailingInterpreter(),
        )

        with pytest.raises(VideoIntentCompilationError) as failure:
            await service.compile(
                shot.id,
                VideoIntentCompileRequest(
                    expected_draft_version=1,
                    intent_text="保留当前人物动作并生成连续转场",
                ),
                actor_account_id=None,
            )

        assert failure.value.code == "video_intent_model_validation_failed"
        assert repository.draft is draft
        assert repository.draft.draft_version == 1
        assert repository.draft.intent.status == VideoIntentStatus.EMPTY

    asyncio.run(scenario())


def test_invalid_explicit_asset_is_rejected_before_model_call() -> None:
    async def scenario() -> None:
        shot = make_shot()
        draft = ShotVideoGenerationDraft(
            project_id=shot.project_id,
            shot_plan_id=shot.id,
            model_alias="minimax_h3",
            resolution="720P",
            duration_seconds=4,
        )
        mention = VideoPromptMention(
            reference_kind=VideoPromptReferenceKind.PROJECT_ASSET,
            reference_id=uuid4(),
            label="资产/服装/已删除资产",
            role=VideoPromptReferenceRole.WARDROBE,
            order=1,
        )
        service = VideoIntentCompilationService(
            FakeRepository(shot, draft),
            FakeDraftService(draft),
            FakeAssets([]),
            FakeSettings(),
            interpreter=UnexpectedInterpreter(),
        )

        with pytest.raises(VideoIntentCompilationError) as failure:
            await service.compile(
                shot.id,
                VideoIntentCompileRequest(
                    expected_draft_version=1,
                    intent_text="服装换成 @资产/服装/已删除资产",
                    intent_mentions=[mention],
                ),
                actor_account_id=None,
            )
        assert failure.value.status_code == 422
        assert failure.value.code == "video_intent_reference_invalid"

    asyncio.run(scenario())


def test_depth_prompt_is_guided_unless_intent_explicitly_requires_strict_fidelity() -> None:
    shot = make_shot()
    depth_reference = VideoGenerationReference(
        reference_kind=VideoPromptReferenceKind.DEPTH_CONTROL,
        reference_id=uuid4(),
        label="深度视频/分镜动作1",
        role=VideoPromptReferenceRole.DEPTH,
        order=1,
    )
    guided = VideoGenerationIntentIR(
        summary="参考原动作并允许自然调整",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.MOTION,
                operation=VideoIntentOperation.PRESERVE,
                fidelity=VideoIntentFidelity.GUIDED,
                preferred_source="depth_control",
            )
        ],
    )
    strict = guided.model_copy(
        update={
            "summary": "逐帧复刻原动作",
            "directives": [
                guided.directives[0].model_copy(update={"fidelity": VideoIntentFidelity.STRICT})
            ],
        }
    )

    guided_prompt, _, _ = compile_intent_prompt(guided, [depth_reference], shot)
    strict_prompt, _, _ = compile_intent_prompt(strict, [depth_reference], shot)

    assert "允许按目标人物及最终场景做自然幅度适配" in guided_prompt
    assert "严格遵循其动作顺序" not in guided_prompt
    assert "严格遵循其动作顺序" in strict_prompt


def test_depth_replacement_is_compiled_as_a_resolved_motion_state() -> None:
    shot = make_shot()
    depth_reference = VideoGenerationReference(
        reference_kind=VideoPromptReferenceKind.DEPTH_CONTROL,
        reference_id=uuid4(),
        label="深度视频/分镜动作1",
        role=VideoPromptReferenceRole.DEPTH,
        order=1,
    )
    intent = VideoGenerationIntentIR(
        summary="把人物动作换成指定深度视频",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.MOTION,
                operation=VideoIntentOperation.REPLACE,
                target_reference_key=f"depth_control:{depth_reference.reference_id}",
                preferred_source="depth_control",
            )
        ],
        final_state_instruction="人物自然完成指定动作序列。",
        creative_instruction=(
            "人物面部呈现@资产/人物/面部的特征，背景和服装保持原样，"
            "除非被其他指令覆盖。"
        ),
    )

    prompt, _, _ = compile_intent_prompt(intent, [depth_reference], shot)

    assert "人物动作、姿态、运动轨迹、节奏、空间位置与镜头关系由" in prompt
    assert "@深度视频/分镜动作1 提供" in prompt
    assert "替换动作" not in prompt
    assert "保持原样" not in prompt
    assert "@资产/人物/面部" not in prompt
    assert intent.summary not in prompt


def test_compiler_keeps_concrete_frame_details_and_inline_reference_roles() -> None:
    shot = make_shot()
    references = [
        *[
            VideoGenerationReference(
                reference_kind=VideoPromptReferenceKind.APPROVED_IMAGE,
                reference_id=beat.approved_image_candidate_id,
                label=f"分镜图/图{beat.index}",
                role=VideoPromptReferenceRole.COMPOSITION,
                order=beat.index,
                visual_beat_id=beat.id,
            )
            for beat in shot.visual_beats
        ],
        VideoGenerationReference(
            reference_kind=VideoPromptReferenceKind.PROJECT_ASSET,
            reference_id=uuid4(),
            label="资产/小喵酱/面部",
            role=VideoPromptReferenceRole.ACTOR_IDENTITY,
            order=3,
        ),
        VideoGenerationReference(
            reference_kind=VideoPromptReferenceKind.DEPTH_CONTROL,
            reference_id=uuid4(),
            label="深度视频/分镜动作1",
            role=VideoPromptReferenceRole.DEPTH,
            order=4,
        ),
    ]
    intent = VideoGenerationIntentIR(
        summary="指定人物身份并采用深度动作",
        directives=[
            VideoIntentDirective(
                dimension=VideoIntentDimension.IDENTITY,
                operation=VideoIntentOperation.REPLACE,
                target_name="小喵酱/面部",
                target_reference_key=(
                    f"project_asset:{references[2].reference_id}"
                ),
                visual_beat_indexes=[1, 2],
            ),
            VideoIntentDirective(
                dimension=VideoIntentDimension.MOTION,
                operation=VideoIntentOperation.PRESERVE,
                fidelity=VideoIntentFidelity.STRICT,
                target_reference_key=(
                    f"depth_control:{references[3].reference_id}"
                ),
                preferred_source="depth_control",
                visual_beat_indexes=[1, 2],
            ),
            VideoIntentDirective(
                dimension=VideoIntentDimension.TRANSITION,
                operation=VideoIntentOperation.REDESIGN,
                preferred_source="text",
            ),
        ],
        final_state_instruction=(
            "全程只有一名双马尾年轻女性，人物面部身份和稳定外貌始终来自 "
            "@资产/小喵酱/面部。室内为明亮白墙场景，人物始终位于画面中央，"
            "采用固定机位和平视全身景别。"
        ),
        creative_instruction=(
            "人物先连续原地跳跃，落地后稳定站立并抬起右手展示；"
            "动作顺序、节奏和空间位置以 @深度视频/分镜动作1 为准。"
        ),
        transition_instruction=(
            "人物跳跃落地的动作节点触发自然变装，转场前后身体中心、脚部落点、"
            "人物尺度、背景位置和固定机位连续一致。"
        ),
    )

    prompt, mentions, _ = compile_intent_prompt(
        intent,
        references,
        shot,
        duration_seconds=6,
        output_aspect_ratio="9:16",
    )

    assert "生成一段 9:16、时长 6.00 秒的竖屏视频" in prompt
    assert "【0.00–3.00 秒｜起始画面】" in prompt
    assert "白色印花长袖睡衣套装" in prompt
    assert "【3.00–6.00 秒｜结束画面】" in prompt
    assert "浅绿色水手服与百褶裙" in prompt
    assert "画面以  为准" not in prompt
    assert "@分镜图/图1 到 @分镜图/图2" in prompt
    assert "人物跳跃落地的动作节点触发自然变装" in prompt
    assert "沿用已选" not in prompt
    assert "。；" not in prompt
    assert "@资产/小喵酱/面部" in prompt
    assert "@深度视频/分镜动作1" in prompt
    assert len(mentions) == 4


def test_intent_regeneration_preserves_manually_edited_prompt_and_updates_baseline() -> None:
    async def scenario() -> None:
        shot = make_shot()
        draft = ShotVideoGenerationDraft(
            project_id=shot.project_id,
            shot_plan_id=shot.id,
            model_alias="minimax_h3",
            resolution="720P",
            duration_seconds=4,
            input_plan=current_default_input_plan(shot),
            video_prompt="这是人工修改后的提示词",
            prompt_manually_modified=True,
        )
        repository = FakeRepository(shot, draft)
        intent = VideoGenerationIntentIR(
            summary="重新设计场景",
            directives=[
                VideoIntentDirective(
                    dimension=VideoIntentDimension.SCENE,
                    operation=VideoIntentOperation.REDESIGN,
                    preferred_source="text",
                    instruction="改为明亮摄影棚",
                )
            ],
            final_state_instruction="人物位于明亮摄影棚内。",
        )
        service = VideoIntentCompilationService(
            repository,
            FakeDraftService(draft),
            FakeAssets([]),
            FakeSettings(),
            interpreter=FakeInterpreter(intent),
        )

        result = await service.compile(
            shot.id,
            VideoIntentCompileRequest(
                expected_draft_version=1,
                intent_text="场景改为明亮摄影棚",
                merge_strategy="preserve_manual",
            ),
            actor_account_id=None,
        )

        assert result.draft.video_prompt == "这是人工修改后的提示词"
        assert result.draft.prompt_manually_modified is True
        assert result.draft.auto_baseline is not None
        assert "人物位于明亮摄影棚内" in result.draft.auto_baseline.video_prompt
        assert "重新设计场景" not in result.draft.auto_baseline.video_prompt
        assert [item.code for item in result.draft.intent_conflicts] == ["manual_prompt_preserved"]

    asyncio.run(scenario())
