"""Shared selection gate and stable ordering, without any paid generation."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_image_stage_gate import project_environment
from test_upstream_changes import adopt

from viral_dna_api import main
from viral_dna_api.models import (
    ProductionAdvanceRequest,
    ProductionStep,
    ShotEditingSelectionUpdate,
    ShotPlan,
    ShotPlanReorder,
    TimelineHandoffSyncRequest,
)
from viral_dna_api.production import ProductionServiceError
from viral_dna_api.projects.contracts import Project, SkillProjectSource
from viral_dna_api.skill_workflow.contracts import (
    GateDecision,
    GateDecisionRequest,
    SkillGate,
    SkillRun,
)
from viral_dna_api.skill_workflow.service import SkillWorkflowService, SkillWorkflowServiceError
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.timeline import TimelineService


async def video_environment(tmp_path, monkeypatch, origin="skill", durable=False):
    env = await project_environment(tmp_path, monkeypatch, origin, durable)
    env.project = env.project.model_copy(update={"active_step": ProductionStep.SHOT_VIDEOS})
    await env.store.save_production_project(env.project)
    return env


async def choose(env, shot_id, included):
    project = await env.store.get_production_project(env.project.id)
    return await env.service.update_editing_selection(
        shot_id,
        ShotEditingSelectionUpdate(
            expected_revision_id=project.current_revision_id, include_in_editing=included
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["skill", "analysis"])
@pytest.mark.parametrize("durable", [False, True])
async def test_one_adopted_video_advances_and_exclusion_survives_reload_and_readoption(
    tmp_path, monkeypatch, origin, durable
):
    env = await video_environment(tmp_path, monkeypatch, origin, durable)
    assert not (await env.service.gate_status(env.project.id)).allowed
    shot, candidate, path = await adopt(env, env.shots[0], "video")
    # Legacy optional/required marks do not control participation.
    shot = shot.model_copy(update={"required": False})
    await env.store.save_shot_plan(shot)
    gate = await env.service.gate_status(env.project.id)
    assert gate.allowed and gate.selected_video_count == 1
    assert gate.eligible_video_shot_ids == gate.selected_video_shot_ids == [shot.id]
    assert len(env.shots) > 1  # Pending other shots must not block the gate.

    excluded = await choose(env, shot.id, False)
    assert not excluded.plan.include_in_editing
    assert excluded.plan.approved_video_candidate_id == candidate.id
    assert excluded.plan.video_status == "approved" and path.is_file()
    store = SQLiteStore(env.service.workspace.database_path) if durable else env.store
    assert not (await store.get_shot_plan(shot.id)).include_in_editing
    gate = await env.service.gate_status(env.project.id)
    assert not gate.allowed and gate.selected_video_count == 0
    assert gate.eligible_video_shot_ids == [shot.id]
    project = await env.store.get_production_project(env.project.id)
    with pytest.raises(ProductionServiceError, match="至少选择一个"):
        await env.service.advance(
            env.project.id,
            ProductionAdvanceRequest(
                expected_revision_id=project.current_revision_id, target_step="editing"
            ),
        )
    fresh, _, _ = await adopt(env, excluded.plan, "video")
    assert not fresh.include_in_editing
    assert not (await env.service.gate_status(env.project.id)).allowed
    await choose(env, shot.id, True)
    project = await env.store.get_production_project(env.project.id)
    advanced = await env.service.advance(
        env.project.id,
        ProductionAdvanceRequest(
            expected_revision_id=project.current_revision_id, target_step="editing"
        ),
    )
    assert advanced.project.active_step == "editing"
    handoff = await env.service.get_current_editing_handoff(env.project.id)
    assert [clip.shot_plan_id for clip in handoff.clips] == [shot.id]
    assert len(await env.store.list_shot_plans(env.project.id)) == len(env.shots)
    # Returning to the video page still checks the selected subset, never the image gate.
    assert (await env.service.gate_status(env.project.id, step="shot_videos")).allowed
    await choose(env, shot.id, False)
    assert (await env.store.get_production_project(env.project.id)).active_step == "editing"


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["skill", "analysis"])
async def test_order_and_selection_handoff_do_not_replace_a_saved_timeline(
    tmp_path_factory, monkeypatch, origin
):
    env = await video_environment(tmp_path_factory.mktemp("ve"), monkeypatch, origin)
    first, _, _ = await adopt(env, env.shots[0], "video")
    second, _, _ = await adopt(env, env.shots[1], "video")
    entered = await env.service.advance(
        env.project.id,
        ProductionAdvanceRequest(
            expected_revision_id=env.project.current_revision_id, target_step="editing"
        ),
    )
    timeline_service = TimelineService(env.store, env.service.workspace, env.service)
    original = await timeline_service.get_timeline(env.project.id)
    original_clips = [clip.model_dump() for clip in original.clips]
    reordered_ids = list(reversed([plan.id for plan in env.shots]))
    await env.service.reorder_shots(
        env.project.id,
        ShotPlanReorder(
            expected_revision_id=entered.project.current_revision_id,
            ordered_shot_plan_ids=reordered_ids,
        ),
    )
    for before in (first, second):
        after = await env.store.get_shot_plan(before.id)
        assert after.approved_video_candidate_id == before.approved_video_candidate_id
        assert after.video_prompt == before.video_prompt
        assert after.start_seconds == before.start_seconds
    handoff = await env.service.get_current_editing_handoff(env.project.id)
    assert [clip.shot_plan_id for clip in handoff.clips] == [second.id, first.id]
    await choose(env, first.id, False)
    current = await timeline_service.get_timeline(env.project.id)
    assert current.revision_id == original.revision_id
    assert [clip.model_dump() for clip in current.clips] == original_clips
    assert current.upstream_inputs_changed and current.upstream_sync_available
    updated = await timeline_service.synchronize_handoff(
        env.project.id, TimelineHandoffSyncRequest(expected_revision_id=current.revision_id)
    )
    assert updated.revision_id != original.revision_id
    assert [clip.shot_plan_id for clip in updated.clips] == [second.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "archived", "foreign", "preview_only", "discarded"])
async def test_unavailable_video_cannot_be_selected_or_unlock_editing(
    tmp_path, monkeypatch, invalid
):
    env = await video_environment(tmp_path, monkeypatch)
    shot, candidate, path = await adopt(env, env.shots[0], "video")
    if invalid == "missing":
        path.unlink()
    elif invalid == "archived":
        await env.store.save_generation_candidate(
            candidate.model_copy(update={"status": "archived"})
        )
    elif invalid == "foreign":
        run = await env.store.get_generation_run(candidate.generation_run_id)
        await env.store.save_generation_run(run.model_copy(update={"project_id": uuid4()}))
    elif invalid == "preview_only":
        await env.store.save_shot_plan(env.shots[0])
    else:
        await env.store.save_shot_plan(shot.model_copy(update={"lifecycle_status": "discarded"}))
    gate = await env.service.gate_status(env.project.id, step="shot_videos")
    assert not gate.allowed and not gate.selected_video_shot_ids
    with pytest.raises(ProductionServiceError):
        await choose(env, shot.id, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["skill", "analysis"])
async def test_first_timeline_uses_selection_changed_after_advance(
    tmp_path_factory, monkeypatch, origin
):
    env = await video_environment(tmp_path_factory.mktemp("vs"), monkeypatch, origin)
    first, _, _ = await adopt(env, env.shots[0], "video")
    second, _, _ = await adopt(env, env.shots[1], "video")
    await env.service.advance(
        env.project.id,
        ProductionAdvanceRequest(
            expected_revision_id=env.project.current_revision_id, target_step="editing"
        ),
    )
    await choose(env, first.id, False)
    service = TimelineService(env.store, env.service.workspace, env.service)
    timeline = await service.get_timeline(env.project.id)
    assert [clip.shot_plan_id for clip in timeline.clips] == [second.id]
    await choose(env, second.id, False)
    preserved = await service.get_timeline(env.project.id)
    assert preserved.revision_id == timeline.revision_id
    assert [clip.shot_plan_id for clip in preserved.clips] == [second.id]
    assert preserved.upstream_inputs_changed and not preserved.upstream_sync_available


@pytest.mark.asyncio
async def test_skill_video_approval_uses_same_selected_subset(tmp_path, monkeypatch):
    env = await video_environment(tmp_path, monkeypatch)
    run = SkillRun(
        project_id=uuid4(), skill_version_snapshot_id=uuid4(), run_contract_revision_id=uuid4()
    )
    project = Project(
        id=run.project_id,
        name="视频勾选测试",
        kind="skill",
        active_stage="shot_videos",
        source_binding=SkillProjectSource(
            skill_id="test",
            skill_version_id=uuid4(),
            skill_version_digest="sha256:" + "a" * 64,
            production_project_id=env.project.id,
        ),
    )
    for gate in (
        SkillGate.BRIEF_APPROVED,
        SkillGate.STYLE_APPROVED,
        SkillGate.STORYBOARD_APPROVED,
        SkillGate.IMAGES_APPROVED,
    ):
        await env.store.save_gate_decision(
            GateDecision(
                project_id=project.id,
                skill_run_id=run.id,
                gate=gate,
                decision="approve",
                actor_type="user",
            )
        )
    service = SkillWorkflowService(env.store, None, None, production_service=env.service)
    payload = GateDecisionRequest(decision="approve")
    with pytest.raises(SkillWorkflowServiceError, match="至少选择一个"):
        await service._validate_gate(run, project, SkillGate.VIDEOS_APPROVED, payload)
    shot, _, _ = await adopt(env, env.shots[0], "video")
    await service._validate_gate(run, project, SkillGate.VIDEOS_APPROVED, payload)
    await choose(env, shot.id, False)
    with pytest.raises(SkillWorkflowServiceError, match="至少选择一个"):
        await service._validate_gate(run, project, SkillGate.VIDEOS_APPROVED, payload)


@pytest.mark.asyncio
async def test_selection_http_revision_conflict_and_legacy_default(tmp_path, monkeypatch):
    env = await video_environment(tmp_path, monkeypatch, "analysis", durable=True)
    shot, _, _ = await adopt(env, env.shots[0], "video")
    legacy = shot.model_dump(exclude={"include_in_editing"})
    assert ShotPlan.model_validate(legacy).include_in_editing
    monkeypatch.setattr(main, "production_service", env.service)
    with TestClient(main.app) as client:
        url = f"/api/v1/production-shots/{shot.id}/editing-selection"
        bad = client.put(
            url, json={"expected_revision_id": str(uuid4()), "include_in_editing": False}
        )
        assert bad.status_code == 409
        response = client.put(
            url,
            json={
                "expected_revision_id": str(env.project.current_revision_id),
                "include_in_editing": False,
            },
        )
        assert response.status_code == 200, response.text
        assert not response.json()["plan"]["include_in_editing"]
        gate = client.get(
            f"/api/v1/productions/{env.project.id}/gate-status?step=shot_videos"
        ).json()
        assert gate["eligible_video_shot_ids"] == [str(shot.id)]
        assert not gate["allowed"] and gate["selected_video_count"] == 0
