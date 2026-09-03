from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from viral_dna_api import media as media_module
from viral_dna_api.ai.catalog import load_model_plan
from viral_dna_api.ai.contracts import ModelRequest, ProviderResult
from viral_dna_api.ai.router import ModelRouter
from viral_dna_api.ai.shot_segmentation import (
    ShotSegmentationService,
    apply_model_selection,
)
from viral_dna_api.media import (
    MediaProcessingError,
    MediaProcessor,
    RawSceneScore,
    boundaries_from_candidates,
    boundary_evidence_timestamps,
    last_safe_frame_timestamp,
    merge_scene_candidates,
    parse_scene_score_metadata,
    shot_motion_evidence_timestamps,
)
from viral_dna_api.models import (
    AnalysisJob,
    AnalysisMode,
    AnalysisProfile,
    MediaEvidence,
    MediaMetadata,
    ModelRunStatus,
    ModelTask,
    ModelUsage,
    SceneBoundaryCandidate,
    SegmentationMetadata,
    ShotBoundaryDecision,
    ShotSegmentationSelection,
    SourceType,
    Video,
)
from viral_dna_api.store import InMemoryStore


class FakeSegmentationProvider:
    provider_id = "dashscope"

    def __init__(self, *, invalid_candidate: bool = False) -> None:
        self.calls = 0
        self.invalid_candidate = invalid_candidate

    async def generate(self, request: ModelRequest, response_schema) -> ProviderResult:
        self.calls += 1
        assert request.task == ModelTask.SHOT_SEGMENTATION
        assert len(request.image_paths) == 5
        assert len(request.image_labels) == 5
        assert "远前、近前、近后、远后" in request.image_labels[1]
        candidate_ids = (
            ["candidate_999"]
            if self.invalid_candidate
            else ["candidate_001", "candidate_002", "candidate_003"]
        )
        selection = response_schema(
            candidate_reviews=[
                ShotBoundaryDecision(
                    candidate_id=candidate_id,
                    before_description="候选前为原叙事画面",
                    after_description="候选后为新的主体或场景",
                    decision="keep",
                    confidence=0.93,
                    reason=(
                        "主体或稳定构图发生明确变化"
                        if candidate_id != "candidate_002"
                        else "同一运镜中的短暂过渡，不形成新镜头"
                    ),
                    semantic_group_before=(
                        "情境/钩子"
                        if candidate_id in {"candidate_001", "candidate_999"}
                        else "产品/主体演示"
                    ),
                    semantic_group_after=(
                        "产品/主体演示" if candidate_id != "candidate_003" else "结果/生活方式"
                    ),
                    progressive_motion=candidate_id == "candidate_002",
                )
                for candidate_id in candidate_ids
            ],
            summary="行走、产品展示、湖边使用和结尾卡构成四个语义段落",
            confidence=0.92,
        )
        usage = ModelUsage(
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            image_count=len(request.image_paths),
        )
        return ProviderResult(
            data=selection,
            usage=usage,
            requested_model=request.target.model,
            resolved_model=request.target.model,
            provider_request_id="segmentation-request-1",
            latency_ms=70,
            raw_content=selection.model_dump_json(),
        )


