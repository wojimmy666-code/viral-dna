"""Explicit image -> video scope; isolated stores/media, never paid generation."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_image_batches import environment
from test_image_stage_gate import project_environment
from test_upstream_changes import adopt
from test_video_editing_selection import choose

from viral_dna_api import main
from viral_dna_api.models import (
    ProductionAdvanceRequest,
    ProductionProjectStatus,
    ProductionStep,
    ShotImageApprovalRevokeRequest,
    ShotOutputMode,
    ShotPlanReorder,
    TimelineHandoffSyncRequest,
    VideoGenerationCreate,
    VideoStageEnterRequest,
)
from viral_dna_api.production import ProductionServiceError, _sync_shot_visual_beats
from viral_dna_api.skill_workflow.service import SkillWorkflowService
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.timeline import TimelineService


async def enter(env):
    project = await env.store.get_production_project(env.project.id)
    return await env.service.enter_video_stage(
        project.id, VideoStageEnterRequest(expected_revision_id=project.current_revision_id)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["skill", "analysis"])
@pytest.mark.parametrize("durable", [False, True])
async def test_entry_persists_one_scope_and_revision_without_removing_other_shots(
    tmp_path_factory, monkeypatch, origin, durable
):
    env = await project_environment(tmp_path_factory.mktemp("scope"), monkeypatch, origin, durable)
    first, _, _ = await adopt(env, env.shots[0])
    # Legacy required flags have no bearing on the explicitly selected scope.
    await env.store.save_shot_plan(first.model_copy(update={"required": False}))
    before = [p.model_dump() for p in await env.store.list_shot_plans(env.project.id)]
    entered = await env.service.advance(
        env.project.id,
        ProductionAdvanceRequest(
            expected_revision_id=env.project.current_revision_id, target_step="shot_videos"
        ),
    )
    assert entered.project.video_stage_shot_ids == [first.id]
    assert entered.project.active_step == "shot_videos"
    assert [p.model_dump() for p in await env.store.list_shot_plans(env.project.id)] == before
    store = SQLiteStore(env.workspace.database_path) if durable else env.store
    assert (await store.get_production_project(env.project.id)).video_stage_shot_ids == [first.id]
    revision = await env.service.get_revision(env.project.id, entered.project.current_revision_id)
    assert revision.snapshot["project"]["video_stage_shot_ids"] == [str(first.id)]
    gate = await env.service.gate_status(env.project.id, step="shot_videos")
    assert gate.required_shot_count == 1
    repeated = await enter(env)
    assert repeated.project.current_revision_id == entered.project.current_revision_id
    with pytest.raises(ProductionServiceError, match="版本|更新"):
        await env.service.enter_video_stage(
            env.project.id, VideoStageEnterRequest(expected_revision_id=uuid4())
        )
    assert (await env.store.get_production_project(env.project.id)) == repeated.project


@pytest.mark.asyncio
async def test_fifteen_shots_five_adoptions_and_two_beats_remain_five_video_shots(
    tmp_path_factory, monkeypatch
):
    env = await environment(tmp_path_factory.mktemp("five"), monkeypatch, count=15)
    ids = []
    for index in [0, 2, 6, 9, 14]:
        shot, _, _ = await adopt(env, env.shots[index])
        ids.append(shot.id)
    first = await env.store.get_shot_plan(ids[0])
    beat1 = first.visual_beats[0].model_copy(update={"end_ratio": 0.5})
    beat2 = beat1.model_copy(
        update={
            "id": uuid4(),
            "index": 2,
            "start_ratio": 0.5,
            "end_ratio": 1,
            "approved_image_candidate_id": None,
        }
    )
    second, _, _ = await adopt(env, first.model_copy(update={"visual_beats": [beat2]}))
    combined = _sync_shot_visual_beats(
        first, [beat1, second.visual_beats[0]], revision_id=first.revision_id
    )
    await env.store.save_shot_plan(combined)
    # A generated/preview-only candidate must not become a sixth participant.
    await adopt(env, env.shots[1])
    await env.store.save_shot_plan(env.shots[1])
    entered = await enter(env)
    assert entered.project.video_stage_shot_ids == ids
    assert (
        await env.service.gate_status(env.project.id, step="shot_images")
    ).approved_image_count == 6
    assert (await env.service.gate_status(env.project.id)).required_shot_count == 5
    assert len(await env.service.list_shots(env.project.id)) == 15


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["skill", "analysis"])
async def test_only_explicit_reentry_changes_scope_and_never_rewrites_saved_timeline(
    tmp_path_factory, monkeypatch, origin
):
    env = await project_environment(tmp_path_factory.mktemp("rescope"), monkeypatch, origin)
    first, first_image, first_path = await adopt(env, env.shots[0])
    first, first_video, video_path = await adopt(env, first, "video")
    entered = await enter(env)
    second, _, _ = await adopt(env, env.shots[1])
    second, second_video, _ = await adopt(env, second, "video")
    # GETs, adoption and refresh do not include the newly adopted second shot.
    assert (await env.service.get_project(env.project.id)).project.video_stage_shot_ids == [
        first.id
    ]
    gate = await env.service.gate_status(env.project.id)
    assert gate.selected_video_shot_ids == [first.id]
    with pytest.raises(ProductionServiceError, match="未选入"):
        await choose(env, second.id, True)
    await env.service.advance(
        env.project.id,
        ProductionAdvanceRequest(
            expected_revision_id=entered.project.current_revision_id, target_step="editing"
        ),
    )
    timeline_service = TimelineService(env.store, env.workspace, env.service)
    original = await timeline_service.get_timeline(env.project.id)
    assert [c.shot_plan_id for c in original.clips] == [first.id]
    expanded = await enter(env)
    assert expanded.project.video_stage_shot_ids == [first.id, second.id]
    assert expanded.project.active_step == "editing"
    await env.service.revoke_image_approval(
        first.id,
        ShotImageApprovalRevokeRequest(
            expected_revision_id=expanded.project.current_revision_id,
            visual_beat_id=first.visual_beats[0].id,
        ),
    )
    assert (
        await env.service.gate_status(env.project.id, step="shot_videos")
    ).selected_video_count == 2
    narrowed = await enter(env)
    assert narrowed.project.video_stage_shot_ids == [second.id]
    current = await timeline_service.get_timeline(env.project.id)
    assert current.revision_id == original.revision_id
    assert current.clips == original.clips
    assert current.upstream_sync_available
    latest = await env.service.get_current_editing_handoff(env.project.id)
    assert [c.shot_plan_id for c in latest.clips] == [second.id]
    refreshed = await timeline_service.synchronize_handoff(
        env.project.id, TimelineHandoffSyncRequest(expected_revision_id=current.revision_id)
    )
    assert [c.shot_plan_id for c in refreshed.clips] == [second.id]
    assert (await env.store.get_shot_plan(first.id)).approved_video_candidate_id == first_video.id
    assert (await env.store.get_shot_plan(second.id)).approved_video_candidate_id == second_video.id
    assert await env.store.get_generation_candidate(first_image.id) is not None
    assert first_path.is_file() and video_path.is_file()


@pytest.mark.asyncio
async def test_scoped_order_changes_only_participant_slots_and_rejects_incomplete_scope(
    tmp_path_factory, monkeypatch
):
    env = await environment(tmp_path_factory.mktemp("order"), monkeypatch, count=5)
    for index in [1, 3]:
        await adopt(env, env.shots[index])
    entered = await enter(env)
    all_ids = [p.id for p in env.shots]
    order = [all_ids[3], all_ids[1]]
    reordered = await env.service.reorder_shots(
        env.project.id,
        ShotPlanReorder(
            expected_revision_id=entered.project.current_revision_id,
            ordered_shot_plan_ids=order,
            scope="shot_videos",
        ),
    )
    assert [s.plan.id for s in reordered] == [
        all_ids[0],
        all_ids[3],
        all_ids[2],
        all_ids[1],
        all_ids[4],
    ]
    for original in env.shots:
        after = await env.store.get_shot_plan(original.id)
        assert after.start_seconds == original.start_seconds
        assert after.video_prompt == original.video_prompt
    project = await env.store.get_production_project(env.project.id)
    for invalid in [all_ids, [all_ids[1]], [all_ids[1], uuid4()]]:
        with pytest.raises(ProductionServiceError, match="排序必须"):
            await env.service.reorder_shots(
                env.project.id,
                ShotPlanReorder(
                    expected_revision_id=project.current_revision_id,
                    ordered_shot_plan_ids=invalid,
                    scope="shot_videos",
                ),
            )
    assert [
        p.id
        for p in env.service._video_stage_plans(
            project, await env.store.list_shot_plans(project.id)
        )
    ] == order


@pytest.mark.asyncio
async def test_excluded_shot_cannot_enqueue_or_execute_a_video_request(
    tmp_path_factory, monkeypatch
):
    env = await environment(tmp_path_factory.mktemp("bounds"), monkeypatch, count=2)
    await adopt(env, env.shots[0])
    entered = await enter(env)
    excluded, _, _ = await adopt(env, env.shots[1])
    env.service._validate_skill_video_contract = AsyncMock()
    request = VideoGenerationCreate(expected_revision_id=entered.project.current_revision_id)
    with pytest.raises(ProductionServiceError, match="未选入"):
        await env.service.create_video_run(excluded.id, request)
    with pytest.raises(ProductionServiceError, match="未选入"):
        await env.service._execute_video_run_request(
            excluded.id, request, run_id=uuid4(), cancellation=Event(), queued_run=None
        )
    env.service._validate_skill_video_contract.assert_not_called()
    assert not [
        r for r in await env.store.list_generation_runs(env.project.id) if r.kind == "video"
    ]


@pytest.mark.asyncio
async def test_legacy_scope_reads_are_unchanged_until_explicit_entry(tmp_path_factory, monkeypatch):
    env = await environment(tmp_path_factory.mktemp("legacy"), monkeypatch, count=3)
    env.project = env.project.model_copy(
        update={
            "active_step": ProductionStep.EXPORT,
            "status": ProductionProjectStatus.COMPLETED,
        }
    )
    await env.store.save_production_project(env.project)
    await adopt(env, env.shots[0], "video")
    await adopt(env, env.shots[1])
    assert (await env.service.get_project(env.project.id)).project.video_stage_shot_ids is None
    assert (await env.service.gate_status(env.project.id)).selected_video_count == 1
    entered = await enter(env)
    assert entered.project.video_stage_shot_ids == [env.shots[1].id]
    assert entered.project.active_step == "export" and entered.project.status == "completed"
    assert not (await env.service.gate_status(env.project.id, step="shot_videos")).allowed
    with pytest.raises(ProductionServiceError, match="重新进入"):
        await env.service.advance(
            env.project.id,
            ProductionAdvanceRequest(
                expected_revision_id=entered.project.current_revision_id,
                target_step="shot_videos",
            ),
        )


@pytest.mark.asyncio
async def test_retained_source_video_counts_as_one_participant_but_not_an_adopted_image(
    tmp_path_factory, monkeypatch
):
    env = await project_environment(tmp_path_factory.mktemp("source"), monkeypatch, "analysis")
    source, _, _ = await adopt(env, env.shots[0], "video")
    await env.store.save_shot_plan(
        source.model_copy(update={"output_mode": ShotOutputMode.SOURCE_VIDEO})
    )
    with pytest.raises(ProductionServiceError, match="至少采用一张"):
        await enter(env)
    await adopt(env, env.shots[1])
    entered = await enter(env)
    assert entered.project.video_stage_shot_ids == [source.id, env.shots[1].id]


@pytest.mark.asyncio
async def test_api_reentry_is_explicit_and_rejects_stale_revision(tmp_path_factory, monkeypatch):
    env = await environment(tmp_path_factory.mktemp("api"), monkeypatch, count=2)
    await adopt(env, env.shots[0])
    monkeypatch.setattr(main, "production_service", env.service)
    client = TestClient(main.app)
    path = f"/api/v1/productions/{env.project.id}/video-stage/enter"
    response = client.post(
        path, json={"expected_revision_id": str(env.project.current_revision_id)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["project"]["video_stage_shot_ids"] == [str(env.shots[0].id)]
    assert client.post(path, json={"expected_revision_id": str(uuid4())}).status_code == 409


@pytest.mark.asyncio
async def test_full_auto_uses_the_saved_scope_including_optional_participants(
    tmp_path_factory, monkeypatch
):
    env = await environment(tmp_path_factory.mktemp("auto"), monkeypatch, count=4)
    for index in [0, 2]:
        shot, _, _ = await adopt(env, env.shots[index])
        await env.store.save_shot_plan(shot.model_copy(update={"required": False}))
    entered = await enter(env)
    # Later adoptions cannot silently expand the already-approved execution scope.
    await adopt(env, env.shots[1])
    env.service.create_video_run = AsyncMock()
    service = SkillWorkflowService(env.store, None, None, production_service=env.service)
    service._require_skill_project = AsyncMock(
        return_value=SimpleNamespace(
            source_binding=SimpleNamespace(production_project_id=env.project.id),
        )
    )
    contract = SimpleNamespace(
        generate_video_audio=False,
        candidate_count_by_stage={},
        video_model_id="test_video",
        video_resolution_label="720P",
    )
    await service._full_auto_generate_videos(SimpleNamespace(project_id=uuid4()), contract)
    assert [call.args[0] for call in env.service.create_video_run.await_args_list] == (
        entered.project.video_stage_shot_ids
    )
