"""Image-stage entry is shared across Skill and analysis, independent of shot completion."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_image_batches import environment
from test_production_api import seed_completed_analysis
from test_upstream_changes import adopt

from viral_dna_api import main
from viral_dna_api.models import (
    ProductionAdvanceRequest,
    ProductionProjectCreate,
    ShotImageApprovalRevokeRequest,
    WorkflowItemStatus,
)
from viral_dna_api.production import ProductionServiceError, _sync_shot_visual_beats
from viral_dna_api.projects.contracts import Project, SkillProjectSource
from viral_dna_api.skill_workflow.contracts import (
    GateDecision,
    GateDecisionRequest,
    SkillGate,
    SkillRun,
)
from viral_dna_api.skill_workflow.service import SkillWorkflowService, SkillWorkflowServiceError


async def project_environment(tmp_path, monkeypatch, origin, durable=False):
    env = await environment(tmp_path, monkeypatch, count=3, durable=durable)
    if origin == "analysis":
        record, _, analysis, _ = await seed_completed_analysis(env.store)
        detail = await env.service.create_project(
            record.id,
            ProductionProjectCreate(base_analysis_id=analysis.id),
        )
        env.project = detail.project
        env.shots = await env.store.list_shot_plans(detail.project.id)
    return env


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["skill", "analysis"])
@pytest.mark.parametrize("durable", [False, True])
async def test_zero_then_one_picture_advances_without_completing_other_shots(
    tmp_path,
    monkeypatch,
    origin,
    durable,
):
    env = await project_environment(tmp_path, monkeypatch, origin, durable)
    before = await env.service.gate_status(env.project.id, step="shot_images")
    assert not before.allowed
    assert before.approved_image_count == 0
    assert before.blocker_messages == ["请至少采用一张分镜图"]
    with pytest.raises(ProductionServiceError, match="请至少采用一张分镜图"):
        await env.service.advance(
            env.project.id,
            ProductionAdvanceRequest(
                expected_revision_id=env.project.current_revision_id,
                target_step="shot_videos",
            ),
        )
    shot, candidate, path = await adopt(env, env.shots[0])
    # Old optional flags must not exclude a genuinely adopted picture.
    shot = shot.model_copy(
        update={
            "required": False,
            "visual_beats": [shot.visual_beats[0].model_copy(update={"required": False})],
        }
    )
    await env.store.save_shot_plan(shot)
    ready = await env.service.gate_status(env.project.id, step="shot_images")
    assert ready.allowed and ready.approved_image_count == 1
    assert not ready.blocker_messages
    entered = await env.service.advance(
        env.project.id,
        ProductionAdvanceRequest(
            expected_revision_id=env.project.current_revision_id,
            target_step="shot_videos",
        ),
    )
    assert entered.project.active_step == "shot_videos"
    assert (await env.service.gate_status(env.project.id, step="shot_images")).allowed
    assert not (await env.service.gate_status(env.project.id)).allowed  # Editing is unchanged.
    plans = await env.store.list_shot_plans(env.project.id)
    assert len(plans) == len(env.shots)
    assert all(plan.video_status != "approved" for plan in plans)
    await env.service.revoke_image_approval(
        shot.id,
        ShotImageApprovalRevokeRequest(
            expected_revision_id=entered.project.current_revision_id,
            visual_beat_id=shot.visual_beats[0].id,
        ),
    )
    after = await env.service.gate_status(env.project.id, step="shot_images")
    assert not after.allowed and after.approved_image_count == 0
    assert (await env.store.get_production_project(env.project.id)).active_step == "shot_videos"
    assert path.is_file() and await env.store.get_generation_candidate(candidate.id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["skill", "analysis"])
async def test_one_adopted_beat_counts_even_with_another_required_beat_pending(
    tmp_path, monkeypatch, origin
):
    env = await project_environment(tmp_path, monkeypatch, origin)
    shot, _, _ = await adopt(env, env.shots[0])
    first = shot.visual_beats[0].model_copy(update={"end_ratio": 0.5})
    second = first.model_copy(
        update={
            "id": uuid4(),
            "index": 2,
            "start_ratio": 0.5,
            "end_ratio": 1,
            "image_status": WorkflowItemStatus.READY,
            "approved_image_candidate_id": None,
        }
    )
    shot = _sync_shot_visual_beats(shot, [first, second], revision_id=shot.revision_id)
    await env.store.save_shot_plan(shot)
    gate = await env.service.gate_status(env.project.id, step="shot_images")
    assert gate.allowed and gate.approved_image_count == 1
    assert not await env.service._has_valid_approved_image_output(env.project, shot)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", ["missing", "archived", "rejected", "discarded", "foreign", "preview_only"]
)
async def test_unavailable_or_unadopted_pictures_never_open_the_gate(
    tmp_path, monkeypatch, invalid
):
    env = await project_environment(tmp_path, monkeypatch, "skill")
    shot, candidate, path = await adopt(env, env.shots[0])
    if invalid == "missing":
        path.unlink()
    elif invalid in {"archived", "rejected"}:
        await env.store.save_generation_candidate(candidate.model_copy(update={"status": invalid}))
    elif invalid == "discarded":
        await env.store.save_shot_plan(shot.model_copy(update={"lifecycle_status": "discarded"}))
    elif invalid == "foreign":
        run = await env.store.get_generation_run(candidate.generation_run_id)
        await env.store.save_generation_run(run.model_copy(update={"project_id": uuid4()}))
    else:
        # The original plan has no adoption; selecting a candidate is not adopting it.
        await env.store.save_shot_plan(env.shots[0])
    gate = await env.service.gate_status(env.project.id, step="shot_images")
    assert not gate.allowed and gate.approved_image_count == 0


@pytest.mark.asyncio
async def test_skill_image_approval_uses_the_shared_gate_but_still_requires_adopted_video(
    tmp_path, monkeypatch
):
    env = await project_environment(tmp_path, monkeypatch, "skill")
    run = SkillRun(
        project_id=uuid4(), skill_version_snapshot_id=uuid4(), run_contract_revision_id=uuid4()
    )
    project = Project(
        id=run.project_id,
        name="图片门禁测试",
        kind="skill",
        active_stage="shot_images",
        source_binding=SkillProjectSource(
            skill_id="test-image-gate",
            skill_version_id=uuid4(),
            skill_version_digest="sha256:" + "a" * 64,
            production_project_id=env.project.id,
        ),
    )
    for gate in (SkillGate.BRIEF_APPROVED, SkillGate.STYLE_APPROVED, SkillGate.STORYBOARD_APPROVED):
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
    with pytest.raises(SkillWorkflowServiceError, match="请至少采用一张分镜图"):
        await service._validate_gate(run, project, SkillGate.IMAGES_APPROVED, payload)
    await adopt(env, env.shots[0])
    await service._validate_gate(run, project, SkillGate.IMAGES_APPROVED, payload)
    await env.store.save_gate_decision(
        GateDecision(
            project_id=project.id,
            skill_run_id=run.id,
            gate=SkillGate.IMAGES_APPROVED,
            decision="approve",
            actor_type="user",
        )
    )
    with pytest.raises(SkillWorkflowServiceError, match="至少选择一个有效的已采用视频"):
        await service._validate_gate(run, project, SkillGate.VIDEOS_APPROVED, payload)


@pytest.mark.asyncio
async def test_http_image_gate_can_be_read_after_advancement_without_mutating_stage(
    tmp_path, monkeypatch
):
    env = await project_environment(tmp_path, monkeypatch, "analysis")
    await adopt(env, env.shots[0])
    entered = await env.service.advance(
        env.project.id,
        ProductionAdvanceRequest(
            expected_revision_id=env.project.current_revision_id,
            target_step="shot_videos",
        ),
    )
    monkeypatch.setattr(main, "production_service", env.service)
    with TestClient(main.app) as client:
        image = client.get(f"/api/v1/productions/{env.project.id}/gate-status?step=shot_images")
        assert image.status_code == 200, image.text
        assert image.json()["allowed"] and image.json()["approved_image_count"] == 1
        video = client.get(f"/api/v1/productions/{env.project.id}/gate-status")
        assert video.status_code == 200 and not video.json()["allowed"]
        assert (
            client.get(f"/api/v1/productions/{env.project.id}/gate-status?step=invalid").status_code
            == 422
        )
    assert (
        await env.store.get_production_project(env.project.id)
    ).current_revision_id == entered.project.current_revision_id
