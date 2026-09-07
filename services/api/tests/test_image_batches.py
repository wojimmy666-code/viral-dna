from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from test_generation_jobs import _project, _shot, _workspace

from viral_dna_api.image_batches_models import ImageBatchRequest
from viral_dna_api.models import (
    GenerationCandidate,
    ProductionProject,
    ProductionRunStatus,
    PromptAssetMention,
    ReferenceAsset,
    ReferenceBinding,
    ShotVisualBeat,
    WorkflowItemStatus,
    utc_now,
)
from viral_dna_api.production import ProductionService, ProductionServiceError
from viral_dna_api.production_seeds import (
    ProductionSeedAudioIntent,
    ProductionSeedShot,
    ProductionSeedSubtitleIntent,
    SkillProductionSeedBuilder,
    canonical_digest,
)
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.store import InMemoryStore


class ControlledGateway:
    def __init__(self, repository):
        self.repository = repository
        self.release = asyncio.Event()
        self.calls = []
        self.release_first = asyncio.Event()
        self.active = 0
        self.max_active = 0

    async def generate(self, project, shot, revision, bindings, assets, **options):
        self.calls.append((shot.id, options, bindings))
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            waits = [asyncio.create_task(self.release.wait())]
            if len(self.calls) == 1:
                waits.append(asyncio.create_task(self.release_first.wait()))
            try:
                await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for waiting in waits:
                    waiting.cancel()
                await asyncio.gather(*waits, return_exceptions=True)
            run = await self.repository.get_generation_run(options["run_id"])
            run = run.model_copy(
                update={
                    "status": ProductionRunStatus.COMPLETED,
                    "provider": "dashscope",
                    "model": "qwen-image-2.0-pro",
                    "adapter_id": "dashscope-qwen-image",
                    "actual_cost_micros": 100,
                    "estimated_cost_micros": 100,
                    "completed_at": utc_now(),
                }
            )
            candidate = GenerationCandidate(
                generation_run_id=run.id,
                ordinal=1,
                kind="image",
                relative_path=f"images/{run.id}.png",
                thumbnail_relative_path=f"images/{run.id}.webp",
                sha256="a" * 64,
                metadata_relative_path=f"images/{run.id}.json",
            )
            return run, [candidate]
        finally:
            self.active -= 1


async def environment(tmp_path, monkeypatch, count=5, durable=False):
    workspace = _workspace(tmp_path, monkeypatch)
    store = SQLiteStore(workspace.database_path) if durable else InMemoryStore()
    project = ProductionProject.model_validate(
        {
            **_project().model_dump(),
            "origin_type": "skill_run",
            "origin_id": uuid4(),
            "production_seed_id": uuid4(),
            "style_bible_revision_id": uuid4(),
            "video_id": None,
            "base_analysis_id": None,
            "source_prompt_package_id": None,
            "active_step": "shot_images",
        }
    )
    await store.save_production_project(project)
    shots = []
    for index in range(count):
        shot = type(_shot(project)).model_validate(
            {**_shot(project).model_dump(), "index": index + 1, "source_kind": "skill_generated"}
        )
        await store.save_shot_plan(shot)
        shots.append(shot)
    seed_shots = []
    for index, shot in enumerate(shots):
        seed_shot = {
            "stable_shot_key": f"shot_batch{index:04d}",
            "order": index + 1,
            "start_frame": index * 90,
            "duration_frames": 90,
            "description": "测试画面",
            "image_prompt": shot.image_prompt,
            "video_prompt": "缓慢推进",
        }
        seed_shot["input_hash"] = canonical_digest(seed_shot)
        seed_shots.append(ProductionSeedShot.model_validate(seed_shot))
    seed = SkillProductionSeedBuilder().build(
        owner_project_id=project.owner_project_id,
        skill_run_id=project.origin_id,
        name=project.name,
        output_aspect_ratio="9:16",
        output_width=1080,
        output_height=1920,
        fps=30,
        style_bible_revision_id=project.style_bible_revision_id,
        style_bible_snapshot={"palette": "brand"},
        shots=seed_shots,
        reference_assets=[],
        audio_intent=ProductionSeedAudioIntent(clip_audio_strategy="candidate"),
        subtitle_intent=ProductionSeedSubtitleIntent(enabled=False, source="none"),
    )
    await store.save_production_seed(seed)
    project = project.model_copy(update={"production_seed_id": seed.id})
    await store.save_production_project(project)
    gateway = ControlledGateway(store)
    service = ProductionService(store, workspace, image_gateway=gateway)
    service._skill_run_contract = AsyncMock(
        return_value=SimpleNamespace(
            image_model_id="qwen_image_2_pro",
            image_provider_connection_id="dashscope",
            allow_unknown_local_image_cost=False,
            budget_limit_micros=None,
            automation_mode="guided",
            candidate_count_by_stage={"shot_image": 1},
            image_width=576,
            image_height=1024,
        )
    )
    return SimpleNamespace(
        store=store,
        project=project,
        shots=shots,
        gateway=gateway,
        service=service,
        batch=service.image_batches,
        workspace=workspace,
    )


