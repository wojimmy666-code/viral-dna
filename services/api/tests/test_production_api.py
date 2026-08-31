from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from viral_dna_api import main
from viral_dna_api.generation import generate_simulated_images
from viral_dna_api.image_generation.contracts import (
    ImageGenerationRequest,
    build_reference_inputs,
)
from viral_dna_api.image_generation.gateway import _compiled_prompt, _negative_prompt
from viral_dna_api.image_generation.identity_policy import (
    build_input_manifest,
    policy_snapshot,
    validate_identity_bindings,
)
from viral_dna_api.models import (
    AnalysisJob,
    AnalysisRecord,
    AnalysisStage,
    ApprovalDecision,
    CandidateApprovalRequest,
    CandidateBatchLifecycleRequest,
    CandidateSelectRequest,
    GenerationCandidateArchiveReason,
    GenerationCandidateStatus,
    ImageExecutionMode,
    ImageGenerationCreate,
    MediaEvidence,
    MediaMetadata,
    ProductionAdvanceRequest,
    ProductionChangeKind,
    ProductionProjectCreate,
    ProductionPromptSyncRequest,
    ProductionStep,
    ReferenceAssetCreate,
    ReferenceAssetType,
    SceneBoundaryCandidate,
    SegmentationMetadata,
    ShotOutputModeUpdateRequest,
    ShotPlan,
    ShotPlanUpdate,
    ShotVideoApprovalRevokeRequest,
    ShotVisualBeatCreate,
    SourceType,
    Video,
    VideoClipAudioMode,
    VideoClipPreparationStatus,
    VideoClipPreparationUpdate,
    VideoGenerationCreate,
    VideoQualityStatus,
    VideoStatus,
    WorkflowItemStatus,
)
from viral_dna_api.pipeline import build_simulated_report
from viral_dna_api.production import (
    ProductionService,
    ProductionServiceError,
    inspect_reference_image,
)
from viral_dna_api.production_media import VideoInspectionResult
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.store import InMemoryStore
from viral_dna_api.video_generation import VideoGenerationGateway
from viral_dna_api.workspace import WorkspaceManager


@pytest.fixture(autouse=True)
def isolate_production_image_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    monkeypatch.delenv("VIRAL_DNA_IMAGE_GENERATION_ENABLED", raising=False)


def image_bytes(
    image_format: str = "PNG",
    *,
    size: tuple[int, int] = (640, 960),
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (94, 78, 219)).save(output, format=image_format)
    return output.getvalue()


def write_fake_frame(
    source_path: Path,
    timestamp_seconds: float,
    output_path: Path,
) -> None:
    assert source_path.is_file()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    color = (min(255, round(timestamp_seconds * 20) + 40), 92, 180)
    Image.new("RGB", (720, 1280), color).save(output_path, "JPEG")


class FakeFrameProcessor:
    async def extract_frame(
        self,
        source_path: Path,
        timestamp_seconds: float,
        output_path: Path,
    ) -> None:
        await asyncio.to_thread(
            write_fake_frame,
            source_path,
            timestamp_seconds,
            output_path,
        )


class FakeSourceVideoProcessor(FakeFrameProcessor):
    async def extract_video_clip(
        self,
        source_path: Path,
        output_path: Path,
        *,
        start_seconds: float,
        end_seconds: float,
    ) -> None:
        assert await asyncio.to_thread(source_path.is_file)
        assert end_seconds > start_seconds >= 0
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            output_path.write_bytes,
            b"\x00\x00\x00\x18ftypmp42viral-dna-source-segment"
        )


@pytest.mark.parametrize("legacy_mode", ["source_images", "generated_images"])
def test_legacy_shot_output_modes_use_the_unified_image_route(legacy_mode: str) -> None:
    payload = ShotOutputModeUpdateRequest(
        expected_revision_id=uuid4(),
        shot_plan_ids=[uuid4()],
        output_mode=legacy_mode,
    )

    assert payload.output_mode.value == "image_to_video"


class FakeStillVideoProcessor:
    async def create_still_video(
        self,
        image_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        width: int,
        height: int,
    ) -> None:
        await asyncio.to_thread(
            write_fake_video,
            image_path,
            output_path,
            duration_seconds,
            width,
            height,
        )


def write_fake_video_cover(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (360, 640), (42, 48, 68)).save(output_path, "WEBP")


class FakeVideoInspector:
    async def inspect(
        self,
        source_path: Path,
        cover_path: Path,
        *,
        cover_timestamp_seconds: float,
        expected_width: int | None,
        expected_height: int | None,
        expected_duration_seconds: float | None,
    ) -> VideoInspectionResult:
        del source_path
        await asyncio.to_thread(write_fake_video_cover, cover_path)
        duration = float(expected_duration_seconds or 2.5)
        metadata = MediaMetadata(
            duration_seconds=duration,
            width=expected_width or 1080,
            height=expected_height or 1920,
            fps=24,
            format_name="mp4",
            video_codec="h264",
            has_audio=False,
            size_bytes=1,
            sha256="a" * 64,
            aspect_ratio="9:16",
        )
        return VideoInspectionResult(
            metadata=metadata,
            cover_timestamp_seconds=min(cover_timestamp_seconds, duration - 0.04),
            quality_status="passed",
            quality_report={
                "schema_version": "viral-dna-video-quality/v2",
                "status": "passed",
                "summary": "测试视频基础技术质检通过。",
                "automated_checks": {
                    "file_integrity": {"status": "passed"},
                    "duration": {"status": "passed"},
                    "dimensions": {"status": "passed"},
                },
                "warnings": [],
            },
        )


def write_fake_video(
    image_path: Path,
    output_path: Path,
    duration_seconds: float,
    width: int,
    height: int,
) -> None:
    assert image_path.is_file()
    assert duration_seconds > 0
    assert width > 0 and height > 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        b"\x00\x00\x00\x18ftypmp42viral-dna-video-foundation"
    )


class FakeRealImageGateway:
    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    async def generate(
        self,
        project,
        plan,
        revision_id,
        bindings,
        assets,
        *,
        candidate_count,
        source_path,
        input_mode,
        execution_mode,
        model_alias,
        allow_unknown_cost,
        seed=None,
        reuse_cache=True,
        run_id=None,
        cancel_event=None,
    ):
        del model_alias, execution_mode, allow_unknown_cost, reuse_cache, cancel_event
        run, candidates = await asyncio.to_thread(
            generate_simulated_images,
            self.workspace,
            project,
            plan,
            revision_id,
            bindings,
            assets,
            candidate_count=candidate_count,
            source_path=source_path,
            input_mode=input_mode,
            run_id=run_id,
        )
        references = build_reference_inputs(
            bindings,
            assets,
            resolve_path=self.workspace.resolve,
        )
        identity_policy = validate_identity_bindings(bindings, assets)
        request = ImageGenerationRequest(
            project=project,
            shot=plan,
            revision_id=revision_id,
            input_mode=input_mode,
            source_path=source_path,
            source_sha256=None,
            references=references,
            candidate_count=candidate_count,
            execution_mode=ImageExecutionMode.REMOTE_API,
            seed=seed,
        )
        input_path = self.workspace.resolve(run.input_snapshot_relative_path)
        filesystem_input = (
            Path(chr(92) * 2 + "?" + chr(92) + str(input_path))
            if os.name == "nt"
            else input_path
        )
        input_payload = json.loads(filesystem_input.read_text(encoding="utf-8"))
        input_payload.update(
            {
                "schema_version": "viral-dna-image-generation/v2",
                "prompt": {
                    "positive": _compiled_prompt(request),
                    "negative": _negative_prompt(request),
                },
                "references": [
                    {
                        "asset_id": str(item.asset_id),
                        "name": item.name,
                        "role": item.role,
                        "weight": item.weight,
                        "crop_hint": item.crop_hint,
                        "notes": item.notes,
                        "sha256": item.sha256,
                    }
                    for item in references
                ],
                "identity_policy": policy_snapshot(state=identity_policy),
                "input_manifest": build_input_manifest(
                    source_present=(
                        input_mode.value == "keyframe_edit"
                        and bool(
                            source_path
                            or plan.source_keyframe_url
                            or plan.source_keyframe_relative_path
                        )
                    ),
                    references=references,
                ),
            }
        )
        filesystem_input.write_text(
            json.dumps(input_payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        if seed is not None:
            run = run.model_copy(
                update={
                    "request_payload": {
                        **run.request_payload,
                        "seed": seed,
                    }
                }
            )
        run = run.model_copy(
            update={
                "id": run_id or run.id,
                "provider": "test_image_provider",
                "model": "test-image-model",
                "model_snapshot": "test-image-model-v1",
                "execution_mode": ImageExecutionMode.REMOTE_API,
                "adapter_id": "test-image-adapter",
                "adapter_version": "test-v1",
                "schema_version": "viral-dna-image-generation/v2",
                "prompt_version": "shot-image-v3",
                "execution_summary": {
                    "identity_policy": input_payload["identity_policy"],
                    "input_manifest": input_payload["input_manifest"],
                },
            }
        )
        return run, [
            candidate.model_copy(update={"generation_run_id": run.id})
            for candidate in candidates
        ]


TERMINAL_GENERATION_STATUSES = {
    "completed",
    "cached",
    "failed",
    "blocked",
    "cancelled",
}


async def wait_for_generation(service: ProductionService, run_id: UUID):
    for _ in range(200):
        run = await service.get_generation_run(run_id)
        if run.status in TERMINAL_GENERATION_STATUSES:
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("图片生成任务未在测试超时内完成")


def wait_for_generation_http(client: TestClient, run_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/generation-runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] in TERMINAL_GENERATION_STATUSES:
            return run
        time.sleep(0.01)
    raise AssertionError("图片生成任务未在测试超时内完成")


async def seed_completed_analysis(repository):
    record_id = uuid4()
    video = Video(
        id=uuid4(),
        record_id=record_id,
        source_type=SourceType.UPLOAD,
        original_filename="source.mp4",
        title="参考视频",
        status=VideoStatus.COMPLETED,
    )
    analysis = AnalysisJob(
        id=uuid4(),
        record_id=record_id,
        video_id=video.id,
        stage=AnalysisStage.COMPLETED,
        progress=100,
        message="分析完成",
        simulated=True,
    )
    record = AnalysisRecord(
        id=record_id,
        name="参考视频",
        video_id=video.id,
        source_type=video.source_type,
        latest_analysis_id=analysis.id,
        status=VideoStatus.COMPLETED,
    )
    report = build_simulated_report(video, analysis)
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    await repository.save_record(record)
    await repository.save_report(report)
    return record, video, analysis, report


async def seed_updated_prompt_analysis(repository, record, analysis, report):
    next_analysis = analysis.model_copy(
        update={
            "id": uuid4(),
            "message": "重新分析完成",
        }
    )
    next_image_prompt = "更新后的画面提示词：丝带贴近镜头并完全遮挡画面。"
    next_shot_prompt = "更新后的镜头提示词：镜头持续推近丝带，直至丝带覆盖整个画面。"
    source_shot = report.shots[0]
    next_visual_beats = list(source_shot.visual_beats)
    if next_visual_beats:
        next_visual_beats[0] = next_visual_beats[0].model_copy(
            update={"image_prompt": next_image_prompt}
        )
    next_shots = list(report.shots)
    next_shots[0] = source_shot.model_copy(
        update={
            "prompt": next_shot_prompt,
            "action": "丝带向镜头推进并形成满屏遮挡",
            "camera": "连续推进至极近特写并穿过丝带",
            "visual_beats": next_visual_beats,
        }
    )
    next_prompt_shots = list(report.prompt_package.shots)
    next_prompt_shots[0] = next_prompt_shots[0].model_copy(
        update={"prompt": next_image_prompt}
    )
    next_prompt_package = report.prompt_package.model_copy(
        update={
            "id": uuid4(),
            "shots": next_prompt_shots,
        }
    )
    next_report = report.model_copy(
        update={
            "analysis_id": next_analysis.id,
            "shots": next_shots,
            "prompt_package": next_prompt_package,
        }
    )
    await repository.add_analysis(next_analysis)
    await repository.save_report(next_report)
    await repository.save_record(
        record.model_copy(update={"latest_analysis_id": next_analysis.id})
    )
    return next_analysis, next_report


def isolated_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository=None,
    media_processor=None,
) -> tuple[ProductionService, object]:
    root = tmp_path / "workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    monkeypatch.delenv("VIRAL_DNA_IMAGE_GENERATION_ENABLED", raising=False)
    workspace = WorkspaceManager()
    repository = repository or InMemoryStore()
    return ProductionService(
        repository,
        workspace,
        image_gateway=FakeRealImageGateway(workspace),
        media_processor=media_processor,
    ), repository


def test_project_default_output_follows_source_video_ratio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, video, analysis, _ = await seed_completed_analysis(repository)
        await repository.save_video(
            video.model_copy(update={"width": 1920, "height": 1080})
        )

        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )

        assert detail.project.output_aspect_ratio == "16:9"
        assert detail.project.output_width == 1920
        assert detail.project.output_height == 1080

    asyncio.run(scenario())