def _build_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_cost_micros: int | None = None,
) -> tuple[Video, AnalysisJob, MediaEvidence]:
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    monkeypatch.setenv("VIRAL_DNA_VLM_MODEL_ALIAS", "qwen37")
    plan = load_model_plan(AnalysisProfile.BALANCED)
    assert plan is not None

    video = Video(
        source_type=SourceType.UPLOAD,
        title="混合分镜测试",
        sha256="a" * 64,
    )
    analysis = AnalysisJob(
        video_id=video.id,
        analysis_mode=AnalysisMode.MODEL,
        simulated=False,
        model_plan=plan,
        max_cost_micros=max_cost_micros,
    )
    artifact_root = storage_root / "analyses" / str(analysis.id)
    segmentation_dir = artifact_root / "segmentation"
    segmentation_dir.mkdir(parents=True)
    context_url = f"/api/v1/analyses/{analysis.id}/artifacts/segmentation/context-sheet.jpg"
    (segmentation_dir / "context-sheet.jpg").write_bytes(b"context-jpeg")

    candidates = []
    candidate_specs = [
        (3.6, 0.042, False),
        (6.267, 0.49, False),
        (8.783, 0.233, False),
        (15.35, 0.803, True),
    ]
    for index, (timestamp, score, hard) in enumerate(candidate_specs, 1):
        candidate_id = f"candidate_{index:03d}"
        filename = f"{candidate_id}.jpg"
        (segmentation_dir / filename).write_bytes(f"jpeg-{candidate_id}".encode())
        url = f"/api/v1/analyses/{analysis.id}/artifacts/segmentation/{filename}"
        candidates.append(
            SceneBoundaryCandidate(
                id=candidate_id,
                timestamp_seconds=timestamp,
                score=score,
                methods=["adjacent_scene_score"],
                hard_boundary=hard,
                evidence_frame_urls=[url],
                evidence_timestamps=[
                    round(timestamp - 0.75, 3),
                    round(timestamp - 0.12, 3),
                    round(timestamp + 0.12, 3),
                    round(timestamp + 0.75, 3),
                ],
                comparison_image_url=url,
            )
        )

    evidence = MediaEvidence(
        processor_version="test-hybrid-v2",
        metadata=MediaMetadata(
            duration_seconds=18.342,
            width=720,
            height=1280,
            fps=55.043,
            format_name="mp4",
            video_codec="h264",
            has_audio=True,
            size_bytes=100,
            sha256="a" * 64,
            aspect_ratio="9:16",
        ),
        proxy_url=f"/api/v1/analyses/{analysis.id}/artifacts/proxy.mp4",
        manifest_url=f"/api/v1/analyses/{analysis.id}/artifacts/manifest.json",
        shots=[],
        segmentation=SegmentationMetadata(
            detector_version="test-detector-v2",
            candidate_count=len(candidates),
            candidates=candidates,
            context_sheet_url=context_url,
            context_timestamps=[1.0, 4.0, 7.0, 10.0, 13.0, 16.0],
            program_boundaries=[0.0, 15.35, 18.342],
            selected_candidate_ids=["candidate_004"],
            final_boundaries=[0.0, 15.35, 18.342],
            final_shot_count=2,
        ),
    )
    return video, analysis, evidence


def test_scene_metadata_is_parsed_and_candidates_are_nms_merged() -> None:
    output = (
        "[metadata] frame:0 pts_time:3.500\n"
        "[metadata] lavfi.scene_score=0.030347\n"
        "[metadata] frame:1 pts_time:3.600\n"
        "[metadata] lavfi.scene_score=0.042295\n"
        "[metadata] frame:2 pts_time:15.350\n"
        "[metadata] lavfi.scene_score=0.803484\n"
    )
    adjacent = parse_scene_score_metadata(
        output,
        method="adjacent_scene_score",
        hard_threshold=0.24,
    )
    temporal = [
        RawSceneScore(4.0, 0.21, "temporal_window_scene_score"),
        RawSceneScore(9.0, 0.23, "temporal_window_scene_score"),
    ]
    candidates = merge_scene_candidates(
        [*adjacent, *temporal],
        duration_seconds=18.342,
    )

    assert [item.timestamp_seconds for item in candidates] == [3.5, 9.0, 15.35]
    assert candidates[0].methods == [
        "adjacent_scene_score",
        "temporal_window_scene_score",
    ]
    assert candidates[-1].hard_boundary is True
    assert boundaries_from_candidates(candidates, 18.342) == [0.0, 15.35, 18.342]


def test_boundary_evidence_uses_near_and_far_frames_with_safe_clamping() -> None:
    assert boundary_evidence_timestamps(6.267, 18.342) == (
        5.517,
        6.147,
        6.387,
        7.017,
    )


def test_boundary_evidence_clamps_to_last_decodable_frame() -> None:
    assert boundary_evidence_timestamps(17.533, 18.167, fps=30) == (
        16.783,
        17.413,
        17.653,
        18.133,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output_payload",
    [None, b"not-an-image"],
    ids=["missing", "invalid"],
)
async def test_image_command_rejects_missing_or_invalid_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_payload: bytes | None,
) -> None:
    output_path = tmp_path / "candidate_018.jpg"

    async def fake_run_command(
        args: list[str],
        *,
        timeout_seconds: float,
    ) -> tuple[str, str]:
        del args, timeout_seconds
        if output_payload is not None:
            output_path.write_bytes(output_payload)
        return "", ""

    monkeypatch.setattr(media_module, "_run_command", fake_run_command)

    with pytest.raises(MediaProcessingError, match="candidate_018"):
        await media_module._run_image_command(
            ["ffmpeg", str(output_path)],
            output_path,
            timeout_seconds=60,
            context="生成分镜边界证据图 candidate_018",
        )

    assert not output_path.exists()