async def until(predicate, deadline_seconds=6):
    async with asyncio.timeout(deadline_seconds):
        while not predicate():  # noqa: ASYNC110 - observes persisted state, not an event producer
            await asyncio.sleep(0.01)


async def finish(env, batch):
    env.gateway.release.set()
    task = env.batch.tasks.get(batch.id)
    if task:
        await asyncio.wait_for(task, 10)
    return await env.store.get_image_batch(batch.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_parallel_three_progress_cost_and_idempotency(tmp_path, monkeypatch, durable):
    env = await environment(tmp_path, monkeypatch, durable=durable)
    request = ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    batch = await env.batch.create(env.project.id, request)
    try:
        await until(lambda: env.gateway.active == 3)
        assert env.gateway.max_active == 3
        assert (await env.batch.create(env.project.id, request)).id == batch.id
        assert (
            sum(item.status == "running" for item in (await env.batch.latest(env.project.id)).items)
            == 3
        )
        # An editor operation can acquire the project lock while providers are running.
        lock = await env.service._project_lock(env.project.id)
        await asyncio.wait_for(lock.acquire(), 0.3)
        lock.release()
        result = await finish(env, batch)
        assert result.status == "completed", [
            (item.status, item.error_message) for item in result.items
        ]
        assert all(item.candidate_ids for item in result.items)
        assert len(env.gateway.calls) == 5
        assert env.gateway.max_active == 3
        assert (await env.store.get_production_project(env.project.id)).actual_cost_micros == 500
        for shot in env.shots:
            assert (await env.store.get_shot_plan(shot.id)).image_status == "review_required"
        latest = await env.store.get_production_project(env.project.id)
        preview = await env.batch.preview(
            env.project.id, ImageBatchRequest(expected_revision_id=latest.current_revision_id)
        )
        assert all(item.status == "pending" for item in preview.items)
        preview = await env.batch.preview(
            env.project.id,
            ImageBatchRequest(expected_revision_id=latest.current_revision_id, mode="missing"),
        )
        assert all(item.status == "skipped" for item in preview.items)
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_stop_pending_and_resume_only_missing(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=5)
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    try:
        await until(lambda: env.gateway.active == 3)
        stopped = await env.batch.stop(env.project.id, batch.id)
        assert sum(item.status == "cancelled" for item in stopped.items) == 2
        finished = await finish(env, batch)
        assert len(env.gateway.calls) == 3
        assert finished.status == "cancelled"
        defaults = env.service._skill_run_contract.return_value
        defaults.image_model_id = defaults.image_provider_connection_id = "local_tool"
        defaults.image_width, defaults.image_height = 1080, 1920
        await env.batch.resume(env.project.id, batch.id)
        finished = await finish(env, batch)
        assert finished.status == "completed"
        assert len(env.gateway.calls) == 5
        assert (finished.model_alias, finished.width, finished.height) == (
            "qwen_image_2_pro",
            576,
            1024,
        )
        assert all(call[1]["model_alias"] == "qwen_image_2_pro" for call in env.gateway.calls)
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_reload_and_restart_never_resubmit_unknown_outcomes(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=4, durable=True)
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    await until(lambda: env.gateway.active == 3)
    await env.service.shutdown_generation_runs()
    second = ProductionService(
        SQLiteStore(env.workspace.database_path), env.workspace, image_gateway=env.gateway
    )
    second._skill_run_contract = env.service._skill_run_contract
    try:
        await second.recover_generation_runs()
        interrupted = await second.image_batches.latest(env.project.id)
        assert interrupted.status == "interrupted"
        assert len(env.gateway.calls) == 3
        env.gateway.release.set()
        await second.image_batches.resume(env.project.id, batch.id)
        await asyncio.wait_for(second.image_batches.tasks[batch.id], 10)
        result = await second.image_batches.latest(env.project.id)
        assert len(env.gateway.calls) == 4  # Only the never-submitted fourth picture.
        assert sum(item.status == "unknown" for item in result.items) == 3
    finally:
        await second.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_edited_prompt_is_not_overwritten_by_late_result(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    try:
        await until(lambda: env.gateway.active == 1)
        shot = await env.store.get_shot_plan(env.shots[0].id)
        beat = shot.visual_beats[0].model_copy(
            update={"image_prompt": "人工修改的新画面", "image_status": WorkflowItemStatus.READY}
        )
        await env.store.save_shot_plan(
            shot.model_copy(
                update={
                    "visual_beats": [beat],
                    "image_prompt": beat.image_prompt,
                    "revision_id": uuid4(),
                }
            )
        )
        await finish(env, batch)
        final = await env.store.get_shot_plan(shot.id)
        assert final.visual_beats[0].image_prompt == "人工修改的新画面"
        assert final.visual_beats[0].image_status == "ready"
        assert (
            len(
                await env.store.list_generation_candidates_by_run_ids(
                    {item.run_id for item in (await env.batch.latest(env.project.id)).items}
                )
            )
            == 1
        )
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_preview_per_picture_references_and_multiple_beats(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot = env.shots[0]
    assets = []
    for index in range(20):
        asset = ReferenceAsset(
            project_id=env.project.id,
            type="product",
            name=f"参考{index}",
            relative_path=f"refs/{index}.png",
            sha256="a" * 64,
            rights_confirmed=True,
            width=64,
            height=64,
            mime_type="image/png",
        )
        assets.append(asset)
        await env.store.save_reference_asset(asset)
        await env.store.save_reference_binding(
            ReferenceBinding(shot_plan_id=shot.id, reference_asset_id=asset.id, role="product")
        )
    first = shot.visual_beats[0].model_copy(
        update={
            "end_ratio": 0.5,
            "image_prompt_mentions": [
                PromptAssetMention(reference_asset_id=asset.id, label=asset.name)
                for asset in assets[:2]
            ],
        }
    )
    second = ShotVisualBeat(
        index=2,
        title="画面2",
        start_ratio=0.5,
        end_ratio=1,
        image_prompt="细节画面",
        source_origin="skill",
    )
    await env.store.save_shot_plan(shot.model_copy(update={"visual_beats": [first, second]}))
    preview = await env.batch.preview(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    assert len(preview.items) == 1
    assert preview.items[0].visual_beat_id == first.id
    # Automatic missing-output recovery still covers every required visual beat.
    preview = await env.batch.preview(
        env.project.id,
        ImageBatchRequest(expected_revision_id=env.project.current_revision_id, mode="missing"),
    )
    assert len(preview.items) == 2
    assert all(item.status == "pending" for item in preview.items)
    assert (
        len(
            env.service._image_bindings_for_beat(
                shot, first, await env.store.list_reference_bindings(shot.id)
            )
        )
        == 2
    )
    assert (
        env.service._image_bindings_for_beat(
            shot, second, await env.store.list_reference_bindings(shot.id)
        )
        == []
    )


@pytest.mark.asyncio
async def test_batch_fixes_one_image_and_primary_beat_without_changing_defaults(
    tmp_path, monkeypatch
):
    env = await environment(tmp_path, monkeypatch, count=2)
    defaults = env.service._skill_run_contract.return_value
    defaults.candidate_count_by_stage = {"shot_image": 4}
    primary_ids = []
    for shot in env.shots:
        first = shot.visual_beats[0].model_copy(update={"end_ratio": 0.5})
        second = ShotVisualBeat(
            index=2,
            title="补充画面",
            start_ratio=0.5,
            end_ratio=1,
            image_prompt="细节特写",
            source_origin="skill",
        )
        await env.store.save_shot_plan(shot.model_copy(update={"visual_beats": [second, first]}))
        primary_ids.append(first.id)
    request = ImageBatchRequest(
        expected_revision_id=env.project.current_revision_id, candidate_count=4
    )
    preview = await env.batch.preview(env.project.id, request)
    assert preview.candidate_count == 1
    assert [item.visual_beat_id for item in preview.items] == primary_ids
    baseline = await env.batch.preview(
        env.project.id, request.model_copy(update={"candidate_count": 1})
    )
    assert preview.estimated_cost_micros == baseline.estimated_cost_micros
    batch = await env.batch.create(env.project.id, request)
    try:
        result = await finish(env, batch)
        assert result.status == "completed", result.model_dump()
        assert len(env.gateway.calls) == len(env.shots)
        assert all(call[1]["candidate_count"] == 1 for call in env.gateway.calls)
        assert defaults.candidate_count_by_stage == {"shot_image": 4}
        assert request.candidate_count == 4
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_legacy_batch_resume_preserves_frozen_multi_image_membership(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot = env.shots[0]
    first = shot.visual_beats[0].model_copy(update={"end_ratio": 0.5})
    second = ShotVisualBeat(
        index=2,
        title="补充画面",
        start_ratio=0.5,
        end_ratio=1,
        image_prompt="细节特写",
        source_origin="skill",
    )
    await env.store.save_shot_plan(shot.model_copy(update={"visual_beats": [first, second]}))
    preview = await env.batch.preview(
        env.project.id,
        ImageBatchRequest(
            expected_revision_id=env.project.current_revision_id,
            mode="missing",
        ),
    )
    legacy = preview.model_copy(
        update={
            "mode": "all",
            "candidate_count": 2,
            "status": "cancelled",
            "items": [
                item.model_copy(update={"status": "cancelled", "retryable": True})
                for item in preview.items
            ],
        }
    )
    await env.store.save_image_batch(legacy)
    env.service._skill_run_contract.return_value.candidate_count_by_stage = {"shot_image": 4}
    try:
        resumed = await env.batch.resume(env.project.id, legacy.id)
        result = await finish(env, resumed)
        assert result.status == "completed", result.model_dump()
        assert [item.visual_beat_id for item in result.items] == [first.id, second.id]
        assert result.candidate_count == 2
        assert len(env.gateway.calls) == 2
        assert all(call[1]["candidate_count"] == 2 for call in env.gateway.calls)
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_regenerate_preserves_approval_and_history(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    try:
        result = await finish(env, batch)
        shot = await env.store.get_shot_plan(env.shots[0].id)
        approved_id = result.items[0].candidate_ids[0]
        beat = shot.visual_beats[0].model_copy(
            update={
                "image_status": WorkflowItemStatus.APPROVED,
                "approved_image_candidate_id": approved_id,
            }
        )
        await env.store.save_shot_plan(
            shot.model_copy(
                update={
                    "visual_beats": [beat],
                    "image_status": WorkflowItemStatus.APPROVED,
                    "approved_image_candidate_id": approved_id,
                }
            )
        )
        current = await env.store.get_production_project(env.project.id)
        second = await env.batch.create(
            env.project.id,
            ImageBatchRequest(expected_revision_id=current.current_revision_id),
        )
        result = await finish(env, second)
        assert result.status == "completed", result.model_dump()
        shot = await env.store.get_shot_plan(shot.id)
        assert shot.visual_beats[0].approved_image_candidate_id == approved_id
        assert shot.visual_beats[0].image_status == "approved"
        assert len(await env.store.list_generation_runs(env.project.id)) == 2
        assert all(not call[1]["reuse_cache"] for call in env.gateway.calls)
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_concurrent_budget_reservations(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    await env.store.save_production_project(
        env.project.model_copy(update={"budget_limit_micros": 150})
    )
    await env.service._reserve_image_cost(env.project.id, uuid4(), 100)
    with pytest.raises(ProductionServiceError, match="预留费用"):
        await env.service._reserve_image_cost(env.project.id, uuid4(), 100)


@pytest.mark.asyncio
async def test_navigation_is_small_no_prompts_or_images(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=11)
    navigation = await env.service.shot_navigation(env.project.id)
    assert len(navigation) == 11
    assert "image_prompt" not in navigation[0]["plan"]
    assert "source_keyframe_url" not in navigation[0]["plan"]
    assert "image_preview" not in navigation[0]


@pytest.mark.asyncio
async def test_each_completed_picture_is_persisted_before_batch_finishes(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=4)
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    try:
        await until(lambda: env.gateway.active == 3)
        env.gateway.release_first.set()
        async with asyncio.timeout(5):
            while True:
                current = await env.batch.latest(env.project.id)
                if any(item.status == "completed" for item in current.items):
                    break
                await asyncio.sleep(0.02)
        assert current.status == "running"
        completed = next(item for item in current.items if item.status == "completed")
        assert len(await env.store.list_generation_candidates(completed.run_id)) == 1
        assert sum(item.status == "completed" for item in current.items) == 1
        await finish(env, batch)
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_resume_all_mode_estimates_only_unfinished_items(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=4)
    batch = await env.batch.create(
        env.project.id,
        ImageBatchRequest(expected_revision_id=env.project.current_revision_id, mode="all"),
    )
    try:
        await until(lambda: env.gateway.active == 3)
        await env.batch.stop(env.project.id, batch.id)
        result = await finish(env, batch)
        assert sum(item.status == "completed" for item in result.items) == 3
        project = await env.store.get_production_project(env.project.id)
        await env.store.save_production_project(
            project.model_copy(update={"budget_limit_micros": 500_300})
        )
        await env.batch.resume(env.project.id, batch.id)
        result = await finish(env, batch)
        assert result.status == "completed"
        assert len(env.gateway.calls) == 4
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_unknown_provider_outcome_is_not_resubmitted_by_new_batch(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    try:
        result = await finish(env, batch)
        run = await env.store.get_generation_run(result.items[0].run_id)
        await env.store.save_generation_run(
            run.model_copy(
                update={
                    "status": ProductionRunStatus.FAILED,
                    "error_code": "remote_outcome_unknown",
                }
            )
        )
        project = await env.store.get_production_project(env.project.id)
        preview = await env.batch.preview(
            env.project.id, ImageBatchRequest(expected_revision_id=project.current_revision_id)
        )
        assert preview.items[0].status == "unknown"
        assert preview.estimated_cost_micros == 0
        assert preview.items[0].retryable is False
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_provider_read_timeout_does_not_repeat_paid_post(tmp_path):
    from viral_dna_api.image_generation.catalog import load_image_model_catalog
    from viral_dna_api.image_generation.contracts import ImageGenerationError
    from viral_dna_api.image_generation.dashscope import DashScopeQwenImageAdapter

    attempts = []

    def provider(request):
        attempts.append(request)
        raise httpx.ReadTimeout("connection lost after submission", request=request)

    option = load_image_model_catalog().option("qwen_image_2_pro")
    adapter = DashScopeQwenImageAdapter(
        identity=SimpleNamespace(capability=option.capabilities, model=option.model),
        api_key="test-only",
        base_url="https://provider.invalid",
        max_attempts=3,
        transport=httpx.MockTransport(provider),
    )
    request = SimpleNamespace(
        source_path=None,
        references=(),
        positive_prompt="测试图片",
        negative_prompt="",
        candidate_count=1,
        width=576,
        height=1024,
        seed=None,
    )
    with pytest.raises(ImageGenerationError) as error:
        await adapter.generate(request)
    assert error.value.code == "remote_outcome_unknown"
    assert len(attempts) == 1