def test_analysis_update_preview_and_prompt_only_sync_preserve_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, report = await seed_completed_analysis(repository)
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        plans = await repository.list_shot_plans(detail.project.id)
        retained_candidate_id = uuid4()
        manually_edited = plans[1].model_copy(
            update={
                "video_prompt": "用户手工修改的视频提示词",
                "approved_image_candidate_id": retained_candidate_id,
                "image_status": WorkflowItemStatus.APPROVED,
            }
        )
        await repository.save_shot_plan(manually_edited)
        next_analysis, next_report = await seed_updated_prompt_analysis(
            repository,
            record,
            analysis,
            report,
        )

        preview = await service.preview_analysis_update(detail.project.id)

        assert preview.update_available is True
        assert preview.compatible is True
        assert preview.target_analysis_id == next_analysis.id
        assert preview.changed_field_count >= 2
        first_video = next(
            field
            for shot in preview.shots
            if shot.index == 1
            for field in shot.fields
            if field.field_key == "video_prompt"
        )
        assert first_video.suggested_choice == "use_latest"
        second_video = next(
            field
            for shot in preview.shots
            if shot.index == 2
            for field in shot.fields
            if field.field_key == "video_prompt"
        )
        assert second_video.manually_edited is True
        assert second_video.suggested_choice == "keep_current"

        synced = await service.sync_analysis_prompts(
            detail.project.id,
            ProductionPromptSyncRequest(
                expected_revision_id=detail.project.current_revision_id,
                target_analysis_id=next_analysis.id,
            ),
        )
        synced_plans = await repository.list_shot_plans(detail.project.id)

        assert synced.project.base_analysis_id == analysis.id
        assert synced.project.prompt_source_analysis_id == next_analysis.id
        assert synced.project.source_prompt_package_id == next_report.prompt_package.id
        assert synced.current_revision.change_kind == ProductionChangeKind.ANALYSIS_PROMPTS_SYNCED
        assert "连续推进至极近特写" in synced_plans[0].video_prompt
        assert synced_plans[1].video_prompt == "用户手工修改的视频提示词"
        assert synced_plans[1].approved_image_candidate_id == retained_candidate_id
        assert synced_plans[1].image_status == WorkflowItemStatus.APPROVED
        assert (await service.preview_analysis_update(detail.project.id)).update_available is False

    asyncio.run(scenario())


def test_prompt_sync_preserves_structure_when_analysis_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, report = await seed_completed_analysis(repository)
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        next_analysis, next_report = await seed_updated_prompt_analysis(
            repository,
            record,
            analysis,
            report,
        )
        shortened_report = next_report.model_copy(
            update={
                "shots": next_report.shots[:-1],
                "prompt_package": next_report.prompt_package.model_copy(
                    update={"shots": next_report.prompt_package.shots[:-1]}
                ),
            }
        )
        await repository.save_report(shortened_report)

        preview = await service.preview_analysis_update(detail.project.id)

        assert preview.update_available is True
        assert preview.compatible is True
        assert preview.structural_change_detected is True
        synced = await service.sync_analysis_prompts(
            detail.project.id,
            ProductionPromptSyncRequest(
                expected_revision_id=detail.project.current_revision_id,
                target_analysis_id=next_analysis.id,
            ),
        )
        synced_plans = await repository.list_shot_plans(detail.project.id)
        remaining = await service.preview_analysis_update(detail.project.id)

        assert synced.project.base_analysis_id == analysis.id
        assert synced.project.prompt_source_analysis_id == next_analysis.id
        assert len(synced_plans) == len(report.shots)
        assert remaining.update_available is True
        assert remaining.compatible is False
        assert remaining.structural_change_detected is True

    asyncio.run(scenario())


def test_legacy_multi_scene_prompt_expands_into_ordered_visual_beats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(
            tmp_path,
            monkeypatch,
            media_processor=FakeFrameProcessor(),
        )
        record, video, analysis, _ = await seed_completed_analysis(repository)
        source_path = tmp_path / "legacy-multi-scene.mp4"
        source_path.write_bytes(b"test-video")
        await repository.save_video(
            video.model_copy(update={"stored_path": str(source_path)})
        )
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        original = (await service.list_shots(detail.project.id))[0].plan
        revision_count = detail.revision_count
        legacy = ShotPlan.model_validate(
            {
                **original.model_dump(mode="python"),
                "image_prompt": (
                    "第一部分：室内近景，女子背对镜头。"
                    "第二部分：户外远景，少女坐在木质平台上。"
                ),
                "visual_beats": [],
            }
        )
        assert legacy.visual_beats[0].source_origin == "legacy"
        await repository.save_shot_plan(legacy)

        migrated = (await service.list_shots(detail.project.id))[0].plan

        assert [item.index for item in migrated.visual_beats] == [1, 2]
        assert [item.title for item in migrated.visual_beats] == ["第一部分", "第二部分"]
        assert migrated.visual_beats[0].image_prompt.startswith("室内近景")
        assert migrated.visual_beats[1].image_prompt.startswith("户外远景")
        assert migrated.visual_beats[0].transition_to_next_type == "model_generated"
        assert migrated.visual_beats[1].transition_to_next_type == "cut"
        assert (
            migrated.visual_beats[0].source_frame_url
            != migrated.visual_beats[1].source_frame_url
        )
        assert (
            migrated.visual_beats[0].source_frame_relative_path
            != migrated.visual_beats[1].source_frame_relative_path
        )
        assert all(
            item.source_origin == "auto_extract" for item in migrated.visual_beats
        )
        assert all(item.source_frame_sha256 for item in migrated.visual_beats)
        assert (
            migrated.visual_beats[0].source_timestamp_seconds
            < migrated.visual_beats[1].source_timestamp_seconds
        )
        assert (await service.get_project(detail.project.id)).revision_count == (
            revision_count + 1
        )

    asyncio.run(scenario())


def test_existing_duplicate_visual_beat_frames_are_repaired_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(
            tmp_path,
            monkeypatch,
            media_processor=FakeFrameProcessor(),
        )
        record, video, analysis, _ = await seed_completed_analysis(repository)
        source_path = tmp_path / "duplicate-visual-beats.mp4"
        source_path.write_bytes(b"test-video")
        await repository.save_video(
            video.model_copy(update={"stored_path": str(source_path)})
        )
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        original = (await service.list_shots(detail.project.id))[0].plan
        duplicate_url = (
            f"/api/v1/analyses/{analysis.id}/artifacts/shots/shot_001.jpg"
        )
        first = original.visual_beats[0].model_copy(
            update={
                "index": 1,
                "title": "第一部分",
                "start_ratio": 0,
                "end_ratio": 0.5,
                "source_frame_url": duplicate_url,
                "source_timestamp_seconds": original.start_seconds + 0.25,
                "source_origin": "analysis",
                "image_prompt": "室内近景",
            }
        )
        second = first.model_copy(
            update={
                "id": uuid4(),
                "index": 2,
                "title": "第二部分",
                "start_ratio": 0.5,
                "end_ratio": 1,
                "source_timestamp_seconds": round(
                    float(first.source_timestamp_seconds or original.start_seconds) + 0.5,
                    3,
                ),
                "image_prompt": "户外远景",
            }
        )
        duplicated = original.model_copy(update={"visual_beats": [first, second]})
        await repository.save_shot_plan(duplicated)
        before = len(await repository.list_production_revisions(detail.project.id))

        repaired = (await service.list_shots(detail.project.id))[0].plan
        after = len(await repository.list_production_revisions(detail.project.id))

        assert after == before + 1
        assert [item.source_origin for item in repaired.visual_beats] == [
            "auto_extract",
            "auto_extract",
        ]
        assert len({item.source_frame_url for item in repaired.visual_beats}) == 2
        assert len({item.source_frame_relative_path for item in repaired.visual_beats}) == 2
        assert len({item.source_frame_sha256 for item in repaired.visual_beats}) == 2
        assert (
            repaired.visual_beats[0].source_timestamp_seconds
            < repaired.visual_beats[1].source_timestamp_seconds
        )

        await service.list_shots(detail.project.id)
        assert len(await repository.list_production_revisions(detail.project.id)) == after

    asyncio.run(scenario())


def test_leading_visual_beat_from_previous_shot_is_removed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, video, analysis, _ = await seed_completed_analysis(repository)
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        responses = await service.list_shots(detail.project.id)
        target = responses[1].plan
        report = await repository.get_report_by_analysis(analysis.id)
        assert report is not None
        source_shot = next(item for item in report.shots if item.id == target.source_shot_id)
        boundary = target.start_seconds
        candidate = SceneBoundaryCandidate(
            id="candidate_001",
            timestamp_seconds=boundary,
            score=0.09,
            methods=["adjacent_scene_score", "temporal_window_scene_score"],
            evidence_timestamps=[
                round(boundary - 0.75, 3),
                round(boundary - 0.12, 3),
                round(boundary + 0.12, 3),
                round(boundary + 0.75, 3),
            ],
            selected_by_model=True,
            model_decision="keep",
            semantic_group_before="产品/主体演示",
            semantic_group_after="结果/生活方式",
        )
        media_evidence = MediaEvidence(
            processor_version="test-boundary-content-v1",
            metadata=MediaMetadata(
                duration_seconds=report.overview.duration_seconds,
                width=720,
                height=1280,
                fps=30,
                format_name="mp4",
                video_codec="h264",
                has_audio=False,
                size_bytes=100,
                sha256="b" * 64,
                aspect_ratio="9:16",
            ),
            proxy_url=f"/api/v1/analyses/{analysis.id}/artifacts/proxy.mp4",
            manifest_url=f"/api/v1/analyses/{analysis.id}/artifacts/manifest.json",
            shots=[],
            segmentation=SegmentationMetadata(
                detector_version="test-boundary-content-v1",
                candidate_count=1,
                candidates=[candidate],
                selected_candidate_ids=[candidate.id],
                final_boundaries=[0, boundary, report.overview.duration_seconds],
                final_shot_count=2,
                verified_by_model=True,
            ),
        )
        updated_shot = source_shot.model_copy(
            update={"source_candidate_ids": [candidate.id]}
        )
        await repository.save_report(
            report.model_copy(
                update={
                    "shots": [
                        updated_shot if item.id == updated_shot.id else item
                        for item in report.shots
                    ],
                    "media_evidence": media_evidence,
                }
            )
        )

        original = target.visual_beats[0]
        contaminated = original.model_copy(
            update={
                "index": 1,
                "title": "第一部分",
                "start_ratio": 0,
                "end_ratio": 0.5,
                "source_frame_url": "/test/previous-scene.jpg",
                "source_timestamp_seconds": round(boundary + 0.18, 3),
                "source_origin": "auto_extract",
                "image_prompt": "室内女子背影，属于上一分镜。",
            }
        )
        valid = contaminated.model_copy(
            update={
                "id": uuid4(),
                "index": 2,
                "title": "第二部分",
                "start_ratio": 0.5,
                "end_ratio": 1,
                "source_frame_url": "/test/current-scene.jpg",
                "source_timestamp_seconds": round(boundary + 0.75, 3),
                "image_prompt": "户外稻田观景台上的少女。",
            }
        )
        await repository.save_shot_plan(
            target.model_copy(
                update={
                    "image_prompt": contaminated.image_prompt,
                    "video_prompt": (
                        f"第一部分：{contaminated.image_prompt}"
                        f"第二部分：{valid.image_prompt}"
                    ),
                    "visual_beats": [contaminated, valid],
                }
            )
        )
        before = len(await repository.list_production_revisions(detail.project.id))

        repaired = next(
            item.plan
            for item in await service.list_shots(detail.project.id)
            if item.plan.id == target.id
        )
        after = len(await repository.list_production_revisions(detail.project.id))

        assert after == before + 1
        assert len(repaired.visual_beats) == 1
        assert repaired.visual_beats[0].id == valid.id
        assert repaired.visual_beats[0].index == 1
        assert repaired.visual_beats[0].start_ratio == 0
        assert repaired.visual_beats[0].end_ratio == 1
        assert repaired.image_prompt == valid.image_prompt
        assert "上一分镜" not in repaired.video_prompt
        assert repaired.approved_video_candidate_id is None

        await service.list_shots(detail.project.id)
        assert len(await repository.list_production_revisions(detail.project.id)) == after

    asyncio.run(scenario())


