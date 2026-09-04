from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from viral_dna_api.models import (
    GenerationRun,
    ProductionOriginType,
    ProductionProject,
    ProductionTimeline,
    ShotPlan,
    ShotSourceKind,
    TimelineAudioTrack,
    TimelineBackgroundAudioTrack,
    TimelineClip,
    TimelineExportValidationSummary,
    TimelineRenderJob,
    TimelineRenderKind,
    TimelineRenderStatus,
    TimelineSubtitleCue,
    TimelineTransition,
    VideoClipAudioMode,
    WorkflowItemStatus,
)
from viral_dna_api.platform_skills import PlatformSkillCatalogService
from viral_dna_api.projects import ProjectCreate, ProjectService
from viral_dna_api.skill_workflow.contracts import (
    AssetUsageInput,
    BrandSnapshotCreate,
    CreativeBriefInput,
    DeliveryFromExportRequest,
    ExecutionStatus,
    GateActorType,
    GateDecision,
    GateDecisionRequest,
    GateDecisionValue,
    ProductionAudioCaptionFinalize,
    ProductionPictureLockRequest,
    RightsStatus,
    RunContractInput,
    SkillGate,
    SkillRunCreate,
    SkillStepRun,
    SkillWorkflowStage,
)
from viral_dna_api.skill_workflow.service import (
    SkillWorkflowService,
    SkillWorkflowServiceError,
)
from viral_dna_api.store import InMemoryStore


class FakeAccountContext:
    def __init__(self) -> None:
        self.account = SimpleNamespace(id=uuid4())

    async def current_account(self):
        return self.account


class FakeTimelineReader:
    def __init__(self, timeline: ProductionTimeline, audio_path: Path) -> None:
        self.timeline = timeline
        self.audio_path = audio_path

    async def get_timeline(self, project_id: UUID) -> ProductionTimeline:
        assert project_id == self.timeline.project_id
        return self.timeline

    async def resolve_background_audio(self, project_id: UUID):
        assert project_id == self.timeline.project_id
        return self.audio_path, self.timeline.background_audio_track


class FakeExportReader:
    def __init__(self) -> None:
        self.job: TimelineRenderJob | None = None

    async def get_export(self, project_id: UUID, job_id: UUID) -> TimelineRenderJob:
        assert self.job is not None
        assert project_id == self.job.project_id
        assert job_id == self.job.id
        return self.job