@pytest.mark.asyncio
async def test_single_frame_extraction_retries_one_frame_earlier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    async def fake_run_image_command(
        args: list[str],
        output_path: Path,
        *,
        timeout_seconds: float,
        context: str,
    ) -> None:
        del output_path, timeout_seconds, context
        attempts.append(args[args.index("-ss") + 1])
        if len(attempts) == 1:
            raise MediaProcessingError(
                "frame_extract_failed",
                "FFmpeg 未生成有效图片",
                retryable=True,
            )

    monkeypatch.setattr(media_module, "_run_image_command", fake_run_image_command)

    resolved = await MediaProcessor()._extract_jpeg_frame(
        tmp_path / "proxy.mp4",
        18.135,
        tmp_path / "frame.jpg",
        scale_filter=None,
        quality=2,
        timeout_seconds=60,
        context="测试末帧回退",
        fps=30,
    )

    assert resolved == pytest.approx(18.102)
    assert attempts == ["18.135", "18.102"]


@pytest.mark.asyncio
async def test_keyframe_extraction_excludes_transition_from_shot_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    async def fake_run_command(
        args: list[str],
        *,
        timeout_seconds: float,
    ) -> tuple[str, str]:
        del timeout_seconds
        commands.append(args)
        return "", ""

    monkeypatch.setattr(media_module, "_run_command", fake_run_command)
    monkeypatch.setattr(media_module, "_image_file_is_valid", lambda _: True)
    candidate = SceneBoundaryCandidate(
        id="candidate_001",
        timestamp_seconds=3.167,
        score=0.084,
        methods=["adjacent_scene_score"],
        evidence_timestamps=[2.417, 3.047, 3.287, 3.917],
        selected_by_model=True,
        model_decision="keep",
        transition_start_seconds=3.047,
        stable_new_scene_seconds=3.917,
    )

    shots = await MediaProcessor().extract_keyframes(
        tmp_path / "proxy.mp4",
        [0, 3.167, 9.2],
        tmp_path / "shots",
        UUID("00000000-0000-0000-0000-000000000001"),
        boundary_candidates=[candidate],
        duration_seconds=9.2,
        fps=30,
    )

    assert shots[0].content_end_seconds == pytest.approx(3.047)
    assert shots[0].outgoing_transition_start_seconds == pytest.approx(3.047)
    assert shots[0].outgoing_transition_end_seconds == pytest.approx(3.917)
    assert shots[0].analysis_clip_start_seconds == pytest.approx(0)
    assert shots[0].analysis_clip_end_seconds == pytest.approx(3.917)
    assert shots[0].analysis_clip_url.endswith("/shots/shot_001_analysis.mp4")
    assert any(value > 3.167 for value in shots[0].motion_timestamps)
    assert shots[1].content_start_seconds == pytest.approx(3.917)
    assert shots[1].incoming_transition_start_seconds == pytest.approx(3.047)
    assert shots[1].incoming_transition_end_seconds == pytest.approx(3.917)
    assert shots[1].evidence_timestamps[0] > 3.917
    assert all(value >= 3.917 for value in shots[1].evidence_timestamps)
    assert len(commands) == 4
    assert any(command[-1].endswith("shot_001_analysis.mp4") for command in commands)
    assert any(command[-1].endswith("shot_001_motion_09.jpg") for command in commands)
    image_commands = [command for command in commands if "-filter_complex" in command]
    assert len(image_commands) == 2
    assert all(
        "format=yuvj420p" in command[command.index("-filter_complex") + 1]
        for command in image_commands
    )
    assert boundary_evidence_timestamps(0.45, 1.0, fps=30) == (
        0.001,
        0.33,
        0.57,
        0.966,
    )


def test_motion_evidence_samples_content_and_outgoing_transition() -> None:
    timestamps = shot_motion_evidence_timestamps(
        0,
        3.047,
        transition_start_seconds=3.047,
        transition_end_seconds=3.917,
    )

    assert len(timestamps) == 9
    assert timestamps == sorted(timestamps)
    assert timestamps[0] == pytest.approx(0.152)
    assert timestamps[5] == pytest.approx(2.895)
    assert timestamps[6] > 3.047
    assert timestamps[-1] < 3.917


def test_last_shot_motion_evidence_is_clamped_to_last_decodable_frame() -> None:
    maximum = last_safe_frame_timestamp(18.167, 30)
    timestamps = shot_motion_evidence_timestamps(
        17.533,
        18.167,
        maximum_seconds=maximum,
    )

    assert maximum == pytest.approx(18.133)
    assert timestamps == [17.565, 17.66, 17.787, 17.913, 18.04, 18.133]