def test_each_visual_beat_has_independent_images_and_video_uses_all_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, _ = await seed_completed_analysis(repository)
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        shot = (await service.list_shots(detail.project.id))[0].plan
        second = await service.create_visual_beat(
            shot.id,
            ShotVisualBeatCreate(
                expected_revision_id=detail.project.current_revision_id,
                insert_after_visual_beat_id=shot.visual_beats[0].id,
                title="户外画面",
                image_prompt="少女坐在户外平台，保持人物身份一致。",
            ),
        )
        beats = second.plan.visual_beats
        assert len(beats) == 2

        for beat in beats:
            current = await service.get_project(detail.project.id)
            queued = await service.create_image_run(
                shot.id,
                ImageGenerationCreate(
                    expected_revision_id=current.project.current_revision_id,
                    visual_beat_id=beat.id,
                    input_mode=(
                        "keyframe_edit" if beat.source_frame_url else "text_to_image"
                    ),
                    candidate_count=1,
                ),
            )
            run = await wait_for_generation(service, queued.id)
            assert run.visual_beat_id == beat.id
            current = await service.get_project(detail.project.id)
            selected = await service.select_candidate(
                run.candidates[0].id,
                CandidateSelectRequest(
                    expected_revision_id=current.project.current_revision_id,
                    visual_beat_id=beat.id,
                ),
            )
            await service.approve_candidate(
                run.candidates[0].id,
                CandidateApprovalRequest(
                    expected_revision_id=selected.shot.current_revision_id,
                    visual_beat_id=beat.id,
                    decision=ApprovalDecision.APPROVED,
                ),
            )

        approved = await service.get_shot(shot.id)
        assert approved.plan.image_status == WorkflowItemStatus.APPROVED
        assert all(
            item.approved_image_candidate_id is not None
            for item in approved.plan.visual_beats
        )
        for other_shot in (await service.list_shots(detail.project.id))[1:]:
            current = await service.get_project(detail.project.id)
            await service.update_shot(
                other_shot.plan.id,
                ShotPlanUpdate(
                    expected_revision_id=current.project.current_revision_id,
                    required=False,
                ),
            )
        current = await service.get_project(detail.project.id)
        await service.advance(
            detail.project.id,
            ProductionAdvanceRequest(
                expected_revision_id=current.project.current_revision_id,
                target_step=ProductionStep.SHOT_VIDEOS,
            ),
        )
        service.video_gateway = VideoGenerationGateway(
            service.workspace,
            media_processor=FakeStillVideoProcessor(),
        )
        current = await service.get_project(detail.project.id)
        queued_video = await service.create_video_run(
            shot.id,
            VideoGenerationCreate(
                expected_revision_id=current.project.current_revision_id,
                duration_seconds=3,
            ),
        )
        video_run = await wait_for_generation(service, queued_video.id)
        assert video_run.status == "completed"
        stored_video_run = await repository.get_generation_run(video_run.id)
        assert stored_video_run is not None
        snapshot_path = service.workspace.resolve(
            stored_video_run.input_snapshot_relative_path
        )
        filesystem_snapshot = Path(chr(92) * 2 + "?" + chr(92) + str(snapshot_path))
        snapshot_text = await asyncio.to_thread(
            filesystem_snapshot.read_text,
            encoding="utf-8",
        )
        snapshot = json.loads(snapshot_text)
        assert [item["ordinal"] for item in snapshot["reference_images"]] == [1, 2]
        assert [item["visual_beat_id"] for item in snapshot["reference_images"]] == [
            str(item.id) for item in approved.plan.visual_beats
        ]

    asyncio.run(scenario())


def test_reference_image_validation_uses_file_content_and_generates_thumbnail() -> None:
    original = image_bytes("PNG", size=(800, 1200))

    info = inspect_reference_image(original, "image/png")

    assert info.mime_type == "image/png"
    assert info.extension == ".png"
    assert (info.width, info.height) == (800, 1200)
    assert len(info.sha256) == 64
    with Image.open(BytesIO(info.thumbnail)) as thumbnail:
        assert thumbnail.format == "WEBP"
        assert max(thumbnail.size) == 480

    with pytest.raises(ProductionServiceError) as mismatch:
        inspect_reference_image(original, "image/jpeg")
    assert mismatch.value.status_code == 415
    assert mismatch.value.code == "reference_image_mime_mismatch"

    with pytest.raises(ProductionServiceError) as invalid:
        inspect_reference_image(b"not-an-image", "image/png")
    assert invalid.value.status_code == 415
    assert invalid.value.code == "invalid_reference_image"


def test_production_service_rejects_incomplete_or_foreign_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, _ = await seed_completed_analysis(repository)
        analysis.stage = AnalysisStage.UNDERSTANDING
        await repository.save_analysis(analysis)

        with pytest.raises(ProductionServiceError) as incomplete:
            await service.create_project(
                record.id,
                ProductionProjectCreate(base_analysis_id=analysis.id),
            )
        assert incomplete.value.status_code == 409
        assert incomplete.value.code == "analysis_incomplete"

        analysis.stage = AnalysisStage.COMPLETED
        analysis.record_id = uuid4()
        await repository.save_analysis(analysis)
        with pytest.raises(ProductionServiceError) as foreign:
            await service.create_project(
                record.id,
                ProductionProjectCreate(base_analysis_id=analysis.id),
            )
        assert foreign.value.status_code == 404
        assert foreign.value.code == "analysis_not_found"

    asyncio.run(scenario())


def test_optional_reference_stage_is_normalized_for_existing_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, _ = await seed_completed_analysis(repository)
        created = await service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        legacy = created.project.model_copy(
            update={"active_step": ProductionStep.REFERENCE_ASSETS}
        )
        await repository.save_production_project(legacy)

        detail = await service.get_project(legacy.id)
        projects = await service.list_projects(record.id)

        assert detail.project.active_step == ProductionStep.SHOT_IMAGES
        assert projects[0].active_step == ProductionStep.SHOT_IMAGES

    asyncio.run(scenario())


def test_production_http_api_revision_reference_and_branch_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = isolated_service(tmp_path, monkeypatch)
    record, _, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    monkeypatch.setattr(main, "production_service", service)
    original = image_bytes("PNG")

    with TestClient(main.app) as client:
        create_response = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={
                "base_analysis_id": str(analysis.id),
                "name": "人物復刻方案",
            },
        )
        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        project_id = created["project"]["id"]
        revision_1 = created["project"]["current_revision_id"]
        assert created["project"]["name"] == "人物复刻方案"
        assert created["project"]["output_width"] == 1080
        assert created["project"]["output_height"] == 1920
        assert created["project"]["active_step"] == "shot_images"
        assert created["reference_count"] == 0

        revision_response = client.get(f"/api/v1/productions/{project_id}/revisions/{revision_1}")
        assert revision_response.status_code == 200
        snapshot = revision_response.json()["snapshot"]
        assert snapshot["schema_version"] == "production-revision-v4"
        assert snapshot["source_analysis"]["analysis_id"] == str(analysis.id)
        assert len(snapshot["source_analysis"]["shots"]) == 5
        assert "snapshot_relative_path" not in revision_response.json()

        conflict = client.patch(
            f"/api/v1/productions/{project_id}",
            json={
                "expected_revision_id": str(uuid4()),
                "name": "冲突修改",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "创作方案已更新，请刷新后重试"

        update_response = client.patch(
            f"/api/v1/productions/{project_id}",
            json={
                "expected_revision_id": revision_1,
                "name": "產品替換版",
            },
        )
        assert update_response.status_code == 200, update_response.text
        updated = update_response.json()
        revision_2 = updated["project"]["current_revision_id"]
        assert updated["project"]["name"] == "产品替换版"
        assert revision_2 != revision_1

        upload_response = client.post(
            f"/api/v1/productions/{project_id}/references",
            files={"file": ("person.png", original, "image/png")},
            data={
                "expected_revision_id": revision_2,
                "type": "person",
                "name": "人物參考",
                "description": "正面與全身",
                "tags": '["正面", "全身"]',
                "rights_confirmed": "true",
                "rights_note": "已取得授權",
            },
        )
        assert upload_response.status_code == 201, upload_response.text
        asset = upload_response.json()
        asset_id = asset["id"]
        revision_3 = asset["current_revision_id"]
        assert asset["name"] == "人物参考"
        assert asset["description"] == "正面与全身"
        assert asset["rights_note"] == "已取得授权"
        assert "relative_path" not in asset
        assert revision_3 != revision_2
        assert client.get(f"/api/v1/productions/{project_id}").json()["project"][
            "active_step"
        ] == "shot_images"

        content_response = client.get(asset["content_url"])
        thumbnail_response = client.get(asset["thumbnail_url"])
        assert content_response.status_code == 200
        assert content_response.content == original
        assert content_response.headers["content-type"].startswith("image/png")
        assert thumbnail_response.status_code == 200
        assert thumbnail_response.headers["content-type"].startswith("image/webp")
        with Image.open(BytesIO(thumbnail_response.content)) as thumbnail:
            assert max(thumbnail.size) == 480

        edit_response = client.patch(
            f"/api/v1/references/{asset_id}",
            json={
                "expected_revision_id": revision_3,
                "name": "主角參考圖",
                "tags": ["正面", "棚拍"],
            },
        )
        assert edit_response.status_code == 200, edit_response.text
        edited = edit_response.json()
        revision_4 = edited["current_revision_id"]
        assert edited["name"] == "主角参考图"
        assert edited["tags"] == ["正面", "棚拍"]

        branch_response = client.post(
            f"/api/v1/productions/{project_id}/branches",
            json={
                "name": "歷史版本分支",
                "source_revision_id": revision_3,
            },
        )
        assert branch_response.status_code == 201, branch_response.text
        branch = branch_response.json()
        branch_id = branch["project"]["id"]
        assert branch["project"]["name"] == "历史版本分支"
        assert branch["project"]["source_project_id"] == project_id
        assert branch["project"]["source_revision_id"] == revision_3
        assert branch["project"]["active_step"] == "shot_images"
        assert branch["reference_count"] == 1
        branch_assets = client.get(f"/api/v1/productions/{branch_id}/references").json()
        assert len(branch_assets) == 1
        assert branch_assets[0]["id"] != asset_id
        branch_content = client.get(branch_assets[0]["content_url"])
        assert branch_content.content == original

        archive_response = client.delete(
            f"/api/v1/references/{asset_id}",
            params={"expected_revision_id": revision_4},
        )
        assert archive_response.status_code == 200, archive_response.text
        archived = archive_response.json()
        assert archived["archived_at"] is not None
        assert client.get(f"/api/v1/productions/{project_id}/references").json() == []
        archived_list = client.get(
            f"/api/v1/productions/{project_id}/references",
            params={"include_archived": "true"},
        ).json()
        assert len(archived_list) == 1
        assert client.get(archived["content_url"]).content == original

        revisions = client.get(f"/api/v1/productions/{project_id}/revisions").json()
        assert [item["revision_number"] for item in revisions] == [5, 4, 3, 2, 1]
        assert all("snapshot_relative_path" not in item for item in revisions)

    project_root = tmp_path / "workspace" / "records" / str(record.id) / "productions" / project_id
    assert (project_root / "project.json").is_file()
    assert len(list((project_root / "revisions").glob("*.json"))) == 5
    assert (project_root / "references" / asset_id / "asset.json").is_file()


def test_production_http_api_recycle_bin_and_permanent_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "recycle-workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    workspace = WorkspaceManager()
    repository = SQLiteStore(workspace.database_path)
    service = ProductionService(
        repository,
        workspace,
        image_gateway=FakeRealImageGateway(workspace),
    )
    record, _, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        create_response = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={
                "base_analysis_id": str(analysis.id),
                "name": "可删除创作方案",
            },
        )
        assert create_response.status_code == 201, create_response.text
        project_id = create_response.json()["project"]["id"]
        project_root = workspace.production_root(record.id, UUID(project_id))
        assert project_root.is_dir()

        active_delete = client.delete(f"/api/v1/productions/{project_id}/permanent")
        assert active_delete.status_code == 409
        assert active_delete.json()["detail"] == "只有回收站中的创作方案可以永久删除"

        trash_response = client.delete(f"/api/v1/productions/{project_id}")
        assert trash_response.status_code == 200, trash_response.text
        assert trash_response.json()["trashed_at"] is not None
        assert client.get(f"/api/v1/productions/{project_id}").status_code == 404
        assert client.get(
            f"/api/v1/records/{record.id}/productions"
        ).json() == []
        trashed_projects = client.get(
            f"/api/v1/records/{record.id}/productions",
            params={"lifecycle": "trashed"},
        ).json()
        assert [item["id"] for item in trashed_projects] == [project_id]
        all_projects = client.get(
            f"/api/v1/records/{record.id}/productions",
            params={"lifecycle": "all"},
        ).json()
        assert [item["id"] for item in all_projects] == [project_id]

        restore_response = client.post(f"/api/v1/productions/{project_id}/restore")
        assert restore_response.status_code == 200, restore_response.text
        assert restore_response.json()["trashed_at"] is None
        assert client.get(f"/api/v1/productions/{project_id}").status_code == 200

        assert client.delete(f"/api/v1/productions/{project_id}").status_code == 200
        permanent_response = client.delete(
            f"/api/v1/productions/{project_id}/permanent"
        )
        assert permanent_response.status_code == 204, permanent_response.text
        assert permanent_response.content == b""

    async def verify_cleanup() -> None:
        project_uuid = UUID(project_id)
        assert await repository.get_production_project(project_uuid) is None
        assert await repository.list_production_revisions(project_uuid) == []
        assert await repository.list_shot_plans(project_uuid) == []
        assert await repository.get_record(record.id) is not None

    asyncio.run(verify_cleanup())
    assert not project_root.exists()


def test_production_service_survives_sqlite_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        root = tmp_path / "durable-workspace"
        monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
        workspace = WorkspaceManager()
        first_store = SQLiteStore(workspace.database_path)
        record, _, analysis, _ = await seed_completed_analysis(first_store)
        first_service = ProductionService(
            first_store,
            workspace,
            image_gateway=FakeRealImageGateway(workspace),
        )
        detail = await first_service.create_project(
            record.id,
            ProductionProjectCreate(
                base_analysis_id=analysis.id,
                name="可恢复方案",
            ),
        )
        revision_id = detail.project.current_revision_id
        assert revision_id is not None
        asset = await first_service.create_reference(
            detail.project.id,
            ReferenceAssetCreate(
                expected_revision_id=revision_id,
                type=ReferenceAssetType.PRODUCT,
                name="产品参考",
                rights_confirmed=True,
            ),
            image_bytes("JPEG"),
            "image/jpeg",
        )
        first_shot = (await first_service.list_shots(detail.project.id))[0]
        run = await first_service.create_image_run(
            first_shot.plan.id,
            ImageGenerationCreate(
                expected_revision_id=asset.current_revision_id,
            ),
        )
        run = await wait_for_generation(first_service, run.id)
        after_run = await first_service.get_project(detail.project.id)
        selected = await first_service.select_candidate(
            run.candidates[0].id,
            CandidateSelectRequest(
                expected_revision_id=after_run.project.current_revision_id,
            ),
        )
        approved = await first_service.approve_candidate(
            run.candidates[0].id,
            CandidateApprovalRequest(
                expected_revision_id=selected.shot.current_revision_id,
                decision=ApprovalDecision.APPROVED,
            ),
        )

        restarted_store = SQLiteStore(workspace.database_path)
        restarted = ProductionService(restarted_store, workspace)
        restored = await restarted.get_project(detail.project.id)
        restored_assets = await restarted.list_references(detail.project.id)
        revisions = await restarted.list_revisions(detail.project.id)
        content, media_type = await restarted.resolve_reference_content(UUID(asset.id.hex))
        restored_shot = await restarted.get_shot(first_shot.plan.id)

        assert restored.project.name == "可恢复方案"
        assert restored.revision_count == 5
        assert restored.reference_count == 1
        assert len(restored_assets) == 1
        assert len(revisions) == 5
        assert content.is_file()
        assert media_type == "image/jpeg"
        assert restored_shot.plan.image_status == "approved"
        assert restored_shot.plan.approved_image_candidate_id == approved.candidate.id
        assert len(restored_shot.generation_runs) == 1
        assert len(restored_shot.approval_events) == 1

    asyncio.run(scenario())


def test_legacy_simulated_candidates_are_archived_and_never_pass_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, _ = await seed_completed_analysis(repository)
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(
                base_analysis_id=analysis.id,
                name="历史模拟候选修复",
            ),
        )
        plan = (await service.list_shots(detail.project.id))[0].plan
        legacy_revision_id = uuid4()
        run, candidates = await asyncio.to_thread(
            generate_simulated_images,
            service.workspace,
            detail.project,
            plan,
            legacy_revision_id,
            [],
            [],
            candidate_count=2,
            source_path=None,
        )
        selected_candidate = candidates[0].model_copy(
            update={"status": GenerationCandidateStatus.SELECTED}
        )
        updated_plan = plan.model_copy(
            update={
                "revision_id": legacy_revision_id,
                "image_status": WorkflowItemStatus.APPROVED,
                "approved_image_candidate_id": selected_candidate.id,
            }
        )
        plans = await repository.list_shot_plans(detail.project.id)
        next_plans = [
            updated_plan if item.id == updated_plan.id else item
            for item in plans
        ]
        legacy_project, legacy_revision = await service._prepare_revision(
            detail.project,
            ProductionChangeKind.IMAGE_APPROVED,
            "旧版模拟候选被错误确认",
            revision_id=legacy_revision_id,
            shot_plans=next_plans,
        )
        await repository.save_production_bundle(
            legacy_project,
            legacy_revision,
            shot_plans=[updated_plan],
            generation_runs=[run],
            generation_candidates=[selected_candidate, candidates[1]],
        )

        with pytest.raises(ProductionServiceError) as select_error:
            await service.select_candidate(
                selected_candidate.id,
                CandidateSelectRequest(
                    expected_revision_id=legacy_project.current_revision_id,
                ),
            )
        assert select_error.value.code == "simulated_candidate_forbidden"

        with pytest.raises(ProductionServiceError) as approval_error:
            await service.approve_candidate(
                selected_candidate.id,
                CandidateApprovalRequest(
                    expected_revision_id=legacy_project.current_revision_id,
                    decision=ApprovalDecision.APPROVED,
                ),
            )
        assert approval_error.value.code == "simulated_candidate_forbidden"

        repaired = await service.get_project(detail.project.id)
        repaired_shot = await service.get_shot(plan.id)
        gate = await service.gate_status(detail.project.id)

        assert repaired.revision_count == 3
        assert repaired.approved_image_count == 0
        assert repaired_shot.plan.image_status == WorkflowItemStatus.READY
        assert repaired_shot.plan.approved_image_candidate_id is None
        assert {
            candidate.status
            for candidate in repaired_shot.generation_runs[0].candidates
        } == {GenerationCandidateStatus.ARCHIVED}
        assert gate.allowed is False
        assert gate.approved_shot_count == 0

    asyncio.run(scenario())


