from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from viral_dna_api.models import (
    AnalysisReport,
    PromptPackage,
    PromptShot,
    Shot,
    ShotMotionPhaseFact,
    ShotTransitionFact,
    ShotVisualBeatFact,
    VideoOverview,
)
from viral_dna_api.quality.cli import run
from viral_dna_api.quality.contracts import (
    GoldenAnalysisExpectation,
    GoldenShotExpectation,
)
from viral_dna_api.quality.golden import (
    evaluate_golden_report,
    report_quality_fingerprint,
)


def _build_shot(
    *,
    index: int,
    start_seconds: float,
    end_seconds: float,
    prompt: str,
    scene: str,
    with_motion: bool = False,
) -> Shot:
    visual_beats = [
        ShotVisualBeatFact(
            index=1,
            title=f"画面 {index}",
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            source_timestamp_seconds=(start_seconds + end_seconds) / 2,
            image_prompt=prompt,
        )
    ]
    motion_phases = []
    outgoing_transition = ShotTransitionFact()
    if with_motion:
        motion_phases = [
            ShotMotionPhaseFact(
                index=1,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                description="镜头快速推近，浅绿色丝带屏占比增至100%并完全遮挡镜头",
                camera_motion="快速推近至极近景",
                subject_motion="手部整理丝带",
                foreground_motion="丝带向镜头移动",
                focus_change="焦点从人物后背转移到丝带纹理",
                foreground_occupancy_start_percent=15,
                foreground_occupancy_end_percent=100,
                occlusion_start_percent=0,
                occlusion_end_percent=100,
                confidence=0.94,
            )
        ]
        outgoing_transition = ShotTransitionFact(
            kind="foreground_occlusion",
            start_seconds=end_seconds - 0.4,
            end_seconds=end_seconds,
            description="浅绿色丝带完全遮挡镜头形成自然转场",
            mask_object="浅绿色丝带",
            terminal_frame="浅绿色模糊画面",
            generation_prompt="快速推近直到丝带覆盖整个画面",
            confidence=0.95,
        )
    return Shot(
        id=f"shot_{index:03d}",
        index=index,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        content_start_seconds=start_seconds,
        content_end_seconds=end_seconds,
        title=f"分镜 {index}",
        subjects=["黑长直发女性"],
        action="人物完成当前动作",
        scene=scene,
        camera="写实摄影",
        composition="主体位于画面中央",
        lighting="自然柔光",
        color="清新自然",
        audio="原始音轨",
        transition="自然衔接",
        narrative_role="建立画面并推进转场",
        prompt=prompt,
        confidence=0.9,
        visual_beats=visual_beats,
        motion_phases=motion_phases,
        outgoing_transition=outgoing_transition,
    )


def _build_report() -> AnalysisReport:
    shots = [
        _build_shot(
            index=1,
            start_seconds=0,
            end_seconds=3.2,
            prompt=(
                "室内人物背对镜头，镜头快速推近，浅绿色丝带逐渐占满画面，"
                "最后完全遮挡镜头并形成浅绿色模糊末帧。"
            ),
            scene="室内木门与白墙",
            with_motion=True,
        ),
        _build_shot(
            index=2,
            start_seconds=3.2,
            end_seconds=9.2,
            prompt="户外稻田，一名少女坐在木质平台上眺望远方。",
            scene="户外稻田与蓝天",
        ),
    ]
    return AnalysisReport(
        video_id=uuid4(),
        analysis_id=uuid4(),
        overview=VideoOverview(
            summary="丝带遮挡转场后进入户外场景",
            content_type="转场短片",
            narrative_structure="室内动作到户外定场",
            audience_inference="短视频创作者",
            visual_style="清新写实",
            duration_seconds=9.2,
            aspect_ratio="9:16",
            viral_potential_score=75,
            confidence=0.9,
        ),
        shots=shots,
        entities=[],
        viral_findings=[],
        prompt_package=PromptPackage(
            target_model="Seedance",
            aspect_ratio="9:16",
            global_prompt="清新写实短片",
            continuity_locks=["人物身份", "浅绿色丝带"],
            entities={},
            shots=[
                PromptShot(
                    shot_id=shot.id,
                    duration_seconds=shot.end_seconds - shot.start_seconds,
                    prompt=shot.prompt,
                    negative_constraints=[],
                )
                for shot in shots
            ],
            negative_constraints=[],
        ),
    )