@pytest.mark.asyncio
async def test_segmentation_selection_is_metered_cached_and_keeps_hard_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence = _build_inputs(tmp_path, monkeypatch)
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    provider = FakeSegmentationProvider()
    service = ShotSegmentationService(
        repository,
        router=ModelRouter({"dashscope": provider}),
    )

    first = await service.analyze(analysis=analysis, video=video, evidence=evidence)

    assert first.segmentation.verified_by_model is True
    assert first.segmentation.selected_candidate_ids == [
        "candidate_001",
        "candidate_003",
        "candidate_004",
    ]
    assert first.segmentation.final_boundaries == [
        0.0,
        3.6,
        8.783,
        15.35,
        18.342,
    ]
    assert first.segmentation.final_shot_count == 4
    accepted = first.segmentation.candidates[0]
    assert accepted.transition_start_seconds == pytest.approx(3.48)
    assert accepted.stable_new_scene_seconds == pytest.approx(4.35)
    hard = first.segmentation.candidates[-1]
    assert hard.transition_start_seconds == pytest.approx(15.35)
    assert hard.stable_new_scene_seconds == pytest.approx(15.35)
    rejected = first.segmentation.candidates[1]
    assert rejected.selected_by_model is False
    assert rejected.model_confidence == pytest.approx(0.93)
    assert rejected.model_decision == "keep"
    assert rejected.model_consistency_adjusted is True
    assert "一致性校验" in (rejected.model_reason or "")
    assert "candidate_002" in (first.segmentation.model_summary or "")
    assert provider.calls == 1
    assert first.cost_summary.measured_cost_micros == 6000

    second = await service.analyze(analysis=analysis, video=video, evidence=evidence)

    assert second.segmentation.final_shot_count == 4
    assert provider.calls == 1
    runs = await repository.list_model_runs(analysis.id)
    assert [run.status for run in runs] == [
        ModelRunStatus.COMPLETED,
        ModelRunStatus.CACHED,
    ]


@pytest.mark.asyncio
async def test_unknown_candidate_from_model_is_rejected_with_program_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence = _build_inputs(tmp_path, monkeypatch)
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    provider = FakeSegmentationProvider(invalid_candidate=True)
    service = ShotSegmentationService(
        repository,
        router=ModelRouter({"dashscope": provider}),
    )

    outcome = await service.analyze(analysis=analysis, video=video, evidence=evidence)

    assert outcome.segmentation.verified_by_model is False
    assert outcome.segmentation.final_boundaries == [0.0, 15.35, 18.342]
    assert "不存在的候选边界" in outcome.warnings[0]
    runs = await repository.list_model_runs(analysis.id)
    assert runs[0].status == ModelRunStatus.FAILED
    assert runs[0].measured_cost_micros == 6000


@pytest.mark.asyncio
async def test_segmentation_budget_blocks_provider_before_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence = _build_inputs(
        tmp_path,
        monkeypatch,
        max_cost_micros=1,
    )
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    provider = FakeSegmentationProvider()
    service = ShotSegmentationService(
        repository,
        router=ModelRouter({"dashscope": provider}),
    )

    outcome = await service.analyze(analysis=analysis, video=video, evidence=evidence)

    assert outcome.segmentation.verified_by_model is False
    assert provider.calls == 0
    runs = await repository.list_model_runs(analysis.id)
    assert runs[0].status == ModelRunStatus.BLOCKED
    assert "成本上限" in outcome.warnings[0]


def test_segmentation_requires_a_review_for_every_soft_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, evidence = _build_inputs(tmp_path, monkeypatch)
    assert evidence.segmentation is not None
    incomplete = ShotSegmentationSelection(
        candidate_reviews=[
            ShotBoundaryDecision(
                candidate_id="candidate_001",
                before_description="人物中景",
                after_description="稳定产品特写",
                decision="keep",
                confidence=0.9,
                reason="主体与稳定构图持续改变",
                semantic_group_before="情境/钩子",
                semantic_group_after="产品/主体演示",
                progressive_motion=False,
            )
        ],
        summary="仅返回了部分候选",
        confidence=0.5,
    )

    with pytest.raises(ValueError, match="缺少候选边界审核结果"):
        apply_model_selection(
            evidence.segmentation,
            incomplete,
            evidence.metadata.duration_seconds,
        )