def test_source_keyframe_selection_direct_approval_and_candidate_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
    workspace = WorkspaceManager()
    repository = InMemoryStore()
    record, video, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    source_video = workspace.source_root(record.id) / "source.mp4"
    source_video.parent.mkdir(parents=True, exist_ok=True)
    source_video.write_bytes(b"fake-video-for-range-and-picker")
    video.stored_relative_path = workspace.relative(source_video)
    asyncio.run(repository.add_video(video))
    service = ProductionService(
        repository,
        workspace,
        media_processor=FakeFrameProcessor(),
    )
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={"base_analysis_id": str(analysis.id), "name": "关键帧工作流"},
        ).json()
        project_id = created["project"]["id"]
        revision_id = created["project"]["current_revision_id"]
        assert created["project"]["active_step"] == "shot_images"
        assert created["reference_count"] == 0
        shots = client.get(f"/api/v1/productions/{project_id}/shots").json()
        plan = shots[0]["plan"]
        timestamp = round(
            (plan["start_seconds"] + plan["end_seconds"]) / 2,
            2,
        )

        video_response = client.get(
            f"/api/v1/productions/{project_id}/source-video"
        )
        assert video_response.status_code == 200
        assert video_response.content == b"fake-video-for-range-and-picker"
        assert video_response.headers["content-type"].startswith("video/mp4")

        selected_response = client.post(
            f"/api/v1/production-shots/{plan['id']}/source-keyframe",
            json={
                "expected_revision_id": revision_id,
                "timestamp_seconds": timestamp,
            },
        )
        assert selected_response.status_code == 200, selected_response.text
        selected = selected_response.json()
        selected_plan = selected["plan"]
        assert selected_plan["source_keyframe_origin"] == "video_selection"
        assert selected_plan["source_keyframe_timestamp_seconds"] == timestamp
        assert selected_plan["image_status"] == "ready"
        assert selected_plan["source_keyframe_url"].startswith(
            f"/api/v1/production-shots/{plan['id']}/visual-beats/"
        )
        keyframe_response = client.get(selected_plan["source_keyframe_url"])
        assert keyframe_response.status_code == 200
        with Image.open(BytesIO(keyframe_response.content)) as keyframe:
            assert keyframe.size == (720, 1280)

        approval_response = client.post(
            f"/api/v1/production-shots/{plan['id']}/source-keyframe/approval",
            json={"expected_revision_id": selected["current_revision_id"]},
        )
        assert approval_response.status_code == 200, approval_response.text
        approval = approval_response.json()
        assert approval["shot"]["plan"]["image_status"] == "approved"
        assert approval["candidate"]["status"] == "selected"
        approved_candidate_id = approval["candidate"]["id"]
        shot_detail = client.get(
            f"/api/v1/production-shots/{plan['id']}"
        ).json()
        source_run = shot_detail["generation_runs"][0]
        assert source_run["execution_mode"] == "source_frame"
        assert source_run["input_mode"] == "keyframe_edit"
        assert source_run["actual_cost_micros"] == 0

        conflict = client.post(
            f"/api/v1/production-shots/{plan['id']}/source-keyframe",
            json={
                "expected_revision_id": approval["shot"]["current_revision_id"],
                "timestamp_seconds": min(timestamp + 0.1, plan["end_seconds"]),
            },
        )
        assert conflict.status_code == 409

        replaced = client.post(
            f"/api/v1/production-shots/{plan['id']}/source-keyframe",
            json={
                "expected_revision_id": approval["shot"]["current_revision_id"],
                "timestamp_seconds": min(timestamp + 0.1, plan["end_seconds"]),
                "confirm_stale": True,
            },
        )
        assert replaced.status_code == 200, replaced.text
        replaced_detail = replaced.json()
        assert replaced_detail["plan"]["image_status"] == "ready"
        assert replaced_detail["plan"]["approved_image_candidate_id"] is None
        historical_candidate = next(
            candidate
            for run in replaced_detail["generation_runs"]
            for candidate in run["candidates"]
            if candidate["id"] == approved_candidate_id
        )
        assert historical_candidate["status"] == "ready"

        branch_response = client.post(
            f"/api/v1/productions/{project_id}/branches",
            json={
                "name": "保留关键帧的分支",
                "source_revision_id": replaced_detail["current_revision_id"],
            },
        )
        assert branch_response.status_code == 201, branch_response.text
        branch_id = branch_response.json()["project"]["id"]
        branch_plan = client.get(
            f"/api/v1/productions/{branch_id}/shots"
        ).json()[0]["plan"]
        assert branch_plan["source_keyframe_origin"] == "video_selection"
        assert branch_plan["source_keyframe_url"].startswith(
            f"/api/v1/production-shots/{branch_plan['id']}/source-keyframe"
        )
        assert client.get(branch_plan["source_keyframe_url"]).status_code == 200


def test_shot_output_mode_can_use_source_video_and_switch_back_without_deleting_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
    workspace = WorkspaceManager()
    repository = InMemoryStore()
    record, video, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    source_video = workspace.source_root(record.id) / "source.mp4"
    source_video.parent.mkdir(parents=True, exist_ok=True)
    source_video.write_bytes(b"fake-source-video")
    video = video.model_copy(
        update={
            "stored_relative_path": workspace.relative(source_video),
            "sha256": "b" * 64,
        }
    )
    asyncio.run(repository.add_video(video))
    service = ProductionService(
        repository,
        workspace,
        media_processor=FakeSourceVideoProcessor(),
        video_inspector=FakeVideoInspector(),
    )
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={"base_analysis_id": str(analysis.id), "name": "分镜直通方案"},
        ).json()
        project_id = created["project"]["id"]
        revision_id = created["project"]["current_revision_id"]
        initial_shots = client.get(f"/api/v1/productions/{project_id}/shots").json()
        assert all(item["plan"]["output_mode"] == "image_to_video" for item in initial_shots)
        first = initial_shots[0]

        selected_response = client.post(
            f"/api/v1/productions/{project_id}/shot-output-mode",
            json={
                "expected_revision_id": revision_id,
                "shot_plan_ids": [first["plan"]["id"]],
                "output_mode": "source_video",
            },
        )
        assert selected_response.status_code == 200, selected_response.text
        selected_shots = selected_response.json()
        selected = next(
            item for item in selected_shots if item["plan"]["id"] == first["plan"]["id"]
        )
        assert selected["plan"]["output_mode"] == "source_video"
        assert selected["plan"]["video_status"] == "approved"
        assert selected["video_preview"]["execution_mode"] == "source_video"

        detail = client.get(
            f"/api/v1/production-shots/{first['plan']['id']}"
        ).json()
        source_run = next(
            run for run in detail["generation_runs"] if run["execution_mode"] == "source_video"
        )
        source_candidate = source_run["candidates"][0]
        assert source_run["input_mode"] == "video_to_video"
        assert source_run["actual_cost_micros"] == 0
        assert source_candidate["status"] == "selected"
        assert client.get(source_candidate["content_url"]).status_code == 200

        gate = client.get(f"/api/v1/productions/{project_id}/gate-status").json()
        assert gate["approved_shot_count"] == 1

        switched_response = client.post(
            f"/api/v1/productions/{project_id}/shot-output-mode",
            json={
                "expected_revision_id": selected["current_revision_id"],
                "shot_plan_ids": [first["plan"]["id"]],
                "output_mode": "image_to_video",
                "confirm_downstream_stale": True,
            },
        )
        assert switched_response.status_code == 200, switched_response.text
        switched = next(
            item
            for item in switched_response.json()
            if item["plan"]["id"] == first["plan"]["id"]
        )
        assert switched["plan"]["output_mode"] == "image_to_video"
        assert switched["plan"]["video_status"] == "ready"
        assert switched["plan"]["approved_video_candidate_id"] is None

        switched_detail = client.get(
            f"/api/v1/production-shots/{first['plan']['id']}"
        ).json()
        historical_source = next(
            candidate
            for run in switched_detail["generation_runs"]
            if run["id"] == source_run["id"]
            for candidate in run["candidates"]
        )
        assert historical_source["status"] == "ready"
        assert client.get(historical_source["content_url"]).status_code == 200


