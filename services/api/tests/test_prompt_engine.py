from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from viral_dna_api.models import (
    AnalysisMode,
    AnalysisReport,
    PromptPackage,
    PromptShot,
    Shot,
    ShotMotionPhaseFact,
    ShotTransitionFact,
    VideoOverview,
)
from viral_dna_api.prompt_engine.compiler import compile_prompt_draft, draft_from_shot
from viral_dna_api.prompt_engine.contracts import (
    PromptDraftUpdateRequest,
    PromptShotDraftUpdate,
)
from viral_dna_api.prompt_engine.language_policy import (
    contains_unlabeled_english,
    find_prompt_draft_language_issues,
    normalize_prompt_draft,
)
from viral_dna_api.prompt_engine.service import PromptDraftService, PromptDraftServiceError


def build_shot() -> Shot:
    return Shot(
        id="shot_001",
        index=1,
        start_seconds=0,
        end_seconds=3,
        title="人物伸手并以遮挡结束",
        subjects=["一名黑色长发女子", "浅绿色丝带"],
        action="女子伸手，丝带逐渐靠近镜头",
        scene="户外栏杆前，远处是城市天际线",
        camera="中景固定机位",
        composition="人物居中，手掌位于前景",
        lighting="阴天柔光",
        color="浅黄与绿色",
        audio="无对白",
        transition="丝带遮满画面",
        narrative_role="开场钩子",
        prompt="旧版重复提示词",
        confidence=0.9,
        motion_phases=[
            ShotMotionPhaseFact(
                index=1,
                start_seconds=0,
                end_seconds=1.2,
                description="人物伸手",
                subject_motion="女子向镜头伸出右手",
                camera_motion="固定中景",
                foreground_motion="手掌由中景进入前景",
                focus_change="焦点保持在人物上半身",
            ),
            ShotMotionPhaseFact(
                index=2,
                start_seconds=1.2,
                end_seconds=3,
                description="丝带遮挡",
                subject_motion="女子轻触丝带",
                camera_motion="镜头保持静止",
                foreground_motion="浅绿色丝带快速靠近并遮满镜头",
                focus_change="焦点转移至丝带纹理",
            ),
        ],
        outgoing_transition=ShotTransitionFact(
            kind="foreground_occlusion",
            start_seconds=2.6,
            end_seconds=3,
            description="丝带遮满镜头",
            generation_prompt="丝带从右侧靠近镜头并形成完整遮挡",
            mask_object="浅绿色丝带",
            direction="右侧至镜头中心",
            terminal_frame="画面被丝带完全覆盖",
        ),
    )


def build_report() -> AnalysisReport:
    shot = build_shot()
    return AnalysisReport(
        video_id=uuid4(),
        analysis_id=uuid4(),
        analysis_mode=AnalysisMode.SIMULATED,
        overview=VideoOverview(
            summary="测试视频",
            content_type="人物展示",
            narrative_structure="开场钩子",
            audience_inference="普通观众",
            visual_style="写实",
            duration_seconds=3,
            aspect_ratio="9:16",
            viral_potential_score=60,
            confidence=0.8,
        ),
        shots=[shot],
        entities=[],
        viral_findings=[],
        prompt_package=PromptPackage(
            target_model="Seedance",
            global_prompt="统一写实风格",
            continuity_locks=[],
            entities={},
            shots=[
                PromptShot(
                    shot_id=shot.id,
                    duration_seconds=3,
                    prompt="旧版重复提示词",
                    negative_constraints=["不要增加无关人物"],
                )
            ],
            negative_constraints=[],
        ),
    )


class PromptRepository:
    def __init__(self, report: AnalysisReport) -> None:
        self.report = report
        self.save_count = 0

    async def get_report_by_analysis(self, analysis_id):
        return self.report if analysis_id == self.report.analysis_id else None

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        self.report = report
        self.save_count += 1
        return report