async def _prepared_runtime(
    tmp_path: Path,
) -> tuple[
    InMemoryStore,
    FakeAccountContext,
    ProjectService,
    SkillWorkflowService,
    UUID,
    UUID,
    FakeTimelineReader,
    FakeExportReader,
]:
    store = InMemoryStore()
    account = FakeAccountContext()
    catalog = PlatformSkillCatalogService(None)
    projects = ProjectService(store, catalog, account)
    skill = await catalog.get_catalog_item("cinematic-product-story")
    project = await projects.create(
        ProjectCreate(
            kind="skill",
            name="Delivery workflow",
            skill_version_id=skill.current_version.id,
        )
    )
    production_project_id = uuid4()
    candidate_id = uuid4()
    revision_id = uuid4()
    plan = ShotPlan(
        project_id=production_project_id,
        revision_id=revision_id,
        source_shot_id="shot_delivery0001",
        stable_shot_key="shot_delivery0001",
        index=1,
        order=1,
        timing_fps=30,
        start_frame=0,
        duration_frames=60,
        handle_in_frames=6,
        handle_out_frames=6,
        source_kind=ShotSourceKind.SKILL_GENERATED,
        source_keyframe_origin="skill",
        start_seconds=0,
        end_seconds=2,
        duration_seconds=2,
        image_status=WorkflowItemStatus.APPROVED,
        video_status=WorkflowItemStatus.APPROVED,
        approved_video_candidate_id=candidate_id,
    )
    await store.save_shot_plan(plan)
    clip = TimelineClip(
        shot_plan_id=plan.id,
        shot_index=1,
        candidate_id=candidate_id,
        candidate_content_url="/api/v1/media/final-candidate.mp4",
        order=1,
        candidate_duration_seconds=2,
        trim_in_seconds=0.25,
        trim_out_seconds=1.75,
        playback_rate=1,
        timeline_start_seconds=0,
        timeline_end_seconds=1.5,
        timeline_duration_seconds=1.5,
        audio_mode=VideoClipAudioMode.MUTED,
        candidate_audio_available=False,
        source_audio_start_seconds=0.25,
        source_audio_end_seconds=1.75,
        transition_after=TimelineTransition(kind="fade", duration_seconds=0.2),
    )
    production_timeline = ProductionTimeline(
        project_id=production_project_id,
        source_handoff_revision_id=revision_id,
        revision_id=uuid4(),
        revision_number=1,
        output_aspect_ratio="9:16",
        output_width=1080,
        output_height=1920,
        fps=30,
        duration_seconds=1.5,
        clips=[clip],
        audio_track=TimelineAudioTrack(strategy="muted", enabled=False),
    )
    audio_path = tmp_path / "music.bin"
    audio_path.write_bytes(b"licensed-audio-fixture")
    timeline_reader = FakeTimelineReader(production_timeline, audio_path)
    export_reader = FakeExportReader()
    service = SkillWorkflowService(
        store,
        projects,
        account,
        timeline_reader=timeline_reader,
        export_reader=export_reader,
    )
    brand = await service.create_brand_snapshot(
        project.id,
        BrandSnapshotCreate(name="ViralDNA", description="Video creation platform"),
    )
    usages = await service.replace_asset_usages(
        project.id,
        [
            AssetUsageInput(
                asset_id=uuid4(),
                role="product_hero",
                fidelity="identity_lock",
                rights_status="confirmed",
                allowed_distribution=["douyin"],
                snapshot_sha256="a" * 64,
            )
        ],
    )
    await service.put_brief(
        project.id,
        CreativeBriefInput(
            brand_snapshot_id=brand.id,
            objective="Launch a new product",
            audience="Creators",
            distribution_channel="douyin",
            target_duration_seconds=15,
            output_aspect_ratio="9:16",
            creative_basis="hybrid",
            selected_asset_usage_ids=[usages[0].id],
            skill_answers={"primary_message": "Reliable branded video production"},
        ),
    )
    contract = await service.put_run_contract(
        project.id,
        RunContractInput(
            image_provider_connection_id="dashscope",
            image_model_id="qwen_image_2_pro",
            image_width=1024,
            image_height=1824,
            video_provider_connection_id="gemini_omni",
            video_model_id="gemini_omni_1_1_flash",
            video_width=1080,
            video_height=1920,
            video_resolution_label="1080P",
            video_fps=30,
            video_duration_capabilities_seconds=[5, 8],
            text_model_selection="workspace_default",
            audio_source_strategy="muted",
            generate_video_audio=False,
            music_strategy="select",
            subtitle_strategy="final_speech",
            estimate_status="known",
            estimated_cost_micros=2_000_000,
            budget_limit_micros=5_000_000,
            supports_exact_overlay=True,
        ),
    )
    started = await service.start_run(
        project.id,
        SkillRunCreate(
            run_contract_revision_id=contract.id,
            idempotency_key="delivery-workflow-test",
        ),
    )
    await projects.bind_skill_run(
        project.id,
        production_project_id=production_project_id,
    )
    for gate in list(SkillGate)[:5]:
        await store.save_gate_decision(
            GateDecision(
                project_id=project.id,
                skill_run_id=started.run.id,
                gate=gate,
                decision=GateDecisionValue.APPROVE,
                actor_type=GateActorType.USER,
                actor_id=account.account.id,
            )
        )
    return (
        store,
        account,
        projects,
        service,
        project.id,
        started.run.id,
        timeline_reader,
        export_reader,
    )