def test_batch41_shot_generation_approval_stale_and_gate_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = isolated_service(tmp_path, monkeypatch)
    record, _, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={
                "base_analysis_id": str(analysis.id),
                "name": "Batch 4.1 验收方案",
            },
        ).json()
        project_id = created["project"]["id"]
        current_revision_id = created["project"]["current_revision_id"]

        shots_response = client.get(f"/api/v1/productions/{project_id}/shots")
        assert shots_response.status_code == 200, shots_response.text
        shots = shots_response.json()
        assert len(shots) == 5
        assert [item["plan"]["index"] for item in shots] == [1, 2, 3, 4, 5]
        assert all(item["plan"]["image_status"] == "ready" for item in shots)
        assert all(item["plan"]["source_keyframe_url"] for item in shots)

        asset_response = client.post(
            f"/api/v1/productions/{project_id}/references",
            files={"file": ("person.png", image_bytes("PNG"), "image/png")},
            data={
                "expected_revision_id": current_revision_id,
                "type": "person",
                "name": "主角参考图",
                "rights_confirmed": "true",
            },
        )
        assert asset_response.status_code == 201, asset_response.text
        asset = asset_response.json()
        current_revision_id = asset["current_revision_id"]

        first_shot_id = shots[0]["plan"]["id"]
        update_response = client.patch(
            f"/api/v1/production-shots/{first_shot_id}",
            json={
                "expected_revision_id": current_revision_id,
                "image_prompt": "保持原构图，替换为参考图中的人物，写实自然光。",
                "reference_bindings": [
                    {
                        "reference_asset_id": asset["id"],
                        "role": "identity",
                        "weight": 1.2,
                    }
                ],
            },
        )
        assert update_response.status_code == 200, update_response.text
        updated_first = update_response.json()
        assert len(updated_first["reference_bindings"]) == 1
        current_revision_id = updated_first["current_revision_id"]

        gate_before = client.get(f"/api/v1/productions/{project_id}/gate-status").json()
        assert gate_before["allowed"] is False
        assert gate_before["approved_shot_count"] == 0

        first_candidate_id = None
        for index, shot in enumerate(shots):
            shot_id = shot["plan"]["id"]
            run_response = client.post(
                f"/api/v1/production-shots/{shot_id}/image-runs",
                json={
                    "expected_revision_id": current_revision_id,
                    "candidate_count": 2 if index == 0 else 1,
                },
            )
            assert run_response.status_code == 202, run_response.text
            queued_run = run_response.json()
            run = wait_for_generation_http(client, queued_run["id"])
            assert run["provider"] == "test_image_provider"
            assert run["execution_mode"] == "remote_api"
            assert run["actual_cost_micros"] == 0
            assert len(run["candidates"]) == (2 if index == 0 else 1)
            candidate = run["candidates"][0]
            if index == 0:
                first_candidate_id = candidate["id"]
            thumbnail = client.get(candidate["thumbnail_url"])
            assert thumbnail.status_code == 200
            assert thumbnail.headers["content-type"].startswith("image/webp")

            current_revision_id = client.get(f"/api/v1/productions/{project_id}").json()["project"][
                "current_revision_id"
            ]
            select_response = client.post(
                f"/api/v1/generation-candidates/{candidate['id']}/select",
                json={"expected_revision_id": current_revision_id},
            )
            assert select_response.status_code == 200, select_response.text
            selected = select_response.json()
            assert selected["candidate"]["status"] == "selected"
            current_revision_id = selected["shot"]["current_revision_id"]

            approval_response = client.post(
                f"/api/v1/generation-candidates/{candidate['id']}/approvals",
                json={
                    "expected_revision_id": current_revision_id,
                    "decision": "approved",
                },
            )
            assert approval_response.status_code == 200, approval_response.text
            approved = approval_response.json()
            assert approved["shot"]["plan"]["image_status"] == "approved"
            current_revision_id = approved["shot"]["current_revision_id"]
            if index == 0:
                duplicate_approval = client.post(
                    f"/api/v1/generation-candidates/{candidate['id']}/approvals",
                    json={
                        "expected_revision_id": current_revision_id,
                        "decision": "approved",
                    },
                )
                assert duplicate_approval.status_code == 409
                assert duplicate_approval.json()["detail"] == (
                    "该分镜图片已审批，如需修改请先调整分镜输入"
                )

        gate_after = client.get(f"/api/v1/productions/{project_id}/gate-status").json()
        assert gate_after["allowed"] is True
        assert gate_after["approved_shot_count"] == 5
        assert gate_after["stale_shot_count"] == 0

        advance_response = client.post(
            f"/api/v1/productions/{project_id}/advance",
            json={
                "expected_revision_id": current_revision_id,
                "target_step": "shot_videos",
            },
        )
        assert advance_response.status_code == 200, advance_response.text
        assert advance_response.json()["project"]["active_step"] == "shot_videos"
        current_revision_id = advance_response.json()["project"]["current_revision_id"]

        duplicate_advance = client.post(
            f"/api/v1/productions/{project_id}/advance",
            json={
                "expected_revision_id": current_revision_id,
                "target_step": "shot_videos",
            },
        )
        assert duplicate_advance.status_code == 409
        assert duplicate_advance.json()["detail"] == "当前方案已进入分段视频阶段"

        branch_response = client.post(
            f"/api/v1/productions/{project_id}/branches",
            json={
                "name": "审批前可回退分支",
                "source_revision_id": current_revision_id,
            },
        )
        assert branch_response.status_code == 201, branch_response.text
        branch_id = branch_response.json()["project"]["id"]
        branch_shots = client.get(f"/api/v1/productions/{branch_id}/shots").json()
        assert all(item["plan"]["approved_image_candidate_id"] is None for item in branch_shots)
        assert all(item["plan"]["image_status"] == "ready" for item in branch_shots)

        impact = client.post(
            f"/api/v1/productions/{project_id}/change-impact",
            json={
                "expected_revision_id": current_revision_id,
                "change_type": "reference_asset",
                "reference_asset_ids": [asset["id"]],
            },
        ).json()
        assert impact["requires_confirmation"] is True
        assert impact["impacted_shot_plan_ids"] == [first_shot_id]

        rejected_edit = client.patch(
            f"/api/v1/references/{asset['id']}",
            json={
                "expected_revision_id": current_revision_id,
                "description": "更新后的人物参考说明",
            },
        )
        assert rejected_edit.status_code == 409
        assert rejected_edit.json()["detail"] == (
            "参考资产修改会使已绑定分镜过期，请确认影响范围后重试"
        )

        confirmed_edit = client.patch(
            f"/api/v1/references/{asset['id']}",
            json={
                "expected_revision_id": current_revision_id,
                "confirm_stale": True,
                "description": "更新后的人物参考说明",
            },
        )
        assert confirmed_edit.status_code == 200, confirmed_edit.text
        current_revision_id = confirmed_edit.json()["current_revision_id"]
        stale_shots = client.get(f"/api/v1/productions/{project_id}/shots").json()
        assert stale_shots[0]["plan"]["image_status"] == "stale"
        assert all(item["plan"]["image_status"] == "approved" for item in stale_shots[1:])
        assert first_candidate_id is not None
        stale_candidate = client.post(
            f"/api/v1/generation-candidates/{first_candidate_id}/select",
            json={"expected_revision_id": current_revision_id},
        )
        assert stale_candidate.status_code == 200, stale_candidate.text
        assert stale_candidate.json()["candidate"]["status"] == "selected"
        current_revision_id = stale_candidate.json()["shot"]["current_revision_id"]

        global_update = client.patch(
            f"/api/v1/productions/{project_id}",
            json={
                "expected_revision_id": current_revision_id,
                "confirm_stale": True,
                "output_aspect_ratio": "16:9",
                "output_width": 1920,
                "output_height": 1080,
            },
        )
        assert global_update.status_code == 200, global_update.text
        all_stale = client.get(f"/api/v1/productions/{project_id}/shots").json()
        assert all(item["plan"]["image_status"] == "stale" for item in all_stale)


def test_single_candidate_approval_can_be_revoked_and_regenerated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = isolated_service(tmp_path, monkeypatch)
    record, _, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={"base_analysis_id": str(analysis.id), "name": "单候选取消采用测试"},
        ).json()
        project_id = created["project"]["id"]
        shot = client.get(f"/api/v1/productions/{project_id}/shots").json()[0]
        shot_id = shot["plan"]["id"]
        revision_id = created["project"]["current_revision_id"]

        first_queued = client.post(
            f"/api/v1/production-shots/{shot_id}/image-runs",
            json={
                "expected_revision_id": revision_id,
                "candidate_count": 1,
            },
        )
        assert first_queued.status_code == 202, first_queued.text
        first_run = wait_for_generation_http(client, first_queued.json()["id"])
        assert len(first_run["candidates"]) == 1
        first_candidate = first_run["candidates"][0]

        revision_id = client.get(
            f"/api/v1/productions/{project_id}"
        ).json()["project"]["current_revision_id"]
        selected = client.post(
            f"/api/v1/generation-candidates/{first_candidate['id']}/select",
            json={"expected_revision_id": revision_id},
        )
        assert selected.status_code == 200, selected.text
        approved = client.post(
            f"/api/v1/generation-candidates/{first_candidate['id']}/approvals",
            json={
                "expected_revision_id": selected.json()["shot"]["current_revision_id"],
                "decision": "approved",
            },
        )
        assert approved.status_code == 200, approved.text
        approved_revision_id = approved.json()["shot"]["current_revision_id"]

        revoked = client.post(
            f"/api/v1/production-shots/{shot_id}/image-approval/revoke",
            json={
                "expected_revision_id": approved_revision_id,
                "reason": "需要生成新的图片候选",
            },
        )
        assert revoked.status_code == 200, revoked.text
        revoked_body = revoked.json()
        assert revoked_body["shot"]["plan"]["image_status"] == "review_required"
        assert revoked_body["shot"]["plan"]["approved_image_candidate_id"] is None
        assert revoked_body["candidate"]["id"] == first_candidate["id"]
        assert revoked_body["candidate"]["status"] == "selected"
        assert revoked_body["approval_event"]["decision"] == "revoked"

        duplicate_revoke = client.post(
            f"/api/v1/production-shots/{shot_id}/image-approval/revoke",
            json={
                "expected_revision_id": revoked_body["shot"]["current_revision_id"],
            },
        )
        assert duplicate_revoke.status_code == 409
        assert duplicate_revoke.json()["detail"] == "当前画面图片尚未采用，无需取消"

        second_queued = client.post(
            f"/api/v1/production-shots/{shot_id}/image-runs",
            json={
                "expected_revision_id": revoked_body["shot"]["current_revision_id"],
                "candidate_count": 1,
                "generation_intent": "new_variation",
            },
        )
        assert second_queued.status_code == 202, second_queued.text
        stored_queued = asyncio.run(
            repository.get_generation_run(UUID(second_queued.json()["id"]))
        )
        assert stored_queued is not None
        assert stored_queued.request_payload["generation_intent"] == "new_variation"
        assert isinstance(stored_queued.request_payload["seed"], int)

        second_run = wait_for_generation_http(client, second_queued.json()["id"])
        assert second_run["status"] == "completed"
        assert second_run["candidates"][0]["id"] != first_candidate["id"]
        stored_first_candidate = asyncio.run(
            repository.get_generation_candidate(UUID(first_candidate["id"]))
        )
        assert stored_first_candidate is not None
        assert stored_first_candidate.status == GenerationCandidateStatus.READY

        revision_id = client.get(
            f"/api/v1/productions/{project_id}"
        ).json()["project"]["current_revision_id"]
        selected_again = client.post(
            f"/api/v1/generation-candidates/{second_run['candidates'][0]['id']}/select",
            json={"expected_revision_id": revision_id},
        )
        assert selected_again.status_code == 200, selected_again.text
        approved_again = client.post(
            f"/api/v1/generation-candidates/{second_run['candidates'][0]['id']}/approvals",
            json={
                "expected_revision_id": selected_again.json()["shot"]["current_revision_id"],
                "decision": "approved",
            },
        )
        assert approved_again.status_code == 200, approved_again.text

        persisted_plan = asyncio.run(repository.get_shot_plan(UUID(shot_id)))
        persisted_project = asyncio.run(
            repository.get_production_project(UUID(project_id))
        )
        assert persisted_plan is not None
        assert persisted_project is not None
        asyncio.run(
            repository.save_shot_plan(
                persisted_plan.model_copy(
                    update={"video_status": WorkflowItemStatus.APPROVED}
                )
            )
        )
        asyncio.run(
            repository.save_production_project(
                persisted_project.model_copy(
                    update={"active_step": ProductionStep.SHOT_VIDEOS}
                )
            )
        )
        approved_revision_id = approved_again.json()["shot"]["current_revision_id"]
        impact = client.post(
            f"/api/v1/productions/{project_id}/change-impact",
            json={
                "expected_revision_id": approved_revision_id,
                "change_type": "image_approval_revoke",
                "shot_plan_ids": [shot_id],
            },
        )
        assert impact.status_code == 200, impact.text
        assert impact.json()["requires_confirmation"] is True
        assert impact.json()["stale_candidate_ids"] == []
        assert impact.json()["stale_stage_ids"] == [
            "shot_videos",
            "editing",
            "export",
        ]

        blocked_revoke = client.post(
            f"/api/v1/production-shots/{shot_id}/image-approval/revoke",
            json={"expected_revision_id": approved_revision_id},
        )
        assert blocked_revoke.status_code == 409
        assert blocked_revoke.json()["detail"] == (
            "取消采用会使该分镜的后续视频或合成结果过期，请确认影响后重试"
        )
        confirmed_revoke = client.post(
            f"/api/v1/production-shots/{shot_id}/image-approval/revoke",
            json={
                "expected_revision_id": approved_revision_id,
                "confirm_downstream_stale": True,
            },
        )
        assert confirmed_revoke.status_code == 200, confirmed_revoke.text
        assert confirmed_revoke.json()["shot"]["plan"]["video_status"] == "stale"
        project_after_revoke = client.get(
            f"/api/v1/productions/{project_id}"
        ).json()["project"]
        assert project_after_revoke["active_step"] == "shot_images"


