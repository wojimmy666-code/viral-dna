from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

from viral_dna_api.models import (
    GenerationCandidate,
    GenerationKind,
    GenerationRun,
    ImageExecutionMode,
    ProductionRunStatus,
)
from viral_dna_api.platform_skills import PlatformSkillCatalogService
from viral_dna_api.projects import ProjectCreate, ProjectService
from viral_dna_api.skill_workflow.contracts import (
    CreativeBriefRevision,
    ExecutionStatus,
    LookTest,
    LookTestItem,
    RunContractRevision,
    SkillRun,
    SkillStepRun,
    SkillWorkflowStage,
    StyleBibleRevision,
)
from viral_dna_api.skill_workflow.service import SkillWorkflowService
from viral_dna_api.store import InMemoryStore


class FakeAccountContext:
    def __init__(self) -> None:
        self.account = SimpleNamespace(id=uuid4())

    async def current_account(self):
        return self.account


class ParallelImageGateway:
    def __init__(self, delays: dict[int, float] | None = None) -> None:
        self.active = 0
        self.max_active = 0
        self.execution_modes: list[ImageExecutionMode] = []
        self.model_aliases: list[str | None] = []
        self.delays = delays or {}

    async def generate(self, project, shot, revision_id, _bindings, _assets, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.execution_modes.append(kwargs["execution_mode"])
        self.model_aliases.append(kwargs["model_alias"])
        try:
            await asyncio.sleep(self.delays.get(shot.index, 0.04))
            generation_run_id = kwargs["run_id"]
            candidates = [
                GenerationCandidate(
                    generation_run_id=generation_run_id,
                    ordinal=index,
                    kind=GenerationKind.IMAGE,
                    relative_path=f"look-test/{generation_run_id}/{index}.png",
                    thumbnail_relative_path=f"look-test/{generation_run_id}/{index}-thumb.png",
                    width=project.output_width,
                    height=project.output_height,
                    sha256=f"{index:064x}",
                    metadata_relative_path=f"look-test/{generation_run_id}/{index}.json",
                )
                for index in range(1, kwargs["candidate_count"] + 1)
            ]
            run = GenerationRun(
                id=generation_run_id,
                project_id=project.id,
                shot_plan_id=shot.id,
                revision_id=revision_id,
                kind=GenerationKind.IMAGE,
                input_mode=kwargs["input_mode"],
                provider="dashscope",
                model="qwen-image-2.0-pro",
                model_snapshot="qwen-image-2.0-pro@test",
                model_alias=kwargs["model_alias"],
                prompt_version="test",
                schema_version="test",
                pricing_version="test",
                request_fingerprint="f" * 64,
                input_snapshot_relative_path=f"look-test/{generation_run_id}/input.json",
                execution_mode=kwargs["execution_mode"],
                adapter_id="test",
                adapter_version="test",
                status=ProductionRunStatus.COMPLETED,
                estimated_cost_micros=10,
                actual_cost_micros=10,
                latency_ms=40,
            )
            return run, candidates
        finally:
            self.active -= 1


async def seed_look_test(gateway: ParallelImageGateway):
    store = InMemoryStore()
    account = FakeAccountContext()
    catalog = PlatformSkillCatalogService(None)
    projects = ProjectService(store, catalog, account)
    service = SkillWorkflowService(store, projects, account, image_gateway=gateway)
    skill = await catalog.get_catalog_item("cinematic-product-story")
    project = await projects.create(
        ProjectCreate(
            kind="skill",
            name="Parallel Look Test",
            skill_version_id=skill.current_version.id,
        )
    )
    snapshot = await store.get_skill_version_snapshot(project.id)
    brief = CreativeBriefRevision(
        project_id=project.id,
        revision_number=1,
        brand_snapshot_id=uuid4(),
        objective="Create a cinematic product story",
        audience="Drivers",
        distribution_channel="douyin",
        target_duration_seconds=15,
        target_duration_frames=450,
        output_aspect_ratio="9:16",
        fps=30,
        creative_basis="brand_led",
        input_hash="sha256:" + "1" * 64,
    )
    await store.save_creative_brief_revision(brief)
    contract = RunContractRevision(
        project_id=project.id,
        revision_number=1,
        image_provider_connection_id="dashscope",
        image_model_id="qwen_image_2_pro",
        image_width=576,
        image_height=1024,
        video_provider_connection_id="gemini_omni",
        video_model_id="gemini_omni_1_1_flash",
        video_width=1080,
        video_height=1920,
        video_resolution_label="1080P",
        video_fps=30,
        video_duration_capabilities_seconds=[5],
        candidate_count_by_stage={"look_test": 2},
        text_model_selection="workspace_default",
        estimated_cost_micros=100,
        estimate_status="known",
        input_hash="sha256:" + "2" * 64,
    )
    await store.save_run_contract_revision(contract)
    bible = StyleBibleRevision(
        project_id=project.id,
        revision_number=1,
        skill_version_digest=snapshot.content_digest,
        brand_snapshot_digest="sha256:" + "3" * 64,
        brief_revision_id=brief.id,
        lighting={"direction": "soft"},
        composition={"layout": "centered"},
        positive_lock=["cinematic product lighting"],
        input_hash="sha256:" + "4" * 64,
        content_hash="sha256:" + "5" * 64,
    )
    await store.save_style_bible_revision(bible)
    shot_keys = ["shot_aaaaaaaa", "shot_bbbbbbbb"]
    look = LookTest(
        project_id=project.id,
        style_bible_revision_id=bible.id,
        representative_shot_keys=shot_keys,
        run_contract_revision_id=contract.id,
        items=[
            LookTestItem(shot_key=shot_key, requested_candidate_count=2) for shot_key in shot_keys
        ],
        output_width=576,
        output_height=1024,
    )
    await store.save_look_test(look)
    run = SkillRun(
        project_id=project.id,
        skill_version_snapshot_id=snapshot.id,
        run_contract_revision_id=contract.id,
        execution_status=ExecutionStatus.RUNNING,
    )
    await store.save_skill_run(run)
    return store, service, project, run, look


def test_look_test_uses_locked_remote_model_and_parallel_incremental_tasks() -> None:
    async def scenario() -> None:
        gateway = ParallelImageGateway()
        store, service, _, run, _ = await seed_look_test(gateway)

        before = time.perf_counter()
        started = await service.start_look_test_generation(run.id)
        assert time.perf_counter() - before < 0.1
        assert started.execution_status == ExecutionStatus.RUNNING
        completed = await service.generate_look_test(run.id)

        assert completed.execution_status == ExecutionStatus.SUCCEEDED
        assert completed.progress == 100
        assert len(completed.candidate_ids) == 4
        assert all(item.execution_status == ExecutionStatus.SUCCEEDED for item in completed.items)
        assert gateway.max_active == 2
        assert gateway.execution_modes == [
            ImageExecutionMode.REMOTE_API,
            ImageExecutionMode.REMOTE_API,
        ]
        assert gateway.model_aliases == ["qwen_image_2_pro", "qwen_image_2_pro"]
        for item in completed.items:
            generation_run = await store.get_generation_run(item.generation_run_id)
            assert generation_run is not None
            assert await store.get_production_project(generation_run.project_id) is not None
            assert await store.get_shot_plan(generation_run.shot_plan_id) is not None

    asyncio.run(scenario())


def test_look_test_cancel_preserves_completed_images() -> None:
    async def scenario() -> None:
        gateway = ParallelImageGateway(delays={1: 0.01, 2: 5})
        _, service, _, run, _ = await seed_look_test(gateway)

        await service.start_look_test_generation(run.id)
        await asyncio.sleep(0.12)
        cancelled = await service.cancel_look_test_generation(run.id)

        assert cancelled.execution_status == ExecutionStatus.CANCELLED
        assert cancelled.items[0].execution_status == ExecutionStatus.SUCCEEDED
        assert len(cancelled.items[0].candidate_ids) == 2
        assert cancelled.items[1].execution_status == ExecutionStatus.CANCELLED
        assert cancelled.items[1].retryable is True
        assert cancelled.progress == 50

    asyncio.run(scenario())


def test_recover_keeps_completed_images_and_releases_unsubmitted_items() -> None:
    async def scenario() -> None:
        gateway = ParallelImageGateway()
        store, service, project, run, look = await seed_look_test(gateway)
        completed_candidate_id = uuid4()
        interrupted = look.model_copy(
            update={
                "execution_status": ExecutionStatus.RUNNING,
                "progress": 50,
                "candidate_ids": [completed_candidate_id],
                "items": [
                    look.items[0].model_copy(
                        update={
                            "execution_status": ExecutionStatus.SUCCEEDED,
                            "progress": 100,
                            "candidate_ids": [completed_candidate_id],
                        }
                    ),
                    look.items[1].model_copy(update={"execution_status": ExecutionStatus.RUNNING}),
                ],
            }
        )
        await store.save_look_test(interrupted)
        await store.save_skill_step_run(
            SkillStepRun(
                skill_run_id=run.id,
                stage=SkillWorkflowStage.STYLE_CONFIRMATION,
                operation="generate_look_test",
                input_hash="sha256:" + "6" * 64,
                execution_status=ExecutionStatus.RUNNING,
            )
        )

        await service.recover()

        recovered = max(await store.list_look_tests(project.id), key=lambda item: item.updated_at)
        recovered_run = await store.get_skill_run(run.id)
        assert recovered.execution_status == ExecutionStatus.FAILED
        assert recovered.progress == 50
        assert recovered.items[0].execution_status == ExecutionStatus.SUCCEEDED
        assert recovered.items[0].candidate_ids == [completed_candidate_id]
        assert recovered.items[1].execution_status == ExecutionStatus.FAILED
        assert recovered.items[1].retryable is True
        assert recovered_run.execution_status == ExecutionStatus.RUNNING

    asyncio.run(scenario())


def test_workspace_repairs_legacy_success_without_candidates_and_allows_retry() -> None:
    async def scenario() -> None:
        gateway = ParallelImageGateway()
        store, service, project, run, look = await seed_look_test(gateway)
        await store.save_look_test(
            look.model_copy(update={"execution_status": ExecutionStatus.SUCCEEDED})
        )
        legacy_step = SkillStepRun(
            skill_run_id=run.id,
            stage=SkillWorkflowStage.STYLE_CONFIRMATION,
            operation="generate_look_test",
            input_hash="sha256:" + "7" * 64,
            execution_status=ExecutionStatus.SUCCEEDED,
            progress=100,
        )
        await store.save_skill_step_run(legacy_step)

        workspace = await service.workspace(project.id)

        assert workspace.look_test.execution_status == ExecutionStatus.FAILED
        assert workspace.look_test.progress == 0
        assert len(workspace.look_test.items) == 2
        assert all(item.retryable for item in workspace.look_test.items)
        repaired_step = await store.get_skill_step_run(legacy_step.id)
        assert repaired_step.execution_status == ExecutionStatus.FAILED
        assert repaired_step.error_code == "look_test_empty_result"

        completed = await service.generate_look_test(run.id)
        assert completed.execution_status == ExecutionStatus.SUCCEEDED
        assert len(completed.candidate_ids) == 4
        assert gateway.execution_modes == [
            ImageExecutionMode.REMOTE_API,
            ImageExecutionMode.REMOTE_API,
        ]

    asyncio.run(scenario())


def test_workspace_repairs_missing_look_test_media_relations() -> None:
    async def scenario() -> None:
        gateway = ParallelImageGateway()
        store, service, project, run, _ = await seed_look_test(gateway)
        completed = await service.generate_look_test(run.id)
        generation_runs = [
            await store.get_generation_run(item.generation_run_id) for item in completed.items
        ]
        for generation_run in generation_runs:
            store.production_projects.pop(generation_run.project_id, None)
            store.shot_plans.pop(generation_run.shot_plan_id, None)

        await service.workspace(project.id)

        for generation_run in generation_runs:
            assert await store.get_production_project(generation_run.project_id) is not None
            assert await store.get_shot_plan(generation_run.shot_plan_id) is not None

    asyncio.run(scenario())