def test_picture_lock_audio_caption_and_delivery_are_revision_bound(tmp_path: Path) -> None:
    async def scenario() -> None:
        (
            store,
            _,
            _,
            service,
            project_id,
            run_id,
            timeline_reader,
            export_reader,
        ) = await _prepared_runtime(tmp_path)
        source_audio_timeline = timeline_reader.timeline.model_copy(
            update={
                "revision_id": uuid4(),
                "audio_track": TimelineAudioTrack(strategy="per_shot", enabled=True),
                "clips": [
                    timeline_reader.timeline.clips[0].model_copy(
                        update={"audio_mode": VideoClipAudioMode.SOURCE}
                    )
                ],
            }
        )
        timeline_reader.timeline = source_audio_timeline
        with pytest.raises(SkillWorkflowServiceError) as unavailable_source:
            await service.picture_lock_from_production(
                run_id,
                ProductionPictureLockRequest(
                    production_project_id=source_audio_timeline.project_id,
                    expected_timeline_revision_id=source_audio_timeline.revision_id,
                ),
            )
        assert unavailable_source.value.code == "skill_source_audio_unavailable"

        visual_timeline = source_audio_timeline.model_copy(
            update={
                "revision_id": uuid4(),
                "clips": [
                    source_audio_timeline.clips[0].model_copy(
                        update={"audio_mode": VideoClipAudioMode.MUTED}
                    )
                ],
            }
        )
        timeline_reader.timeline = visual_timeline
        picture_lock = await service.picture_lock_from_production(
            run_id,
            ProductionPictureLockRequest(
                production_project_id=visual_timeline.project_id,
                expected_timeline_revision_id=visual_timeline.revision_id,
            ),
        )
        assert picture_lock.source_timeline_revision_id == visual_timeline.revision_id
        assert picture_lock.video_clips[0].source_in_frame == 8
        assert picture_lock.video_clips[0].duration_frames == 45
        assert picture_lock.video_clips[0].transition_after.duration_frames == 6
        await service.decide_gate(
            run_id,
            SkillGate.PICTURE_LOCKED,
            GateDecisionRequest(
                decision="approve",
                related_revision_ids=[picture_lock.id],
            ),
        )

        changed_visual = visual_timeline.model_copy(
            update={
                "revision_id": uuid4(),
                "revision_number": 2,
                "clips": [
                    visual_timeline.clips[0].model_copy(
                        update={
                            "trim_in_seconds": 0.3,
                            "timeline_duration_seconds": 1.45,
                            "timeline_end_seconds": 1.45,
                        }
                    )
                ],
            }
        )
        timeline_reader.timeline = changed_visual
        with pytest.raises(SkillWorkflowServiceError) as stale_picture:
            await service.finalize_audio_caption_from_production(
                run_id,
                ProductionAudioCaptionFinalize(
                    production_project_id=changed_visual.project_id,
                    expected_timeline_revision_id=changed_visual.revision_id,
                ),
            )
        assert stale_picture.value.code == "picture_lock_stale"

        audio_timeline = visual_timeline.model_copy(
            update={
                "revision_id": uuid4(),
                "revision_number": 3,
                "background_audio_track": TimelineBackgroundAudioTrack(
                    source_relative_path="audio/music.bin",
                    source_url="/api/v1/media/music.bin",
                    name="Licensed music",
                    enabled=True,
                    volume=0.5,
                    loop=True,
                    source_duration_seconds=3,
                    timeline_start_seconds=0,
                    timeline_end_seconds=1.5,
                ),
                "subtitle_cues": [
                    TimelineSubtitleCue(
                        id="caption-1",
                        text="Reliable branded video production",
                        language="zh-CN",
                        start_seconds=0,
                        end_seconds=1,
                    )
                ],
            }
        )
        timeline_reader.timeline = audio_timeline
        final_timeline = await service.finalize_audio_caption_from_production(
            run_id,
            ProductionAudioCaptionFinalize(
                production_project_id=audio_timeline.project_id,
                expected_timeline_revision_id=audio_timeline.revision_id,
                background_audio_kind="music",
                background_audio_rights_status=RightsStatus.CONFIRMED,
                integrated_loudness_lufs=-14,
                true_peak_dbtp=-1,
            ),
        )
        assert final_timeline.source_timeline_revision_id == audio_timeline.revision_id
        assert final_timeline.music
        assert final_timeline.subtitles[0].speech_revision_id == audio_timeline.revision_id
        mixes = await store.list_mix_revisions(project_id)
        assert mixes[-1].validation_status == "passed"
        await service.decide_gate(
            run_id,
            SkillGate.AUDIO_CAPTION_APPROVED,
            GateDecisionRequest(
                decision="approve",
                related_revision_ids=[final_timeline.id, mixes[-1].id],
            ),
        )

        wrong_summary = TimelineExportValidationSummary(
            valid=True,
            expected_duration_seconds=1.5,
            duration_seconds=1.5,
            width=720,
            height=1280,
            fps=30,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
            has_subtitles=True,
            size_bytes=1024,
            sha256="b" * 64,
        )
        export_reader.job = TimelineRenderJob(
            project_id=audio_timeline.project_id,
            timeline_revision_id=audio_timeline.revision_id,
            kind=TimelineRenderKind.FINAL,
            status=TimelineRenderStatus.SUCCEEDED,
            progress_percent=100,
            preview_width=720,
            preview_height=1280,
            output_filename="final.mp4",
            output_url="/api/v1/media/final.mp4",
            file_size_bytes=1024,
            sha256="b" * 64,
            validation_summary=wrong_summary,
        )
        with pytest.raises(SkillWorkflowServiceError) as wrong_resolution:
            await service.create_delivery_from_export(
                run_id,
                DeliveryFromExportRequest(
                    production_project_id=audio_timeline.project_id,
                    export_job_id=export_reader.job.id,
                ),
            )
        assert wrong_resolution.value.code == "export_resolution_mismatch"

        missing_audio_summary = wrong_summary.model_copy(
            update={"width": 1080, "height": 1920, "has_audio": False}
        )
        export_reader.job = export_reader.job.model_copy(
            update={
                "preview_width": 1080,
                "preview_height": 1920,
                "validation_summary": missing_audio_summary,
            }
        )
        with pytest.raises(SkillWorkflowServiceError) as missing_audio:
            await service.create_delivery_from_export(
                run_id,
                DeliveryFromExportRequest(
                    production_project_id=audio_timeline.project_id,
                    export_job_id=export_reader.job.id,
                ),
            )
        assert missing_audio.value.code == "export_audio_missing"

        missing_subtitles_summary = missing_audio_summary.model_copy(
            update={"has_audio": True, "has_subtitles": False}
        )
        export_reader.job = export_reader.job.model_copy(
            update={"validation_summary": missing_subtitles_summary}
        )
        with pytest.raises(SkillWorkflowServiceError) as missing_subtitles:
            await service.create_delivery_from_export(
                run_id,
                DeliveryFromExportRequest(
                    production_project_id=audio_timeline.project_id,
                    export_job_id=export_reader.job.id,
                ),
            )
        assert missing_subtitles.value.code == "export_subtitles_missing"

        correct_summary = missing_subtitles_summary.model_copy(
            update={"has_subtitles": True}
        )
        export_reader.job = export_reader.job.model_copy(
            update={"validation_summary": correct_summary}
        )
        manifest = await service.create_delivery_from_export(
            run_id,
            DeliveryFromExportRequest(
                production_project_id=audio_timeline.project_id,
                export_job_id=export_reader.job.id,
            ),
        )
        assert manifest.files[0].media["width"] == 1080
        assert manifest.rights_summary["audio_asset_ids"]
        await service.decide_gate(
            run_id,
            SkillGate.DELIVERY_APPROVED,
            GateDecisionRequest(
                decision="approve",
                related_revision_ids=[manifest.id],
            ),
        )
        assert (await service.run_detail(run_id)).run.execution_status == "succeeded"

    asyncio.run(scenario())