def test_shot_structure_add_reorder_discard_and_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = isolated_service(tmp_path, monkeypatch)
    record, _, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={"base_analysis_id": str(analysis.id), "name": "分镜编排测试"},
        ).json()
        project_id = created["project"]["id"]
        revision_id = created["project"]["current_revision_id"]
        initial = client.get(f"/api/v1/productions/{project_id}/shots").json()
        first_id = initial[0]["plan"]["id"]

        duplicate_response = client.post(
            f"/api/v1/productions/{project_id}/shots",
            json={
                "expected_revision_id": revision_id,
                "mode": "duplicate",
                "source_shot_plan_id": first_id,
                "insert_after_shot_plan_id": first_id,
            },
        )
        assert duplicate_response.status_code == 201, duplicate_response.text
        duplicate = duplicate_response.json()
        duplicate_id = duplicate["plan"]["id"]
        assert duplicate["plan"]["source_kind"] == "duplicate"
        assert duplicate["plan"]["index"] == 2
        assert duplicate["plan"]["approved_image_candidate_id"] is None

        revision_id = duplicate["current_revision_id"]
        shots = client.get(f"/api/v1/productions/{project_id}/shots").json()
        active_ids = [
            item["plan"]["id"]
            for item in shots
            if item["plan"]["lifecycle_status"] == "active"
        ]
        reordered_ids = [active_ids[-1], *active_ids[:-1]]
        reordered = client.put(
            f"/api/v1/productions/{project_id}/shots/order",
            json={
                "expected_revision_id": revision_id,
                "ordered_shot_plan_ids": reordered_ids,
            },
        )
        assert reordered.status_code == 200, reordered.text
        reordered_body = reordered.json()
        assert [
            item["plan"]["id"]
            for item in reordered_body
            if item["plan"]["lifecycle_status"] == "active"
        ] == reordered_ids
        assert [
            item["plan"]["index"]
            for item in reordered_body
            if item["plan"]["lifecycle_status"] == "active"
        ] == list(range(1, 7))

        revision_id = client.get(
            f"/api/v1/productions/{project_id}"
        ).json()["project"]["current_revision_id"]
        discarded = client.post(
            f"/api/v1/production-shots/{duplicate_id}/discard",
            json={"expected_revision_id": revision_id},
        )
        assert discarded.status_code == 200, discarded.text
        discarded_body = discarded.json()
        discarded_plan = next(
            item["plan"] for item in discarded_body if item["plan"]["id"] == duplicate_id
        )
        assert discarded_plan["lifecycle_status"] == "discarded"
        assert len([
            item for item in discarded_body
            if item["plan"]["lifecycle_status"] == "active"
        ]) == 5
        project_detail = client.get(f"/api/v1/productions/{project_id}").json()
        assert project_detail["shot_count"] == 5
        assert project_detail["discarded_shot_count"] == 1
        gate = client.get(f"/api/v1/productions/{project_id}/gate-status").json()
        assert gate["required_shot_count"] == 5

        blocked_edit = client.patch(
            f"/api/v1/production-shots/{duplicate_id}",
            json={
                "expected_revision_id": project_detail["project"]["current_revision_id"],
                "image_prompt": "不应允许修改",
            },
        )
        assert blocked_edit.status_code == 409

        restored = client.post(
            f"/api/v1/production-shots/{duplicate_id}/restore",
            json={
                "expected_revision_id": project_detail["project"]["current_revision_id"],
            },
        )
        assert restored.status_code == 200, restored.text
        restored_active = [
            item["plan"] for item in restored.json()
            if item["plan"]["lifecycle_status"] == "active"
        ]
        assert len(restored_active) == 6
        assert restored_active[-1]["id"] == duplicate_id

        revision_id = client.get(
            f"/api/v1/productions/{project_id}"
        ).json()["project"]["current_revision_id"]
        blank = client.post(
            f"/api/v1/productions/{project_id}/shots",
            json={
                "expected_revision_id": revision_id,
                "mode": "blank",
                "insert_after_shot_plan_id": duplicate_id,
                "image_prompt": "纯文字创建的新画面",
            },
        )
        assert blank.status_code == 201, blank.text
        assert blank.json()["plan"]["source_kind"] == "blank"
        assert blank.json()["plan"]["source_keyframe_url"] is None
        assert blank.json()["plan"]["image_status"] == "ready"


def test_prompt_asset_mentions_are_stable_and_auto_bind_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = isolated_service(tmp_path, monkeypatch)
    record, _, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={"base_analysis_id": str(analysis.id), "name": "提示词资产关联"},
        ).json()
        project_id = created["project"]["id"]
        revision_id = created["project"]["current_revision_id"]
        shot_id = client.get(
            f"/api/v1/productions/{project_id}/shots"
        ).json()[0]["plan"]["id"]

        asset_response = client.post(
            f"/api/v1/productions/{project_id}/references",
            files={"file": ("person.png", image_bytes("PNG"), "image/png")},
            data={
                "expected_revision_id": revision_id,
                "type": "person",
                "name": "主角参考图",
                "rights_confirmed": "true",
            },
        )
        assert asset_response.status_code == 201, asset_response.text
        asset = asset_response.json()

        updated = client.patch(
            f"/api/v1/production-shots/{shot_id}",
            json={
                "expected_revision_id": asset["current_revision_id"],
                "image_prompt": "保持原构图，把人物替换为 @主角参考图，写实自然光。",
                "image_prompt_mentions": [
                    {
                        "reference_asset_id": asset["id"],
                        "label": "主角参考图",
                    }
                ],
            },
        )
        assert updated.status_code == 200, updated.text
        shot = updated.json()
        assert shot["plan"]["image_prompt_mentions"] == [
            {
                "reference_asset_id": asset["id"],
                "label": "主角参考图",
            }
        ]
        assert len(shot["reference_bindings"]) == 1
        assert shot["reference_bindings"][0]["reference_asset_id"] == asset["id"]
        assert shot["reference_bindings"][0]["role"] == "identity"

        run_response = client.post(
            f"/api/v1/production-shots/{shot_id}/image-runs",
            json={
                "expected_revision_id": shot["current_revision_id"],
                "candidate_count": 1,
            },
        )
        assert run_response.status_code == 202, run_response.text
        queued_run = run_response.json()
        run = wait_for_generation_http(client, queued_run["id"])
        stored_run = asyncio.run(repository.get_generation_run(UUID(run["id"])))
        assert stored_run is not None
        input_snapshot = service.workspace.resolve(stored_run.input_snapshot_relative_path)
        filesystem_input = Path(chr(92) * 2 + '?' + chr(92) + str(input_snapshot))
        input_payload = json.loads(filesystem_input.read_text(encoding="utf-8"))
        assert input_payload["image_prompt_mentions"] == [
            {"asset_id": asset["id"], "label": "主角参考图"}
        ]
        assert "@主角参考图" in input_payload["image_prompt"]
        assert input_payload["references"][0]["asset_id"] == asset["id"]
        assert input_payload["references"][0]["name"] == "主角参考图"
        assert input_payload["identity_policy"]["enabled"] is True
        assert input_payload["identity_policy"]["primary_identity_asset_id"] == asset["id"]
        assert input_payload["input_manifest"][0]["input_index"] == 1
        assert input_payload["input_manifest"][0]["identity_source"] is False
        assert input_payload["input_manifest"][1]["input_index"] == 2
        assert input_payload["input_manifest"][1]["asset_id"] == asset["id"]
        assert input_payload["input_manifest"][1]["identity_source"] is True
        assert "严禁从图像1继承人物" in input_payload["prompt"]["positive"]


def test_visual_beat_saves_prompt_mentions_and_bindings_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = isolated_service(tmp_path, monkeypatch)
    record, _, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={"base_analysis_id": str(analysis.id), "name": "画面引用原子保存"},
        ).json()
        project_id = created["project"]["id"]
        revision_id = created["project"]["current_revision_id"]
        shot = client.get(f"/api/v1/productions/{project_id}/shots").json()[0]
        shot_id = shot["plan"]["id"]
        visual_beat_id = shot["plan"]["visual_beats"][0]["id"]

        asset_response = client.post(
            f"/api/v1/productions/{project_id}/references",
            files={"file": ("person.png", image_bytes("PNG"), "image/png")},
            data={
                "expected_revision_id": revision_id,
                "type": "person",
                "name": "小喵酱",
                "rights_confirmed": "true",
            },
        )
        assert asset_response.status_code == 201, asset_response.text
        asset = asset_response.json()
        revision_count = len(
            asyncio.run(repository.list_production_revisions(UUID(project_id)))
        )

        updated = client.patch(
            f"/api/v1/production-shots/{shot_id}/visual-beats/{visual_beat_id}",
            json={
                "expected_revision_id": asset["current_revision_id"],
                "image_prompt": "双马尾女性站在画面中央。",
                "reference_bindings": [
                    {
                        "reference_asset_id": asset["id"],
                        "role": "identity",
                        "weight": 1,
                    }
                ],
            },
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        expected_label = f"{asset.get('folder_name') or '未分类'}/小喵酱"
        beat = next(
            item
            for item in body["plan"]["visual_beats"]
            if item["id"] == visual_beat_id
        )
        assert beat["image_prompt"] == (
            f"@{expected_label}\n双马尾女性站在画面中央。"
        )
        assert beat["image_prompt_mentions"] == [
            {"reference_asset_id": asset["id"], "label": expected_label}
        ]
        assert len(body["reference_bindings"]) == 1
        assert body["reference_bindings"][0]["reference_asset_id"] == asset["id"]
        assert len(
            asyncio.run(repository.list_production_revisions(UUID(project_id)))
        ) == revision_count + 1

        reopened = client.get(f"/api/v1/production-shots/{shot_id}")
        assert reopened.status_code == 200, reopened.text
        reopened_beat = next(
            item
            for item in reopened.json()["plan"]["visual_beats"]
            if item["id"] == visual_beat_id
        )
        assert reopened_beat["image_prompt"] == beat["image_prompt"]
        assert reopened_beat["image_prompt_mentions"] == beat["image_prompt_mentions"]

        removed = client.patch(
            f"/api/v1/production-shots/{shot_id}/visual-beats/{visual_beat_id}",
            json={
                "expected_revision_id": body["current_revision_id"],
                "image_prompt": "双马尾女性站在画面中央。",
                "image_prompt_mentions": [],
                "reference_bindings": [],
            },
        )
        assert removed.status_code == 200, removed.text
        removed_body = removed.json()
        removed_beat = next(
            item
            for item in removed_body["plan"]["visual_beats"]
            if item["id"] == visual_beat_id
        )
        assert removed_beat["image_prompt"] == "双马尾女性站在画面中央。"
        assert removed_beat["image_prompt_mentions"] == []
        assert removed_body["reference_bindings"] == []


def test_create_shot_from_source_video_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
    workspace = WorkspaceManager()
    repository = InMemoryStore()
    record, video, analysis, _ = asyncio.run(seed_completed_analysis(repository))
    source_video = workspace.source_root(record.id) / "source.mp4"
    source_video.parent.mkdir(parents=True, exist_ok=True)
    source_video.write_bytes(b"fake-video-for-new-shot")
    video.stored_relative_path = workspace.relative(source_video)
    asyncio.run(repository.add_video(video))
    service = ProductionService(
        repository,
        workspace,
        media_processor=FakeFrameProcessor(),
    )
    monkeypatch.setattr(main, "production_service", service)

    with TestClient(main.app) as client:
        created = client.post(
            f"/api/v1/records/{record.id}/productions",
            json={"base_analysis_id": str(analysis.id), "name": "视频选段新增分镜"},
        ).json()
        project_id = created["project"]["id"]
        first_shot_id = client.get(
            f"/api/v1/productions/{project_id}/shots"
        ).json()[0]["plan"]["id"]
        response = client.post(
            f"/api/v1/productions/{project_id}/shots",
            json={
                "expected_revision_id": created["project"]["current_revision_id"],
                "mode": "video_range",
                "insert_after_shot_plan_id": first_shot_id,
                "start_seconds": 1,
                "end_seconds": 3,
                "source_keyframe_timestamp_seconds": 2,
                "image_prompt": "新增的视频选段画面",
            },
        )
        assert response.status_code == 201, response.text
        plan = response.json()["plan"]
        assert plan["source_kind"] == "video_range"
        assert plan["source_keyframe_origin"] == "video_selection"
        assert plan["source_keyframe_timestamp_seconds"] == 2
        assert plan["index"] == 2
        keyframe = client.get(plan["source_keyframe_url"])
        assert keyframe.status_code == 200
        with Image.open(BytesIO(keyframe.content)) as rendered:
            assert rendered.size == (720, 1280)


def test_image_candidate_soft_delete_restore_and_approval_protection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, _ = await seed_completed_analysis(repository)
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(
                base_analysis_id=analysis.id,
                name="图片候选软删除",
            ),
        )
        shot = (await service.list_shots(detail.project.id))[0]
        current = await service.get_project(detail.project.id)
        queued = await service.create_image_run(
            shot.plan.id,
            ImageGenerationCreate(
                expected_revision_id=current.project.current_revision_id,
                candidate_count=2,
            ),
        )
        run = await wait_for_generation(service, queued.id)
        assert run.status == "completed"
        selected = await service.select_candidate(
            run.candidates[0].id,
            CandidateSelectRequest(
                expected_revision_id=(
                    await service.get_project(detail.project.id)
                ).project.current_revision_id,
            ),
        )

        deleted = await service.archive_generation_candidates(
            CandidateBatchLifecycleRequest(
                expected_revision_id=selected.shot.current_revision_id,
                candidate_ids=[run.candidates[1].id],
            ),
            actor_account_id=uuid4(),
        )
        assert deleted.candidates[0].status == GenerationCandidateStatus.ARCHIVED
        assert (
            deleted.candidates[0].archive_reason
            == GenerationCandidateArchiveReason.USER_DELETED
        )
        content, _ = await service.resolve_candidate_content(run.candidates[1].id)
        assert content.is_file()

        with pytest.raises(ProductionServiceError) as unavailable:
            await service.select_candidate(
                run.candidates[1].id,
                CandidateSelectRequest(
                    expected_revision_id=deleted.current_revision_id,
                ),
            )
        assert unavailable.value.code == "candidate_unavailable"

        restored = await service.restore_generation_candidates(
            CandidateBatchLifecycleRequest(
                expected_revision_id=deleted.current_revision_id,
                candidate_ids=[run.candidates[1].id],
            )
        )
        assert restored.candidates[0].status == GenerationCandidateStatus.READY
        assert restored.candidates[0].archive_reason is None

        approved = await service.approve_candidate(
            run.candidates[0].id,
            CandidateApprovalRequest(
                expected_revision_id=restored.current_revision_id,
                decision=ApprovalDecision.APPROVED,
            ),
        )
        with pytest.raises(ProductionServiceError) as protected:
            await service.archive_generation_candidates(
                CandidateBatchLifecycleRequest(
                    expected_revision_id=approved.shot.current_revision_id,
                    candidate_ids=[run.candidates[0].id],
                )
            )
        assert protected.value.code == "approved_image_candidate_archive_forbidden"

    asyncio.run(scenario())