def test_compiler_emits_readable_sections_without_legacy_duplication() -> None:
    draft = draft_from_shot(build_shot(), negative_constraints=["不要增加无关人物"])
    compiled = compile_prompt_draft(draft, "Seedance 2.0")

    assert compiled.startswith("【基础画面】\n主体：")
    assert "\n\n【时间轴】\n0.00–1.20s" in compiled
    assert "\n\n【出场转场】\n2.60–3.00s｜" in compiled
    assert "\n\n【约束】\n- 不要增加无关人物" in compiled
    assert compiled.count("丝带从右侧靠近镜头并形成完整遮挡") == 1
    assert "无法确认" not in compiled
    assert "时序运镜" not in compiled
    assert "动作过程" not in compiled


def test_language_policy_requires_chinese_but_keeps_tagged_english_literals() -> None:
    draft = draft_from_shot(build_shot())
    draft.visual.scene = "城市露台，画面英文标识：“Customer Map”"
    draft.phases[0].camera_motion = "Static / Locked-off"

    issues = find_prompt_draft_language_issues(draft)

    assert contains_unlabeled_english("英文字幕：“The End”") is False
    assert contains_unlabeled_english("Static / Locked-off") is True
    assert [issue.field for issue in issues] == ["时间轴 1·镜头运动"]

    draft.phases[0].camera_motion = "固定机位"
    draft.phases[0].foreground_motion = "None"
    normalized = normalize_prompt_draft(draft)
    assert normalized.phases[0].foreground_motion == ""
    assert find_prompt_draft_language_issues(normalized) == []


def test_prompt_draft_service_hydrates_autosaves_and_detects_conflicts() -> None:
    asyncio.run(_exercise_prompt_draft_service())


async def _exercise_prompt_draft_service() -> None:
    repository = PromptRepository(build_report())
    service = PromptDraftService(repository)
    hydrated = await service.get_package(repository.report.analysis_id)

    assert hydrated.revision_id is not None
    assert hydrated.revision_number == 1
    assert hydrated.shots[0].draft is not None
    assert hydrated.shots[0].source_draft is not None

    changed = hydrated.shots[0].draft.model_copy(deep=True)
    changed.visual.scene = "夜晚天台，城市灯光作为远景"
    saved = await service.update_package(
        repository.report.analysis_id,
        PromptDraftUpdateRequest(
            expected_revision_id=hydrated.revision_id,
            shots=[PromptShotDraftUpdate(shot_id="shot_001", draft=changed)],
        ),
    )

    assert repository.save_count == 1
    assert saved.revision_number == 2
    assert saved.revision_id != hydrated.revision_id
    assert "场景：夜晚天台，城市灯光作为远景" in saved.shots[0].prompt
    assert repository.report.shots[0].prompt == saved.shots[0].prompt
    assert saved.shots[0].source_draft.visual.scene != changed.visual.scene

    with pytest.raises(PromptDraftServiceError) as raised:
        await service.update_package(
            repository.report.analysis_id,
            PromptDraftUpdateRequest(
                expected_revision_id=hydrated.revision_id,
                shots=[PromptShotDraftUpdate(shot_id="shot_001", draft=changed)],
            ),
        )
    assert raised.value.status_code == 409
    assert raised.value.code == "prompt_revision_conflict"

    invalid = saved.shots[0].draft.model_copy(deep=True)
    invalid.phases[0].camera_motion = "Static / Locked-off"
    with pytest.raises(PromptDraftServiceError) as language_error:
        await service.update_package(
            repository.report.analysis_id,
            PromptDraftUpdateRequest(
                expected_revision_id=saved.revision_id,
                shots=[PromptShotDraftUpdate(shot_id="shot_001", draft=invalid)],
            ),
        )
    assert language_error.value.status_code == 422
    assert language_error.value.code == "prompt_language_invalid"
    assert "时间轴 1·镜头运动" in str(language_error.value)