def _build_expectation() -> GoldenAnalysisExpectation:
    return GoldenAnalysisExpectation(
        sample_id="spring-ribbon-transition-v1",
        name="丝带遮挡转场分析基线",
        expected_shot_count=2,
        shots=[
            GoldenShotExpectation(
                shot_index=1,
                expected_start_seconds=0,
                expected_end_seconds=3.2,
                required_prompt_terms=["快速推近", "完全遮挡镜头", "浅绿色模糊末帧"],
                forbidden_prompt_terms=["切换到丝带特写"],
                required_motion_terms=["屏占比增至100%"],
                min_visual_beat_count=1,
                max_visual_beat_count=1,
                min_motion_phase_count=1,
                expected_transition_kind="foreground_occlusion",
            ),
            GoldenShotExpectation(
                shot_index=2,
                expected_start_seconds=3.2,
                expected_end_seconds=9.2,
                required_prompt_terms=["户外稻田"],
                min_visual_beat_count=1,
                max_visual_beat_count=1,
                expected_transition_kind="none",
            ),
        ],
    )


def test_golden_report_passes_stable_shot_motion_and_transition_baseline() -> None:
    result = evaluate_golden_report(_build_report(), _build_expectation())

    assert result.passed is True
    assert result.score == 100
    assert result.findings == []


def test_golden_report_detects_prompt_and_absolute_timeline_regressions() -> None:
    report = _build_report()
    first_shot = report.shots[0].model_copy(
        update={"prompt": "室内人物背对镜头，随后画面切换到丝带特写。"}
    )
    second_shot = report.shots[1].model_copy(
        update={"start_seconds": 0, "content_start_seconds": 0}
    )
    drifted = report.model_copy(update={"shots": [first_shot, second_shot]})

    result = evaluate_golden_report(drifted, _build_expectation())
    codes = {finding.code for finding in result.findings}

    assert result.passed is False
    assert result.error_count >= 4
    assert "timeline_overlap" in codes
    assert "shot_start_drift" in codes
    assert "required_prompt_term_missing" in codes
    assert "forbidden_prompt_term_present" in codes


def test_quality_fingerprint_ignores_report_identity_and_generation_time() -> None:
    report = _build_report()
    changed_identity = report.model_copy(
        update={
            "analysis_id": uuid4(),
            "video_id": uuid4(),
            "generated_at": datetime.now(UTC) + timedelta(days=1),
        }
    )

    assert report_quality_fingerprint(report) == report_quality_fingerprint(changed_identity)


def test_expectation_rejects_duplicate_shot_definitions() -> None:
    with pytest.raises(ValidationError, match="不能重复定义"):
        GoldenAnalysisExpectation(
            sample_id="duplicate-shot",
            name="重复分镜",
            expected_shot_count=2,
            shots=[
                GoldenShotExpectation(shot_index=1),
                GoldenShotExpectation(shot_index=1),
            ],
        )


def test_quality_cli_writes_a_machine_readable_result(tmp_path) -> None:
    expectation_path = tmp_path / "expectation.json"
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "result.json"
    expectation_path.write_text(
        _build_expectation().model_dump_json(indent=2),
        encoding="utf-8",
    )
    report_path.write_text(
        _build_report().model_dump_json(indent=2),
        encoding="utf-8",
    )

    exit_code = run(
        [
            "--expectation",
            str(expectation_path),
            "--report",
            str(report_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert '"passed": true' in output_path.read_text(encoding="utf-8")