def test_incompatible_shot_workflow_is_reset_and_rebuilt_per_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        root = tmp_path / "schema-reset-workspace"
        monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
        workspace = WorkspaceManager()
        repository = SQLiteStore(workspace.database_path)
        service = ProductionService(
            repository,
            workspace,
            image_gateway=FakeRealImageGateway(workspace),
        )
        record, _, analysis, _ = await seed_completed_analysis(repository)
        affected = await service.create_project(
            record.id,
            ProductionProjectCreate(
                base_analysis_id=analysis.id,
                name="需要重建的方案",
            ),
        )
        unaffected = await service.create_project(
            record.id,
            ProductionProjectCreate(
                base_analysis_id=analysis.id,
                name="不受影响的方案",
            ),
        )
        affected_plans = await repository.list_shot_plans(affected.project.id)
        unaffected_plan_ids = {
            item.id for item in await repository.list_shot_plans(unaffected.project.id)
        }
        affected_plan_ids = {item.id for item in affected_plans}
        invalid_plan = affected_plans[0]
        fake_run_id = uuid4()
        fake_candidate_id = uuid4()

        with sqlite3.connect(workspace.database_path) as connection:
            row = connection.execute(
                "SELECT payload FROM shot_plans WHERE record_key = ?",
                (str(invalid_plan.id),),
            ).fetchone()
            assert row is not None
            invalid_payload = json.loads(str(row[0]))
            invalid_payload["video_reference_bindings"] = [
                {
                    "id": str(uuid4()),
                    "role": "motion",
                    "source_kind": "generated_proxy",
                    "media_type": "video",
                    "reference_asset_id": str(uuid4()),
                    "person_class": "non_photoreal_proxy",
                    "rights_state": "confirmed",
                    "order": 1,
                    "enabled": True,
                }
            ]
            connection.execute(
                "UPDATE shot_plans SET payload = ? WHERE record_key = ?",
                (json.dumps(invalid_payload), str(invalid_plan.id)),
            )

            dependent_rows = {
                "reference_bindings": (
                    uuid4(),
                    {"shot_plan_id": str(invalid_plan.id)},
                ),
                "generation_runs": (
                    fake_run_id,
                    {
                        "project_id": str(affected.project.id),
                        "shot_plan_id": str(invalid_plan.id),
                    },
                ),
                "generation_candidates": (
                    fake_candidate_id,
                    {"generation_run_id": str(fake_run_id)},
                ),
                "video_provider_tasks": (
                    uuid4(),
                    {"generation_run_id": str(fake_run_id)},
                ),
                "video_clip_preparations": (
                    uuid4(),
                    {
                        "project_id": str(affected.project.id),
                        "shot_plan_id": str(invalid_plan.id),
                    },
                ),
                "approval_events": (
                    uuid4(),
                    {
                        "project_id": str(affected.project.id),
                        "shot_plan_id": str(invalid_plan.id),
                    },
                ),
                "continuity_reports": (
                    uuid4(),
                    {"project_id": str(affected.project.id)},
                ),
                "shot_video_generation_drafts": (
                    invalid_plan.id,
                    {
                        "project_id": str(affected.project.id),
                        "shot_plan_id": str(invalid_plan.id),
                    },
                ),
            }
            for table, (record_key, payload) in dependent_rows.items():
                connection.execute(
                    f"INSERT OR REPLACE INTO {table} (record_key, payload) VALUES (?, ?)",
                    (str(record_key), json.dumps(payload)),
                )
            connection.commit()

        with pytest.raises(ProductionServiceError) as removed_deep_link:
            await service.get_shot(invalid_plan.id)
        assert removed_deep_link.value.code == "shot_plan_not_found"

        recovered = await service.get_project(affected.project.id)
        rebuilt_plans = await repository.list_shot_plans(affected.project.id)

        assert recovered.shot_count == len(affected_plans)
        assert {item.id for item in rebuilt_plans}.isdisjoint(affected_plan_ids)
        assert all(not item.video_reference_bindings for item in rebuilt_plans)
        assert all(
            item.reference_policy_version == "video-reference-policy/v3-depth-only"
            for item in rebuilt_plans
        )
        assert {
            item.id for item in await repository.list_shot_plans(unaffected.project.id)
        } == unaffected_plan_ids

        with sqlite3.connect(workspace.database_path) as connection:
            for table, (record_key, _) in dependent_rows.items():
                remaining = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE record_key = ?",
                    (str(record_key),),
                ).fetchone()
                assert remaining == (0,)

    asyncio.run(scenario())