def test_budget_recovery_and_retry_guards_are_durable(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, _, _, service, _, run_id, _, _ = await _prepared_runtime(tmp_path)
        run = await store.get_skill_run(run_id)
        assert run is not None
        over_budget = run.model_copy(
            update={
                "execution_status": ExecutionStatus.RUNNING,
                "actual_cost_micros": 5_000_001,
            }
        )
        await store.save_skill_run(over_budget)
        with pytest.raises(SkillWorkflowServiceError) as budget_error:
            await service.compile_style(run_id)
        assert budget_error.value.code == "budget_exceeded"
        assert (await store.get_skill_run(run_id)).execution_status == ExecutionStatus.BLOCKED

        await store.save_skill_run(
            over_budget.model_copy(
                update={
                    "execution_status": ExecutionStatus.RUNNING,
                    "actual_cost_micros": 0,
                }
            )
        )
        provider_step = SkillStepRun(
            skill_run_id=run_id,
            stage=SkillWorkflowStage.STYLE_CONFIRMATION,
            operation="paid_provider_call",
            input_hash=f"sha256:{'c' * 64}",
            execution_status=ExecutionStatus.RUNNING,
            request_id="provider-request-1",
        )
        local_step = SkillStepRun(
            skill_run_id=run_id,
            stage=SkillWorkflowStage.STORYBOARD_DESIGN,
            operation="local_compile",
            input_hash=f"sha256:{'d' * 64}",
            execution_status=ExecutionStatus.RUNNING,
        )
        await store.save_skill_step_run(provider_step)
        await store.save_skill_step_run(local_step)
        await service.recover()
        recovered_provider = await store.get_skill_step_run(provider_step.id)
        recovered_local = await store.get_skill_step_run(local_step.id)
        assert recovered_provider.execution_status == ExecutionStatus.BLOCKED
        assert recovered_provider.error_code == "provider_reconcile_required"
        assert recovered_provider.retryable is False
        assert recovered_local.execution_status == ExecutionStatus.FAILED
        assert recovered_local.error_code == "worker_interrupted"
        assert recovered_local.retryable is True
        retry = await service.retry_step(run_id, local_step.id)
        assert retry.attempt == 2
        assert retry.execution_status == ExecutionStatus.PENDING

    asyncio.run(scenario())


def test_run_metrics_include_downstream_generation_wait_model_and_cost(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (
            store,
            _,
            _,
            service,
            project_id,
            run_id,
            timeline_reader,
            _,
        ) = await _prepared_runtime(tmp_path)
        production_id = timeline_reader.timeline.project_id
        production = ProductionProject(
            id=production_id,
            record_id=project_id,
            owner_project_id=project_id,
            origin_type=ProductionOriginType.SKILL_RUN,
            origin_id=run_id,
            production_seed_id=uuid4(),
            style_bible_revision_id=uuid4(),
            name="Skill production metrics",
            current_revision_id=uuid4(),
            output_aspect_ratio="9:16",
            output_width=1080,
            output_height=1920,
            estimated_cost_micros=350_000,
            actual_cost_micros=300_000,
        )
        await store.save_production_project(production)
        plan = (await store.list_shot_plans(production_id))[0]
        finished = datetime.now(UTC)
        generation = GenerationRun(
            project_id=production_id,
            shot_plan_id=plan.id,
            revision_id=plan.revision_id,
            kind="image",
            provider="test-provider",
            model="test-image-model",
            model_snapshot="test-image-model@1",
            prompt_version="test/v1",
            schema_version="test/v1",
            pricing_version="test/v1",
            request_fingerprint="f" * 64,
            input_snapshot_relative_path="runs/image/input.json",
            status="completed",
            estimated_cost_micros=350_000,
            actual_cost_micros=300_000,
            latency_ms=5_000,
            retry_count=1,
            created_at=finished - timedelta(seconds=10),
            started_at=finished - timedelta(seconds=8),
            updated_at=finished,
            completed_at=finished,
        )
        await store.save_generation_run(generation)

        metrics = await service.run_metrics(run_id)
        image_stage = next(item for item in metrics.stages if item.stage == "shot_images")
        assert image_stage.queue_wait_ms == 2_000
        assert image_stage.provider_ms == 5_000
        assert image_stage.postprocess_ms == 3_000
        assert image_stage.total_ms == 10_000
        assert image_stage.retry_count == 1
        assert metrics.actual_cost_micros == 300_000

        operations = await service.operations_summary()
        item = next(value for value in operations.items if value.run_count == 1)
        assert item.average_actual_cost_micros == 300_000
        assert item.average_total_ms >= 10_000

    asyncio.run(scenario())