def test_batch451_video_generation_review_revoke_and_gate_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, repository = isolated_service(tmp_path, monkeypatch)
        record, _, analysis, _ = await seed_completed_analysis(repository)
        detail = await service.create_project(
            record.id,
            ProductionProjectCreate(
                base_analysis_id=analysis.id,
                name="Batch 4.5.1 视频基础架构",
            ),
        )
        shots = await service.list_shots(detail.project.id)

        for shot in shots:
            current = await service.get_project(detail.project.id)
            image_run = await service.create_image_run(
                shot.plan.id,
                ImageGenerationCreate(
                    expected_revision_id=current.project.current_revision_id,
                ),
            )
            image_run = await wait_for_generation(service, image_run.id)
            assert image_run.status == "completed"
            current = await service.get_project(detail.project.id)
            selected = await service.select_candidate(
                image_run.candidates[0].id,
                CandidateSelectRequest(
                    expected_revision_id=current.project.current_revision_id,
                ),
            )
            await service.approve_candidate(
                image_run.candidates[0].id,
                CandidateApprovalRequest(
                    expected_revision_id=selected.shot.current_revision_id,
                    decision=ApprovalDecision.APPROVED,
                ),
            )

        image_preview_shots = await service.list_shots(detail.project.id)
        assert all(item.image_preview is not None for item in image_preview_shots)
        assert all(
            item.image_preview.kind == "approved_image"
            for item in image_preview_shots
            if item.image_preview is not None
        )
        assert all(item.video_preview is None for item in image_preview_shots)

        current = await service.get_project(detail.project.id)
        advanced = await service.advance(
            detail.project.id,
            ProductionAdvanceRequest(
                expected_revision_id=current.project.current_revision_id,
                target_step=ProductionStep.SHOT_VIDEOS,
            ),
        )
        assert advanced.project.active_step == ProductionStep.SHOT_VIDEOS
        updated_video_plan = await service.update_shot(
            shots[0].plan.id,
            ShotPlanUpdate(
                expected_revision_id=advanced.project.current_revision_id,
                video_prompt="镜头缓慢向人物推进，人物自然抬手展示产品。",
                video_negative_constraints=["人物身份漂移", "画面抖动"],
            ),
        )
        assert updated_video_plan.plan.video_status == WorkflowItemStatus.READY
        current_after_video_edit = await service.get_project(detail.project.id)
        assert current_after_video_edit.project.active_step == ProductionStep.SHOT_VIDEOS
        service.video_gateway = VideoGenerationGateway(
            service.workspace,
            media_processor=FakeStillVideoProcessor(),
        )
        service.video_inspector = FakeVideoInspector()

        with pytest.raises(ProductionServiceError) as remote:
            await service.create_video_run(
                shots[0].plan.id,
                VideoGenerationCreate(
                    expected_revision_id=current_after_video_edit.project.current_revision_id,
                    execution_mode="remote_api",
                ),
            )
        assert remote.value.code == "video_remote_provider_not_configured"

        first_candidate_id = None
        for index, shot in enumerate(shots):
            current = await service.get_project(detail.project.id)
            requested_duration = (
                round(max(0.2, shot.plan.duration_seconds * 0.5), 3)
                if index == 0
                else shot.plan.duration_seconds
            )
            video_run = await service.create_video_run(
                shot.plan.id,
                VideoGenerationCreate(
                    expected_revision_id=current.project.current_revision_id,
                    candidate_count=2 if index == 0 else 1,
                    duration_seconds=requested_duration,
                ),
            )
            video_run = await wait_for_generation(service, video_run.id)
            assert video_run.status == "completed", (
                video_run.error_code,
                video_run.error_message,
            )
            assert video_run.kind == "video"
            assert video_run.input_mode == "image_to_video"
            assert video_run.execution_mode == "simulated"
            assert len(video_run.candidates) == (2 if index == 0 else 1)
            candidate = video_run.candidates[0]
            assert candidate.status == "ready", video_run.model_dump(mode="json")
            content_path, content_type = await service.resolve_candidate_content(
                candidate.id
            )
            thumbnail_path, thumbnail_type = await service.resolve_candidate_content(
                candidate.id,
                thumbnail=True,
            )
            assert content_path.is_file()
            assert content_type == "video/mp4"
            assert thumbnail_path.is_file()
            assert thumbnail_type == "image/webp"

            current = await service.get_project(detail.project.id)
            approved = await service.approve_candidate(
                candidate.id,
                CandidateApprovalRequest(
                    expected_revision_id=current.project.current_revision_id,
                    decision=ApprovalDecision.APPROVED,
                ),
            )
            assert approved.shot.plan.video_status == WorkflowItemStatus.APPROVED
            assert approved.approval_event is not None
            assert approved.approval_event.target_kind == "video"

            if index == 0:
                stale = await service.update_shot(
                    shot.plan.id,
                    ShotPlanUpdate(
                        expected_revision_id=approved.shot.current_revision_id,
                        confirm_stale=True,
                        video_prompt=(
                            "镜头缓慢向人物推进，人物自然抬手展示产品，结尾停顿。"
                        ),
                    ),
                )
                assert stale.plan.video_status == WorkflowItemStatus.STALE
                stale_gate = await service.gate_status(detail.project.id)
                assert "有 1 个分镜使用旧输入，尚未确认采用" in (
                    stale_gate.blocker_messages
                )

                with pytest.raises(ProductionServiceError) as stale_confirmation:
                    await service.approve_candidate(
                        candidate.id,
                        CandidateApprovalRequest(
                            expected_revision_id=stale.current_revision_id,
                            decision=ApprovalDecision.APPROVED,
                        ),
                    )
                assert stale_confirmation.value.code == "stale_input_confirmation_required"

                approved = await service.approve_candidate(
                    candidate.id,
                    CandidateApprovalRequest(
                        expected_revision_id=stale.current_revision_id,
                        decision=ApprovalDecision.APPROVED,
                        confirm_stale_input=True,
                    ),
                )
                assert approved.shot.plan.video_status == WorkflowItemStatus.APPROVED

            # The last shot intentionally skips the legacy preparation record. An
            # approved candidate must still be allowed into the independent editor.
            if index == len(shots) - 1:
                continue

            trim_in = 0.0 if index == 0 else 0.1
            trim_out = requested_duration if index == 0 else shot.plan.duration_seconds - 0.1
            prepared = await service.prepare_video_clip(
                shot.plan.id,
                VideoClipPreparationUpdate(
                    expected_revision_id=approved.shot.current_revision_id,
                    trim_in_seconds=trim_in,
                    trim_out_seconds=trim_out,
                    cover_timestamp_seconds=(trim_in + trim_out) / 2,
                    audio_mode=VideoClipAudioMode.MUTED,
                ),
            )
            assert prepared.status == VideoClipPreparationStatus.READY
            assert prepared.cover_url.endswith("/video-preparation/cover")
            assert prepared.prepared_duration_seconds == pytest.approx(trim_out - trim_in)
            if index == 0:
                assert prepared.duration_alignment == "outside_safe_range"
                assert prepared.blocker_messages == []
                assert len(prepared.warning_messages) == 1
                assert "请在剪辑阶段复核节奏" in prepared.warning_messages[0]
                stored_preparation = await repository.get_video_clip_preparation(shot.plan.id)
                assert stored_preparation is not None
                await repository.save_video_clip_preparation(
                    stored_preparation.model_copy(
                        update={
                            "status": VideoClipPreparationStatus.BLOCKED,
                            "blocker_messages": [
                                "裁剪后时长与原分镜差异过大；请调整入点、出点或重新生成视频"
                            ],
                            "warning_messages": [],
                        }
                    )
                )
                legacy_detail = await service.get_shot(shot.plan.id)
                assert legacy_detail.video_preparation is not None
                assert legacy_detail.video_preparation.status == VideoClipPreparationStatus.READY
                assert legacy_detail.video_preparation.blocker_messages == []
                assert legacy_detail.video_preparation.warning_messages

            if index == 0:
                first_candidate_id = candidate.id
                current = await service.get_project(detail.project.id)
                alternative_run = await service.create_video_run(
                    shot.plan.id,
                    VideoGenerationCreate(
                        expected_revision_id=current.project.current_revision_id,
                        candidate_count=1,
                        duration_seconds=requested_duration,
                        generation_intent="new_variation",
                        seed=20260810,
                    ),
                )
                alternative_run = await wait_for_generation(
                    service,
                    alternative_run.id,
                )
                assert alternative_run.status == "completed"
                alternative = alternative_run.candidates[0]

                history_detail = await service.get_shot(shot.plan.id)
                video_runs = [
                    run for run in history_detail.generation_runs if run.kind == "video"
                ]
                assert len(video_runs) == 2
                assert sum(len(run.candidates) for run in video_runs) == 3
                assert history_detail.plan.video_status == WorkflowItemStatus.APPROVED
                assert history_detail.plan.approved_video_candidate_id == candidate.id
                assert history_detail.video_preparation is not None
                assert history_detail.video_preparation.status == VideoClipPreparationStatus.READY
                old_candidate = await repository.get_generation_candidate(candidate.id)
                assert old_candidate is not None
                assert old_candidate.status == GenerationCandidateStatus.SELECTED

                await repository.save_generation_candidate(
                    old_candidate.model_copy(
                        update={"status": GenerationCandidateStatus.ARCHIVED}
                    )
                )
                repaired_history = await service.get_shot(shot.plan.id)
                repaired_old = next(
                    item
                    for run in repaired_history.generation_runs
                    for item in run.candidates
                    if item.id == candidate.id
                )
                assert repaired_old.status == GenerationCandidateStatus.SELECTED

                current = await service.get_project(detail.project.id)
                rejected_alternative = await service.approve_candidate(
                    alternative.id,
                    CandidateApprovalRequest(
                        expected_revision_id=current.project.current_revision_id,
                        decision=ApprovalDecision.REJECTED,
                        reason="动作节奏暂不符合当前选择",
                    ),
                )
                assert (
                    rejected_alternative.candidate.status
                    == GenerationCandidateStatus.REJECTED
                )
                assert (
                    rejected_alternative.shot.plan.approved_video_candidate_id
                    == candidate.id
                )
                rejected_history = await service.get_shot(shot.plan.id)
                retained_rejected = next(
                    item
                    for run in rejected_history.generation_runs
                    for item in run.candidates
                    if item.id == alternative.id
                )
                assert retained_rejected.status == GenerationCandidateStatus.REJECTED

                current = await service.get_project(detail.project.id)
                with pytest.raises(ProductionServiceError) as protected_archive:
                    await service.archive_video_candidates(
                        CandidateBatchLifecycleRequest(
                            expected_revision_id=current.project.current_revision_id,
                            candidate_ids=[candidate.id, alternative.id],
                        )
                    )
                assert (
                    protected_archive.value.code
                    == "approved_video_candidate_archive_forbidden"
                )
                unchanged_alternative = await repository.get_generation_candidate(
                    alternative.id
                )
                assert unchanged_alternative is not None
                assert unchanged_alternative.status == GenerationCandidateStatus.REJECTED

                actor_account_id = uuid4()
                archived = await service.archive_video_candidates(
                    CandidateBatchLifecycleRequest(
                        expected_revision_id=current.project.current_revision_id,
                        candidate_ids=[alternative.id],
                    ),
                    actor_account_id=actor_account_id,
                )
                assert archived.affected_count == 1
                assert archived.candidates[0].status == GenerationCandidateStatus.ARCHIVED
                assert (
                    archived.candidates[0].archive_reason
                    == GenerationCandidateArchiveReason.USER_DELETED
                )
                assert archived.candidates[0].archived_by_account_id == actor_account_id
                archived_content, _ = await service.resolve_candidate_content(
                    alternative.id
                )
                assert archived_content.is_file()
                archived_history = await service.get_shot(shot.plan.id)
                archived_alternative = next(
                    item
                    for run in archived_history.generation_runs
                    for item in run.candidates
                    if item.id == alternative.id
                )
                assert archived_alternative.status == GenerationCandidateStatus.ARCHIVED

                restored = await service.restore_video_candidates(
                    CandidateBatchLifecycleRequest(
                        expected_revision_id=archived.current_revision_id,
                        candidate_ids=[alternative.id],
                    )
                )
                assert restored.affected_count == 1
                assert restored.candidates[0].status == GenerationCandidateStatus.READY
                assert restored.candidates[0].archive_reason is None
                assert restored.candidates[0].archived_at is None

                rejected_again = await service.approve_candidate(
                    alternative.id,
                    CandidateApprovalRequest(
                        expected_revision_id=restored.current_revision_id,
                        decision=ApprovalDecision.REJECTED,
                        reason="保留历史候选，稍后复核",
                    ),
                )
                assert rejected_again.candidate.status == GenerationCandidateStatus.REJECTED
                switched = await service.approve_candidate(
                    alternative.id,
                    CandidateApprovalRequest(
                        expected_revision_id=rejected_again.shot.current_revision_id,
                        decision=ApprovalDecision.APPROVED,
                    ),
                )
                assert switched.shot.plan.approved_video_candidate_id == alternative.id
                assert switched.candidate.status == GenerationCandidateStatus.SELECTED
                switched_detail = await service.get_shot(shot.plan.id)
                assert switched_detail.video_preparation is not None
                assert (
                    switched_detail.video_preparation.status
                    == VideoClipPreparationStatus.STALE
                )
                old_candidate = await repository.get_generation_candidate(candidate.id)
                assert old_candidate is not None
                assert old_candidate.status == GenerationCandidateStatus.READY

                switched_back = await service.approve_candidate(
                    candidate.id,
                    CandidateApprovalRequest(
                        expected_revision_id=switched.shot.current_revision_id,
                        decision=ApprovalDecision.APPROVED,
                    ),
                )
                assert switched_back.shot.plan.approved_video_candidate_id == candidate.id
                prepared = await service.prepare_video_clip(
                    shot.plan.id,
                    VideoClipPreparationUpdate(
                        expected_revision_id=switched_back.shot.current_revision_id,
                        audio_mode=VideoClipAudioMode.MUTED,
                    ),
                )
                assert prepared.status == VideoClipPreparationStatus.READY

                reopened = await service.revoke_video_approval(
                    shot.plan.id,
                    ShotVideoApprovalRevokeRequest(
                        expected_revision_id=prepared.revision_id,
                    ),
                )
                assert reopened.shot.plan.video_status == WorkflowItemStatus.REVIEW_REQUIRED
                stale_detail = await service.get_shot(shot.plan.id)
                assert stale_detail.video_preparation is not None
                assert stale_detail.video_preparation.status == VideoClipPreparationStatus.STALE
                reselected = await service.select_candidate(
                    candidate.id,
                    CandidateSelectRequest(
                        expected_revision_id=reopened.shot.current_revision_id,
                    ),
                )
                approved = await service.approve_candidate(
                    candidate.id,
                    CandidateApprovalRequest(
                        expected_revision_id=reselected.shot.current_revision_id,
                        decision=ApprovalDecision.APPROVED,
                    ),
                )
                assert approved.shot.plan.approved_video_candidate_id == candidate.id
                prepared = await service.prepare_video_clip(
                    shot.plan.id,
                    VideoClipPreparationUpdate(
                        expected_revision_id=approved.shot.current_revision_id,
                        audio_mode=VideoClipAudioMode.MUTED,
                    ),
                )
                assert prepared.status == VideoClipPreparationStatus.READY

        assert first_candidate_id is not None
        video_preview_shots = await service.list_shots(detail.project.id)
        assert all(item.video_preview is not None for item in video_preview_shots)
        assert all(
            item.video_preview.kind == "approved_video"
            for item in video_preview_shots
            if item.video_preview is not None
        )
        first_detail = await service.get_shot(shots[0].plan.id)
        assert [run.kind for run in first_detail.generation_runs[:3]] == [
            "video",
            "video",
            "image",
        ]

        async def unexpected_continuity_call(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("进入剪辑不应触发跨分镜连续性检查")

        monkeypatch.setattr(
            service.continuity,
            "latest_report",
            unexpected_continuity_call,
        )
        monkeypatch.setattr(
            service.continuity,
            "ensure_current_report",
            unexpected_continuity_call,
        )
        gate = await service.gate_status(detail.project.id)
        assert gate.current_step == ProductionStep.SHOT_VIDEOS
        assert gate.next_step == ProductionStep.EDITING
        assert gate.allowed is True
        assert gate.approved_shot_count == len(shots)
        assert gate.prepared_shot_count == len(shots) - 1
        assert gate.quality_warning_shot_count == 1
        assert gate.continuity_status == "not_run"
        assert gate.continuity_blocker_count == 0
        assert await repository.get_video_clip_preparation(shots[-1].plan.id) is None

        current = await service.get_project(detail.project.id)
        editing = await service.advance(
            detail.project.id,
            ProductionAdvanceRequest(
                expected_revision_id=current.project.current_revision_id,
                target_step=ProductionStep.EDITING,
            ),
        )
        assert editing.project.active_step == ProductionStep.EDITING
        handoff = await service.get_editing_handoff(detail.project.id)
        assert handoff.audio_strategy == "muted"
        assert len(handoff.clips) == len(shots)
        assert handoff.clips[0].trim_in_seconds == 0.0
        assert handoff.clips[0].warning_messages
        assert handoff.clips[-1].quality_status == VideoQualityStatus.WARNING
        assert handoff.clips[-1].audio_mode == VideoClipAudioMode.MUTED
        assert handoff.clips[-1].trim_in_seconds == 0
        assert handoff.clips[-1].trim_out_seconds > 0
        assert handoff.clips[0].timeline_start_seconds == 0
        assert handoff.clips[-1].timeline_end_seconds == handoff.timeline_duration_seconds
        await service.shutdown_generation_runs()

    asyncio.run(scenario())
